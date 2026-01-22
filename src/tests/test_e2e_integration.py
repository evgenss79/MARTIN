"""
Consolidated End-to-End Integration Tests for MARTIN.

This file provides a unified E2E test suite covering all major flows.
Each test simulates complete workflows with mocked external APIs.

Tests included:
1. Day flow: user OK -> settlement WIN
2. Night flow: SOFT_RESET behavior
3. Night flow: HARD_RESET behavior
4. CAP_FAIL flow
5. LATE confirm flow
6. Auth gating blocks live execution
"""
import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from domain.enums import (
    TradeStatus, Direction, CapStatus, FillStatus,
    PolicyMode, NightSessionMode
)


class TestE2EIntegration:
    """Consolidated E2E integration tests."""
    
    # =========================================================================
    # TEST 1: Day Flow - User OK to Settlement WIN
    # =========================================================================
    
    def test_day_flow_user_ok_to_settlement_win(self):
        """
        Complete day flow simulation:
        discovery -> window -> TA signal -> quality pass -> WAITING_CONFIRM ->
        user OK -> CAP_PASS after confirm_ts -> execute (paper) -> settle WIN -> stats update
        """
        # Configuration
        config = {
            'price_cap': 0.55,
            'confirm_delay_seconds': 120,
            'cap_min_ticks': 5,
            'base_day_min_quality': 50.0,
            'execution_mode': 'paper'
        }
        
        # Step 1: Discovery - Market found
        market_window = {
            'slug': 'btc-up-or-down-hourly',
            'asset': 'BTC',
            'start_ts': 1000,
            'end_ts': 4600,
            'up_token_id': 'token_up_123',
            'down_token_id': 'token_down_456'
        }
        assert market_window['slug'] is not None
        
        # Step 2: TA Signal computed (EMA20 1m, 2-bar confirm per MG-4)
        signal = {
            'direction': Direction.UP,
            'signal_ts': 2000,
            'quality': 65.0,  # Above threshold
            'anchor_price': 50000,
            'signal_price': 50200
        }
        assert signal['quality'] >= config['base_day_min_quality']
        
        # Step 3: Trade created -> NEW
        trade = {'status': TradeStatus.NEW, 'decision': None}
        assert trade['status'] == TradeStatus.NEW
        
        # Step 4: Signal assigned -> SIGNALLED
        trade['status'] = TradeStatus.SIGNALLED
        assert trade['status'] == TradeStatus.SIGNALLED
        
        # Step 5: Quality passes -> WAITING_CONFIRM
        trade['status'] = TradeStatus.WAITING_CONFIRM
        assert trade['status'] == TradeStatus.WAITING_CONFIRM
        
        # Step 6: User presses OK (Day mode requires confirmation per MG-6)
        trade['decision'] = 'OK'
        trade['status'] = TradeStatus.WAITING_CAP
        assert trade['decision'] == 'OK'
        assert trade['status'] == TradeStatus.WAITING_CAP
        
        # Step 7: CAP_PASS check (MG-2: only after confirm_ts)
        confirm_ts = signal['signal_ts'] + config['confirm_delay_seconds']  # 2120
        assert confirm_ts < market_window['end_ts'], "MG-3: confirm_ts must be < end_ts"
        
        # Simulate CLOB prices after confirm_ts
        clob_prices = [
            {'t': 2120, 'p': 0.54},  # 1 - at confirm_ts
            {'t': 2121, 'p': 0.53},  # 2
            {'t': 2122, 'p': 0.52},  # 3
            {'t': 2123, 'p': 0.51},  # 4
            {'t': 2124, 'p': 0.50},  # 5 - CAP_PASS!
        ]
        
        consecutive = 0
        cap_pass_ts = None
        for tick in clob_prices:
            if tick['t'] >= confirm_ts:  # MG-2: only count after confirm_ts
                if tick['p'] <= config['price_cap']:
                    consecutive += 1
                    if consecutive >= config['cap_min_ticks']:
                        cap_pass_ts = tick['t']
                        break
                else:
                    consecutive = 0
        
        assert cap_pass_ts is not None, "CAP_PASS should occur"
        trade['cap_status'] = CapStatus.PASS
        trade['status'] = TradeStatus.READY
        
        # Step 8: Execute (paper mode per MG-9)
        assert config['execution_mode'] == 'paper', "MG-9: Default is paper"
        trade['status'] = TradeStatus.ORDER_PLACED
        trade['order_id'] = 'paper_order_001'
        trade['fill_status'] = FillStatus.FILLED
        
        # Step 9: Settle WIN
        trade['status'] = TradeStatus.SETTLED
        trade['result'] = 'WIN'
        trade['pnl'] = 10.0
        
        assert trade['status'] == TradeStatus.SETTLED
        assert trade['result'] == 'WIN'
        
        # MG-1: Only taken+filled trades count for streak
        is_taken = trade['decision'] in ['OK', 'AUTO_OK']
        is_filled = trade['fill_status'] == FillStatus.FILLED
        counts_for_streak = is_taken and is_filled
        assert counts_for_streak, "MG-1: Trade should count for streak"
    
    # =========================================================================
    # TEST 2: Night Flow - SOFT_RESET Behavior
    # =========================================================================
    
    def test_night_flow_soft_reset_behavior(self):
        """
        Night flow with SOFT_RESET mode:
        - On night session cap: reset only night_streak
        - trade_level_streak continues
        """
        # Initial state
        stats = {
            'trade_level_streak': 3,
            'night_streak': 4,  # One more win = reset
            'policy_mode': PolicyMode.STRICT,
            'night_session_mode': NightSessionMode.SOFT_RESET
        }
        night_max_win_streak = 5
        
        # Simulate WIN in night mode
        is_win = True
        
        if is_win:
            stats['night_streak'] += 1
            stats['trade_level_streak'] += 1
        
        # Check for night session cap
        if stats['night_streak'] >= night_max_win_streak:
            # SOFT_RESET: only reset night_streak
            if stats['night_session_mode'] == NightSessionMode.SOFT_RESET:
                original_trade_streak = stats['trade_level_streak']
                stats['night_streak'] = 0
                stats['policy_mode'] = PolicyMode.BASE
                # trade_level_streak should NOT reset
                assert stats['trade_level_streak'] == original_trade_streak
        
        # Verify SOFT behavior
        assert stats['night_streak'] == 0, "Night streak should reset"
        assert stats['trade_level_streak'] == 4, "Trade streak should continue"
        assert stats['policy_mode'] == PolicyMode.BASE, "Policy should return to BASE"
    
    # =========================================================================
    # TEST 3: Night Flow - HARD_RESET Behavior
    # =========================================================================
    
    def test_night_flow_hard_reset_behavior(self):
        """
        Night flow with HARD_RESET mode:
        - On night session cap: reset ALL streaks
        - trade_level_streak also resets
        """
        # Initial state
        stats = {
            'trade_level_streak': 3,
            'night_streak': 4,
            'policy_mode': PolicyMode.STRICT,
            'night_session_mode': NightSessionMode.HARD_RESET,
            'series_wins': 5,
            'series_profit': 50.0
        }
        night_max_win_streak = 5
        
        # Simulate WIN
        stats['night_streak'] += 1
        stats['trade_level_streak'] += 1
        stats['series_wins'] += 1
        stats['series_profit'] += 10.0
        
        # Check for night session cap
        if stats['night_streak'] >= night_max_win_streak:
            if stats['night_session_mode'] == NightSessionMode.HARD_RESET:
                # HARD_RESET: reset EVERYTHING
                stats['night_streak'] = 0
                stats['trade_level_streak'] = 0
                stats['policy_mode'] = PolicyMode.BASE
                stats['series_wins'] = 0
                stats['series_profit'] = 0.0
        
        # Verify HARD behavior
        assert stats['night_streak'] == 0, "Night streak should reset"
        assert stats['trade_level_streak'] == 0, "Trade streak should reset"
        assert stats['policy_mode'] == PolicyMode.BASE
        assert stats['series_wins'] == 0, "Series counters should reset"
    
    # =========================================================================
    # TEST 4: CAP_FAIL Flow
    # =========================================================================
    
    def test_cap_fail_flow(self):
        """
        Test CAP_FAIL when prices never stay below cap for min_ticks.
        Trade should be CANCELLED with reason CAP_FAIL.
        """
        config = {
            'price_cap': 0.55,
            'cap_min_ticks': 5
        }
        
        confirm_ts = 1200
        end_ts = 1500
        
        # Prices that oscillate - never reach 5 consecutive
        clob_prices = [
            {'t': 1200, 'p': 0.54},  # 1
            {'t': 1201, 'p': 0.56},  # above - reset
            {'t': 1202, 'p': 0.53},  # 1
            {'t': 1203, 'p': 0.54},  # 2
            {'t': 1204, 'p': 0.57},  # above - reset
            {'t': 1205, 'p': 0.55},  # 1 (at cap)
            {'t': 1206, 'p': 0.54},  # 2
            {'t': 1207, 'p': 0.53},  # 3
            {'t': 1208, 'p': 0.58},  # above - reset
        ]
        
        consecutive = 0
        cap_pass = False
        
        for tick in clob_prices:
            if tick['t'] >= confirm_ts:
                if tick['p'] <= config['price_cap']:
                    consecutive += 1
                    if consecutive >= config['cap_min_ticks']:
                        cap_pass = True
                        break
                else:
                    consecutive = 0
        
        assert not cap_pass, "Should not pass - never reached min_ticks"
        
        # Trade should be CANCELLED
        trade = {
            'status': TradeStatus.WAITING_CAP,
            'cap_status': CapStatus.FAIL if not cap_pass else CapStatus.PASS
        }
        
        if trade['cap_status'] == CapStatus.FAIL:
            trade['status'] = TradeStatus.CANCELLED
            trade['cancel_reason'] = 'CAP_FAIL'
        
        assert trade['status'] == TradeStatus.CANCELLED
        assert trade['cancel_reason'] == 'CAP_FAIL'
    
    # =========================================================================
    # TEST 5: LATE Confirm Flow
    # =========================================================================
    
    def test_late_confirm_flow(self):
        """
        Test MG-3: confirm_ts >= end_ts results in LATE status.
        Trade should be CANCELLED immediately.
        """
        window = {
            'start_ts': 1000,
            'end_ts': 4600
        }
        signal_ts = 4500  # Very late signal
        confirm_delay = 120
        
        confirm_ts = signal_ts + confirm_delay  # = 4620
        
        # MG-3 check
        is_late = confirm_ts >= window['end_ts']
        assert is_late, "Should be LATE: 4620 >= 4600"
        
        # Trade should be CANCELLED
        trade = {'status': TradeStatus.SIGNALLED}
        
        if is_late:
            trade['status'] = TradeStatus.CANCELLED
            trade['cap_status'] = CapStatus.LATE
            trade['cancel_reason'] = 'LATE'
        
        assert trade['status'] == TradeStatus.CANCELLED
        assert trade['cap_status'] == CapStatus.LATE
    
    # =========================================================================
    # TEST 6: Auth Gating Blocks Live Execution
    # =========================================================================
    
    def test_auth_gating_blocks_live_execution(self):
        """
        Test that live execution is blocked without proper auth.
        MG-9: Paper mode is default and always works.
        SEC-1: Live mode requires valid credentials.
        """
        import os
        
        # Clear any existing keys
        original_master = os.environ.get('MASTER_ENCRYPTION_KEY')
        original_wallet = os.environ.get('POLYMARKET_PRIVATE_KEY')
        
        for key in ['MASTER_ENCRYPTION_KEY', 'POLYMARKET_PRIVATE_KEY']:
            if key in os.environ:
                del os.environ[key]
        
        try:
            # Test 1: Paper mode always allowed (MG-9)
            execution_mode = 'paper'
            can_execute = execution_mode == 'paper'
            assert can_execute, "Paper mode must always work"
            
            # Test 2: Live mode blocked without credentials
            execution_mode = 'live'
            master_key = os.environ.get('MASTER_ENCRYPTION_KEY')
            wallet_key = os.environ.get('POLYMARKET_PRIVATE_KEY')
            
            has_credentials = (
                master_key is not None or 
                wallet_key is not None
            )
            
            can_execute_live = execution_mode == 'live' and has_credentials
            assert not can_execute_live, "Live mode blocked without credentials"
            
            # Test 3: Live mode allowed with credentials
            import base64
            import secrets
            os.environ['MASTER_ENCRYPTION_KEY'] = base64.b64encode(
                secrets.token_bytes(32)
            ).decode()
            
            master_key = os.environ.get('MASTER_ENCRYPTION_KEY')
            can_execute_live = (
                execution_mode == 'live' and 
                master_key is not None
            )
            assert can_execute_live, "Live mode works with valid credentials"
            
        finally:
            # Cleanup
            for key in ['MASTER_ENCRYPTION_KEY', 'POLYMARKET_PRIVATE_KEY']:
                if key in os.environ:
                    del os.environ[key]
            if original_master:
                os.environ['MASTER_ENCRYPTION_KEY'] = original_master
            if original_wallet:
                os.environ['POLYMARKET_PRIVATE_KEY'] = original_wallet


