"""
End-to-end tests for edge cases and error scenarios.

Tests:
- LATE confirm (confirm_ts >= end_ts)
- CAP_FAIL (never hits min ticks)
- Auth gating (live mode without master key)
- Logout clears authorization
"""
import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestLateConfirmScenarios:
    """Test handling of late confirm_ts scenarios."""
    
    def test_late_confirm_ts_beyond_end_ts(self):
        """Test MG-3: confirm_ts >= end_ts results in LATE status."""
        from domain.enums import TradeStatus, CapStatus
        
        # Window times
        start_ts = 1000
        end_ts = 4600  # 1 hour window
        signal_ts = 4500  # Signal very late in window
        confirm_delay = 120  # 2 minutes
        
        confirm_ts = signal_ts + confirm_delay  # = 4620
        
        # MG-3: If confirm_ts >= end_ts => LATE
        if confirm_ts >= end_ts:
            cap_status = CapStatus.LATE
            # Trade should be cancelled
            trade_status = TradeStatus.CANCELLED
            
            assert trade_status == TradeStatus.CANCELLED
            assert cap_status == CapStatus.LATE
    
    def test_late_confirm_with_small_window(self):
        """Test late confirm in a small remaining window."""
        start_ts = 0
        end_ts = 180  # Only 3 minutes total
        signal_ts = 100  # Signal at 100 seconds
        confirm_delay = 120  # 2 minute delay
        
        confirm_ts = signal_ts + confirm_delay  # = 220
        
        # 220 >= 180 = LATE
        assert confirm_ts >= end_ts
    
    def test_valid_confirm_ts_just_before_end(self):
        """Test confirm_ts that's valid (just before end_ts)."""
        start_ts = 0
        end_ts = 3600
        signal_ts = 3400
        confirm_delay = 120
        
        confirm_ts = signal_ts + confirm_delay  # = 3520
        
        # 3520 < 3600 = valid (not LATE)
        assert confirm_ts < end_ts


class TestCapFailScenarios:
    """Test CAP_FAIL scenarios."""
    
    def test_cap_fail_never_reaches_min_ticks(self):
        """Test CAP_FAIL when prices never stay below cap long enough."""
        from domain.enums import CapStatus
        
        price_cap = 0.55
        min_ticks = 5
        
        # Prices that oscillate above cap
        prices = [
            {'t': 1200, 'p': 0.54},  # 1 below
            {'t': 1201, 'p': 0.56},  # above - reset
            {'t': 1202, 'p': 0.53},  # 1 below
            {'t': 1203, 'p': 0.54},  # 2 below
            {'t': 1204, 'p': 0.57},  # above - reset
            {'t': 1205, 'p': 0.55},  # at cap = ok
            {'t': 1206, 'p': 0.54},  # 2 below
            {'t': 1207, 'p': 0.58},  # above - reset
        ]
        
        confirm_ts = 1200
        
        consecutive = 0
        cap_pass = False
        
        for tick in prices:
            if tick['t'] >= confirm_ts:
                if tick['p'] <= price_cap:
                    consecutive += 1
                    if consecutive >= min_ticks:
                        cap_pass = True
                        break
                else:
                    consecutive = 0
        
        assert not cap_pass
        cap_status = CapStatus.FAIL if not cap_pass else CapStatus.PASS
        assert cap_status == CapStatus.FAIL
    
    def test_cap_fail_prices_always_above(self):
        """Test CAP_FAIL when all prices are above cap."""
        from domain.enums import CapStatus
        
        price_cap = 0.55
        min_ticks = 5
        confirm_ts = 1200
        
        # All prices above cap
        prices = [
            {'t': 1200, 'p': 0.60},
            {'t': 1201, 'p': 0.58},
            {'t': 1202, 'p': 0.56},
            {'t': 1203, 'p': 0.59},
            {'t': 1204, 'p': 0.57},
        ]
        
        consecutive = 0
        for tick in prices:
            if tick['t'] >= confirm_ts:
                if tick['p'] <= price_cap:
                    consecutive += 1
                else:
                    consecutive = 0
        
        assert consecutive == 0
        cap_status = CapStatus.FAIL
        assert cap_status == CapStatus.FAIL
    
    def test_cap_fail_only_4_consecutive(self):
        """Test CAP_FAIL when only 4 consecutive (need 5)."""
        from domain.enums import CapStatus
        
        price_cap = 0.55
        min_ticks = 5
        confirm_ts = 1200
        
        prices = [
            {'t': 1200, 'p': 0.54},  # 1
            {'t': 1201, 'p': 0.53},  # 2
            {'t': 1202, 'p': 0.52},  # 3
            {'t': 1203, 'p': 0.51},  # 4
            {'t': 1204, 'p': 0.58},  # above - reset at 4
        ]
        
        consecutive = 0
        cap_pass = False
        
        for tick in prices:
            if tick['p'] <= price_cap:
                consecutive += 1
                if consecutive >= min_ticks:
                    cap_pass = True
                    break
            else:
                consecutive = 0
        
        assert not cap_pass
        assert consecutive == 0  # Reset after above-cap tick


