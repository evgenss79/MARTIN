"""
Tests for Night Session Mode (A/B/C) functionality.

Tests the NightSessionMode enum and its integration with:
- DayNightConfigService (get/set/persist)
- StatsService (reset behavior by mode)
- Telegram UI (mode selection)
"""

import pytest

from src.domain.enums import NightSessionMode, PolicyMode, TimeMode
from src.services.day_night_config import DayNightConfigService
from src.services.stats_service import StatsService, compute_quantile


class MockSettingsRepo:
    """Mock settings repository for testing."""
    
    def __init__(self):
        self._data = {}
    
    def get(self, key: str) -> str | None:
        return self._data.get(key)
    
    def set(self, key: str, value: str) -> None:
        self._data[key] = value


class MockStatsRepo:
    """Mock stats repository for testing."""
    
    def __init__(self, stats=None):
        from src.domain.models import Stats
        self._stats = stats or Stats(
            id=1,
            total_trades=0,
            total_wins=0,
            total_losses=0,
            trade_level_streak=0,
            night_streak=0,
            policy_mode=PolicyMode.BASE,
        )
    
    def get(self):
        return self._stats
    
    def update(self, stats):
        self._stats = stats


class MockTradeRepo:
    """Mock trade repository for testing."""
    
    def get_filled_trades_for_quantile(self, time_mode, since_ts, max_samples):
        return []


class TestNightSessionModeEnum:
    """Test the NightSessionMode enum."""
    
    def test_enum_values(self):
        """Test enum has all required values."""
        assert NightSessionMode.OFF.value == "OFF"
        assert NightSessionMode.SOFT_RESET.value == "SOFT"
        assert NightSessionMode.HARD_RESET.value == "HARD"
    
    def test_enum_from_string(self):
        """Test creating enum from string."""
        assert NightSessionMode("OFF") == NightSessionMode.OFF
        assert NightSessionMode("SOFT") == NightSessionMode.SOFT_RESET
        assert NightSessionMode("HARD") == NightSessionMode.HARD_RESET
    
    def test_enum_invalid_string(self):
        """Test invalid string raises ValueError."""
        with pytest.raises(ValueError):
            NightSessionMode("INVALID")


class TestDayNightConfigNightSessionMode:
    """Test DayNightConfigService night session mode methods."""
    
    def test_default_mode_is_off(self):
        """Test default night session mode is OFF."""
        config = DayNightConfigService()
        assert config.get_night_session_mode() == NightSessionMode.OFF
    
    def test_set_mode_soft(self):
        """Test setting mode to SOFT_RESET."""
        repo = MockSettingsRepo()
        config = DayNightConfigService(settings_repo=repo)
        
        success = config.set_night_session_mode(NightSessionMode.SOFT_RESET)
        
        assert success is True
        assert config.get_night_session_mode() == NightSessionMode.SOFT_RESET
        # SOFT mode enables night autotrade
        assert config.get_night_autotrade_enabled() is True
    
    def test_set_mode_hard(self):
        """Test setting mode to HARD_RESET."""
        repo = MockSettingsRepo()
        config = DayNightConfigService(settings_repo=repo)
        
        success = config.set_night_session_mode(NightSessionMode.HARD_RESET)
        
        assert success is True
        assert config.get_night_session_mode() == NightSessionMode.HARD_RESET
        # HARD mode enables night autotrade
        assert config.get_night_autotrade_enabled() is True
    
    def test_set_mode_off_disables_autotrade(self):
        """Test setting mode to OFF disables night autotrade."""
        repo = MockSettingsRepo()
        config = DayNightConfigService(settings_repo=repo)
        
        # First enable SOFT
        config.set_night_session_mode(NightSessionMode.SOFT_RESET)
        assert config.get_night_autotrade_enabled() is True
        
        # Then set OFF
        config.set_night_session_mode(NightSessionMode.OFF)
        assert config.get_night_autotrade_enabled() is False
    
    def test_set_mode_from_string(self):
        """Test setting mode from string value."""
        repo = MockSettingsRepo()
        config = DayNightConfigService(settings_repo=repo)
        
        success = config.set_night_session_mode("SOFT")
        
        assert success is True
        assert config.get_night_session_mode() == NightSessionMode.SOFT_RESET
    
    def test_set_mode_invalid_string(self):
        """Test setting invalid mode string fails."""
        repo = MockSettingsRepo()
        config = DayNightConfigService(settings_repo=repo)
        
        success = config.set_night_session_mode("INVALID")
        
        assert success is False
    
    def test_mode_persists(self):
        """Test mode persists to repository."""
        repo = MockSettingsRepo()
        config1 = DayNightConfigService(settings_repo=repo)
        config1.set_night_session_mode(NightSessionMode.HARD_RESET)
        
        # Create new service with same repo
        config2 = DayNightConfigService(settings_repo=repo)
        
        assert config2.get_night_session_mode() == NightSessionMode.HARD_RESET
    
    def test_mode_description_off(self):
        """Test mode description for OFF."""
        config = DayNightConfigService()
        desc = config.get_night_session_mode_description(NightSessionMode.OFF)
        assert "OFF" in desc
        assert "disabled" in desc.lower()
    
    def test_mode_description_soft(self):
        """Test mode description for SOFT."""
        config = DayNightConfigService()
        desc = config.get_night_session_mode_description(NightSessionMode.SOFT_RESET)
        assert "SOFT" in desc
        assert "night_streak" in desc
    
    def test_mode_description_hard(self):
        """Test mode description for HARD."""
        config = DayNightConfigService()
        desc = config.get_night_session_mode_description(NightSessionMode.HARD_RESET)
        assert "HARD" in desc
        assert "ALL" in desc or "reset" in desc.lower()
    
    def test_mode_short_labels(self):
        """Test short labels for all modes."""
        config = DayNightConfigService()
        
        assert "OFF" in config.get_night_session_mode_short(NightSessionMode.OFF)
        assert "SOFT" in config.get_night_session_mode_short(NightSessionMode.SOFT_RESET)
        assert "HARD" in config.get_night_session_mode_short(NightSessionMode.HARD_RESET)
    
    def test_all_settings_includes_mode(self):
        """Test get_all_settings includes night_session_mode."""
        repo = MockSettingsRepo()
        config = DayNightConfigService(settings_repo=repo)
        config.set_night_session_mode(NightSessionMode.SOFT_RESET)
        
        settings = config.get_all_settings()
        
        assert "night_session_mode" in settings
        assert settings["night_session_mode"] == "SOFT"


