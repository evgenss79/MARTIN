"""
Tests for Telegram handlers and UX.

Tests verify:
- Handler registration
- Callback timeout fix (answer called immediately)
- Settings menu renders human-readable text
- Gamma query strings don't include 'hourly'
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio


class TestHandlersRegistered:
    """Test that all required handlers are registered."""
    
    def test_start_status_handlers_registered(self):
        """Test that /start and /status handlers are registered."""
        from src.adapters.telegram.bot import TelegramHandler
        
        # Check that TelegramHandler has the methods we expect
        assert hasattr(TelegramHandler, '_register_handlers')
        
    def test_telegram_handler_has_required_methods(self):
        """Test TelegramHandler has all required methods."""
        from src.adapters.telegram.bot import TelegramHandler
        
        # Check key methods exist
        assert hasattr(TelegramHandler, 'start')
        assert hasattr(TelegramHandler, 'stop')
        assert hasattr(TelegramHandler, 'send_trade_card')
        assert hasattr(TelegramHandler, '_show_settings_menu')
        assert hasattr(TelegramHandler, '_handle_auth_callback')
        assert hasattr(TelegramHandler, '_build_auth_buttons_keyboard')


class TestCallbackAnswerEarly:
    """Test that callback.answer() is called immediately."""
    
    def test_callback_answer_called_immediately_pattern(self):
        """Test that callback handler calls answer() as first async operation."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        # Get the source of _register_handlers
        source = inspect.getsource(TelegramHandler._register_handlers)
        
        # The callback handler should call answer() immediately
        # Look for the pattern in handle_callback function
        assert "await callback.answer()" in source
        
        # Find the handle_callback section
        lines = source.split('\n')
        in_handle_callback = False
        found_answer_early = False
        
        for i, line in enumerate(lines):
            if "async def handle_callback" in line:
                in_handle_callback = True
            if in_handle_callback:
                # The first await should be callback.answer()
                if "await callback.answer()" in line:
                    # Check it's before any other work (no data processing before it)
                    found_answer_early = True
                    break
                # If we find data processing before answer(), fail
                if "data = callback.data" in line:
                    # answer() should come before this
                    assert found_answer_early, "callback.answer() should be called before processing data"
        
        # The pattern where answer() is called first is present
        assert "# CRITICAL: Answer callback IMMEDIATELY" in source


class TestSettingsMenuRendersHumanText:
    """Test that settings menu renders human-readable text."""
    
    def test_settings_menu_has_human_readable_sections(self):
        """Test _show_settings_menu produces human-readable output."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._show_settings_menu)
        
        # Check for human-readable section headers
        assert "⚙️ *Settings*" in source
        assert "*Current Mode:*" in source
        assert "*Day/Night Hours:*" in source
        assert "*Quality Thresholds:*" in source
        
        # Check it doesn't dump raw JSON
        assert "json.dumps" not in source
        assert ".json()" not in source
    
    def test_settings_menu_has_edit_buttons(self):
        """Test settings menu has interactive edit buttons."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._show_settings_menu)
        
        # Check for edit buttons
        assert "🕐 Day Hours" in source
        assert "📊 Quality" in source
        assert "🌙 Night Mode" in source
        assert "⏰ Reminder" in source


class TestGammaQueryStrings:
    """Test that Gamma query strings don't include 'hourly'."""
    
    def test_gamma_query_strings_do_not_include_hourly(self):
        """Test discover_hourly_markets uses correct query format."""
        import inspect
        from src.adapters.polymarket.gamma_client import GammaClient
        
        source = inspect.getsource(GammaClient.discover_hourly_markets)
        
        # Should NOT have 'hourly' in the query string
        # The recurrence=hourly is passed as a parameter, not in q string
        assert 'query = f"{asset} up or down hourly"' not in source, \
            "Query string should NOT include 'hourly' - it's a separate parameter"
        
        # Should have the correct pattern
        assert 'f"{asset} up or down"' in source
    
    def test_gamma_has_fallback_queries(self):
        """Test that Gamma discovery has fallback query strategies."""
        import inspect
        from src.adapters.polymarket.gamma_client import GammaClient
        
        source = inspect.getsource(GammaClient.discover_hourly_markets)
        
        # Should have fallback for Bitcoin/Ethereum
        assert "Bitcoin" in source or "fallback" in source.lower()
    
    def test_gamma_logs_search_results(self):
        """Test that Gamma logs search results for debugging."""
        import inspect
        from src.adapters.polymarket.gamma_client import GammaClient
        
        source = inspect.getsource(GammaClient.discover_hourly_markets)
        
        # Should log results for debugging
        assert "logger.debug" in source
        assert "top_titles" in source or "Gamma search" in source


