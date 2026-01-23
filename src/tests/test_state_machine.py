"""
Tests for Trade State Machine.

Ensures state transitions are correct per specification.
"""

import pytest
from unittest.mock import MagicMock

from src.services.state_machine import TradeStateMachine, VALID_TRANSITIONS
from src.domain.models import Trade, Signal, CapCheck
from src.domain.enums import (
    TradeStatus, Decision, CancelReason, FillStatus,
    CapStatus, Direction, TimeMode, PolicyMode
)
from src.common.exceptions import TradeError


class TestStateTransitions:
    """Tests for state machine transitions."""
    
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
    
    def test_valid_transitions_defined(self):
        """All states should have defined transitions."""
        all_states = set(TradeStatus)
        defined_states = set(VALID_TRANSITIONS.keys())
        
        assert all_states == defined_states
    
    def test_terminal_states_have_no_transitions(self):
        """Terminal states should have empty transition sets."""
        terminal_states = [TradeStatus.SETTLED, TradeStatus.CANCELLED, TradeStatus.ERROR]
        
        for state in terminal_states:
            assert VALID_TRANSITIONS[state] == set()
    
    def test_new_to_signalled(self, state_machine, new_trade):
        """NEW -> SIGNALLED on signal detection."""
        state_machine.on_searching_signal(new_trade)
        signal = Signal(id=1, window_id=1, direction=Direction.UP)
        
        result = state_machine.on_signal(new_trade, signal)
        
        assert result.status == TradeStatus.SIGNALLED
        assert result.signal_id == 1

    def test_new_to_searching_signal(self, state_machine, new_trade):
        """NEW -> SEARCHING_SIGNAL on start."""
        result = state_machine.on_searching_signal(new_trade)

        assert result.status == TradeStatus.SEARCHING_SIGNAL
    
    def test_new_to_cancelled_no_signal(self, state_machine, new_trade):
        """NEW -> CANCELLED on no signal."""
        result = state_machine.on_no_signal(new_trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.NO_SIGNAL
        assert result.decision == Decision.AUTO_SKIP
    
    def test_signalled_to_cancelled_low_quality(self, state_machine, new_trade):
        """SIGNALLED -> CANCELLED on low quality."""
        new_trade.status = TradeStatus.SIGNALLED
        
        result = state_machine.on_low_quality(new_trade, quality=30.0, threshold=50.0)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.LOW_QUALITY
    
    def test_signalled_to_waiting_confirm(self, state_machine, new_trade):
        """SIGNALLED -> WAITING_CONFIRM on quality pass."""
        new_trade.status = TradeStatus.SIGNALLED
        
        result = state_machine.on_quality_pass(new_trade, confirm_ts=1234)
        
        assert result.status == TradeStatus.WAITING_CONFIRM
    
    def test_waiting_confirm_to_waiting_cap(self, state_machine, new_trade):
        """WAITING_CONFIRM -> WAITING_CAP on confirm reached."""
        new_trade.status = TradeStatus.WAITING_CONFIRM
        
        result = state_machine.on_confirm_reached(new_trade)
        
        assert result.status == TradeStatus.WAITING_CAP
    
    def test_waiting_cap_to_ready(self, state_machine, new_trade):
        """WAITING_CAP -> READY on CAP_PASS."""
        new_trade.status = TradeStatus.WAITING_CAP
        cap_check = CapCheck(id=1, trade_id=1, first_pass_ts=1000)
        
        result = state_machine.on_cap_pass(new_trade, cap_check)
        
        assert result.status == TradeStatus.READY
    
    def test_waiting_cap_to_cancelled_cap_fail(self, state_machine, new_trade):
        """WAITING_CAP -> CANCELLED on CAP_FAIL."""
        new_trade.status = TradeStatus.WAITING_CAP
        
        result = state_machine.on_cap_fail(new_trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.CAP_FAIL
    
    def test_waiting_cap_to_cancelled_late(self, state_machine, new_trade):
        """WAITING_CAP -> CANCELLED on LATE."""
        new_trade.status = TradeStatus.WAITING_CAP
        
        result = state_machine.on_cap_late(new_trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.LATE
    
    def test_ready_to_order_placed(self, state_machine, new_trade):
        """READY -> ORDER_PLACED on order placement."""
        new_trade.status = TradeStatus.READY
        new_trade.decision = Decision.OK
        
        result = state_machine.on_order_placed(
            new_trade, 
            order_id="ORD123", 
            token_id="TOKEN123",
            stake_amount=10.0
        )
        
        assert result.status == TradeStatus.ORDER_PLACED
        assert result.order_id == "ORD123"
        assert result.token_id == "TOKEN123"
        assert result.stake_amount == 10.0
    
    def test_order_placed_to_settled(self, state_machine, new_trade):
        """ORDER_PLACED -> SETTLED on settlement."""
        new_trade.status = TradeStatus.ORDER_PLACED
        
        result = state_machine.on_settled(new_trade, is_win=True, pnl=5.0)
        
        assert result.status == TradeStatus.SETTLED
        assert result.is_win == True
        assert result.pnl == 5.0
    
    def test_order_placed_to_error(self, state_machine, new_trade):
        """ORDER_PLACED -> ERROR on rejection."""
        new_trade.status = TradeStatus.ORDER_PLACED
        
        result = state_machine.on_order_rejected(new_trade, reason="Insufficient funds")
        
        assert result.status == TradeStatus.ERROR
        assert result.fill_status == FillStatus.REJECTED
    
    def test_invalid_transition_raises_error(self, state_machine, new_trade):
        """Invalid transition should raise TradeError."""
        new_trade.status = TradeStatus.CANCELLED
        
        with pytest.raises(TradeError):
            state_machine.transition(new_trade, TradeStatus.READY)
    
    def test_user_ok_updates_decision(self, state_machine, new_trade, mock_trade_repo):
        """User OK should update decision."""
        new_trade.status = TradeStatus.READY
        
        result = state_machine.on_user_ok(new_trade)
        
        assert result.decision == Decision.OK
        mock_trade_repo.update.assert_called()
    
    def test_user_skip_cancels_trade(self, state_machine, new_trade):
        """User skip should cancel trade."""
        new_trade.status = TradeStatus.READY
        
        result = state_machine.on_user_skip(new_trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.decision == Decision.SKIP
        assert result.cancel_reason == CancelReason.SKIP
    
    def test_auto_ok_updates_decision(self, state_machine, new_trade, mock_trade_repo):
        """Auto OK should update decision."""
        new_trade.status = TradeStatus.READY
        
        result = state_machine.on_auto_ok(new_trade)
        
        assert result.decision == Decision.AUTO_OK
        mock_trade_repo.update.assert_called()
    
    def test_expired_cancels_non_terminal(self, state_machine, new_trade):
        """Expiration should cancel non-terminal trades."""
        new_trade.status = TradeStatus.WAITING_CAP
        
        result = state_machine.on_expired(new_trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.EXPIRED
    
    def test_expired_no_op_for_terminal(self, state_machine, new_trade):
        """Expiration should not affect terminal trades."""
        new_trade.status = TradeStatus.SETTLED
        
        result = state_machine.on_expired(new_trade)
        
        assert result.status == TradeStatus.SETTLED  # Unchanged


class TestTradeHelpers:
    """Tests for Trade model helper methods."""
    
    def test_is_taken_ok(self):
        """Trade is taken if decision is OK."""
        trade = Trade(decision=Decision.OK)
        assert trade.is_taken() == True
    
    def test_is_taken_auto_ok(self):
        """Trade is taken if decision is AUTO_OK."""
        trade = Trade(decision=Decision.AUTO_OK)
        assert trade.is_taken() == True
    
    def test_is_taken_skip(self):
        """Trade is not taken if decision is SKIP."""
        trade = Trade(decision=Decision.SKIP)
        assert trade.is_taken() == False
    
    def test_is_taken_pending(self):
        """Trade is not taken if decision is PENDING."""
        trade = Trade(decision=Decision.PENDING)
        assert trade.is_taken() == False
    
    def test_is_filled(self):
        """is_filled returns True for FILLED status."""
        trade = Trade(fill_status=FillStatus.FILLED)
        assert trade.is_filled() == True
        
        trade.fill_status = FillStatus.PENDING
        assert trade.is_filled() == False
    
    def test_is_terminal(self):
        """is_terminal returns True for terminal states."""
        terminal = [TradeStatus.SETTLED, TradeStatus.CANCELLED, TradeStatus.ERROR]
        for status in terminal:
            trade = Trade(status=status)
            assert trade.is_terminal() == True
        
        non_terminal = [TradeStatus.NEW, TradeStatus.READY, TradeStatus.ORDER_PLACED]
        for status in non_terminal:
            trade = Trade(status=status)
            assert trade.is_terminal() == False
    
    def test_counts_for_streak(self):
        """counts_for_streak requires taken AND filled."""
        # Both conditions met
        trade = Trade(decision=Decision.OK, fill_status=FillStatus.FILLED)
        assert trade.counts_for_streak() == True
        
        # Taken but not filled
        trade = Trade(decision=Decision.OK, fill_status=FillStatus.PENDING)
        assert trade.counts_for_streak() == False
        
        # Filled but not taken
        trade = Trade(decision=Decision.SKIP, fill_status=FillStatus.FILLED)
        assert trade.counts_for_streak() == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
