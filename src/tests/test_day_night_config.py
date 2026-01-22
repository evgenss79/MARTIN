"""
Tests for Day/Night Configuration Service.

Tests configurable day/night time ranges and persistence.
"""

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo


class MockSettingsRepo:
    """Mock settings repository for testing."""
    
    def __init__(self):
        self._settings = {}
    
    def get(self, key: str) -> str | None:
        return self._settings.get(key)
    
    def set(self, key: str, value: str) -> None:
        self._settings[key] = value


class TestDayNightConfigService:
    """Tests for DayNightConfigService."""
    
    def test_default_values(self):
        """Test that defaults are used when no settings persisted."""
        from src.services.day_night_config import DayNightConfigService
        
        svc = DayNightConfigService(
            settings_repo=None,
            default_day_start=8,
            default_day_end=22,
        )
        
        assert svc.get_day_start_hour() == 8
        assert svc.get_day_end_hour() == 22
    
    def test_persisted_values_override_defaults(self):
        """Test that persisted values override defaults."""
        from src.services.day_night_config import (
            DayNightConfigService,
            SETTING_DAY_START_HOUR,
            SETTING_DAY_END_HOUR,
        )
        
        repo = MockSettingsRepo()
        repo.set(SETTING_DAY_START_HOUR, "6")
        repo.set(SETTING_DAY_END_HOUR, "20")
        
        svc = DayNightConfigService(
            settings_repo=repo,
            default_day_start=8,
            default_day_end=22,
        )
        
        assert svc.get_day_start_hour() == 6
        assert svc.get_day_end_hour() == 20
    
    def test_set_day_hours_persists(self):
        """Test that setting day hours persists to repository."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(settings_repo=repo)
        
        assert svc.set_day_start_hour(7)
        assert svc.set_day_end_hour(23)
        
        assert svc.get_day_start_hour() == 7
        assert svc.get_day_end_hour() == 23
    
    def test_invalid_hour_rejected(self):
        """Test that invalid hours are rejected."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(settings_repo=repo)
        
        assert not svc.set_day_start_hour(-1)
        assert not svc.set_day_start_hour(24)
        assert not svc.set_day_end_hour(25)