class TestAuthButtons:
    """Test that auth buttons are present in the bot."""
    
    def test_auth_buttons_keyboard_builder_exists(self):
        """Test that _build_auth_buttons_keyboard method exists."""
        from src.adapters.telegram.bot import TelegramHandler
        
        assert hasattr(TelegramHandler, '_build_auth_buttons_keyboard')
    
    def test_auth_callback_handler_exists(self):
        """Test that _handle_auth_callback method exists."""
        from src.adapters.telegram.bot import TelegramHandler
        
        assert hasattr(TelegramHandler, '_handle_auth_callback')
    
    def test_auth_buttons_has_paper_mode_handling(self):
        """Test auth buttons handle paper mode correctly."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._build_auth_buttons_keyboard)
        
        assert "paper" in source.lower()
        assert "Paper Mode" in source
    
    def test_auth_buttons_has_live_mode_handling(self):
        """Test auth buttons handle live mode correctly."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._build_auth_buttons_keyboard)
        
        # Should have authorize, recheck, and logout buttons for live mode
        assert "Authorize" in source
        assert "Recheck" in source or "recheck" in source
        assert "Log out" in source or "logout" in source


class TestHandlerLogging:
    """Test that handlers log their activity."""
    
    def test_commands_have_logging(self):
        """Test that command handlers log their invocation."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._register_handlers)
        
        # Check for logging in handlers
        assert 'logger.info("Command /start"' in source
        assert 'logger.info("Command /status"' in source
        assert 'logger.info("Command /pause"' in source
        assert 'logger.info("Command /settings"' in source
    
    def test_callbacks_have_logging(self):
        """Test that callback handlers log their activity."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._register_handlers)
        
        # Check for callback logging
        assert 'logger.debug("Callback received"' in source


class TestUnknownCommandHandler:
    """Test that unknown commands like /command1 are handled."""
    
    def test_unknown_command_handler_exists(self):
        """Test that handler for /command1-8 exists."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._register_handlers)
        
        # Check that unknown command handler is registered
        assert "command1" in source
        assert "Unknown Command" in source
    
    def test_unknown_command_shows_available_commands(self):
        """Test that unknown command response lists available commands."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._register_handlers)
        
        # Check that response includes available commands
        assert "/start" in source
        assert "/status" in source
        assert "/settings" in source


