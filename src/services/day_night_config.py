"""
Day/Night Configuration Service for MARTIN.

Manages user-configurable day/night time ranges with persistence.
Supports wrap-around midnight scenarios (e.g., 22:00 to 06:00).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.domain.enums import TimeMode
from src.common.logging import get_logger

logger = get_logger(__name__)


# Settings keys for persistence
SETTING_DAY_START_HOUR = "day_night.day_start_hour"
SETTING_DAY_END_HOUR = "day_night.day_end_hour"
SETTING_BASE_DAY_QUALITY = "day_night.base_day_min_quality"
SETTING_BASE_NIGHT_QUALITY = "day_night.base_night_min_quality"
SETTING_NIGHT_AUTOTRADE = "day_night.night_autotrade_enabled"
SETTING_NIGHT_MAX_STREAK = "day_night.night_max_win_streak"
SETTING_SWITCH_STREAK_AT = "day_night.switch_streak_at"
SETTING_REMINDER_MINUTES = "day_night.reminder_minutes_before_day_end"


class DayNightConfigService:
    """
    Service for managing day/night configuration with persistence.
    
    Supports:
    - User-configurable day/night time ranges
    - Wrap-around midnight scenarios
    - Persistence via settings repository
    - Immediate application of changes
    """
    
    # Fixed timezone per specification
    TIMEZONE = "Europe/Zurich"
    
    def __init__(
        self,
        settings_repo=None,
        default_day_start: int = 8,
        default_day_end: int = 22,
        default_base_day_quality: float = 50.0,
        default_base_night_quality: float = 60.0,
        default_night_autotrade: bool = False,
        default_night_max_streak: int = 5,
        default_switch_streak_at: int = 3,
        default_reminder_minutes: int = 30,
    ):
        """
        Initialize Day/Night Configuration Service.
        
        Args:
            settings_repo: Repository for persisting settings
            default_day_start: Default day start hour (0-23)
            default_day_end: Default day end hour (0-23)
            default_base_day_quality: Default base quality for day mode
            default_base_night_quality: Default base quality for night mode
            default_night_autotrade: Default night autotrade setting
            default_night_max_streak: Default night max win streak
            default_switch_streak_at: Default streak count for STRICT mode
            default_reminder_minutes: Default reminder minutes before day end
        """
        self._settings_repo = settings_repo
        self._tz = ZoneInfo(self.TIMEZONE)
        
        # Defaults from config
        self._defaults = {
            SETTING_DAY_START_HOUR: default_day_start,
            SETTING_DAY_END_HOUR: default_day_end,
            SETTING_BASE_DAY_QUALITY: default_base_day_quality,
            SETTING_BASE_NIGHT_QUALITY: default_base_night_quality,
            SETTING_NIGHT_AUTOTRADE: default_night_autotrade,
            SETTING_NIGHT_MAX_STREAK: default_night_max_streak,
            SETTING_SWITCH_STREAK_AT: default_switch_streak_at,
            SETTING_REMINDER_MINUTES: default_reminder_minutes,
        }
    
    def _get_setting(self, key: str) -> str | None:
        """Get setting from repository if available."""
        if self._settings_repo is None:
            return None
        return self._settings_repo.get(key)
    
    def _set_setting(self, key: str, value: str) -> None:
        """Set setting in repository if available."""
        if self._settings_repo is None:
            logger.warning("Settings repository not available, changes will not persist")
            return
        self._settings_repo.set(key, value)
    
    def get_day_start_hour(self) -> int:
        """
        Get configured day start hour.
        
        Returns:
            Hour (0-23) when day mode starts
        """
        stored = self._get_setting(SETTING_DAY_START_HOUR)
        if stored is not None:
            return int(stored)
        return self._defaults[SETTING_DAY_START_HOUR]
    
    def set_day_start_hour(self, hour: int) -> bool:
        """
        Set day start hour.
        
        Args:
            hour: Hour (0-23)
            
        Returns:
            True if successfully set
        """
        if not self._validate_hour(hour):
            logger.error("Invalid day start hour", hour=hour)
            return False
        
        self._set_setting(SETTING_DAY_START_HOUR, str(hour))
        logger.info("Updated day start hour", hour=hour)
        return True
    
    def get_day_end_hour(self) -> int:
        """
        Get configured day end hour.
        
        Returns:
            Hour (0-23) when day mode ends
        """
        stored = self._get_setting(SETTING_DAY_END_HOUR)
        if stored is not None:
            return int(stored)
        return self._defaults[SETTING_DAY_END_HOUR]
    
    def set_day_end_hour(self, hour: int) -> bool:
        """
        Set day end hour.
        
        Args:
            hour: Hour (0-23)
            
        Returns:
            True if successfully set
        """
        if not self._validate_hour(hour):
            logger.error("Invalid day end hour", hour=hour)
            return False
        
        self._set_setting(SETTING_DAY_END_HOUR, str(hour))
        logger.info("Updated day end hour", hour=hour)
        return True
    
    def get_base_day_quality(self) -> float:
        """Get base minimum quality for day mode."""
        stored = self._get_setting(SETTING_BASE_DAY_QUALITY)
        if stored is not None:
            return float(stored)
        return self._defaults[SETTING_BASE_DAY_QUALITY]
    
    def set_base_day_quality(self, quality: float) -> bool:
        """Set base minimum quality for day mode."""
        if quality < 0:
            logger.error("Invalid base day quality", quality=quality)
            return False
        
        self._set_setting(SETTING_BASE_DAY_QUALITY, str(quality))
        logger.info("Updated base day quality", quality=quality)
        return True
    
    def get_base_night_quality(self) -> float:
        """Get base minimum quality for night mode."""
        stored = self._get_setting(SETTING_BASE_NIGHT_QUALITY)
        if stored is not None:
            return float(stored)
        return self._defaults[SETTING_BASE_NIGHT_QUALITY]
    
    def set_base_night_quality(self, quality: float) -> bool:
        """Set base minimum quality for night mode."""
        if quality < 0:
            logger.error("Invalid base night quality", quality=quality)
            return False
        
        self._set_setting(SETTING_BASE_NIGHT_QUALITY, str(quality))
        logger.info("Updated base night quality", quality=quality)
        return True
    
    def get_night_autotrade_enabled(self) -> bool:
        """Get night autotrade enabled setting."""
        stored = self._get_setting(SETTING_NIGHT_AUTOTRADE)
        if stored is not None:
            return stored.lower() == "true"
        return self._defaults[SETTING_NIGHT_AUTOTRADE]
    
    def set_night_autotrade_enabled(self, enabled: bool) -> bool:
        """Set night autotrade enabled setting."""
        self._set_setting(SETTING_NIGHT_AUTOTRADE, str(enabled).lower())
        logger.info("Updated night autotrade enabled", enabled=enabled)
        return True
    
    def get_night_max_streak(self) -> int:
        """Get night max win streak."""
        stored = self._get_setting(SETTING_NIGHT_MAX_STREAK)
        if stored is not None:
            return int(stored)
        return self._defaults[SETTING_NIGHT_MAX_STREAK]
    
    def set_night_max_streak(self, streak: int) -> bool:
        """Set night max win streak."""
        if streak < 1:
            logger.error("Invalid night max streak", streak=streak)
            return False
        
        self._set_setting(SETTING_NIGHT_MAX_STREAK, str(streak))
        logger.info("Updated night max streak", streak=streak)
        return True
    
    def get_switch_streak_at(self) -> int:
        """Get streak count for STRICT mode switch."""
        stored = self._get_setting(SETTING_SWITCH_STREAK_AT)
        if stored is not None:
            return int(stored)
        return self._defaults[SETTING_SWITCH_STREAK_AT]
    
    def set_switch_streak_at(self, streak: int) -> bool:
        """Set streak count for STRICT mode switch."""
        if streak < 1:
            logger.error("Invalid switch streak at", streak=streak)
            return False
        
        self._set_setting(SETTING_SWITCH_STREAK_AT, str(streak))
        logger.info("Updated switch streak at", streak=streak)
        return True
    
    def get_reminder_minutes(self) -> int:
        """
        Get reminder minutes before day end.
        
        Returns:
            Minutes before day end to send reminder (0 = disabled)
        """
        stored = self._get_setting(SETTING_REMINDER_MINUTES)
        if stored is not None:
            return int(stored)
        return self._defaults[SETTING_REMINDER_MINUTES]
    
    def set_reminder_minutes(self, minutes: int) -> bool:
        """
        Set reminder minutes before day end.
        
        Args:
            minutes: Minutes (0-180, 0 = disabled)
            
        Returns:
            True if successfully set
        """
        if not 0 <= minutes <= 180:
            logger.error("Invalid reminder minutes", minutes=minutes)
            return False
        
        self._set_setting(SETTING_REMINDER_MINUTES, str(minutes))
        logger.info("Updated reminder minutes", minutes=minutes)
        return True
    
    def _validate_hour(self, hour: int) -> bool:
        """Validate hour is in range 0-23."""
        return isinstance(hour, int) and 0 <= hour <= 23
    
    def get_current_mode(self, ts: int | None = None) -> TimeMode:
        """
        Get current time mode (DAY or NIGHT).
        
        Handles wrap-around midnight scenarios:
        - If day_start < day_end (e.g., 8 to 22): normal range
        - If day_start >= day_end (e.g., 22 to 6): wrap-around midnight
        
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
        day_start = self.get_day_start_hour()
        day_end = self.get_day_end_hour()
        
        # Handle wrap-around midnight
        if day_start < day_end:
            # Normal case: e.g., 8 to 22
            # Day if day_start <= hour < day_end
            if day_start <= hour < day_end:
                return TimeMode.DAY
        else:
            # Wrap-around case: e.g., 22 to 6
            # Day if hour >= day_start OR hour < day_end
            if hour >= day_start or hour < day_end:
                return TimeMode.DAY
        
        return TimeMode.NIGHT
    
    def get_current_local_time(self, ts: int | None = None) -> datetime:
        """
        Get current local time in Europe/Zurich.
        
        Args:
            ts: Unix timestamp (uses current time if None)
            
        Returns:
            Datetime in Europe/Zurich timezone
        """
        if ts is None:
            return datetime.now(self._tz)
        return datetime.fromtimestamp(ts, self._tz)
    
    def get_next_day_end_ts(self, from_ts: int | None = None) -> int:
        """
        Calculate the next day end timestamp.
        
        Args:
            from_ts: Starting timestamp (uses current time if None)
            
        Returns:
            Unix timestamp of next day end
        """
        dt = self.get_current_local_time(from_ts)
        day_end = self.get_day_end_hour()
        
        # Create datetime for today's day end
        today_end = dt.replace(hour=day_end, minute=0, second=0, microsecond=0)
        
        # If already past today's day end, use tomorrow's
        if dt >= today_end:
            from datetime import timedelta
            today_end = today_end + timedelta(days=1)
        
        return int(today_end.timestamp())
    
    def get_reminder_ts(self, from_ts: int | None = None) -> int | None:
        """
        Calculate the next reminder timestamp.
        
        Args:
            from_ts: Starting timestamp (uses current time if None)
            
        Returns:
            Unix timestamp of next reminder, or None if disabled
        """
        minutes = self.get_reminder_minutes()
        if minutes == 0:
            return None
        
        day_end_ts = self.get_next_day_end_ts(from_ts)
        reminder_ts = day_end_ts - (minutes * 60)
        
        # If reminder is in the past, return None (will trigger next cycle)
        dt = self.get_current_local_time(from_ts)
        if reminder_ts <= int(dt.timestamp()):
            return None
        
        return reminder_ts
    
    def format_local_time(self, ts: int) -> str:
        """
        Format timestamp as local time string.
        
        Args:
            ts: Unix timestamp
            
        Returns:
            Formatted time string
        """
        dt = datetime.fromtimestamp(ts, self._tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    
    def format_time_only(self, hour: int) -> str:
        """
        Format hour as HH:00 string.
        
        Args:
            hour: Hour (0-23)
            
        Returns:
            Formatted time string
        """
        return f"{hour:02d}:00"
    
    def get_all_settings(self) -> dict:
        """
        Get all current settings.
        
        Returns:
            Dictionary of all settings with current values
        """
        return {
            "day_start_hour": self.get_day_start_hour(),
            "day_end_hour": self.get_day_end_hour(),
            "base_day_quality": self.get_base_day_quality(),
            "base_night_quality": self.get_base_night_quality(),
            "night_autotrade_enabled": self.get_night_autotrade_enabled(),
            "night_max_streak": self.get_night_max_streak(),
            "switch_streak_at": self.get_switch_streak_at(),
            "reminder_minutes": self.get_reminder_minutes(),
        }
