"""
Tests for CAP_PASS logic.

Ensures:
- CAP_PASS before confirm_ts does NOT count (MG-2)
- Minimum consecutive ticks logic works correctly
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.cap_check import CapCheckService
from src.domain.models import CapCheck, Trade
from src.domain.enums import CapStatus, TradeStatus


class TestCapPassLogic:
    """Tests for CAP_PASS validation."""
    
    @pytest.fixture
    def mock_clob_client(self):
        """Create mock CLOB client."""
        client = MagicMock()
        client.get_prices_in_range = AsyncMock()
        return client
    
    @pytest.fixture
    def mock_cap_check_repo(self):
        """Create mock CAP check repository."""
        repo = MagicMock()
        repo.create = MagicMock(side_effect=lambda x: x)
        repo.update = MagicMock()
        return repo
    
    @pytest.fixture
    def cap_check_service(self, mock_clob_client, mock_cap_check_repo):
        """Create CAP check service with mocks."""
        return CapCheckService(
            clob_client=mock_clob_client,
            cap_check_repo=mock_cap_check_repo,
            price_cap=0.55,
            cap_min_ticks=3,
        )
    
    @pytest.mark.asyncio
    async def test_cap_pass_ignores_ticks_before_confirm_ts(
        self, 
        cap_check_service, 
        mock_clob_client
    ):
        """
        MG-2: CAP_PASS is valid ONLY if consecutive ticks occur AFTER confirm_ts.
        Ticks before confirm_ts must be ignored.
        """
        # Setup: Prices that would pass IF we counted before confirm_ts
        # But the passing ticks are before confirm_ts
        mock_clob_client.get_prices_in_range.return_value = [
            (1000, 0.50),  # Before confirm_ts - should be ignored
            (1001, 0.51),  # Before confirm_ts - should be ignored
            (1002, 0.52),  # Before confirm_ts - should be ignored
            (1100, 0.60),  # After confirm_ts - above cap
            (1101, 0.58),  # After confirm_ts - above cap
        ]
        
        cap_check = CapCheck(
            id=1,
            trade_id=1,
            token_id="token123",
            confirm_ts=1050,  # Confirm at 1050
            end_ts=1200,
            status=CapStatus.PENDING,
        )
        
        # Process
        result = await cap_check_service.check_cap_pass(cap_check, current_ts=1200)
        
        # The ticks before confirm_ts (1000, 1001, 1002) should be ignored
        # The ticks after (1100, 1101) are above cap, so FAIL
        assert result.status == CapStatus.FAIL
    
    @pytest.mark.asyncio
    async def test_cap_pass_with_consecutive_ticks_after_confirm(
        self,
        cap_check_service,
        mock_clob_client
    ):
        """CAP_PASS should trigger when consecutive ticks meet threshold after confirm_ts."""
        mock_clob_client.get_prices_in_range.return_value = [
            (1100, 0.54),  # <= 0.55, tick 1
            (1101, 0.53),  # <= 0.55, tick 2
            (1102, 0.52),  # <= 0.55, tick 3 -> PASS!
        ]
        
        cap_check = CapCheck(
            id=1,
            trade_id=1,
            token_id="token123",
            confirm_ts=1050,
            end_ts=1200,
            status=CapStatus.PENDING,
        )
        
        result = await cap_check_service.check_cap_pass(cap_check, current_ts=1150)
        
        assert result.status == CapStatus.PASS
        assert result.consecutive_ticks == 3
        assert result.first_pass_ts == 1100
        assert result.price_at_pass == 0.54
    
    @pytest.mark.asyncio
    async def test_cap_pass_resets_on_price_above_cap(
        self,
        cap_check_service,
        mock_clob_client
    ):
        """Consecutive count should reset when price exceeds cap."""
        mock_clob_client.get_prices_in_range.return_value = [
            (1100, 0.54),  # <= 0.55, tick 1
            (1101, 0.53),  # <= 0.55, tick 2
            (1102, 0.60),  # > 0.55, RESET!
            (1103, 0.52),  # <= 0.55, tick 1 (restart)
            (1104, 0.51),  # <= 0.55, tick 2
        ]
        
        cap_check = CapCheck(
            id=1,
            trade_id=1,
            token_id="token123",
            confirm_ts=1050,
            end_ts=1200,
            status=CapStatus.PENDING,
        )
        
        result = await cap_check_service.check_cap_pass(cap_check, current_ts=1200)
        
        # Only 2 consecutive after reset, not enough
        assert result.status == CapStatus.FAIL
        assert result.consecutive_ticks == 2
    
    @pytest.mark.asyncio
    async def test_cap_pass_requires_min_ticks(
        self,
        cap_check_service,
        mock_clob_client
    ):
        """CAP_PASS requires minimum consecutive ticks."""
        # Only 2 ticks, but we need 3
        mock_clob_client.get_prices_in_range.return_value = [
            (1100, 0.54),  # <= 0.55, tick 1
            (1101, 0.53),  # <= 0.55, tick 2
        ]
        
        cap_check = CapCheck(
            id=1,
            trade_id=1,
            token_id="token123",
            confirm_ts=1050,
            end_ts=1200,
            status=CapStatus.PENDING,
        )
        
        result = await cap_check_service.check_cap_pass(cap_check, current_ts=1200)
        
        assert result.status == CapStatus.FAIL
        assert result.consecutive_ticks == 2
    
    def test_late_condition_when_confirm_after_end(
        self,
        cap_check_service,
        mock_cap_check_repo
    ):
        """CAP check should be LATE if confirm_ts >= end_ts."""
        trade = Trade(id=1, window_id=1, status=TradeStatus.WAITING_CAP)
        
        cap_check = cap_check_service.create_cap_check(
            trade=trade,
            token_id="token123",
            confirm_ts=1200,  # confirm_ts >= end_ts
            end_ts=1100,
        )
        
        assert cap_check.status == CapStatus.LATE
    
    @pytest.mark.asyncio
    async def test_cap_pass_edge_case_exact_price_cap(
        self,
        cap_check_service,
        mock_clob_client
    ):
        """Price exactly at cap should count (<= not <)."""
        mock_clob_client.get_prices_in_range.return_value = [
            (1100, 0.55),  # == 0.55, should count
            (1101, 0.55),  # == 0.55, should count
            (1102, 0.55),  # == 0.55, should count -> PASS
        ]
        
        cap_check = CapCheck(
            id=1,
            trade_id=1,
            token_id="token123",
            confirm_ts=1050,
            end_ts=1200,
            status=CapStatus.PENDING,
        )
        
        result = await cap_check_service.check_cap_pass(cap_check, current_ts=1150)
        
        assert result.status == CapStatus.PASS
        assert result.consecutive_ticks == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