class TestCurrentModeDetection:
    """Tests for current mode detection including wrap-around."""
    
    def test_normal_day_range(self):
        """Test normal day range (8 to 22)."""
        from src.services.day_night_config import DayNightConfigService
        from src.domain.enums import TimeMode
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(
            settings_repo=repo,
            default_day_start=8,
            default_day_end=22,
        )
        
        # Create timestamps for testing in Europe/Zurich
        tz = ZoneInfo("Europe/Zurich")
        
        # 10:00 should be DAY
        dt_10 = datetime(2026, 1, 21, 10, 0, 0, tzinfo=tz)
        ts_10 = int(dt_10.timestamp())
        assert svc.get_current_mode(ts_10) == TimeMode.DAY
        
        # 23:00 should be NIGHT
        dt_23 = datetime(2026, 1, 21, 23, 0, 0, tzinfo=tz)
        ts_23 = int(dt_23.timestamp())
        assert svc.get_current_mode(ts_23) == TimeMode.NIGHT
        
        # 07:00 should be NIGHT
        dt_07 = datetime(2026, 1, 21, 7, 0, 0, tzinfo=tz)
        ts_07 = int(dt_07.timestamp())
        assert svc.get_current_mode(ts_07) == TimeMode.NIGHT
    
    def test_wrap_around_midnight(self):
        """Test wrap-around range (22 to 6) - evening to morning."""
        from src.services.day_night_config import DayNightConfigService
        from src.domain.enums import TimeMode
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(
            settings_repo=repo,
            default_day_start=22,  # Day starts at 22:00
            default_day_end=6,     # Day ends at 06:00
        )
        
        tz = ZoneInfo("Europe/Zurich")
        
        # 23:00 should be DAY (in the wrap range)
        dt_23 = datetime(2026, 1, 21, 23, 0, 0, tzinfo=tz)
        ts_23 = int(dt_23.timestamp())
        assert svc.get_current_mode(ts_23) == TimeMode.DAY
        
        # 02:00 should be DAY (in the wrap range)
        dt_02 = datetime(2026, 1, 21, 2, 0, 0, tzinfo=tz)
        ts_02 = int(dt_02.timestamp())
        assert svc.get_current_mode(ts_02) == TimeMode.DAY
        
        # 05:59 should be DAY
        dt_0559 = datetime(2026, 1, 21, 5, 59, 0, tzinfo=tz)
        ts_0559 = int(dt_0559.timestamp())
        assert svc.get_current_mode(ts_0559) == TimeMode.DAY
        
        # 06:00 should be NIGHT (day ends at 6)
        dt_06 = datetime(2026, 1, 21, 6, 0, 0, tzinfo=tz)
        ts_06 = int(dt_06.timestamp())
        assert svc.get_current_mode(ts_06) == TimeMode.NIGHT
        
        # 12:00 should be NIGHT
        dt_12 = datetime(2026, 1, 21, 12, 0, 0, tzinfo=tz)
        ts_12 = int(dt_12.timestamp())
        assert svc.get_current_mode(ts_12) == TimeMode.NIGHT
        
        # 21:59 should be NIGHT
        dt_2159 = datetime(2026, 1, 21, 21, 59, 0, tzinfo=tz)
        ts_2159 = int(dt_2159.timestamp())
        assert svc.get_current_mode(ts_2159) == TimeMode.NIGHT
    
    def test_same_hour_start_end(self):
        """Test edge case where start equals end (24 hour day)."""
        from src.services.day_night_config import DayNightConfigService
        from src.domain.enums import TimeMode
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(
            settings_repo=repo,
            default_day_start=8,
            default_day_end=8,  # Same as start
        )
        
        tz = ZoneInfo("Europe/Zurich")
        
        # With start == end, the wrap logic applies: hour >= 8 OR hour < 8 = always true
        dt_10 = datetime(2026, 1, 21, 10, 0, 0, tzinfo=tz)
        ts_10 = int(dt_10.timestamp())
        assert svc.get_current_mode(ts_10) == TimeMode.DAY


class TestReminderMinutes:
    """Tests for reminder configuration."""
    
    def test_default_reminder(self):
        """Test default reminder minutes."""
        from src.services.day_night_config import DayNightConfigService
        
        svc = DayNightConfigService(
            settings_repo=None,
            default_reminder_minutes=30,
        )
        
        assert svc.get_reminder_minutes() == 30
    
    def test_set_reminder_minutes(self):
        """Test setting reminder minutes."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(settings_repo=repo)
        
        assert svc.set_reminder_minutes(45)
        assert svc.get_reminder_minutes() == 45
        
        assert svc.set_reminder_minutes(0)  # Disable
        assert svc.get_reminder_minutes() == 0
    
    def test_invalid_reminder_rejected(self):
        """Test that invalid reminder values are rejected."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(settings_repo=repo)
        
        assert not svc.set_reminder_minutes(-1)
        assert not svc.set_reminder_minutes(181)  # Max is 180


class TestGetAllSettings:
    """Tests for get_all_settings."""
    
    def test_get_all_settings(self):
        """Test getting all settings as dict."""
        from src.services.day_night_config import DayNightConfigService
        
        repo = MockSettingsRepo()
        svc = DayNightConfigService(
            settings_repo=repo,
            default_day_start=9,
            default_day_end=21,
            default_reminder_minutes=60,
        )
        
        settings = svc.get_all_settings()
        
        assert settings["day_start_hour"] == 9
        assert settings["day_end_hour"] == 21
        assert settings["reminder_minutes"] == 60
        assert "base_day_quality" in settings
        assert "night_autotrade_enabled" in settings