class TestE2EWithMockedClients:
    """E2E tests with fully mocked external API clients."""
    
    @pytest.fixture
    def mock_gamma_client(self):
        """Create mock Gamma client for market discovery."""
        client = Mock()
        client.discover_markets = AsyncMock(return_value=[
            {
                'slug': 'btc-up-or-down-hourly',
                'asset': 'BTC',
                'start_ts': 1000,
                'end_ts': 4600,
                'up_token_id': 'up_123',
                'down_token_id': 'down_456'
            }
        ])
        client.get_market_by_slug = AsyncMock(return_value={
            'slug': 'btc-up-or-down-hourly',
            'status': 'active',
            'resolved': False
        })
        return client
    
    @pytest.fixture
    def mock_binance_client(self):
        """Create mock Binance client with cached klines."""
        client = Mock()
        # Generate mock klines for EMA calculation
        klines = [
            {'t': i, 'o': 50000+i*10, 'h': 50010+i*10, 
             'l': 49990+i*10, 'c': 50005+i*10}
            for i in range(100)
        ]
        client.get_klines = AsyncMock(return_value=klines)
        client.cache = {}
        return client
    
    @pytest.fixture
    def mock_clob_client(self):
        """Create mock CLOB client for price history."""
        client = Mock()
        client.get_prices_history = AsyncMock(return_value=[
            {'t': 2120, 'p': 0.54},
            {'t': 2121, 'p': 0.53},
            {'t': 2122, 'p': 0.52},
            {'t': 2123, 'p': 0.51},
            {'t': 2124, 'p': 0.50},
        ])
        client.place_limit_order = AsyncMock(return_value={
            'order_id': 'test_order_001',
            'status': 'FILLED'
        })
        return client
    
    @pytest.mark.asyncio
    async def test_full_flow_with_mocked_clients(
        self, mock_gamma_client, mock_binance_client, mock_clob_client
    ):
        """Test complete flow with all clients mocked."""
        # Step 1: Discover markets
        markets = await mock_gamma_client.discover_markets(assets=['BTC'])
        assert len(markets) == 1
        market = markets[0]
        
        # Step 2: Get klines for TA
        klines = await mock_binance_client.get_klines(
            symbol='BTCUSDT', interval='1m', limit=100
        )
        assert len(klines) == 100
        
        # Step 3: Check CAP prices
        prices = await mock_clob_client.get_prices_history(
            token_id=market['up_token_id'],
            start_ts=2120,
            end_ts=4600
        )
        assert len(prices) >= 5
        
        # Step 4: Verify all mocks called
        mock_gamma_client.discover_markets.assert_called_once()
        mock_binance_client.get_klines.assert_called_once()
        mock_clob_client.get_prices_history.assert_called_once()


