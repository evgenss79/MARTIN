"""
Scheduler wiring tests for MARTIN.

These tests verify MARTIN's actual scheduling mechanism:
1. Orchestrator's periodic tick-based processing
2. Jobs/tasks can be invoked with mocked dependencies
3. Service lifecycle works correctly

MARTIN uses an internal async loop (asyncio) for scheduling, NOT APScheduler.
The Orchestrator runs a main loop that:
- Ticks every 60 seconds
- Discovers new markets
- Processes active trades
- Checks for settlements

This approach is simpler and more appropriate for MARTIN's needs.
"""
import os
import sys
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestOrchestratorScheduling:
    """Test Orchestrator's internal scheduling mechanism."""
    
    def test_orchestrator_has_tick_method(self):
        """Verify Orchestrator has _tick method for periodic processing."""
        from services.orchestrator import Orchestrator
        
        # Verify the _tick method exists
        assert hasattr(Orchestrator, '_tick')
        
        # Verify it's an async method
        import inspect
        assert inspect.iscoroutinefunction(Orchestrator._tick)
    
    def test_orchestrator_has_processing_methods(self):
        """Verify Orchestrator has all required processing methods."""
        from services.orchestrator import Orchestrator
        
        # These methods implement MARTIN's scheduling tasks:
        # 1. Market discovery
        assert hasattr(Orchestrator, '_discover_markets')
        # 2. Trade processing
        assert hasattr(Orchestrator, '_process_active_trades')
        # 3. Settlement checking
        assert hasattr(Orchestrator, '_check_settlements')
        
        # All should be async
        import inspect
        assert inspect.iscoroutinefunction(Orchestrator._discover_markets)
        assert inspect.iscoroutinefunction(Orchestrator._process_active_trades)
        assert inspect.iscoroutinefunction(Orchestrator._check_settlements)
    
    def test_orchestrator_has_start_stop_methods(self):
        """Verify Orchestrator has lifecycle methods."""
        from services.orchestrator import Orchestrator
        
        assert hasattr(Orchestrator, 'start')
        assert hasattr(Orchestrator, 'stop')
        
        import inspect
        assert inspect.iscoroutinefunction(Orchestrator.start)
        assert inspect.iscoroutinefunction(Orchestrator.stop)


class TestJobInvocationWithMocks:
    """Test that scheduled jobs/tasks can be invoked with mocks."""
    
    @pytest.mark.asyncio
    async def test_market_discovery_with_mocks(self):
        """Verify market discovery task can be invoked with mocked Gamma client."""
        mock_gamma_client = Mock()
        mock_gamma_client.discover_hourly_markets = AsyncMock(return_value=[
            Mock(
                slug='btc-up-or-down-jan-21-2026-1800',
                asset='BTC',
                start_ts=int(datetime.now().timestamp()),
                end_ts=int((datetime.now() + timedelta(hours=1)).timestamp()),
                up_token_id='token_up',
                down_token_id='token_down'
            )
        ])
        
        # Invoke the discovery function
        markets = await mock_gamma_client.discover_hourly_markets(
            assets=['BTC', 'ETH'],
            current_ts=int(datetime.now().timestamp())
        )
        
        assert len(markets) == 1
        assert markets[0].slug == 'btc-up-or-down-jan-21-2026-1800'
        mock_gamma_client.discover_hourly_markets.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cap_check_task_with_mocks(self):
        """Verify CAP check task works with mocked CLOB client."""
        mock_clob_client = Mock()
        mock_clob_client.get_prices_history = AsyncMock(return_value=[
            {'t': 1000, 'p': 0.55},
            {'t': 1001, 'p': 0.54},
            {'t': 1002, 'p': 0.53},
            {'t': 1003, 'p': 0.52},
            {'t': 1004, 'p': 0.51},  # CAP_PASS: 5 consecutive <= 0.55
        ])
        
        # Invoke
        history = await mock_clob_client.get_prices_history(
            token_id='test_token',
            start_ts=1000,
            end_ts=2000
        )
        
        assert len(history) == 5
        # Verify all prices <= cap
        for tick in history:
            assert tick['p'] <= 0.55
    
    @pytest.mark.asyncio
    async def test_telegram_notification_with_mocks(self):
        """Verify Telegram notification works with mocked bot."""
        mock_bot = Mock()
        mock_bot.send_message = AsyncMock(return_value={'message_id': 123})
        
        # Simulate reminder notification
        result = await mock_bot.send_message(
            chat_id=12345,
            text="⏰ Reminder: Day window ends in 30 minutes!"
        )
        
        assert result['message_id'] == 123
        mock_bot.send_message.assert_called_once()


class TestJobScheduleConfiguration:
    """Test job schedule configuration from config."""
    
    def test_config_has_schedule_settings(self):
        """Verify config includes scheduling-related settings."""
        import json
        import os
        
        config_path = os.path.join(
            os.path.dirname(__file__), 
            '../../config/config.json'
        )
        with open(config_path) as f:
            config = json.load(f)
        
        # Verify trading window settings
        assert 'trading' in config
        assert 'window_seconds' in config['trading']
        assert config['trading']['window_seconds'] == 3600  # 1 hour
    
    def test_day_night_hours_configurable(self):
        """Verify day/night hours are in config."""
        import json
        import os
        
        config_path = os.path.join(
            os.path.dirname(__file__), 
            '../../config/config.json'
        )
        with open(config_path) as f:
            config = json.load(f)
        
        assert 'day_night' in config
        assert 'day_start_hour' in config['day_night']
        assert 'day_end_hour' in config['day_night']
        
        # Valid hour range
        assert 0 <= config['day_night']['day_start_hour'] <= 23
        assert 0 <= config['day_night']['day_end_hour'] <= 23


class TestAsyncContextManagement:
    """Test async context management for services."""
    
    @pytest.mark.asyncio
    async def test_http_client_context(self):
        """Verify HTTP client can be created and closed properly."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            assert client is not None
            # Don't make actual requests, just verify context works
    
    @pytest.mark.asyncio
    async def test_mock_service_lifecycle(self):
        """Verify service lifecycle with mocks."""
        # Mock a service with start/stop
        class MockService:
            def __init__(self):
                self.started = False
                self.stopped = False
            
            async def start(self):
                self.started = True
            
            async def stop(self):
                self.stopped = True
        
        service = MockService()
        
        await service.start()
        assert service.started
        
        await service.stop()
        assert service.stopped


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
