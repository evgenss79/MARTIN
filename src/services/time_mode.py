"""
Day/Night Time Mode Service for MARTIN.

Determines current time mode and manages quality thresholds.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.domain.enums import TimeMode, PolicyMode
from src.domain.models import Stats
from src.common.logging import get_logger

logger = get_logger(__name__)


class TimeModeService:
    """
    Service for Day/Night mode determination.
    
    Uses Europe/Zurich timezone per specification.
    """
    
    def __init__(
        self,
        timezone: str = "Europe/Zurich",
        day_start_hour: int = 8,
        day_end_hour: int = 22,
        base_day_min_quality: float = 50.0,
        base_night_min_quality: float = 60.0,
        night_autotrade_enabled: bool = False,
    ):
        """
        Initialize Time Mode Service.
        
        Args:
            timezone: Timezone for day/night determination
            day_start_hour: Day mode start hour (0-23)
            day_end_hour: Day mode end hour (0-23)
            base_day_min_quality: Base minimum quality for day mode
            base_night_min_quality: Base minimum quality for night mode
            night_autotrade_enabled: Whether night auto-trading is enabled
        """
        self._tz = ZoneInfo(timezone)
        self._day_start = day_start_hour
        self._day_end = day_end_hour
        self._base_day_q = base_day_min_quality
        self._base_night_q = base_night_min_quality
        self._night_autotrade = night_autotrade_enabled
    
    def get_current_mode(self, ts: int | None = None) -> TimeMode:
        """
        Get current time mode (DAY or NIGHT).
        
        Args:
            ts: Unix timestamp (uses current time if None)
            
        Returns:
            TimeMode.DAY or TimeMode.NIGHT
        """
        if ts is None:
            dt = datetime.now(self._tz)
        else:
            dt = datetime.fromtimestamp(ts, self._tz)
        
        hour = dt.hour
        
        # Day if DAY_START_HOUR <= hour < DAY_END_HOUR
        if self._day_start <= hour < self._day_end:
            return TimeMode.DAY
        return TimeMode.NIGHT
    
    def get_local_datetime(self, ts: int) -> datetime:
        """
        Convert unix timestamp to local datetime.
        
        Args:
            ts: Unix timestamp
            
        Returns:
            Datetime in configured timezone
        """
        return datetime.fromtimestamp(ts, self._tz)
    
    def format_local_time(self, ts: int) -> str:
        """
        Format timestamp as local time string.
        
        Args:
            ts: Unix timestamp
            
        Returns:
            Formatted time string
        """
        dt = self.get_local_datetime(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    
    def get_base_quality_threshold(self, mode: TimeMode) -> float:
        """
        Get base minimum quality for a mode.
        
        Args:
            mode: Time mode (DAY or NIGHT)
            
        Returns:
            Base minimum quality threshold
        """
        if mode == TimeMode.DAY:
            return self._base_day_q
        return self._base_night_q
    
    def get_quality_threshold(
        self,
        mode: TimeMode,
        policy: PolicyMode,
        strict_day_threshold: float | None = None,
        strict_night_threshold: float | None = None,
    ) -> float:
        """
        Get quality threshold based on mode and policy.
        
        Args:
            mode: Time mode (DAY or NIGHT)
            policy: Policy mode (BASE or STRICT)
            strict_day_threshold: Calculated strict threshold for day
            strict_night_threshold: Calculated strict threshold for night
            
        Returns:
            Quality threshold to apply
        """
        base = self.get_base_quality_threshold(mode)
        
        if policy == PolicyMode.BASE:
            return base
        
        # STRICT mode - use calculated threshold if available
        if mode == TimeMode.DAY:
            strict = strict_day_threshold
        else:
            strict = strict_night_threshold
        
        if strict is not None and strict > base:
            return strict
        
        # Fallback to base if strict not calculated yet
        return base
    
    def is_night_autotrade_enabled(self) -> bool:
        """Check if night auto-trading is enabled."""
        return self._night_autotrade
    
    def should_require_confirmation(self, mode: TimeMode) -> bool:
        """
        Check if user confirmation is required.
        
        Day mode always requires confirmation.
        Night mode is autonomous if enabled.
        
        Args:
            mode: Current time mode
            
        Returns:
            True if confirmation required
        """
        if mode == TimeMode.DAY:
            return True
        
        # Night mode - autonomous if enabled
        return not self._night_autotrade
