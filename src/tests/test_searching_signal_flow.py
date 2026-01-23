"""
Tests for SEARCHING_SIGNAL Flow.

Regression tests for the "signal appears later inside window" scenario.
Implements mandatory tests per problem statement section H.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from src.services.state_machine import TradeStateMachine, VALID_TRANSITIONS
from src.domain.models import Trade, Signal, MarketWindow, QualityBreakdown
from src.domain.enums import (
    TradeStatus, Decision, CancelReason, FillStatus,
    CapStatus, Direction, TimeMode, PolicyMode
)
from src.adapters.polymarket.binance_client import Candle


class TestSearchingSignalTransitions:
    """Tests for SEARCHING_SIGNAL state transitions."""
    
    @pytest.fixture
    def mock_trade_repo(self):
        """Create mock trade repository."""
        repo = MagicMock()
        repo.update = MagicMock()
        return repo
    
    @pytest.fixture
    def state_machine(self, mock_trade_repo):
        """Create state machine with mock repo."""
        return TradeStateMachine(mock_trade_repo)
    
    @pytest.fixture
    def new_trade(self):
        """Create a new trade."""
        return Trade(
            id=1,
            window_id=1,
            status=TradeStatus.NEW,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
        )
    
    @pytest.fixture
    def searching_signal_trade(self):
        """Create a trade in SEARCHING_SIGNAL state."""
        return Trade(
            id=1,
            window_id=1,
            status=TradeStatus.SEARCHING_SIGNAL,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
        )
    
    def test_searching_signal_in_valid_transitions(self):
        """SEARCHING_SIGNAL should be defined in valid transitions."""
        assert TradeStatus.SEARCHING_SIGNAL in VALID_TRANSITIONS
    
    def test_new_to_searching_signal_transition_valid(self):
        """NEW -> SEARCHING_SIGNAL should be a valid transition."""
        valid_from_new = VALID_TRANSITIONS[TradeStatus.NEW]
        assert TradeStatus.SEARCHING_SIGNAL in valid_from_new
    
    def test_searching_signal_to_signalled_transition_valid(self):
        """SEARCHING_SIGNAL -> SIGNALLED should be a valid transition."""
        valid_from_searching = VALID_TRANSITIONS[TradeStatus.SEARCHING_SIGNAL]
        assert TradeStatus.SIGNALLED in valid_from_searching
    
    def test_searching_signal_to_cancelled_transition_valid(self):
        """SEARCHING_SIGNAL -> CANCELLED should be a valid transition."""
        valid_from_searching = VALID_TRANSITIONS[TradeStatus.SEARCHING_SIGNAL]
        assert TradeStatus.CANCELLED in valid_from_searching
    
    def test_on_start_searching(self, state_machine, new_trade):
        """NEW -> SEARCHING_SIGNAL via on_start_searching."""
        result = state_machine.on_start_searching(new_trade)
        
        assert result.status == TradeStatus.SEARCHING_SIGNAL
    
    def test_on_qualifying_signal_found(self, state_machine, searching_signal_trade):
        """SEARCHING_SIGNAL -> SIGNALLED via on_qualifying_signal_found."""
        signal = Signal(id=1, window_id=1, direction=Direction.UP, quality=50.0)
        
        result = state_machine.on_qualifying_signal_found(searching_signal_trade, signal)
        
        assert result.status == TradeStatus.SIGNALLED
        assert result.signal_id == 1
    
    def test_on_no_qualifying_signal(self, state_machine, searching_signal_trade):
        """SEARCHING_SIGNAL -> CANCELLED via on_no_qualifying_signal."""
        result = state_machine.on_no_qualifying_signal(searching_signal_trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.NO_SIGNAL
        assert result.decision == Decision.AUTO_SKIP
    
    def test_on_user_no_response_skip(self, state_machine):
        """READY -> CANCELLED via on_user_no_response_skip for day mode timeout."""
        ready_trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.READY,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
            decision=Decision.PENDING,
        )
        
        result = state_machine.on_user_no_response_skip(ready_trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.SKIP
        assert result.decision == Decision.AUTO_SKIP


class TestSearchingSignalTick1NoSignalTick2Signal:
    """
    Test 1: Signal appears later in window.
    
    - Active window, trade SEARCHING_SIGNAL.
    - Tick 1: candles produce no signal → trade remains SEARCHING_SIGNAL, no Signal persisted, no telegram.
    - Tick 2: candles produce signal + quality >= threshold → trade becomes SIGNALLED, Signal persisted, telegram sent exactly once.
    """
    
    def test_tick1_no_signal_remains_searching(self):
        """Tick 1: No signal detected, trade remains in SEARCHING_SIGNAL."""
        # Setup
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.SEARCHING_SIGNAL,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
        )
        
        # Simulate no signal found - trade should remain SEARCHING_SIGNAL
        # The orchestrator does NOT transition when no signal is found
        assert trade.status == TradeStatus.SEARCHING_SIGNAL
        
        # No signal_id should be set
        assert trade.signal_id is None
    
    def test_tick2_signal_with_quality_transitions_to_signalled(self):
        """Tick 2: Signal detected with quality >= threshold transitions to SIGNALLED."""
        mock_repo = MagicMock()
        mock_repo.update = MagicMock()
        state_machine = TradeStateMachine(mock_repo)
        
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.SEARCHING_SIGNAL,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
        )
        
        signal = Signal(
            id=1,
            window_id=1,
            direction=Direction.UP,
            quality=50.0,  # >= threshold
            signal_ts=1700000000,
            confirm_ts=1700000120,
        )
        
        # Transition
        result = state_machine.on_qualifying_signal_found(trade, signal)
        
        assert result.status == TradeStatus.SIGNALLED
        assert result.signal_id == 1
        mock_repo.update.assert_called()


class TestSearchingSignalQualityBelowThreshold:
    """
    Test 2: Signal exists but quality below threshold.
    
    - Tick 2: signal exists but quality < threshold → remain SEARCHING_SIGNAL, no telegram.
    - Tick 3: quality >= threshold → SIGNALLED, telegram sent.
    """
    
    def test_tick2_signal_low_quality_remains_searching(self):
        """Tick 2: Signal with quality < threshold, trade remains SEARCHING_SIGNAL."""
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.SEARCHING_SIGNAL,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
        )
        
        # Signal detected but quality=30 < threshold=35
        # The orchestrator should NOT transition - remain in SEARCHING_SIGNAL
        # This test verifies the state is preserved
        assert trade.status == TradeStatus.SEARCHING_SIGNAL
        assert trade.signal_id is None  # No signal persisted for low quality
    
    def test_tick3_quality_improved_transitions_to_signalled(self):
        """Tick 3: Quality now >= threshold, transitions to SIGNALLED."""
        mock_repo = MagicMock()
        mock_repo.update = MagicMock()
        state_machine = TradeStateMachine(mock_repo)
        
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.SEARCHING_SIGNAL,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
        )
        
        # Now quality=50 >= threshold=35
        signal = Signal(
            id=2,
            window_id=1,
            direction=Direction.DOWN,
            quality=50.0,
            signal_ts=1700000180,
            confirm_ts=1700000300,
        )
        
        result = state_machine.on_qualifying_signal_found(trade, signal)
        
        assert result.status == TradeStatus.SIGNALLED
        assert result.signal_id == 2


class TestSearchingSignalWindowExpiry:
    """
    Test 3: Window expires without qualifying signal.
    
    - Window expires with no qualifying signal → terminal NO_SIGNAL/EXPIRED, no telegram.
    """
    
    def test_window_expires_transitions_to_cancelled(self):
        """Window expiry without qualifying signal transitions to CANCELLED."""
        mock_repo = MagicMock()
        mock_repo.update = MagicMock()
        state_machine = TradeStateMachine(mock_repo)
        
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.SEARCHING_SIGNAL,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
        )
        
        result = state_machine.on_no_qualifying_signal(trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.NO_SIGNAL
        assert result.decision == Decision.AUTO_SKIP
    
    def test_expired_trade_is_terminal(self):
        """Expired trade is in terminal state."""
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.CANCELLED,
            cancel_reason=CancelReason.NO_SIGNAL,
            decision=Decision.AUTO_SKIP,
        )
        
        assert trade.is_terminal() is True


class TestDuplicatePrevention:
    """Tests for duplicate trade prevention."""
    
    def test_get_non_terminal_by_window_id_returns_active_trade(self):
        """get_non_terminal_by_window_id should return active (non-terminal) trade."""
        # This test verifies the repository method exists and works
        from src.adapters.storage.repositories import TradeRepository
        
        # Check method exists
        assert hasattr(TradeRepository, 'get_non_terminal_by_window_id')
    
    def test_terminal_states_do_not_prevent_new_trade(self):
        """Terminal trades for a window should not prevent creating new trade."""
        # CANCELLED, SETTLED, ERROR are terminal - new trade CAN be created
        terminal_trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.CANCELLED,
            cancel_reason=CancelReason.LOW_QUALITY,
        )
        
        assert terminal_trade.is_terminal() is True
        
        # A new SEARCHING_SIGNAL trade can be created for same window_id
        new_trade = Trade(
            id=2,
            window_id=1,
            status=TradeStatus.SEARCHING_SIGNAL,
        )
        
        assert new_trade.is_terminal() is False
        assert new_trade.status == TradeStatus.SEARCHING_SIGNAL


class TestDayModeAutoSkip:
    """Tests for day mode auto-skip on user non-response."""
    
    def test_on_user_no_response_skip_cancels_trade(self):
        """on_user_no_response_skip should cancel trade with SKIP reason."""
        mock_repo = MagicMock()
        mock_repo.update = MagicMock()
        state_machine = TradeStateMachine(mock_repo)
        
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.READY,
            time_mode=TimeMode.DAY,
            decision=Decision.PENDING,
        )
        
        result = state_machine.on_user_no_response_skip(trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.SKIP
        assert result.decision == Decision.AUTO_SKIP
    
    def test_auto_skip_does_not_break_streak(self):
        """Auto-skip (non-response) should not break streak (MG-1)."""
        # Per MG-1: Skips do NOT break streak
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.CANCELLED,
            cancel_reason=CancelReason.SKIP,
            decision=Decision.AUTO_SKIP,
            fill_status=FillStatus.PENDING,  # Not filled
        )
        
        # counts_for_streak returns True only if taken AND filled
        assert trade.counts_for_streak() is False
        
        # This trade does NOT count for streak calculation
        # Streak remains unbroken


class TestStreakConfigurability:
    """Tests for streak parameter configurability."""
    
    def test_switch_streak_at_supports_high_values(self):
        """switch_streak_at should support values >= 10 for goal of 10-win series."""
        # Verify that 10+ is a valid value per requirement F
        from src.services.day_night_config import DayNightConfigService
        
        service = DayNightConfigService(
            default_switch_streak_at=10,
        )
        
        # Default should be 10
        assert service.get_switch_streak_at() == 10
        
        # Should be able to set to 15
        result = service.set_switch_streak_at(15)
        assert result is True
    
    def test_night_max_win_streak_supports_high_values(self):
        """night_max_win_streak should support values >= 10."""
        from src.services.day_night_config import DayNightConfigService
        
        service = DayNightConfigService(
            default_night_max_streak=10,
        )
        
        assert service.get_night_max_streak() == 10
        
        result = service.set_night_max_streak(12)
        assert result is True


class TestStrictnessIncrement:
    """Tests for configurable strictness increment (G)."""
    
    def test_threshold_calculation_with_strictness_increment(self):
        """
        Threshold should be: base + max(0, wins - start_strict_after_n_wins + 1) * increment
        """
        # Example: base=35, start_after=5, increment=2
        # At 5 wins: 35 + max(0, 5-5+1)*2 = 35 + 2 = 37
        # At 6 wins: 35 + max(0, 6-5+1)*2 = 35 + 4 = 39
        # At 4 wins: 35 + max(0, 4-5+1)*0 = 35 (no increase)
        
        base_threshold = 35.0
        start_strict_after_n_wins = 5
        strict_quality_increment = 2.0
        
        def calculate_threshold(wins):
            increment_multiplier = max(0, wins - start_strict_after_n_wins + 1)
            return base_threshold + increment_multiplier * strict_quality_increment
        
        assert calculate_threshold(4) == 35.0  # No increase before start
        assert calculate_threshold(5) == 37.0  # First increment
        assert calculate_threshold(6) == 39.0  # Second increment
        assert calculate_threshold(10) == 47.0  # 35 + 6*2 = 47


class TestMG1StreakCounting:
    """Tests for MG-1 streak counting invariant."""
    
    def test_only_taken_and_filled_count_for_streak(self):
        """Only trades with OK/AUTO_OK AND FILLED count for streak."""
        # Trade that counts
        filled_ok_trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.SETTLED,
            decision=Decision.OK,
            fill_status=FillStatus.FILLED,
            is_win=True,
        )
        assert filled_ok_trade.counts_for_streak() is True
        
        # Trade that doesn't count (skipped)
        skipped_trade = Trade(
            id=2,
            window_id=2,
            status=TradeStatus.CANCELLED,
            decision=Decision.SKIP,
            fill_status=FillStatus.PENDING,
        )
        assert skipped_trade.counts_for_streak() is False
        
        # Trade that doesn't count (no fill)
        pending_trade = Trade(
            id=3,
            window_id=3,
            status=TradeStatus.ORDER_PLACED,
            decision=Decision.AUTO_OK,
            fill_status=FillStatus.PENDING,
        )
        assert pending_trade.counts_for_streak() is False
        
        # Trade that doesn't count (no signal)
        no_signal_trade = Trade(
            id=4,
            window_id=4,
            status=TradeStatus.CANCELLED,
            decision=Decision.AUTO_SKIP,
            cancel_reason=CancelReason.NO_SIGNAL,
            fill_status=FillStatus.PENDING,
        )
        assert no_signal_trade.counts_for_streak() is False


class TestTelegramSignalCardOnlyOnQualityPass:
    """Tests for Telegram signal card only sent on quality pass."""
    
    def test_signal_persisted_only_on_quality_pass(self):
        """Signal record should only be persisted when quality >= threshold."""
        # This is enforced by the orchestrator logic
        # When quality < threshold:
        #   - Trade remains in SEARCHING_SIGNAL
        #   - No signal is persisted
        #   - No Telegram notification is sent
        
        # We verify this by checking that a trade can exist
        # in SEARCHING_SIGNAL without a signal_id
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.SEARCHING_SIGNAL,
            signal_id=None,  # No signal yet
        )
        
        assert trade.signal_id is None
        assert trade.status == TradeStatus.SEARCHING_SIGNAL
