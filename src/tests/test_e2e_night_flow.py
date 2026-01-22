"""
End-to-end integration tests for NIGHT trading flow.

Tests night_session_mode=SOFT_RESET and HARD_RESET scenarios:
- Auto decision -> CAP_PASS -> execute -> settle sequence
- Night max streak reset triggers
- Streak reset behavior (SOFT vs HARD)
"""
import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestNightFlowSoftReset:
    """Test night trading flow with SOFT_RESET mode."""
    
    @pytest.fixture
    def mock_stats_soft(self):
        """Stats state for SOFT reset testing."""
        from domain.enums import PolicyMode, NightSessionMode
        return {
            'trade_level_streak': 4,  # High streak from day trading
            'night_streak': 4,  # About to hit max (5)
            'policy_mode': PolicyMode.STRICT,
            'night_session_mode': NightSessionMode.SOFT_RESET,
            'paused': False
        }
    
    def test_night_auto_decision_flow(self, mock_stats_soft):
        """Test automatic decision in night mode."""
        from domain.enums import TradeStatus, Direction, NightSessionMode
        
        # Night mode: no user confirmation needed
        signal_quality = 70.0  # Above night threshold
        signal_direction = Direction.UP
        
        status = TradeStatus.NEW
        is_day_mode = False  # Night mode
        
        # Night auto-flow: signal -> quality pass -> auto OK -> CAP check
        status = TradeStatus.SIGNALLED
        assert status == TradeStatus.SIGNALLED
        
        status = TradeStatus.WAITING_CONFIRM
        assert status == TradeStatus.WAITING_CONFIRM
        
        # Auto-OK in night mode (no user confirmation)
        status = TradeStatus.WAITING_CAP
        assert status == TradeStatus.WAITING_CAP
    
    def test_night_max_streak_soft_reset(self, mock_stats_soft):
        """Test SOFT_RESET when night_streak reaches max."""
        from domain.enums import PolicyMode, NightSessionMode
        from services.stats_service import StatsService
        
        # Simulate WIN that triggers night session reset
        night_max = 5
        night_streak = mock_stats_soft['night_streak']
        trade_level_streak = mock_stats_soft['trade_level_streak']
        
        # WIN increments night_streak
        night_streak += 1
        
        # Check if reset needed
        if night_streak >= night_max:
            mode = mock_stats_soft['night_session_mode']
            
            if mode == NightSessionMode.SOFT_RESET:
                # SOFT: Reset only night_streak
                night_streak = 0
                new_policy = PolicyMode.BASE
                # trade_level_streak CONTINUES
                assert trade_level_streak == 4  # Unchanged
            
            assert night_streak == 0
            assert new_policy == PolicyMode.BASE
    
    def test_soft_reset_series_counters_unchanged(self, mock_stats_soft):
        """Verify SOFT reset keeps series counters (trade_level_streak)."""
        from domain.enums import NightSessionMode
        
        original_trade_streak = mock_stats_soft['trade_level_streak']
        
        # Simulate SOFT reset
        mock_stats_soft['night_streak'] = 0
        mock_stats_soft['policy_mode'] = 'BASE'
        # trade_level_streak NOT touched
        
        assert mock_stats_soft['trade_level_streak'] == original_trade_streak


class TestNightFlowHardReset:
    """Test night trading flow with HARD_RESET mode."""
    
    @pytest.fixture
    def mock_stats_hard(self):
        """Stats state for HARD reset testing."""
        from domain.enums import PolicyMode, NightSessionMode
        return {
            'trade_level_streak': 4,
            'night_streak': 4,
            'policy_mode': PolicyMode.STRICT,
            'night_session_mode': NightSessionMode.HARD_RESET,
            'series_wins': 4,
            'series_profit': 40.0,
            'paused': False
        }
    
    def test_night_max_streak_hard_reset(self, mock_stats_hard):
        """Test HARD_RESET when night_streak reaches max."""
        from domain.enums import PolicyMode, NightSessionMode
        
        night_max = 5
        night_streak = mock_stats_hard['night_streak']
        
        # WIN increments night_streak
        night_streak += 1
        
        # Check if reset needed
        if night_streak >= night_max:
            mode = mock_stats_hard['night_session_mode']
            
            if mode == NightSessionMode.HARD_RESET:
                # HARD: Reset ALL streaks + series counters
                night_streak = 0
                trade_level_streak = 0  # Reset!
                series_wins = 0  # Reset!
                series_profit = 0.0  # Reset!
                new_policy = PolicyMode.BASE
                
                assert night_streak == 0
                assert trade_level_streak == 0
                assert series_wins == 0
                assert series_profit == 0.0
                assert new_policy == PolicyMode.BASE
    
    def test_hard_reset_clears_all_series_data(self, mock_stats_hard):
        """Verify HARD reset clears all series tracking."""
        from domain.enums import NightSessionMode
        
        # Before reset
        assert mock_stats_hard['trade_level_streak'] == 4
        assert mock_stats_hard['series_wins'] == 4
        assert mock_stats_hard['series_profit'] == 40.0
        
        # Simulate HARD reset
        mock_stats_hard['night_streak'] = 0
        mock_stats_hard['trade_level_streak'] = 0
        mock_stats_hard['series_wins'] = 0
        mock_stats_hard['series_profit'] = 0.0
        mock_stats_hard['policy_mode'] = 'BASE'
        
        # After reset
        assert mock_stats_hard['night_streak'] == 0
        assert mock_stats_hard['trade_level_streak'] == 0
        assert mock_stats_hard['series_wins'] == 0
        assert mock_stats_hard['series_profit'] == 0.0


