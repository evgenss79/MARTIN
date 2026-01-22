"""
Day/Night Configuration Service for MARTIN.

Manages user-configurable day/night time ranges with persistence.
Supports wrap-around midnight scenarios (e.g., 22:00 to 06:00).
Supports NightSessionMode for A/B/C night trading behaviors.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.domain.enums import TimeMode, NightSessionMode
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
SETTING_NIGHT_SESSION_MODE = "day_night.night_session_mode"

# Trading settings keys for persistence
SETTING_PRICE_CAP = "trading.price_cap"
SETTING_CONFIRM_DELAY = "trading.confirm_delay_seconds"
SETTING_CAP_MIN_TICKS = "trading.cap_min_ticks"
SETTING_BASE_STAKE = "risk.stake.base_amount_usdc"

# Validation constants (per spec)
MIN_PRICE_CAP = 0.01
MAX_PRICE_CAP = 0.99
MIN_CAP_TICKS = 1
MIN_BASE_STAKE = 0.01
MIN_CONFIRM_DELAY = 0
MIN_STREAK_THRESHOLD = 1
MIN_QUALITY = 0.0


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
        default_night_session_mode: str = "OFF",
        default_price_cap: float = 0.55,
        default_confirm_delay: int = 120,
        default_cap_min_ticks: int = 3,
        default_base_stake: float = 10.0,
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
            default_night_session_mode: Default night session mode (OFF/SOFT/HARD)
            default_price_cap: Default maximum price for CAP_PASS (0.01-0.99)
            default_confirm_delay: Default confirm delay in seconds
            default_cap_min_ticks: Default minimum consecutive ticks for CAP_PASS
            default_base_stake: Default base stake amount in USDC
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
            SETTING_NIGHT_SESSION_MODE: default_night_session_mode,
            SETTING_PRICE_CAP: default_price_cap,
            SETTING_CONFIRM_DELAY: default_confirm_delay,
            SETTING_CAP_MIN_TICKS: default_cap_min_ticks,
            SETTING_BASE_STAKE: default_base_stake,
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
    
    def get_night_session_mode(self) -> NightSessionMode:
        """
        Get current night session mode.
        
        Returns:
            NightSessionMode (OFF, SOFT_RESET, or HARD_RESET)
        """
        stored = self._get_setting(SETTING_NIGHT_SESSION_MODE)
        if stored is not None:
            try:
                return NightSessionMode(stored)
            except ValueError:
                # Invalid stored value, return default
                logger.warning("Invalid night session mode stored, using default", stored=stored)
        return NightSessionMode(self._defaults[SETTING_NIGHT_SESSION_MODE])
    
    def set_night_session_mode(self, mode: NightSessionMode | str) -> bool:
        """
        Set night session mode.
        
        Args:
            mode: NightSessionMode enum or string value (OFF/SOFT/HARD)
            
        Returns:
            True if successfully set
        """
        if isinstance(mode, str):
            try:
                mode = NightSessionMode(mode)
            except ValueError:
                logger.error("Invalid night session mode", mode=mode)
                return False
        
        # Update night_autotrade_enabled based on mode
        # OFF means night autotrade disabled, others mean enabled
        autotrade_enabled = mode != NightSessionMode.OFF
        self._set_setting(SETTING_NIGHT_AUTOTRADE, str(autotrade_enabled).lower())
        self._set_setting(SETTING_NIGHT_SESSION_MODE, mode.value)
        logger.info(
            "Updated night session mode",
            mode=mode.value,
            autotrade_enabled=autotrade_enabled,
        )
        return True
    
    def get_night_session_mode_description(self, mode: NightSessionMode | None = None) -> str:
        """
        Get human-readable description of night session mode.
        
        Args:
            mode: Mode to describe (uses current if None)
            
        Returns:
            Description string
        """
        if mode is None:
            mode = self.get_night_session_mode()
        
        descriptions = {
            NightSessionMode.OFF: (
                "🌙❌ OFF - Night trading disabled. Series freezes overnight."
            ),
            NightSessionMode.SOFT_RESET: (
                "🌙🔵 SOFT - On night session cap: reset night_streak only. "
                "Trade-level streak continues."
            ),
            NightSessionMode.HARD_RESET: (
                "🌙🔴 HARD - On night session cap: reset ALL streaks + series counters. "
                "Full reset."
            ),
        }
        return descriptions.get(mode, "Unknown mode")
    
    def get_night_session_mode_short(self, mode: NightSessionMode | None = None) -> str:
        """
        Get short label for night session mode.
        
        Args:
            mode: Mode to describe (uses current if None)
            
        Returns:
            Short label
        """
        if mode is None:
            mode = self.get_night_session_mode()
        
        labels = {
            NightSessionMode.OFF: "🌙❌ OFF",
            NightSessionMode.SOFT_RESET: "🌙🔵 SOFT",
            NightSessionMode.HARD_RESET: "🌙🔴 HARD",
        }
        return labels.get(mode, "?")
    
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
            "night_session_mode": self.get_night_session_mode().value,
            "price_cap": self.get_price_cap(),
            "confirm_delay_seconds": self.get_confirm_delay(),
            "cap_min_ticks": self.get_cap_min_ticks(),
            "base_stake": self.get_base_stake(),
        }
    
    # ============================================
    # Trading Parameter Methods
    # ============================================
    
    def get_price_cap(self) -> float:
        """
        Get maximum price for CAP_PASS validation.
        
        Returns:
            Price cap value (0.01 to 0.99)
        """
        stored = self._get_setting(SETTING_PRICE_CAP)
        if stored is not None:
            return float(stored)
        return self._defaults[SETTING_PRICE_CAP]
    
    def set_price_cap(self, value: float) -> bool:
        """
        Set maximum price for CAP_PASS validation.
        
        Args:
            value: Price cap (MIN_PRICE_CAP to MAX_PRICE_CAP)
            
        Returns:
            True if successfully set
        """
        if not MIN_PRICE_CAP <= value <= MAX_PRICE_CAP:
            logger.error("Invalid price cap value", value=value)
            return False
        
        self._set_setting(SETTING_PRICE_CAP, str(value))
        logger.info("Updated price cap", value=value)
        return True
    
    def get_confirm_delay(self) -> int:
        """
        Get confirm delay in seconds.
        
        Returns:
            Confirm delay in seconds (>= 0)
        """
        stored = self._get_setting(SETTING_CONFIRM_DELAY)
        if stored is not None:
            return int(stored)
        return self._defaults[SETTING_CONFIRM_DELAY]
    
    def set_confirm_delay(self, seconds: int) -> bool:
        """
        Set confirm delay in seconds.
        
        Args:
            seconds: Delay in seconds (>= MIN_CONFIRM_DELAY)
            
        Returns:
            True if successfully set
        """
        if seconds < MIN_CONFIRM_DELAY:
            logger.error("Invalid confirm delay", seconds=seconds)
            return False
        
        self._set_setting(SETTING_CONFIRM_DELAY, str(seconds))
        logger.info("Updated confirm delay", seconds=seconds)
        return True
    
    def get_cap_min_ticks(self) -> int:
        """
        Get minimum consecutive ticks for CAP_PASS.
        
        Returns:
            Minimum ticks (>= MIN_CAP_TICKS)
        """
        stored = self._get_setting(SETTING_CAP_MIN_TICKS)
        if stored is not None:
            return int(stored)
        return self._defaults[SETTING_CAP_MIN_TICKS]
    
    def set_cap_min_ticks(self, ticks: int) -> bool:
        """
        Set minimum consecutive ticks for CAP_PASS.
        
        Args:
            ticks: Minimum ticks (>= MIN_CAP_TICKS)
            
        Returns:
            True if successfully set
        """
        if ticks < MIN_CAP_TICKS:
            logger.error("Invalid cap min ticks", ticks=ticks)
            return False
        
        self._set_setting(SETTING_CAP_MIN_TICKS, str(ticks))
        logger.info("Updated cap min ticks", ticks=ticks)
        return True
    
    def get_base_stake(self) -> float:
        """
        Get base stake amount in USDC.
        
        Returns:
            Base stake amount (>= MIN_BASE_STAKE)
        """
        stored = self._get_setting(SETTING_BASE_STAKE)
        if stored is not None:
            return float(stored)
        return self._defaults[SETTING_BASE_STAKE]
    
    def set_base_stake(self, amount: float) -> bool:
        """
        Set base stake amount in USDC.
        
        Args:
            amount: Stake amount (>= MIN_BASE_STAKE)
            
        Returns:
            True if successfully set
        """
        if amount < MIN_BASE_STAKE:
            logger.error("Invalid base stake", amount=amount)
            return False
        
        self._set_setting(SETTING_BASE_STAKE, str(amount))
        logger.info("Updated base stake", amount=amount)
        return True
