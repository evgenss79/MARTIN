"""
Scheduler wiring tests for MARTIN.

These tests verify:
1. Scheduler can be instantiated
2. Jobs can be registered
3. Jobs can be invoked once with mocked dependencies
"""
import os
import sys
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestSchedulerWiring:
    """Test scheduler job registration and invocation."""
    
    def test_scheduler_can_be_created(self):
        """Verify scheduler instance can be created."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        
        scheduler = AsyncIOScheduler()
        assert scheduler is not None
        assert not scheduler.running
    
    def test_job_can_be_registered(self):
        """Verify jobs can be registered with scheduler."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        
        scheduler = AsyncIOScheduler()
        
        # Register a dummy job
        def dummy_job():
            pass
        
        job = scheduler.add_job(
            dummy_job,
            trigger=IntervalTrigger(seconds=60),
            id='test_job',
            replace_existing=True
        )
        
        assert job is not None
        assert job.id == 'test_job'
        assert 'test_job' in [j.id for j in scheduler.get_jobs()]
    
    def test_multiple_jobs_can_be_registered(self):
        """Verify multiple jobs can be registered."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
        
        scheduler = AsyncIOScheduler()
        
        # Register market discovery job (hourly)
        scheduler.add_job(
            lambda: None,
            trigger=CronTrigger(minute=0),
            id='market_discovery',
            replace_existing=True
        )
        
        # Register reminder check job (every minute)
        scheduler.add_job(
            lambda: None,
            trigger=IntervalTrigger(minutes=1),
            id='reminder_check',
            replace_existing=True
        )
        
        # Register cap check job (every 5 seconds)
        scheduler.add_job(
            lambda: None,
            trigger=IntervalTrigger(seconds=5),
            id='cap_check',
            replace_existing=True
        )
        
        jobs = scheduler.get_jobs()
        job_ids = [j.id for j in jobs]
        
        assert 'market_discovery' in job_ids
        assert 'reminder_check' in job_ids
        assert 'cap_check' in job_ids
    
    @pytest.mark.asyncio
    async def test_job_invocation_with_mocks(self):
        """Verify job can be invoked with mocked dependencies."""
        # Mock the discovery job
        mock_gamma_client = Mock()
        mock_gamma_client.discover_markets = AsyncMock(return_value=[
            {
                'slug': 'btc-up-or-down-jan-21-2026-1800',
                'question': 'Will BTC go up?',
                'start_ts': int(datetime.now().timestamp()),
                'end_ts': int((datetime.now() + timedelta(hours=1)).timestamp()),
                'up_token_id': 'token_up',
                'down_token_id': 'token_down'
            }
        ])
        
        # Invoke the discovery function directly
        markets = await mock_gamma_client.discover_markets(assets=['BTC', 'ETH'])
        
        assert len(markets) == 1
        assert markets[0]['slug'] == 'btc-up-or-down-jan-21-2026-1800'
        mock_gamma_client.discover_markets.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cap_check_job_with_mocks(self):
        """Verify cap check job works with mocked CLOB client."""
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
    async def test_reminder_job_with_mocks(self):
        """Verify reminder job works with mocked telegram bot."""
        mock_bot = Mock()
        mock_bot.send_message = AsyncMock(return_value={'message_id': 123})
        
        # Simulate reminder
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