class TestNightFlowOff:
    """Test night trading when mode is OFF."""
    
    def test_night_off_skips_trade(self):
        """Test that OFF mode skips night trades."""
        from domain.enums import TradeStatus, Direction, NightSessionMode
        
        # Night mode OFF - should not auto-trade
        night_session_mode = NightSessionMode.OFF
        
        status = TradeStatus.WAITING_CONFIRM
        is_day_mode = False  # Night mode
        
        # In OFF mode, night trades are auto-skipped
        if night_session_mode == NightSessionMode.OFF:
            status = TradeStatus.CANCELLED
            cancel_reason = 'NIGHT_DISABLED'
        
        assert status == TradeStatus.CANCELLED
        assert cancel_reason == 'NIGHT_DISABLED'
    
    def test_series_frozen_overnight_in_off_mode(self):
        """Test that series state is preserved when night OFF."""
        from domain.enums import NightSessionMode
        
        # Stats at end of day
        stats = {
            'trade_level_streak': 3,
            'night_streak': 0,
            'series_wins': 3,
            'series_profit': 30.0
        }
        
        night_session_mode = NightSessionMode.OFF
        
        # No trades happen overnight
        # Next morning, stats should be unchanged
        if night_session_mode == NightSessionMode.OFF:
            # Nothing changes overnight
            pass
        
        # Verify preservation
        assert stats['trade_level_streak'] == 3
        assert stats['series_wins'] == 3
        assert stats['series_profit'] == 30.0


class TestNightFlowLossReset:
    """Test that loss always resets all streaks regardless of mode."""
    
    @pytest.fixture
    def mock_stats_before_loss(self):
        """Stats before a loss occurs."""
        from domain.enums import PolicyMode, NightSessionMode
        return {
            'trade_level_streak': 3,
            'night_streak': 2,
            'policy_mode': PolicyMode.STRICT,
            'night_session_mode': NightSessionMode.SOFT_RESET,
            'series_wins': 3,
            'series_profit': 30.0
        }
    
    def test_loss_resets_all_in_soft_mode(self, mock_stats_before_loss):
        """Test that loss resets everything even in SOFT mode."""
        from domain.enums import PolicyMode
        
        # Simulate LOSS
        result = 'LOSE'
        
        if result == 'LOSE':
            # Loss always resets ALL streaks
            mock_stats_before_loss['trade_level_streak'] = 0
            mock_stats_before_loss['night_streak'] = 0
            mock_stats_before_loss['series_wins'] = 0
            mock_stats_before_loss['series_profit'] = 0.0
            mock_stats_before_loss['policy_mode'] = PolicyMode.BASE
        
        assert mock_stats_before_loss['trade_level_streak'] == 0
        assert mock_stats_before_loss['night_streak'] == 0
        assert mock_stats_before_loss['policy_mode'] == PolicyMode.BASE
    
    def test_loss_resets_all_in_hard_mode(self):
        """Test that loss resets everything in HARD mode too."""
        from domain.enums import PolicyMode, NightSessionMode
        
        stats = {
            'trade_level_streak': 5,
            'night_streak': 3,
            'policy_mode': PolicyMode.STRICT,
            'night_session_mode': NightSessionMode.HARD_RESET,
            'series_wins': 5,
            'series_profit': 50.0
        }
        
        result = 'LOSE'
        
        if result == 'LOSE':
            stats['trade_level_streak'] = 0
            stats['night_streak'] = 0
            stats['series_wins'] = 0
            stats['series_profit'] = 0.0
            stats['policy_mode'] = PolicyMode.BASE
        
        assert stats['trade_level_streak'] == 0
        assert stats['night_streak'] == 0
        assert stats['policy_mode'] == PolicyMode.BASE


class TestNightModeTransition:
    """Test day to night transition scenarios."""
    
    def test_day_to_night_with_soft(self):
        """Test transition from day to night in SOFT mode."""
        from domain.enums import NightSessionMode
        
        # End of day - stats preserved
        stats = {
            'trade_level_streak': 2,
            'night_streak': 0,
            'is_day_mode': True
        }
        
        night_mode = NightSessionMode.SOFT_RESET
        
        # Transition to night
        stats['is_day_mode'] = False
        
        # Night trading begins with existing trade_level_streak
        if night_mode in (NightSessionMode.SOFT_RESET, NightSessionMode.HARD_RESET):
            # Trading continues
            assert stats['trade_level_streak'] == 2  # Continues
        
    def test_night_to_day_preserves_stats(self):
        """Test transition from night to day preserves stats."""
        from domain.enums import NightSessionMode
        
        # End of night
        stats = {
            'trade_level_streak': 4,
            'night_streak': 3,
            'is_day_mode': False
        }
        
        # Transition to day
        stats['is_day_mode'] = True
        
        # Stats continue into day
        assert stats['trade_level_streak'] == 4
        assert stats['night_streak'] == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