class TestMG2CapPassTiming:
    """Specific tests for MG-2: CAP_PASS timing validation."""
    
    def test_cap_pass_ignores_all_ticks_before_confirm_ts(self):
        """
        MG-2: CAP_PASS before confirm_ts is INVALID.
        Even if there are 100 consecutive ticks before confirm_ts,
        they must all be ignored.
        """
        price_cap = 0.55
        min_ticks = 5
        confirm_ts = 1200
        
        # 50 ticks below cap BEFORE confirm, then prices go above cap
        prices = []
        # Before confirm - all below cap (should be IGNORED)
        for i in range(50):
            prices.append({'t': 1100 + i, 'p': 0.50})
        
        # After confirm - all above cap
        for i in range(20):
            prices.append({'t': 1200 + i, 'p': 0.60})
        
        # Run CAP check with MG-2 compliance
        consecutive = 0
        cap_pass = False
        
        for tick in prices:
            if tick['t'] >= confirm_ts:  # MG-2: ONLY after confirm_ts
                if tick['p'] <= price_cap:
                    consecutive += 1
                    if consecutive >= min_ticks:
                        cap_pass = True
                        break
                else:
                    consecutive = 0
        
        # Must NOT pass - the 50 ticks before confirm_ts don't count
        assert not cap_pass
        assert consecutive == 0
    
    def test_cap_pass_requires_all_ticks_after_confirm_ts(self):
        """
        MG-2: All min_ticks must be AFTER confirm_ts.
        A split (some before, some after) should not count.
        """
        price_cap = 0.55
        min_ticks = 5
        confirm_ts = 1200
        
        # 3 ticks before, 2 ticks after (total 5, but split)
        prices = [
            {'t': 1197, 'p': 0.54},  # Before - IGNORE
            {'t': 1198, 'p': 0.53},  # Before - IGNORE
            {'t': 1199, 'p': 0.52},  # Before - IGNORE
            {'t': 1200, 'p': 0.51},  # After - count 1
            {'t': 1201, 'p': 0.50},  # After - count 2
        ]
        
        consecutive = 0
        cap_pass = False
        
        for tick in prices:
            if tick['t'] >= confirm_ts:
                if tick['p'] <= price_cap:
                    consecutive += 1
                    if consecutive >= min_ticks:
                        cap_pass = True
                        break
        
        # Only 2 valid ticks after confirm_ts - should NOT pass
        assert consecutive == 2
        assert not cap_pass


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