class TestStatsServiceNightSessionMode:
    """Test StatsService with different night session modes."""
    
    def _create_stats_service(
        self,
        mode: NightSessionMode = NightSessionMode.SOFT_RESET,
        initial_trade_streak: int = 5,
        initial_night_streak: int = 4,
    ):
        """Create a StatsService with given mode and initial streaks."""
        from src.domain.models import Stats
        
        stats = Stats(
            id=1,
            total_trades=10,
            total_wins=8,
            total_losses=2,
            trade_level_streak=initial_trade_streak,
            night_streak=initial_night_streak,
            policy_mode=PolicyMode.STRICT,
        )
        stats_repo = MockStatsRepo(stats)
        trade_repo = MockTradeRepo()
        
        return StatsService(
            stats_repo=stats_repo,
            trade_repo=trade_repo,
            night_session_mode=mode,
            night_max_win_streak=5,
        )
    
    def test_soft_reset_keeps_trade_streak(self):
        """Test SOFT reset keeps trade_level_streak."""
        service = self._create_stats_service(
            mode=NightSessionMode.SOFT_RESET,
            initial_trade_streak=5,
            initial_night_streak=4,
        )
        
        stats = service.get_stats()
        # Manually trigger night session reset
        result = service._apply_night_session_reset(stats)
        
        # Night streak reset
        assert result.night_streak == 0
        # Trade streak preserved (SOFT reset)
        assert result.trade_level_streak == 5
        # Policy reverts to BASE
        assert result.policy_mode == PolicyMode.BASE
    
    def test_hard_reset_resets_all(self):
        """Test HARD reset resets all streaks."""
        service = self._create_stats_service(
            mode=NightSessionMode.HARD_RESET,
            initial_trade_streak=5,
            initial_night_streak=4,
        )
        
        stats = service.get_stats()
        result = service._apply_night_session_reset(stats)
        
        # Both streaks reset
        assert result.night_streak == 0
        assert result.trade_level_streak == 0
        # Policy reverts to BASE
        assert result.policy_mode == PolicyMode.BASE
    
    def test_set_mode_at_runtime(self):
        """Test changing mode at runtime."""
        service = self._create_stats_service(mode=NightSessionMode.SOFT_RESET)
        
        assert service.get_night_session_mode() == NightSessionMode.SOFT_RESET
        
        service.set_night_session_mode(NightSessionMode.HARD_RESET)
        
        assert service.get_night_session_mode() == NightSessionMode.HARD_RESET
    
    def test_loss_always_resets_all(self):
        """Test that loss always resets all streaks regardless of mode."""
        from src.domain.models import Trade, Stats
        from src.domain.enums import Decision, FillStatus, TradeStatus
        
        # Create service with SOFT mode
        service = self._create_stats_service(
            mode=NightSessionMode.SOFT_RESET,
            initial_trade_streak=5,
            initial_night_streak=3,
        )
        
        # Create a losing trade
        trade = Trade(
            id=1,
            window_id=1,
            signal_id=1,
            status=TradeStatus.SETTLED,
            decision=Decision.OK,
            fill_status=FillStatus.FILLED,
            time_mode=TimeMode.NIGHT,
        )
        
        # Settle as loss
        result = service.on_trade_settled(trade, is_win=False, time_mode=TimeMode.NIGHT)
        
        # Loss always resets everything (MG-7)
        assert result.trade_level_streak == 0
        assert result.night_streak == 0
        assert result.policy_mode == PolicyMode.BASE
