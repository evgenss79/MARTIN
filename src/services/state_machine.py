"""
Trade State Machine for MARTIN.

Implements trade status transitions per specification:
NEW -> SIGNALLED -> WAITING_CONFIRM -> WAITING_CAP -> READY -> ORDER_PLACED -> SETTLED
CANCELLED/ERROR are terminal states.
"""

from datetime import datetime, timezone
from typing import Callable

from src.domain.models import Trade, Signal, MarketWindow, CapCheck
from src.domain.enums import (
    TradeStatus,
    Decision,
    CancelReason,
    FillStatus,
    CapStatus,
    Direction,
    TimeMode,
    PolicyMode,
)
from src.adapters.storage import TradeRepository
from src.common.logging import get_logger
from src.common.exceptions import TradeError

logger = get_logger(__name__)


# Valid state transitions
# SEARCHING_SIGNAL is the active scanning state where bot re-evaluates each tick
VALID_TRANSITIONS: dict[TradeStatus, set[TradeStatus]] = {
    TradeStatus.NEW: {TradeStatus.SEARCHING_SIGNAL, TradeStatus.SIGNALLED, TradeStatus.CANCELLED},
    TradeStatus.SEARCHING_SIGNAL: {TradeStatus.SIGNALLED, TradeStatus.CANCELLED},
    TradeStatus.SIGNALLED: {TradeStatus.WAITING_CONFIRM, TradeStatus.CANCELLED},
    TradeStatus.WAITING_CONFIRM: {TradeStatus.WAITING_CAP, TradeStatus.CANCELLED},
    TradeStatus.WAITING_CAP: {TradeStatus.READY, TradeStatus.CANCELLED},
    TradeStatus.READY: {TradeStatus.ORDER_PLACED, TradeStatus.CANCELLED},
    TradeStatus.ORDER_PLACED: {TradeStatus.SETTLED, TradeStatus.ERROR},
    TradeStatus.SETTLED: set(),  # Terminal
    TradeStatus.CANCELLED: set(),  # Terminal
    TradeStatus.ERROR: set(),  # Terminal
}


