"""
Domain models for MARTIN.

Data classes representing the core entities.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.domain.enums import (
    Direction,
    PolicyMode,
    TimeMode,
    TradeStatus,
    CapStatus,
    FillStatus,
    Decision,
    CancelReason,
)


@dataclass
class MarketWindow:
    """
    Represents a Polymarket hourly window.
    
    Attributes:
        id: Unique identifier (database primary key)
        asset: Asset symbol (BTC, ETH)
        slug: Polymarket market slug
        condition_id: Polymarket condition ID
        up_token_id: Token ID for UP outcome
        down_token_id: Token ID for DOWN outcome
        start_ts: Window start timestamp (unix seconds)
        end_ts: Window end timestamp (unix seconds)
        outcome: Resolved outcome (UP/DOWN) after settlement
        created_at: Record creation timestamp
    """
    id: int | None = None
    asset: str = ""
    slug: str = ""
    condition_id: str = ""
    up_token_id: str = ""
    down_token_id: str = ""
    start_ts: int = 0
    end_ts: int = 0
    outcome: str | None = None
    created_at: datetime | None = None
    
    def is_expired(self, current_ts: int) -> bool:
        """Check if window has expired."""
        return current_ts >= self.end_ts
    
    def time_remaining(self, current_ts: int) -> int:
        """Get remaining seconds until window end."""
        return max(0, self.end_ts - current_ts)


@dataclass
class QualityBreakdown:
    """
    Breakdown of quality score components.
    
    Quality = (W_ANCHOR*edge_component + W_ADX*q_adx + W_SLOPE*q_slope) * trend_mult
    """
    anchor_price: float = 0.0
    signal_price: float = 0.0
    ret_from_anchor: float = 0.0
    edge_component: float = 0.0
    edge_penalty_applied: bool = False
    adx_value: float = 0.0
    q_adx: float = 0.0
    ema50_slope: float = 0.0
    q_slope: float = 0.0
    trend_mult: float = 1.0
    trend_confirms: bool = True
    
    # Weighted components
    w_anchor: float = 0.0
    w_adx: float = 0.0
    w_slope: float = 0.0
    
    final_quality: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/display."""
        return {
            "anchor_price": self.anchor_price,
            "signal_price": self.signal_price,
            "ret_from_anchor": self.ret_from_anchor,
            "edge_component": self.edge_component,
            "edge_penalty_applied": self.edge_penalty_applied,
            "adx_value": self.adx_value,
            "q_adx": self.q_adx,
            "ema50_slope": self.ema50_slope,
            "q_slope": self.q_slope,
            "trend_mult": self.trend_mult,
            "trend_confirms": self.trend_confirms,
            "w_anchor": self.w_anchor,
            "w_adx": self.w_adx,
            "w_slope": self.w_slope,
            "final_quality": self.final_quality,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualityBreakdown":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Signal:
    """
    Trading signal detected by TA engine.
    
    Attributes:
        id: Unique identifier
        window_id: Associated market window ID
        direction: Signal direction (UP/DOWN)
        signal_ts: Timestamp when signal was confirmed
        confirm_ts: Timestamp when CAP check can begin (signal_ts + confirm_delay)
        quality: Calculated quality score
        quality_breakdown: Detailed breakdown of quality components
        anchor_bar_ts: Timestamp of anchor bar
        created_at: Record creation timestamp
    """
    id: int | None = None
    window_id: int = 0
    direction: Direction | None = None
    signal_ts: int = 0
    confirm_ts: int = 0
    quality: float = 0.0
    quality_breakdown: QualityBreakdown | None = None
    anchor_bar_ts: int = 0
    created_at: datetime | None = None


@dataclass
class Trade:
    """
    Trade record representing a trading opportunity and its lifecycle.
    
    Attributes:
        id: Unique identifier
        window_id: Associated market window ID
        signal_id: Associated signal ID
        status: Current trade status
        time_mode: DAY or NIGHT mode when trade was created
        policy_mode: BASE or STRICT policy at trade creation
        decision: User/system decision (OK/SKIP/etc.)
        cancel_reason: Reason if cancelled
        token_id: Token ID being traded
        order_id: Exchange order ID
        fill_status: Order fill status
        fill_price: Actual fill price
        stake_amount: Trade size in USDC
        pnl: Profit/loss after settlement
        is_win: Whether trade was profitable
        trade_level_streak: Trade-level streak at time of trade
        night_streak: Night streak at time of trade
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """
    id: int | None = None
    window_id: int = 0
    signal_id: int | None = None
    status: TradeStatus = TradeStatus.NEW
    time_mode: TimeMode | None = None
    policy_mode: PolicyMode = PolicyMode.BASE
    decision: Decision = Decision.PENDING
    cancel_reason: CancelReason | None = None
    token_id: str = ""
    order_id: str | None = None
    fill_status: FillStatus = FillStatus.PENDING
    fill_price: float | None = None
    stake_amount: float = 0.0
    pnl: float | None = None
    is_win: bool | None = None
    trade_level_streak: int = 0
    night_streak: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    
    def is_taken(self) -> bool:
        """Check if trade was taken (OK or AUTO_OK decision)."""
        return self.decision in (Decision.OK, Decision.AUTO_OK)
    
    def is_filled(self) -> bool:
        """Check if order was filled."""
        return self.fill_status == FillStatus.FILLED
    
    def is_terminal(self) -> bool:
        """Check if trade is in a terminal state."""
        return self.status in (TradeStatus.SETTLED, TradeStatus.CANCELLED, TradeStatus.ERROR)
    
    def counts_for_streak(self) -> bool:
        """Check if this trade counts toward streak (taken AND filled)."""
        return self.is_taken() and self.is_filled()


@dataclass
class CapCheck:
    """
    CAP check record for price validation.
    
    Attributes:
        id: Unique identifier
        trade_id: Associated trade ID
        token_id: Token ID checked
        confirm_ts: When CAP check began
        end_ts: Window end timestamp
        status: CAP check status
        consecutive_ticks: Number of consecutive ticks <= cap
        first_pass_ts: Timestamp of first CAP_PASS (if passed)
        price_at_pass: Price at first pass
        created_at: Record creation timestamp
    """
    id: int | None = None
    trade_id: int = 0
    token_id: str = ""
    confirm_ts: int = 0
    end_ts: int = 0
    status: CapStatus = CapStatus.PENDING
    consecutive_ticks: int = 0
    first_pass_ts: int | None = None
    price_at_pass: float | None = None
    created_at: datetime | None = None


@dataclass
class Stats:
    """
    Global statistics singleton.
    
    Attributes:
        id: Always 1 (singleton)
        trade_level_streak: Current trade-level win streak
        night_streak: Current night session win streak
        policy_mode: Current policy mode (BASE/STRICT)
        total_trades: Total trades taken
        total_wins: Total winning trades
        total_losses: Total losing trades
        last_strict_day_threshold: Last calculated strict day threshold
        last_strict_night_threshold: Last calculated strict night threshold
        last_quantile_update_ts: Last quantile calculation timestamp
        is_paused: Whether bot is paused
        day_only: Whether bot is day-only mode
        night_only: Whether bot is night-only mode
        updated_at: Last update timestamp
    """
    id: int = 1  # Singleton
    trade_level_streak: int = 0
    night_streak: int = 0
    policy_mode: PolicyMode = PolicyMode.BASE
    total_trades: int = 0
    total_wins: int = 0
    total_losses: int = 0
    last_strict_day_threshold: float | None = None
    last_strict_night_threshold: float | None = None
    last_quantile_update_ts: int | None = None
    is_paused: bool = False
    day_only: bool = False
    night_only: bool = False
    updated_at: datetime | None = None
    
    @property
    def win_rate(self) -> float:
        """Calculate win rate percentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.total_wins / self.total_trades) * 100
