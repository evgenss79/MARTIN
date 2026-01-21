"""
Stats and Streak Management Service for MARTIN.

Handles:
- Trade-level streak tracking (only taken+filled trades)
- Night streak tracking
- Auto-switch between BASE and STRICT modes
- Rolling quantile calculation for strict thresholds
"""

import time
from datetime import datetime, timedelta

from src.domain.models import Stats, Trade, Signal
from src.domain.enums import TimeMode, PolicyMode, Decision, FillStatus
from src.adapters.storage import StatsRepository, TradeRepository
from src.common.logging import get_logger

logger = get_logger(__name__)


def compute_quantile(values: list[float], q: float) -> float:
    """
    Compute quantile using Type 7 interpolation (R/Excel default).
    
    Type 7 formula:
    h = (n-1)*q + 1
    k = floor(h)
    d = h - k
    Q = x[k] + d*(x[k+1] - x[k]) in 1-based indexing
    
    Args:
        values: Sorted list of values
        q: Quantile (0.0 to 1.0)
        
    Returns:
        Quantile value
    """
    if not values:
        return 0.0
    
    n = len(values)
    if n == 1:
        return values[0]
    
    # Sort ascending
    sorted_values = sorted(values)
    
    # Type 7 interpolation (1-based indexing converted to 0-based)
    h = (n - 1) * q
    k = int(h)  # floor
    d = h - k
    
    # Clamp edges
    if k >= n - 1:
        return sorted_values[-1]
    if k < 0:
        return sorted_values[0]
    
    return sorted_values[k] + d * (sorted_values[k + 1] - sorted_values[k])


QUANTILE_MAP = {
    "p90": 0.90,
    "p95": 0.95,
    "p97": 0.97,
    "p99": 0.99,
}