class TradeStateMachine:
    """
    State machine for trade lifecycle management.
    
    Enforces valid state transitions and triggers appropriate actions.
    """
    
    def __init__(self, trade_repo: TradeRepository):
        """
        Initialize state machine.
        
        Args:
            trade_repo: Trade repository for persistence
        """
        self._repo = trade_repo
    
    def can_transition(self, trade: Trade, new_status: TradeStatus) -> bool:
        """
        Check if transition is valid.
        
        Args:
            trade: Current trade
            new_status: Desired new status
            
        Returns:
            True if transition is valid
        """
        valid_next = VALID_TRANSITIONS.get(trade.status, set())
        return new_status in valid_next
    
    def transition(
        self,
        trade: Trade,
        new_status: TradeStatus,
        reason: str | None = None,
    ) -> Trade:
        """
        Transition trade to new status.
        
        Args:
            trade: Trade to transition
            new_status: New status
            reason: Optional reason for transition
            
        Returns:
            Updated trade
            
        Raises:
            TradeError: If transition is invalid
        """
        if not self.can_transition(trade, new_status):
            raise TradeError(
                f"Invalid transition from {trade.status.value} to {new_status.value}"
            )
        
        old_status = trade.status
        trade.status = new_status
        trade.updated_at = datetime.now(timezone.utc)
        
        self._repo.update(trade)
        
        logger.info(
            "Trade status changed",
            trade_id=trade.id,
            old_status=old_status.value,
            new_status=new_status.value,
            reason=reason,
        )
        
        return trade
    
    def on_start_signal_search(self, trade: Trade) -> Trade:
        """
        Start signal search for an active window.
        
        Transition: NEW -> SEARCHING_SIGNAL
        
        Trade remains in SEARCHING_SIGNAL until:
        - A signal with quality >= threshold is found -> SIGNALLED
        - Window expires without qualifying signal -> CANCELLED (NO_SIGNAL/EXPIRED)
        """
        return self.transition(trade, TradeStatus.SEARCHING_SIGNAL, "Starting signal search")
    
    def on_signal(self, trade: Trade, signal: Signal) -> Trade:
        """
        Handle signal detection.
        
        Transition: NEW -> SIGNALLED or SEARCHING_SIGNAL -> SIGNALLED
        """
        trade.signal_id = signal.id
        return self.transition(trade, TradeStatus.SIGNALLED, "Signal detected")
    
    def on_no_signal(self, trade: Trade) -> Trade:
        """
        Handle no signal case.
        
        Transition: NEW -> CANCELLED or SEARCHING_SIGNAL -> CANCELLED (NO_SIGNAL)
        """
        trade.cancel_reason = CancelReason.NO_SIGNAL
        trade.decision = Decision.AUTO_SKIP
        return self.transition(trade, TradeStatus.CANCELLED, "No signal detected")
    
    def on_low_quality(self, trade: Trade, quality: float, threshold: float) -> Trade:
        """
        Handle low quality signal.
        
        Transition: SIGNALLED -> CANCELLED (LOW_QUALITY)
        """
        trade.cancel_reason = CancelReason.LOW_QUALITY
        trade.decision = Decision.AUTO_SKIP
        return self.transition(
            trade, 
            TradeStatus.CANCELLED, 
            f"Quality {quality:.2f} < threshold {threshold:.2f}"
        )
    
    def on_quality_pass(self, trade: Trade, confirm_ts: int) -> Trade:
        """
        Handle quality threshold passed.
        
        Transition: SIGNALLED -> WAITING_CONFIRM
        """
        return self.transition(
            trade, 
            TradeStatus.WAITING_CONFIRM, 
            f"Waiting for confirm_ts {confirm_ts}"
        )
    
    def on_confirm_reached(self, trade: Trade) -> Trade:
        """
        Handle confirm_ts reached.
        
        Transition: WAITING_CONFIRM -> WAITING_CAP
        """
        return self.transition(trade, TradeStatus.WAITING_CAP, "Confirm time reached")
    
    def on_cap_pass(self, trade: Trade, cap_check: CapCheck) -> Trade:
        """
        Handle CAP_PASS.
        
        Transition: WAITING_CAP -> READY
        """
        return self.transition(
            trade, 
            TradeStatus.READY, 
            f"CAP_PASS at ts={cap_check.first_pass_ts}"
        )
    
    def on_cap_fail(self, trade: Trade) -> Trade:
        """
        Handle CAP_FAIL.
        
        Transition: WAITING_CAP -> CANCELLED (CAP_FAIL)
        """
        trade.cancel_reason = CancelReason.CAP_FAIL
        trade.decision = Decision.AUTO_SKIP
        return self.transition(trade, TradeStatus.CANCELLED, "CAP_FAIL")
    
    def on_cap_late(self, trade: Trade) -> Trade:
        """
        Handle LATE condition (confirm_ts >= end_ts).
        
        Transition: WAITING_CONFIRM or WAITING_CAP -> CANCELLED (LATE)
        """
        trade.cancel_reason = CancelReason.LATE
        trade.decision = Decision.AUTO_SKIP
        return self.transition(trade, TradeStatus.CANCELLED, "confirm_ts >= end_ts")
    
    def on_user_ok(self, trade: Trade) -> Trade:
        """
        Handle user OK confirmation (Day mode).
        
        Updates decision to OK.
        """
        trade.decision = Decision.OK
        self._repo.update(trade)
        logger.info("User confirmed trade", trade_id=trade.id)
        return trade
    
    def on_user_skip(self, trade: Trade) -> Trade:
        """
        Handle user SKIP (Day mode).
        
        Transition: READY -> CANCELLED (SKIP)
        """
        trade.decision = Decision.SKIP
        trade.cancel_reason = CancelReason.SKIP
        return self.transition(trade, TradeStatus.CANCELLED, "User skipped")
    
    def on_auto_ok(self, trade: Trade) -> Trade:
        """
        Handle autonomous OK (Night mode).
        
        Updates decision to AUTO_OK.
        """
        trade.decision = Decision.AUTO_OK
        self._repo.update(trade)
        logger.info("Auto-confirmed trade (night mode)", trade_id=trade.id)
        return trade
    
    def on_order_placed(
        self,
        trade: Trade,
        order_id: str,
        token_id: str,
        stake_amount: float,
    ) -> Trade:
        """
        Handle order placement.
        
        Transition: READY -> ORDER_PLACED
        """
        trade.order_id = order_id
        trade.token_id = token_id
        trade.stake_amount = stake_amount
        trade.fill_status = FillStatus.PENDING
        return self.transition(trade, TradeStatus.ORDER_PLACED, f"Order placed: {order_id}")
    
    def on_order_filled(self, trade: Trade, fill_price: float) -> Trade:
        """
        Handle order fill.
        
        Updates fill status and price.
        """
        trade.fill_status = FillStatus.FILLED
        trade.fill_price = fill_price
        self._repo.update(trade)
        logger.info(
            "Order filled",
            trade_id=trade.id,
            fill_price=fill_price,
        )
        return trade
    
    def on_order_rejected(self, trade: Trade, reason: str) -> Trade:
        """
        Handle order rejection.
        
        Transition: ORDER_PLACED -> ERROR
        """
        trade.fill_status = FillStatus.REJECTED
        return self.transition(trade, TradeStatus.ERROR, f"Order rejected: {reason}")
    
    def on_settled(
        self,
        trade: Trade,
        is_win: bool,
        pnl: float,
    ) -> Trade:
        """
        Handle trade settlement.
        
        Transition: ORDER_PLACED -> SETTLED
        """
        trade.is_win = is_win
        trade.pnl = pnl
        trade.fill_status = FillStatus.FILLED  # Ensure marked as filled
        return self.transition(
            trade, 
            TradeStatus.SETTLED, 
            f"{'WIN' if is_win else 'LOSS'} pnl={pnl:.2f}"
        )
    
    def on_expired(self, trade: Trade) -> Trade:
        """
        Handle window expiration.
        
        Transition: any non-terminal -> CANCELLED (EXPIRED)
        """
        if trade.is_terminal():
            return trade
        
        trade.cancel_reason = CancelReason.EXPIRED
        if trade.decision == Decision.PENDING:
            trade.decision = Decision.AUTO_SKIP
        return self.transition(trade, TradeStatus.CANCELLED, "Window expired")
    
    def on_paused(self, trade: Trade) -> Trade:
        """
        Handle bot pause.
        
        Transition: any non-terminal -> CANCELLED (PAUSED)
        """
        if trade.is_terminal():
            return trade
        
        trade.cancel_reason = CancelReason.PAUSED
        trade.decision = Decision.AUTO_SKIP
        return self.transition(trade, TradeStatus.CANCELLED, "Bot paused")
    
    def on_night_disabled(self, trade: Trade) -> Trade:
        """
        Handle night trading disabled.
        
        Transition: any non-terminal -> CANCELLED (NIGHT_DISABLED)
        """
        if trade.is_terminal():
            return trade
        
        trade.cancel_reason = CancelReason.NIGHT_DISABLED
        trade.decision = Decision.AUTO_SKIP
        return self.transition(trade, TradeStatus.CANCELLED, "Night trading disabled")
