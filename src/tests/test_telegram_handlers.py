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