class StatsService:
    """
    Service for stats and streak management.
    
    Key constraints (Memory Gate):
    - MG-1: Trade-level streak counts only taken (OK/AUTO_OK) AND filled trades
    - MG-7: Auto-switch to STRICT at SWITCH_STREAK_AT, revert on loss/night reset
    """
    
    def __init__(
        self,
        stats_repo: StatsRepository,
        trade_repo: TradeRepository,
        switch_streak_at: int = 3,
        night_max_win_streak: int = 5,
        night_session_resets_trade_streak: bool = True,
        strict_day_q: str = "p95",
        strict_night_q: str = "p95",
        rolling_days: int = 14,
        max_samples: int = 500,
        min_samples: int = 50,
        strict_fallback_mult: float = 1.25,
        base_day_min_quality: float = 50.0,
        base_night_min_quality: float = 60.0,
    ):
        """
        Initialize Stats Service.
        
        Args:
            stats_repo: Stats repository
            trade_repo: Trade repository
            switch_streak_at: Streak count to trigger STRICT mode
            night_max_win_streak: Max night wins before session reset
            night_session_resets_trade_streak: Whether night reset also resets trade streak
            strict_day_q: Quantile for strict day threshold
            strict_night_q: Quantile for strict night threshold
            rolling_days: Days to include in rolling quantile
            max_samples: Maximum samples for quantile
            min_samples: Minimum samples required
            strict_fallback_mult: Fallback multiplier when insufficient samples
            base_day_min_quality: Base day quality for fallback
            base_night_min_quality: Base night quality for fallback
        """
        self._stats_repo = stats_repo
        self._trade_repo = trade_repo
        self._switch_streak_at = switch_streak_at
        self._night_max_win_streak = night_max_win_streak
        self._night_resets_trade = night_session_resets_trade_streak
        self._strict_day_q = QUANTILE_MAP.get(strict_day_q, 0.95)
        self._strict_night_q = QUANTILE_MAP.get(strict_night_q, 0.95)
        self._rolling_days = rolling_days
        self._max_samples = max_samples
        self._min_samples = min_samples
        self._fallback_mult = strict_fallback_mult
        self._base_day_q = base_day_min_quality
        self._base_night_q = base_night_min_quality
    
    def get_stats(self) -> Stats:
        """Get current stats."""
        return self._stats_repo.get()
    
    def save_stats(self, stats: Stats) -> None:
        """Save stats."""
        self._stats_repo.update(stats)
    
    def on_trade_settled(
        self,
        trade: Trade,
        is_win: bool,
        time_mode: TimeMode,
    ) -> Stats:
        """
        Handle trade settlement and update streaks.
        
        MG-1: Trade-level streak counts ONLY taken+filled trades.
        MG-7: On loss, revert to BASE and reset streaks.
        
        Args:
            trade: Settled trade
            is_win: Whether trade was won
            time_mode: Time mode when trade was placed
            
        Returns:
            Updated stats
        """
        stats = self.get_stats()
        
        # Only count if trade was taken AND filled (MG-1)
        if not trade.counts_for_streak():
            logger.debug(
                "Trade does not count for streak",
                trade_id=trade.id,
                decision=trade.decision.value,
                fill_status=trade.fill_status.value,
            )
            return stats
        
        # Update totals
        stats.total_trades += 1
        
        if is_win:
            stats.total_wins += 1
            stats.trade_level_streak += 1
            
            # Update night streak if applicable
            if time_mode == TimeMode.NIGHT:
                stats.night_streak += 1
            
            logger.info(
                "Win recorded",
                trade_id=trade.id,
                trade_level_streak=stats.trade_level_streak,
                night_streak=stats.night_streak,
            )
            
            # Check for night session reset (MG-6, MG-7)
            if time_mode == TimeMode.NIGHT and stats.night_streak >= self._night_max_win_streak:
                logger.info(
                    "Night session max streak reached - resetting",
                    night_streak=stats.night_streak,
                    max_streak=self._night_max_win_streak,
                )
                stats = self._apply_night_session_reset(stats)
            
            # Check for STRICT mode activation (MG-7)
            if (stats.policy_mode == PolicyMode.BASE and 
                stats.trade_level_streak >= self._switch_streak_at):
                stats.policy_mode = PolicyMode.STRICT
                logger.info(
                    "Switched to STRICT mode",
                    trade_level_streak=stats.trade_level_streak,
                    switch_at=self._switch_streak_at,
                )
        
        else:  # Loss
            stats.total_losses += 1
            
            logger.info(
                "Loss recorded - resetting streaks",
                trade_id=trade.id,
                previous_trade_streak=stats.trade_level_streak,
                previous_night_streak=stats.night_streak,
            )
            
            # On loss: reset everything (MG-7)
            stats.trade_level_streak = 0
            stats.night_streak = 0
            stats.policy_mode = PolicyMode.BASE
        
        self.save_stats(stats)
        return stats
    
    def _apply_night_session_reset(self, stats: Stats) -> Stats:
        """
        Apply night session reset.
        
        Resets night_streak and policy_mode to BASE.
        Also resets trade_level_streak if configured (default: yes).
        
        Args:
            stats: Current stats
            
        Returns:
            Updated stats
        """
        stats.night_streak = 0
        stats.policy_mode = PolicyMode.BASE
        
        if self._night_resets_trade:
            stats.trade_level_streak = 0
            logger.info("Night session reset - also resetting trade_level_streak")
        
        return stats
    
    def update_rolling_quantiles(self) -> Stats:
        """
        Calculate and update rolling quantile thresholds.
        
        Uses trades from last ROLLING_DAYS that are:
        - Decision OK or AUTO_OK
        - Fill status FILLED
        - Quality not null
        
        Separate thresholds for DAY and NIGHT.
        
        Returns:
            Updated stats with new thresholds
        """
        stats = self.get_stats()
        current_ts = int(time.time())
        since_ts = current_ts - (self._rolling_days * 86400)
        
        # Calculate day threshold
        day_trades = self._trade_repo.get_filled_trades_for_quantile(
            TimeMode.DAY, since_ts, self._max_samples
        )
        day_threshold = self._calculate_threshold(
            day_trades, self._strict_day_q, self._base_day_q
        )
        
        # Calculate night threshold
        night_trades = self._trade_repo.get_filled_trades_for_quantile(
            TimeMode.NIGHT, since_ts, self._max_samples
        )
        night_threshold = self._calculate_threshold(
            night_trades, self._strict_night_q, self._base_night_q
        )
        
        stats.last_strict_day_threshold = day_threshold
        stats.last_strict_night_threshold = night_threshold
        stats.last_quantile_update_ts = current_ts
        
        self.save_stats(stats)
        
        logger.info(
            "Rolling quantiles updated",
            day_samples=len(day_trades),
            day_threshold=day_threshold,
            night_samples=len(night_trades),
            night_threshold=night_threshold,
        )
        
        return stats
    
    def _calculate_threshold(
        self,
        trades: list[Trade],
        quantile: float,
        base_quality: float,
    ) -> float:
        """
        Calculate strict threshold from trades.
        
        Args:
            trades: List of trades
            quantile: Quantile to calculate (0.0-1.0)
            base_quality: Base quality for fallback
            
        Returns:
            Calculated threshold
        """
        # Get quality values from trades
        # Need to get signal quality for each trade
        qualities: list[float] = []
        
        for trade in trades:
            # Trade should have associated signal with quality
            if trade.signal_id:
                from src.adapters.storage import SignalRepository, get_database
                try:
                    signal_repo = SignalRepository(get_database())
                    signal = signal_repo.get_by_id(trade.signal_id)
                    if signal and signal.quality:
                        qualities.append(signal.quality)
                except Exception:
                    pass
        
        if len(qualities) < self._min_samples:
            # Fallback: use base * multiplier or last stored value
            fallback = base_quality * self._fallback_mult
            logger.debug(
                "Insufficient samples for quantile, using fallback",
                samples=len(qualities),
                min_required=self._min_samples,
                fallback=fallback,
            )
            return fallback
        
        return compute_quantile(qualities, quantile)
    
    def get_current_threshold(self, time_mode: TimeMode, policy_mode: PolicyMode) -> float:
        """
        Get current quality threshold.
        
        Args:
            time_mode: Current time mode
            policy_mode: Current policy mode
            
        Returns:
            Quality threshold to use
        """
        stats = self.get_stats()
        
        if policy_mode == PolicyMode.BASE:
            if time_mode == TimeMode.DAY:
                return self._base_day_q
            return self._base_night_q
        
        # STRICT mode
        if time_mode == TimeMode.DAY:
            if stats.last_strict_day_threshold is not None:
                return stats.last_strict_day_threshold
            return self._base_day_q * self._fallback_mult
        
        # Night STRICT
        if stats.last_strict_night_threshold is not None:
            return stats.last_strict_night_threshold
        return self._base_night_q * self._fallback_mult
