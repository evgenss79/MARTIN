"""
Repository classes for MARTIN data access.

Provides CRUD operations for all domain entities.
"""

import json
from datetime import datetime
from typing import Any

from src.adapters.storage.database import Database, get_database
from src.domain.models import (
    MarketWindow,
    Signal,
    Trade,
    CapCheck,
    Stats,
    QualityBreakdown,
)
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
from src.common.logging import get_logger
from src.common.exceptions import StorageError

logger = get_logger(__name__)


class MarketWindowRepository:
    """Repository for market window operations."""
    
    def __init__(self, db: Database | None = None):
        self._db = db or get_database()
    
    def create(self, window: MarketWindow) -> MarketWindow:
        """Create a new market window."""
        cursor = self._db.execute(
            """
            INSERT INTO market_windows (asset, slug, condition_id, up_token_id, down_token_id, start_ts, end_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (window.asset, window.slug, window.condition_id, 
             window.up_token_id, window.down_token_id, window.start_ts, window.end_ts)
        )
        window.id = cursor.lastrowid
        logger.info("Created market window", window_id=window.id, asset=window.asset, slug=window.slug)
        return window
    
    def get_by_id(self, window_id: int) -> MarketWindow | None:
        """Get market window by ID."""
        row = self._db.fetchone("SELECT * FROM market_windows WHERE id = ?", (window_id,))
        return self._row_to_model(row) if row else None
    
    def get_by_slug(self, slug: str) -> MarketWindow | None:
        """Get market window by slug."""
        row = self._db.fetchone("SELECT * FROM market_windows WHERE slug = ?", (slug,))
        return self._row_to_model(row) if row else None
    
    def get_active(self, current_ts: int) -> list[MarketWindow]:
        """Get all active (not expired) windows."""
        rows = self._db.fetchall(
            "SELECT * FROM market_windows WHERE end_ts > ? ORDER BY start_ts",
            (current_ts,)
        )
        return [self._row_to_model(row) for row in rows]
    
    def get_unsettled(self) -> list[MarketWindow]:
        """Get windows that have ended but not settled."""
        rows = self._db.fetchall(
            "SELECT * FROM market_windows WHERE outcome IS NULL ORDER BY end_ts"
        )
        return [self._row_to_model(row) for row in rows]
    
    def update_outcome(self, window_id: int, outcome: str) -> None:
        """Update window outcome after settlement."""
        self._db.execute(
            "UPDATE market_windows SET outcome = ? WHERE id = ?",
            (outcome, window_id)
        )
        logger.info("Updated window outcome", window_id=window_id, outcome=outcome)
    
    def _row_to_model(self, row: dict[str, Any]) -> MarketWindow:
        """Convert database row to model."""
        return MarketWindow(
            id=row["id"],
            asset=row["asset"],
            slug=row["slug"],
            condition_id=row["condition_id"],
            up_token_id=row["up_token_id"],
            down_token_id=row["down_token_id"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            outcome=row["outcome"],
            created_at=row["created_at"],
        )


class SignalRepository:
    """Repository for signal operations."""
    
    def __init__(self, db: Database | None = None):
        self._db = db or get_database()
    
    def create(self, signal: Signal) -> Signal:
        """Create a new signal."""
        breakdown_json = None
        if signal.quality_breakdown:
            breakdown_json = json.dumps(signal.quality_breakdown.to_dict())
        
        cursor = self._db.execute(
            """
            INSERT INTO signals (window_id, direction, signal_ts, confirm_ts, quality, quality_breakdown, anchor_bar_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (signal.window_id, signal.direction.value if signal.direction else None,
             signal.signal_ts, signal.confirm_ts, signal.quality, breakdown_json, signal.anchor_bar_ts)
        )
        signal.id = cursor.lastrowid
        logger.info("Created signal", signal_id=signal.id, window_id=signal.window_id, 
                   direction=signal.direction.value if signal.direction else None, quality=signal.quality)
        return signal
    
    def get_by_id(self, signal_id: int) -> Signal | None:
        """Get signal by ID."""
        row = self._db.fetchone("SELECT * FROM signals WHERE id = ?", (signal_id,))
        return self._row_to_model(row) if row else None
    
    def get_by_window_id(self, window_id: int) -> Signal | None:
        """Get signal for a window."""
        row = self._db.fetchone("SELECT * FROM signals WHERE window_id = ?", (window_id,))
        return self._row_to_model(row) if row else None
    
    def _row_to_model(self, row: dict[str, Any]) -> Signal:
        """Convert database row to model."""
        breakdown = None
        if row["quality_breakdown"]:
            breakdown = QualityBreakdown.from_dict(json.loads(row["quality_breakdown"]))
        
        return Signal(
            id=row["id"],
            window_id=row["window_id"],
            direction=Direction(row["direction"]) if row["direction"] else None,
            signal_ts=row["signal_ts"],
            confirm_ts=row["confirm_ts"],
            quality=row["quality"],
            quality_breakdown=breakdown,
            anchor_bar_ts=row["anchor_bar_ts"],
            created_at=row["created_at"],
        )


class TradeRepository:
    """Repository for trade operations."""
    
    def __init__(self, db: Database | None = None):
        self._db = db or get_database()
    
    def create(self, trade: Trade) -> Trade:
        """Create a new trade."""
        cursor = self._db.execute(
            """
            INSERT INTO trades (window_id, signal_id, status, time_mode, policy_mode, decision,
                              cancel_reason, token_id, order_id, fill_status, fill_price,
                              stake_amount, pnl, is_win, trade_level_streak, night_streak)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade.window_id, trade.signal_id, trade.status.value,
             trade.time_mode.value if trade.time_mode else None,
             trade.policy_mode.value, trade.decision.value,
             trade.cancel_reason.value if trade.cancel_reason else None,
             trade.token_id, trade.order_id, trade.fill_status.value,
             trade.fill_price, trade.stake_amount, trade.pnl,
             1 if trade.is_win else (0 if trade.is_win is False else None),
             trade.trade_level_streak, trade.night_streak)
        )
        trade.id = cursor.lastrowid
        logger.info("Created trade", trade_id=trade.id, window_id=trade.window_id, status=trade.status.value)
        return trade
    
    def update(self, trade: Trade) -> None:
        """Update an existing trade."""
        self._db.execute(
            """
            UPDATE trades SET
                status = ?, decision = ?, cancel_reason = ?,
                token_id = ?, order_id = ?, fill_status = ?, fill_price = ?,
                stake_amount = ?, pnl = ?, is_win = ?,
                trade_level_streak = ?, night_streak = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (trade.status.value, trade.decision.value,
             trade.cancel_reason.value if trade.cancel_reason else None,
             trade.token_id, trade.order_id, trade.fill_status.value, trade.fill_price,
             trade.stake_amount, trade.pnl,
             1 if trade.is_win else (0 if trade.is_win is False else None),
             trade.trade_level_streak, trade.night_streak, trade.id)
        )
        logger.info("Updated trade", trade_id=trade.id, status=trade.status.value, decision=trade.decision.value)
    
    def get_by_id(self, trade_id: int) -> Trade | None:
        """Get trade by ID."""
        row = self._db.fetchone("SELECT * FROM trades WHERE id = ?", (trade_id,))
        return self._row_to_model(row) if row else None
    
    def get_by_window_id(self, window_id: int) -> Trade | None:
        """Get trade for a window."""
        row = self._db.fetchone("SELECT * FROM trades WHERE window_id = ?", (window_id,))
        return self._row_to_model(row) if row else None

    def get_non_terminal_by_window_id(self, window_id: int) -> Trade | None:
        """Get non-terminal trade for a window (if any)."""
        row = self._db.fetchone(
            """
            SELECT * FROM trades
            WHERE window_id = ?
              AND status NOT IN (?, ?, ?)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (window_id, TradeStatus.SETTLED.value, TradeStatus.CANCELLED.value, TradeStatus.ERROR.value),
        )
        return self._row_to_model(row) if row else None
    
    def get_active(self) -> list[Trade]:
        """Get all non-terminal trades."""
        rows = self._db.fetchall(
            """
            SELECT * FROM trades 
            WHERE status NOT IN (?, ?, ?) 
            ORDER BY created_at
            """,
            (TradeStatus.SETTLED.value, TradeStatus.CANCELLED.value, TradeStatus.ERROR.value)
        )
        return [self._row_to_model(row) for row in rows]
    
    def get_pending_settlement(self) -> list[Trade]:
        """Get trades waiting for settlement."""
        rows = self._db.fetchall(
            "SELECT * FROM trades WHERE status = ? ORDER BY created_at",
            (TradeStatus.ORDER_PLACED.value,)
        )
        return [self._row_to_model(row) for row in rows]
    
    def get_filled_trades_for_quantile(
        self, 
        time_mode: TimeMode, 
        since_ts: int,
        limit: int = 500
    ) -> list[Trade]:
        """
        Get filled trades for quantile calculation.
        
        Only includes trades with:
        - decision OK or AUTO_OK
        - fill_status FILLED
        - matching time_mode
        - created since given timestamp
        """
        rows = self._db.fetchall(
            """
            SELECT * FROM trades
            WHERE decision IN (?, ?)
              AND fill_status = ?
              AND time_mode = ?
              AND created_at >= datetime(?, 'unixepoch')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (Decision.OK.value, Decision.AUTO_OK.value, FillStatus.FILLED.value,
             time_mode.value, since_ts, limit)
        )
        return [self._row_to_model(row) for row in rows]
    
    def _row_to_model(self, row: dict[str, Any]) -> Trade:
        """Convert database row to model."""
        is_win = None
        if row["is_win"] is not None:
            is_win = bool(row["is_win"])
        
        return Trade(
            id=row["id"],
            window_id=row["window_id"],
            signal_id=row["signal_id"],
            status=TradeStatus(row["status"]),
            time_mode=TimeMode(row["time_mode"]) if row["time_mode"] else None,
            policy_mode=PolicyMode(row["policy_mode"]),
            decision=Decision(row["decision"]),
            cancel_reason=CancelReason(row["cancel_reason"]) if row["cancel_reason"] else None,
            token_id=row["token_id"] or "",
            order_id=row["order_id"],
            fill_status=FillStatus(row["fill_status"]),
            fill_price=row["fill_price"],
            stake_amount=row["stake_amount"],
            pnl=row["pnl"],
            is_win=is_win,
            trade_level_streak=row["trade_level_streak"],
            night_streak=row["night_streak"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class CapCheckRepository:
    """Repository for CAP check operations."""
    
    def __init__(self, db: Database | None = None):
        self._db = db or get_database()
    
    def create(self, cap_check: CapCheck) -> CapCheck:
        """Create a new CAP check."""
        cursor = self._db.execute(
            """
            INSERT INTO cap_checks (trade_id, token_id, confirm_ts, end_ts, status,
                                   consecutive_ticks, first_pass_ts, price_at_pass)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cap_check.trade_id, cap_check.token_id, cap_check.confirm_ts,
             cap_check.end_ts, cap_check.status.value, cap_check.consecutive_ticks,
             cap_check.first_pass_ts, cap_check.price_at_pass)
        )
        cap_check.id = cursor.lastrowid
        logger.info("Created cap check", cap_check_id=cap_check.id, trade_id=cap_check.trade_id)
        return cap_check
    
    def update(self, cap_check: CapCheck) -> None:
        """Update an existing CAP check."""
        self._db.execute(
            """
            UPDATE cap_checks SET
                status = ?, consecutive_ticks = ?, first_pass_ts = ?, price_at_pass = ?
            WHERE id = ?
            """,
            (cap_check.status.value, cap_check.consecutive_ticks,
             cap_check.first_pass_ts, cap_check.price_at_pass, cap_check.id)
        )
        logger.info("Updated cap check", cap_check_id=cap_check.id, status=cap_check.status.value)
    
    def get_by_trade_id(self, trade_id: int) -> CapCheck | None:
        """Get CAP check for a trade."""
        row = self._db.fetchone("SELECT * FROM cap_checks WHERE trade_id = ?", (trade_id,))
        return self._row_to_model(row) if row else None
    
    def get_pending(self) -> list[CapCheck]:
        """Get all pending CAP checks."""
        rows = self._db.fetchall(
            "SELECT * FROM cap_checks WHERE status = ?",
            (CapStatus.PENDING.value,)
        )
        return [self._row_to_model(row) for row in rows]
    
    def _row_to_model(self, row: dict[str, Any]) -> CapCheck:
        """Convert database row to model."""
        return CapCheck(
            id=row["id"],
            trade_id=row["trade_id"],
            token_id=row["token_id"],
            confirm_ts=row["confirm_ts"],
            end_ts=row["end_ts"],
            status=CapStatus(row["status"]),
            consecutive_ticks=row["consecutive_ticks"],
            first_pass_ts=row["first_pass_ts"],
            price_at_pass=row["price_at_pass"],
            created_at=row["created_at"],
        )


class StatsRepository:
    """Repository for stats (singleton) operations."""
    
    def __init__(self, db: Database | None = None):
        self._db = db or get_database()
    
    def get(self) -> Stats:
        """Get the stats singleton."""
        row = self._db.fetchone("SELECT * FROM stats WHERE id = 1")
        if not row:
            # Initialize if doesn't exist
            self._db.execute("INSERT OR IGNORE INTO stats (id) VALUES (1)")
            row = self._db.fetchone("SELECT * FROM stats WHERE id = 1")
        return self._row_to_model(row)
    
    def update(self, stats: Stats) -> None:
        """Update the stats singleton."""
        self._db.execute(
            """
            UPDATE stats SET
                trade_level_streak = ?,
                night_streak = ?,
                policy_mode = ?,
                total_trades = ?,
                total_wins = ?,
                total_losses = ?,
                last_strict_day_threshold = ?,
                last_strict_night_threshold = ?,
                last_quantile_update_ts = ?,
                is_paused = ?,
                day_only = ?,
                night_only = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (stats.trade_level_streak, stats.night_streak, stats.policy_mode.value,
             stats.total_trades, stats.total_wins, stats.total_losses,
             stats.last_strict_day_threshold, stats.last_strict_night_threshold,
             stats.last_quantile_update_ts, 1 if stats.is_paused else 0,
             1 if stats.day_only else 0, 1 if stats.night_only else 0)
        )
        logger.info("Updated stats", trade_level_streak=stats.trade_level_streak,
                   night_streak=stats.night_streak, policy_mode=stats.policy_mode.value)
    
    def _row_to_model(self, row: dict[str, Any]) -> Stats:
        """Convert database row to model."""
        return Stats(
            id=row["id"],
            trade_level_streak=row["trade_level_streak"],
            night_streak=row["night_streak"],
            policy_mode=PolicyMode(row["policy_mode"]),
            total_trades=row["total_trades"],
            total_wins=row["total_wins"],
            total_losses=row["total_losses"],
            last_strict_day_threshold=row["last_strict_day_threshold"],
            last_strict_night_threshold=row["last_strict_night_threshold"],
            last_quantile_update_ts=row["last_quantile_update_ts"],
            is_paused=bool(row["is_paused"]),
            day_only=bool(row["day_only"]),
            night_only=bool(row["night_only"]),
            updated_at=row["updated_at"],
        )


class SettingsRepository:
    """Repository for runtime settings overrides."""
    
    def __init__(self, db: Database | None = None):
        self._db = db or get_database()
    
    def get(self, key: str) -> str | None:
        """Get setting value by key."""
        row = self._db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else None
    
    def set(self, key: str, value: str) -> None:
        """Set or update a setting."""
        self._db.execute(
            """
            INSERT INTO settings (key, value, updated_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
            """,
            (key, value, value)
        )
        logger.info("Updated setting", key=key, value=value)
    
    def delete(self, key: str) -> None:
        """Delete a setting."""
        self._db.execute("DELETE FROM settings WHERE key = ?", (key,))
    
    def get_all(self) -> dict[str, str]:
        """Get all settings."""
        rows = self._db.fetchall("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in rows}
