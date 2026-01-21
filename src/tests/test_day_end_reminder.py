"""
Tests for Day End Reminder Service.

Tests automatic reminder functionality before day window ends.
"""

import pytest
from datetime import datetime, date
from zoneinfo import ZoneInfo


class MockSettingsRepo:
    """Mock settings repository for testing."""
    
    def __init__(self):
        self._settings = {}
    
    def get(self, key: str) -> str | None:
        return self._settings.get(key)
    
    def set(self, key: str, value: str) -> None:
        self._settings[key] = value


class TestNightSessionMode:
    """Tests for NightSessionMode constants."""
    
    def test_mode_descriptions(self):
        """Test mode descriptions are available."""
        from src.services.day_end_reminder import NightSessionMode
        
        assert NightSessionMode.OFF == "OFF"
        assert NightSessionMode.SOFT_RESET == "SOFT"
        assert NightSessionMode.HARD_RESET == "HARD"
        
        # Descriptions should exist and be non-empty
        assert len(NightSessionMode.get_description("OFF")) > 0
        assert len(NightSessionMode.get_description("SOFT")) > 0
        assert len(NightSessionMode.get_description("HARD")) > 0
        
        # OFF should mention disabled
        assert "disabled" in NightSessionMode.get_description("OFF").lower()


class TestReminderConfig:
    """Tests for ReminderConfig dataclass."""
    
    def test_should_send_today_first_time(self):
        """Test first reminder of the day."""
        from src.services.day_end_reminder import ReminderConfig
        
        config = ReminderConfig(minutes_before=30, last_reminder_date=None)
        assert config.should_send_today()
    
    def test_should_not_send_twice_same_day(self):
        """Test rate limiting to once per day."""
        from src.services.day_end_reminder import ReminderConfig
        
        config = ReminderConfig(minutes_before=30, last_reminder_date=date.today())
        assert not config.should_send_today()
    
    def test_should_send_next_day(self):
        """Test reminder allowed next day."""
        from src.services.day_end_reminder import ReminderConfig
        from datetime import timedelta
        
        yesterday = date.today() - timedelta(days=1)
        config = ReminderConfig(minutes_before=30, last_reminder_date=yesterday)
        assert config.should_send_today()


class TestDayEndReminderService:
    """Tests for DayEndReminderService."""
    
    def test_disabled_when_minutes_zero(self):
        """Test reminder disabled when minutes is 0."""
        from src.services.day_night_config import DayNightConfigService
        from src.services.day_end_reminder import DayEndReminderService
        
        repo = MockSettingsRepo()
        config_svc = DayNightConfigService(
            settings_repo=repo,
            default_reminder_minutes=0,
        )
        
        reminder_svc = DayEndReminderService(config_service=config_svc)
        
        assert not reminder_svc.should_send_reminder()
    
    def test_rate_limited_per_day(self):
        """Test reminder is rate-limited to once per day."""
        from src.services.day_night_config import DayNightConfigService
        from src.services.day_end_reminder import DayEndReminderService
        
        repo = MockSettingsRepo()
        config_svc = DayNightConfigService(
            settings_repo=repo,
            default_reminder_minutes=30,
            default_day_start=8,
            default_day_end=22,
        )
        
        reminder_svc = DayEndReminderService(config_service=config_svc)
        reminder_svc._last_reminder_date = date.today()
        
        assert not reminder_svc.should_send_reminder()
    
    def test_reset_daily_limit(self):
        """Test resetting daily limit."""
        from src.services.day_night_config import DayNightConfigService
        from src.services.day_end_reminder import DayEndReminderService
        
        repo = MockSettingsRepo()
        config_svc = DayNightConfigService(settings_repo=repo)
        
        reminder_svc = DayEndReminderService(config_service=config_svc)
        reminder_svc._last_reminder_date = date.today()
        
        reminder_svc.reset_daily_limit()
        
        assert reminder_svc._last_reminder_date is None