class TestEditableSettings:
    """Test that settings are editable via inline buttons."""
    
    def test_quality_settings_has_adjustment_buttons(self):
        """Test that quality settings has +/- buttons."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._show_quality_settings)
        
        # Check for adjustment buttons
        assert "quality_day_" in source
        assert "quality_night_" in source
        assert "-10" in source or "-5" in source
        assert "+10" in source or "+5" in source
    
    def test_streak_settings_has_adjustment_buttons(self):
        """Test that streak settings has +/- buttons."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._show_streak_settings)
        
        # Check for adjustment buttons
        assert "streak_switch_" in source
        assert "streak_nightmax_" in source
    
    def test_trading_settings_has_adjustment_buttons(self):
        """Test that trading settings has +/- buttons."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._show_trading_info)
        
        # Check for adjustment buttons
        assert "trading_cap_" in source
        assert "trading_delay_" in source
        assert "trading_ticks_" in source
        assert "trading_stake_" in source
    
    def test_adjustment_methods_exist(self):
        """Test that all adjustment methods exist."""
        from src.adapters.telegram.bot import TelegramHandler
        
        # Quality adjustments
        assert hasattr(TelegramHandler, '_adjust_quality_day')
        assert hasattr(TelegramHandler, '_adjust_quality_night')
        
        # Streak adjustments
        assert hasattr(TelegramHandler, '_adjust_switch_streak')
        assert hasattr(TelegramHandler, '_adjust_night_max_streak')
        
        # Trading adjustments
        assert hasattr(TelegramHandler, '_adjust_price_cap')
        assert hasattr(TelegramHandler, '_adjust_confirm_delay')
        assert hasattr(TelegramHandler, '_adjust_cap_min_ticks')
        assert hasattr(TelegramHandler, '_adjust_base_stake')


class TestDayNightConfigServiceTrading:
    """Test DayNightConfigService trading parameter methods."""
    
    def test_trading_getters_exist(self):
        """Test that trading parameter getters exist."""
        from src.services.day_night_config import DayNightConfigService
        
        assert hasattr(DayNightConfigService, 'get_price_cap')
        assert hasattr(DayNightConfigService, 'get_confirm_delay')
        assert hasattr(DayNightConfigService, 'get_cap_min_ticks')
        assert hasattr(DayNightConfigService, 'get_base_stake')
    
    def test_trading_setters_exist(self):
        """Test that trading parameter setters exist."""
        from src.services.day_night_config import DayNightConfigService
        
        assert hasattr(DayNightConfigService, 'set_price_cap')
        assert hasattr(DayNightConfigService, 'set_confirm_delay')
        assert hasattr(DayNightConfigService, 'set_cap_min_ticks')
        assert hasattr(DayNightConfigService, 'set_base_stake')
    
    def test_price_cap_validation(self):
        """Test that price cap validates range 0.01-0.99."""
        from src.services.day_night_config import DayNightConfigService
        
        config = DayNightConfigService(settings_repo=None, default_price_cap=0.55)
        
        # Test valid value
        assert config.get_price_cap() == 0.55
        
        # Test invalid values (no repo, so set_* returns False without persistence)
        # The validation logic is still tested
        assert config.set_price_cap(0.005) is False  # Too low
        assert config.set_price_cap(1.5) is False    # Too high
    
    def test_cap_min_ticks_validation(self):
        """Test that cap min ticks validates >= 1."""
        from src.services.day_night_config import DayNightConfigService
        
        config = DayNightConfigService(settings_repo=None, default_cap_min_ticks=3)
        
        assert config.get_cap_min_ticks() == 3
        assert config.set_cap_min_ticks(0) is False  # Invalid


class TestAuthSectionVisibility:
    """Test that auth section is visible in paper mode."""
    
    def test_auth_section_visible_in_paper_mode(self):
        """Test that _build_auth_buttons_keyboard handles paper mode."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._build_auth_buttons_keyboard)
        
        # Should have paper mode handling with informational button
        assert "paper" in source.lower()
        assert "Paper Mode" in source
    
    def test_start_command_shows_auth_indicator(self):
        """Test that /start command shows auth status."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._register_handlers)
        
        # Find the cmd_start handler and check it includes auth
        assert "Auth Status" in source
        assert "_get_polymarket_auth_indicator" in source
    
    def test_status_command_shows_auth_indicator(self):
        """Test that /status command shows auth status."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._register_handlers)
        
        # Status should include auth indicator
        assert "auth_indicator" in source


class TestAuthIndicatorCompatibility:
    """Test that auth indicator has .authorized property for bot.py compatibility."""
    
    def test_auth_indicator_has_authorized_property(self):
        """Test PolymarketAuthIndicator exposes .authorized property."""
        from src.services.status_indicator import PolymarketAuthIndicator
        
        indicator = PolymarketAuthIndicator(
            is_authorized=True,
            emoji="🟡",
            label="Test",
        )
        
        # Both .authorized and .is_authorized should work
        assert hasattr(indicator, 'authorized')
        assert hasattr(indicator, 'is_authorized')
        assert indicator.authorized == indicator.is_authorized
    
    def test_auth_buttons_uses_defensive_getattr(self):
        """Test that _build_auth_buttons_keyboard has defensive fallback."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._build_auth_buttons_keyboard)
        
        # Should use defensive getattr pattern or try-except
        assert "getattr" in source or "try:" in source
    
    def test_start_and_status_do_not_crash_with_auth_indicator(self):
        """Test that /start and /status handlers reference auth indicator safely."""
        import inspect
        from src.adapters.telegram.bot import TelegramHandler
        
        source = inspect.getsource(TelegramHandler._register_handlers)
        
        # Commands should reference auth indicator
        assert "_get_polymarket_auth_indicator" in source
        
        # Should have defensive handling
        build_auth_source = inspect.getsource(TelegramHandler._build_auth_buttons_keyboard)
        assert "getattr" in build_auth_source or "try:" in build_auth_source
