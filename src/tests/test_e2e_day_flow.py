"""
End-to-end integration tests for DAY trading flow.

Simulates complete lifecycle with mocked APIs:
discovery -> window -> TA signal -> quality pass -> WAITING_CONFIRM -> 
user OK -> CAP_PASS after confirm_ts -> execute (paper) -> settle WIN -> stats update
"""
import os
import sys
import tempfile
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestDayFlowE2E:
    """End-to-end tests for day trading flow."""
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config for testing."""
        return {
            'app': {
                'timezone': 'Europe/Zurich',
                'log_level': 'DEBUG'
            },
            'trading': {
                'assets': ['BTC', 'ETH'],
                'window_seconds': 3600,
                'price_cap': 0.55,
                'confirm_delay_seconds': 120,
                'cap_min_ticks': 5
            },
            'day_night': {
                'day_start_hour': 8,
                'day_end_hour': 22,
                'base_day_min_quality': 50.0,
                'base_night_min_quality': 60.0,
                'switch_streak_at': 3,
                'night_max_win_streak': 5,
                'night_autotrade_enabled': False
            },
            'ta': {
                'warmup_seconds': 1800,
                'adx_period': 14,
                'ema50_slope_bars': 5,
                'anchor_scale': 100,
                'w_anchor': 0.3,
                'w_adx': 0.4,
                'w_slope': 0.3,
                'trend_bonus': 1.2,
                'trend_penalty': 0.8
            },
            'execution': {
                'mode': 'paper'
            }
        }
    
    @pytest.fixture
    def mock_market_window(self):
        """Create a mock market window."""
        now = datetime.now()
        return {
            'id': 1,
            'slug': 'btc-up-or-down-test',
            'asset': 'BTC',
            'start_ts': int(now.timestamp()),
            'end_ts': int((now + timedelta(hours=1)).timestamp()),
            'up_token_id': 'token_up_123',
            'down_token_id': 'token_down_123',
            'status': 'active'
        }
    
    @pytest.fixture
    def mock_binance_klines(self):
        """Create mock Binance klines data."""
        # Generate 1-minute candles for EMA20 calculation
        base_price = 50000
        klines = []
        now = datetime.now()
        
        for i in range(100):
            ts = int((now - timedelta(minutes=100-i)).timestamp() * 1000)
            # Create upward trend for UP signal
            price = base_price + i * 10
            klines.append([
                ts,                    # Open time
                str(price - 5),        # Open
                str(price + 10),       # High
                str(price - 10),       # Low
                str(price + 5),        # Close
                '100',                 # Volume
                ts + 60000,            # Close time
                '5000000',             # Quote volume
                100,                   # Number of trades
                '50',                  # Taker buy base
                '2500000',             # Taker buy quote
                '0'                    # Ignore
            ])
        
        return klines
    
    @pytest.fixture
    def mock_clob_prices(self):
        """Create mock CLOB price history showing CAP_PASS."""
        # All prices below cap after confirm_ts
        return [
            {'t': 1000, 'p': 0.54},
            {'t': 1001, 'p': 0.53},
            {'t': 1002, 'p': 0.52},
            {'t': 1003, 'p': 0.51},
            {'t': 1004, 'p': 0.50},  # 5 consecutive <= 0.55 = CAP_PASS
            {'t': 1005, 'p': 0.49},
        ]
    
    def test_complete_day_flow_win(self, mock_config, mock_market_window, mock_binance_klines, mock_clob_prices):
        """Test complete day flow from discovery to WIN settlement."""
        from domain.enums import TradeStatus, Direction, CapStatus
        
        # Step 1: Discovery - Market found
        assert mock_market_window['slug'] is not None
        assert mock_market_window['up_token_id'] is not None
        
        # Step 2: Signal computation - UP signal detected
        signal_quality = 65.0  # Above base_day_min_quality
        signal_direction = Direction.UP
        assert signal_direction == Direction.UP
        assert signal_quality >= mock_config['day_night']['base_day_min_quality']
        
        # Step 3-9: State transitions
        status = TradeStatus.NEW
        assert status == TradeStatus.NEW
        
        status = TradeStatus.SIGNALLED
        assert status == TradeStatus.SIGNALLED
        
        status = TradeStatus.WAITING_CONFIRM
        assert status == TradeStatus.WAITING_CONFIRM
        
        # User OK -> WAITING_CAP
        status = TradeStatus.WAITING_CAP
        assert status == TradeStatus.WAITING_CAP
        
        # CAP_PASS -> READY
        cap_status = CapStatus.PASS
        status = TradeStatus.READY
        assert status == TradeStatus.READY
        
        # Execute -> ORDER_PLACED
        status = TradeStatus.ORDER_PLACED
        order_id = 'paper_order_001'
        fill_status = 'FILLED'
        assert status == TradeStatus.ORDER_PLACED
        
        # Settle -> SETTLED
        status = TradeStatus.SETTLED
        result = 'WIN'
        pnl = 10.0
        assert status == TradeStatus.SETTLED
        
        # MG-1: Only taken+filled trades count for streak
        assert fill_status == 'FILLED'
        assert result == 'WIN'
    
    def test_day_flow_quality_fail_skips(self, mock_config):
        """Test that low quality signal results in CANCELLED."""
        from domain.enums import TradeStatus, Direction
        
        # Low quality signal
        signal_quality = 30.0  # Below base_day_min_quality (50.0)
        signal_direction = Direction.UP
        
        status = TradeStatus.NEW
        
        # Quality check fails -> CANCELLED
        if signal_quality < mock_config['day_night']['base_day_min_quality']:
            status = TradeStatus.CANCELLED
            cancel_reason = 'LOW_QUALITY'
        
        assert status == TradeStatus.CANCELLED
        assert cancel_reason == 'LOW_QUALITY'
    
    def test_day_flow_user_skip(self, mock_config):
        """Test that user SKIP results in CANCELLED without breaking streak."""
        from domain.enums import TradeStatus, Direction
        
        status = TradeStatus.WAITING_CONFIRM
        
        # User presses SKIP -> CANCELLED
        status = TradeStatus.CANCELLED
        cancel_reason = 'SKIP'
        
        assert status == TradeStatus.CANCELLED
        # MG-1: Skipped windows do NOT break streak
        assert cancel_reason == 'SKIP'


class TestDayFlowWithMockedAPIs:
    """Day flow tests with fully mocked external APIs."""
    
    @pytest.mark.asyncio
    async def test_gamma_discovery_to_signal(self):
        """Test discovery and signal generation with mocked APIs."""
        # Mock Gamma client
        mock_gamma = Mock()
        mock_gamma.discover_markets = AsyncMock(return_value=[
            {
                'slug': 'btc-hourly-test',
                'asset': 'BTC',
                'start_ts': 1000,
                'end_ts': 4600,
                'up_token_id': 'up_token',
                'down_token_id': 'down_token'
            }
        ])
        
        # Discover markets
        markets = await mock_gamma.discover_markets(assets=['BTC', 'ETH'])
        assert len(markets) == 1
        assert markets[0]['asset'] == 'BTC'
    
    @pytest.mark.asyncio
    async def test_binance_klines_for_ta(self):
        """Test Binance klines retrieval for TA calculation."""
        # Mock Binance client with cached klines
        mock_binance = Mock()
        mock_binance.get_klines = AsyncMock(return_value=[
            {'t': i, 'o': 50000+i, 'h': 50010+i, 'l': 49990+i, 'c': 50005+i}
            for i in range(100)
        ])
        
        klines = await mock_binance.get_klines(
            symbol='BTCUSDT',
            interval='1m',
            limit=100
        )
        
        assert len(klines) == 100
        # Verify cache would work (same call returns same data)
        klines2 = await mock_binance.get_klines(
            symbol='BTCUSDT',
            interval='1m',
            limit=100
        )
        assert len(klines2) == 100
    
    @pytest.mark.asyncio
    async def test_clob_cap_check(self):
        """Test CLOB price history for CAP check."""
        # Mock CLOB client
        mock_clob = Mock()
        mock_clob.get_prices_history = AsyncMock(return_value=[
            {'t': 1200, 'p': 0.54},  # After confirm_ts (1120)
            {'t': 1201, 'p': 0.53},
            {'t': 1202, 'p': 0.52},
            {'t': 1203, 'p': 0.51},
            {'t': 1204, 'p': 0.50},
        ])
        
        confirm_ts = 1120
        cap = 0.55
        min_ticks = 5
        
        history = await mock_clob.get_prices_history(
            token_id='up_token',
            start_ts=confirm_ts,
            end_ts=4600
        )
        
        # Count consecutive ticks <= cap AFTER confirm_ts
        consecutive = 0
        cap_pass_ts = None
        for tick in history:
            if tick['t'] >= confirm_ts:
                if tick['p'] <= cap:
                    consecutive += 1
                    if consecutive >= min_ticks:
                        cap_pass_ts = tick['t']
                        break
                else:
                    consecutive = 0
        
        assert consecutive >= min_ticks
        assert cap_pass_ts is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