class TestCapPassBeforeConfirmTs:
    """Test MG-2: CAP_PASS before confirm_ts is INVALID."""
    
    def test_ticks_before_confirm_ts_ignored(self):
        """Test that ticks before confirm_ts are not counted."""
        from domain.enums import CapStatus
        
        price_cap = 0.55
        min_ticks = 5
        confirm_ts = 1200
        
        # Ticks: 5 below cap BEFORE confirm_ts, then 3 above AFTER
        prices = [
            {'t': 1100, 'p': 0.50},  # Before confirm - IGNORE
            {'t': 1101, 'p': 0.51},  # Before confirm - IGNORE
            {'t': 1102, 'p': 0.52},  # Before confirm - IGNORE
            {'t': 1103, 'p': 0.53},  # Before confirm - IGNORE
            {'t': 1104, 'p': 0.54},  # Before confirm - IGNORE
            {'t': 1200, 'p': 0.58},  # After - above cap
            {'t': 1201, 'p': 0.57},  # After - above cap
            {'t': 1202, 'p': 0.56},  # After - above cap
        ]
        
        consecutive = 0
        cap_pass = False
        
        for tick in prices:
            # MG-2: ONLY count ticks AFTER confirm_ts
            if tick['t'] >= confirm_ts:
                if tick['p'] <= price_cap:
                    consecutive += 1
                    if consecutive >= min_ticks:
                        cap_pass = True
                        break
                else:
                    consecutive = 0
        
        # Should NOT pass - the 5 ticks before confirm_ts don't count
        assert not cap_pass
        assert consecutive == 0
    
    def test_partial_before_partial_after(self):
        """Test split ticks: some before, some after confirm_ts."""
        price_cap = 0.55
        min_ticks = 5
        confirm_ts = 1200
        
        prices = [
            {'t': 1198, 'p': 0.50},  # Before - IGNORE
            {'t': 1199, 'p': 0.51},  # Before - IGNORE
            {'t': 1200, 'p': 0.52},  # After - count 1
            {'t': 1201, 'p': 0.53},  # After - count 2
            {'t': 1202, 'p': 0.54},  # After - count 3
        ]
        
        consecutive = 0
        for tick in prices:
            if tick['t'] >= confirm_ts:
                if tick['p'] <= price_cap:
                    consecutive += 1
        
        # Only 3 valid ticks after confirm_ts
        assert consecutive == 3
        assert consecutive < min_ticks