class TestReminderMessageFormatting:
    """Tests for reminder message formatting."""
    
    def test_format_reminder_message(self):
        """Test reminder message contains required elements."""
        from src.services.day_night_config import DayNightConfigService
        from src.services.day_end_reminder import DayEndReminderService
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        repo = MockSettingsRepo()
        config_svc = DayNightConfigService(settings_repo=repo)
        reminder_svc = DayEndReminderService(config_service=config_svc)
        
        tz = ZoneInfo("Europe/Zurich")
        current_time = datetime(2026, 1, 21, 21, 30, 0, tzinfo=tz)
        day_end_time = datetime(2026, 1, 21, 22, 0, 0, tzinfo=tz)
        
        message = reminder_svc.format_reminder_message(
            current_time=current_time,
            day_end_time=day_end_time,
            execution_mode="paper",
            is_authorized=False,
        )
        
        # Check required elements are present
        assert "Day Window Ending" in message
        assert "21:30" in message
        assert "22:00" in message
        assert "Night Session Mode" in message
        assert "Execution" in message
        assert "/settings" in message
    
    def test_format_message_shows_live_authorized(self):
        """Test message shows authorized status for live mode."""
        from src.services.day_night_config import DayNightConfigService
        from src.services.day_end_reminder import DayEndReminderService
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        repo = MockSettingsRepo()
        config_svc = DayNightConfigService(settings_repo=repo)
        reminder_svc = DayEndReminderService(config_service=config_svc)
        
        tz = ZoneInfo("Europe/Zurich")
        current_time = datetime.now(tz)
        day_end_time = datetime.now(tz)
        
        message = reminder_svc.format_reminder_message(
            current_time=current_time,
            day_end_time=day_end_time,
            execution_mode="live",
            is_authorized=True,
        )
        
        assert "🟡" in message  # Yellow = authorized
        assert "Live" in message


class TestCalculateReminderTime:
    """Tests for reminder time calculation."""
    
    def test_next_day_end_ts(self):
        """Test calculation of next day end timestamp."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(
            settings_repo=repo,
            default_day_start=8,
            default_day_end=22,
        )
        
        tz = ZoneInfo("Europe/Zurich")
        
        # If it's 10:00, next day end should be today at 22:00
        dt_10 = datetime(2026, 1, 21, 10, 0, 0, tzinfo=tz)
        ts_10 = int(dt_10.timestamp())
        
        next_end = svc.get_next_day_end_ts(ts_10)
        expected = datetime(2026, 1, 21, 22, 0, 0, tzinfo=tz)
        
        assert next_end == int(expected.timestamp())
    
    def test_next_day_end_after_midnight(self):
        """Test day end calculation when already past today's end."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(
            settings_repo=repo,
            default_day_start=8,
            default_day_end=22,
        )
        
        tz = ZoneInfo("Europe/Zurich")
        
        # If it's 23:00, next day end should be tomorrow at 22:00
        dt_23 = datetime(2026, 1, 21, 23, 0, 0, tzinfo=tz)
        ts_23 = int(dt_23.timestamp())
        
        next_end = svc.get_next_day_end_ts(ts_23)
        expected = datetime(2026, 1, 22, 22, 0, 0, tzinfo=tz)
        
        assert next_end == int(expected.timestamp())
    
    def test_reminder_ts_disabled(self):
        """Test reminder timestamp when disabled."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(
            settings_repo=repo,
            default_reminder_minutes=0,
        )
        
        assert svc.get_reminder_ts() is None
    
    def test_reminder_ts_calculation(self):
        """Test reminder timestamp calculation."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(
            settings_repo=repo,
            default_day_end=22,
            default_reminder_minutes=30,
        )
        
        tz = ZoneInfo("Europe/Zurich")
        
        # At 10:00, reminder should be at 21:30
        dt_10 = datetime(2026, 1, 21, 10, 0, 0, tzinfo=tz)
        ts_10 = int(dt_10.timestamp())
        
        reminder_ts = svc.get_reminder_ts(ts_10)
        expected = datetime(2026, 1, 21, 21, 30, 0, tzinfo=tz)
        
        assert reminder_ts == int(expected.timestamp())
