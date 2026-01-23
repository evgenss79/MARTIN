"""
Enumerations for MARTIN domain.

Defines all possible states and types used throughout the application.
"""

from enum import Enum, auto


class Direction(str, Enum):
    """Trading direction."""
    UP = "UP"
    DOWN = "DOWN"


class PolicyMode(str, Enum):
    """Policy mode for quality thresholds."""
    BASE = "BASE"
    STRICT = "STRICT"


class TimeMode(str, Enum):
    """Day/Night time mode."""
    DAY = "DAY"
    NIGHT = "NIGHT"


class TradeStatus(str, Enum):
    """
    Trade status in state machine.
    
    State transitions:
    NEW -> SEARCHING_SIGNAL -> SIGNALLED -> WAITING_CONFIRM -> WAITING_CAP -> READY -> ORDER_PLACED -> SETTLED
    CANCELLED/ERROR are terminal states.
    
    SEARCHING_SIGNAL: Trade is actively scanning for a qualifying signal within the window.
    The bot re-evaluates TA each tick. If a signal with quality >= threshold is found,
    transition to SIGNALLED. If window expires without qualifying signal, transition to CANCELLED.
    """
    NEW = "NEW"
    SEARCHING_SIGNAL = "SEARCHING_SIGNAL"
    SIGNALLED = "SIGNALLED"
    WAITING_CONFIRM = "WAITING_CONFIRM"
    WAITING_CAP = "WAITING_CAP"
    READY = "READY"
    ORDER_PLACED = "ORDER_PLACED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class CapStatus(str, Enum):
    """CAP check status."""
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    LATE = "LATE"  # confirm_ts >= end_ts


class FillStatus(str, Enum):
    """Order fill status."""
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Decision(str, Enum):
    """User/system decision for trade."""
    PENDING = "PENDING"
    OK = "OK"           # User confirmed in day mode
    AUTO_OK = "AUTO_OK" # System auto-confirmed in night mode
    SKIP = "SKIP"       # User skipped in day mode
    AUTO_SKIP = "AUTO_SKIP"  # System auto-skipped (low quality, etc.)


class CancelReason(str, Enum):
    """Reason for trade cancellation."""
    NO_SIGNAL = "NO_SIGNAL"
    LOW_QUALITY = "LOW_QUALITY"
    SKIP = "SKIP"           # User skipped
    EXPIRED = "EXPIRED"     # Window expired
    LATE = "LATE"           # confirm_ts >= end_ts
    CAP_FAIL = "CAP_FAIL"   # CAP check failed
    PAUSED = "PAUSED"       # Bot is paused
    NIGHT_DISABLED = "NIGHT_DISABLED"  # Night trading disabled


class NightSessionMode(str, Enum):
    """
    Night session mode controlling overnight trading behavior.
    
    The user can quickly switch among these modes via Telegram,
    especially near Day→Night boundary.
    
    Values:
    - OFF: Night autotrade disabled. Series freezes overnight.
    - SOFT_RESET: Night autotrade enabled. On session reset (after max wins),
                  only night_streak resets. trade_level_streak continues.
    - HARD_RESET: Night autotrade enabled. On session reset,
                  both night_streak AND trade_level_streak reset (+ series counters).
    """
    OFF = "OFF"           # Scenario A: Night trading disabled
    SOFT_RESET = "SOFT"   # Scenario B: Reset only night_streak
    HARD_RESET = "HARD"   # Scenario C: Reset all streaks + series counters