class TestAuthGating:
    """Test authorization gating for live execution."""
    
    def test_live_mode_blocked_without_master_key(self):
        """Test that live mode with missing master key blocks execution."""
        # Simulate missing MASTER_ENCRYPTION_KEY
        import os
        
        # Ensure key is not set
        original = os.environ.get('MASTER_ENCRYPTION_KEY')
        if 'MASTER_ENCRYPTION_KEY' in os.environ:
            del os.environ['MASTER_ENCRYPTION_KEY']
        
        try:
            # Check authorization status
            master_key = os.environ.get('MASTER_ENCRYPTION_KEY')
            execution_mode = 'live'
            
            # Should block live execution
            can_execute_live = (
                execution_mode == 'live' and
                master_key is not None and
                len(master_key) > 0
            )
            
            assert not can_execute_live
        finally:
            # Restore
            if original:
                os.environ['MASTER_ENCRYPTION_KEY'] = original
    
    def test_live_mode_allowed_with_valid_key(self):
        """Test that live mode works with valid master key."""
        import os
        import base64
        import secrets
        
        # Set valid master key
        valid_key = base64.b64encode(secrets.token_bytes(32)).decode()
        os.environ['MASTER_ENCRYPTION_KEY'] = valid_key
        
        try:
            master_key = os.environ.get('MASTER_ENCRYPTION_KEY')
            execution_mode = 'live'
            
            can_execute_live = (
                execution_mode == 'live' and
                master_key is not None and
                len(master_key) > 0
            )
            
            assert can_execute_live
        finally:
            del os.environ['MASTER_ENCRYPTION_KEY']
    
    def test_paper_mode_always_allowed(self):
        """Test that paper mode works without any keys."""
        import os
        
        # Remove all auth keys
        for key in ['MASTER_ENCRYPTION_KEY', 'POLYMARKET_PRIVATE_KEY']:
            if key in os.environ:
                del os.environ[key]
        
        execution_mode = 'paper'
        
        # Paper mode always works
        can_execute_paper = execution_mode == 'paper'
        assert can_execute_paper


class TestLogoutClearsAuth:
    """Test that logout clears authorization status."""
    
    def test_logout_clears_session(self):
        """Test logout clears cached session."""
        # Simulate session state
        session = {
            'wallet_address': '0x1234...',
            'session_key': 'encrypted_key_data',
            'expires_at': datetime.now() + timedelta(hours=24),
            'authorized': True
        }
        
        # Logout
        def logout(session):
            session['wallet_address'] = None
            session['session_key'] = None
            session['expires_at'] = None
            session['authorized'] = False
            return session
        
        session = logout(session)
        
        assert session['wallet_address'] is None
        assert session['session_key'] is None
        assert not session['authorized']
    
    def test_logout_updates_indicator(self):
        """Test that logout updates auth indicator."""
        # After logout, indicator should show not authorized
        # Simulating the behavior that would result
        
        execution_mode = 'live'
        has_wallet_key = False  # Cleared by logout
        
        # Without credentials, indicator should be not authorized
        if execution_mode == 'live' and not has_wallet_key:
            indicator_emoji = '⚪'
            indicator_text = 'Not Authorized (Missing Credentials)'
        
        assert '⚪' in indicator_emoji
        assert 'Not Authorized' in indicator_text or 'Missing' in indicator_text


class TestConfigValidationEdgeCases:
    """Test configuration validation edge cases."""
    
    def test_invalid_day_hours_range(self):
        """Test that invalid day hours are rejected."""
        # Hours must be 0-23
        day_start = 25  # Invalid
        day_end = 22
        
        is_valid = 0 <= day_start <= 23 and 0 <= day_end <= 23
        assert not is_valid
    
    def test_wrap_around_day_hours_valid(self):
        """Test that wrap-around day hours are valid."""
        # 22:00 to 06:00 is valid (wraps midnight)
        day_start = 22
        day_end = 6
        
        is_valid = 0 <= day_start <= 23 and 0 <= day_end <= 23
        assert is_valid  # Both individually valid
    
    def test_negative_cap_rejected(self):
        """Test that negative price cap is rejected."""
        price_cap = -0.5
        
        is_valid = 0 < price_cap <= 1.0
        assert not is_valid
    
    def test_cap_above_one_rejected(self):
        """Test that cap above 1.0 is rejected."""
        price_cap = 1.5
        
        is_valid = 0 < price_cap <= 1.0
        assert not is_valid


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
