"""
Tests for Status Indicator Service.

Tests the series activity and Polymarket auth indicators.
"""

import os
import pytest

from src.services.status_indicator import (
    compute_series_indicator,
    compute_polymarket_auth_indicator,
    SeriesIndicator,
    PolymarketAuthIndicator,
    IN_PROGRESS_STATUSES,
)
from src.domain.models import Stats, Trade
from src.domain.enums import TradeStatus, TimeMode, PolicyMode, Decision, FillStatus


class TestSeriesIndicator:
    """Tests for series activity indicator."""
    
    def _create_stats(
        self,
        is_paused: bool = False,
        day_only: bool = False,
        night_only: bool = False,
        trade_level_streak: int = 0,
    ) -> Stats:
        """Create test stats."""
        return Stats(
            id=1,
            policy_mode=PolicyMode.BASE,
            trade_level_streak=trade_level_streak,
            night_streak=0,
            total_trades=0,
            total_wins=0,
            total_losses=0,
            is_paused=is_paused,
            day_only=day_only,
            night_only=night_only,
        )
    
    def _create_trade(self, status: TradeStatus) -> Trade:
        """Create test trade with given status."""
        return Trade(
            id=1,
            window_id=1,
            status=status,
            time_mode=TimeMode.DAY,
            policy_mode=PolicyMode.BASE,
            decision=Decision.PENDING,
            fill_status=FillStatus.PENDING,
        )
    
    def test_inactive_when_paused(self):
        """Series should be inactive when bot is paused."""
        stats = self._create_stats(is_paused=True, trade_level_streak=5)
        trades = [self._create_trade(TradeStatus.READY)]
        
        result = compute_series_indicator(
            stats=stats,
            active_trades=trades,
            current_time_mode=TimeMode.DAY,
            night_autotrade_enabled=True,
        )
        
        assert not result.is_active
        assert result.emoji == "🔴"
        assert "Paused" in result.label
    
    def test_inactive_when_day_only_in_night(self):
        """Series should be inactive when day-only mode during night."""
        stats = self._create_stats(day_only=True, trade_level_streak=3)
        trades = [self._create_trade(TradeStatus.READY)]
        
        result = compute_series_indicator(
            stats=stats,
            active_trades=trades,
            current_time_mode=TimeMode.NIGHT,
            night_autotrade_enabled=True,
        )
        
        assert not result.is_active
        assert result.emoji == "🔴"
        assert "Day Only" in result.label
    
    def test_inactive_when_night_only_in_day(self):
        """Series should be inactive when night-only mode during day."""
        stats = self._create_stats(night_only=True, trade_level_streak=3)
        trades = [self._create_trade(TradeStatus.READY)]
        
        result = compute_series_indicator(
            stats=stats,
            active_trades=trades,
            current_time_mode=TimeMode.DAY,
            night_autotrade_enabled=True,
        )
        
        assert not result.is_active
        assert result.emoji == "🔴"
        assert "Night Only" in result.label
    
    def test_inactive_when_night_autotrade_disabled(self):
        """Series should be inactive in night when autotrade disabled."""
        stats = self._create_stats(trade_level_streak=3)
        trades = [self._create_trade(TradeStatus.READY)]
        
        result = compute_series_indicator(
            stats=stats,
            active_trades=trades,
            current_time_mode=TimeMode.NIGHT,
            night_autotrade_enabled=False,
        )
        
        assert not result.is_active
        assert result.emoji == "🔴"
        assert "Night Auto Disabled" in result.label
    
    def test_active_with_in_progress_trade(self):
        """Series should be active with in-progress trade."""
        stats = self._create_stats(trade_level_streak=0)
        trades = [self._create_trade(TradeStatus.WAITING_CAP)]
        
        result = compute_series_indicator(
            stats=stats,
            active_trades=trades,
            current_time_mode=TimeMode.DAY,
            night_autotrade_enabled=False,
        )
        
        assert result.is_active
        assert result.emoji == "🟢"
        assert "Active" in result.label
    
    def test_active_with_streak(self):
        """Series should be active when streak > 0."""
        stats = self._create_stats(trade_level_streak=2)
        trades = []  # No in-progress trades
        
        result = compute_series_indicator(
            stats=stats,
            active_trades=trades,
            current_time_mode=TimeMode.DAY,
            night_autotrade_enabled=False,
        )
        
        assert result.is_active
        assert result.emoji == "🟢"
        assert "Streak: 2" in result.label
    
    def test_inactive_with_no_trades_and_no_streak(self):
        """Series should be inactive with no trades and no streak."""
        stats = self._create_stats(trade_level_streak=0)
        trades = []
        
        result = compute_series_indicator(
            stats=stats,
            active_trades=trades,
            current_time_mode=TimeMode.DAY,
            night_autotrade_enabled=False,
        )
        
        assert not result.is_active
        assert result.emoji == "🔴"
        assert "Inactive" in result.label
    
    def test_in_progress_statuses(self):
        """Verify in-progress statuses are correctly defined."""
        assert TradeStatus.WAITING_CONFIRM in IN_PROGRESS_STATUSES
        assert TradeStatus.WAITING_CAP in IN_PROGRESS_STATUSES
        assert TradeStatus.READY in IN_PROGRESS_STATUSES
        assert TradeStatus.ORDER_PLACED in IN_PROGRESS_STATUSES
        
        # Terminal states should not be in-progress
        assert TradeStatus.SETTLED not in IN_PROGRESS_STATUSES
        assert TradeStatus.CANCELLED not in IN_PROGRESS_STATUSES
        assert TradeStatus.ERROR not in IN_PROGRESS_STATUSES


class TestPolymarketAuthIndicator:
    """Tests for Polymarket authorization indicator."""
    
    def test_paper_mode_not_authorized(self):
        """Paper mode should show not authorized."""
        result = compute_polymarket_auth_indicator("paper")
        
        assert not result.is_authorized
        assert result.emoji == "⚪"
        assert "Paper Mode" in result.label
    
    def test_live_mode_no_credentials(self):
        """Live mode without credentials should show not authorized."""
        # Clear any existing env vars
        for key in ["POLYMARKET_PRIVATE_KEY", "POLYMARKET_API_KEY", 
                    "POLYMARKET_API_SECRET", "POLYMARKET_PASSPHRASE"]:
            if key in os.environ:
                del os.environ[key]
        
        result = compute_polymarket_auth_indicator("live")
        
        assert not result.is_authorized
        assert result.emoji == "⚪"
        assert "Missing Credentials" in result.label
    
    def test_live_mode_with_wallet_key(self):
        """Live mode with wallet key should show authorized."""
        os.environ["POLYMARKET_PRIVATE_KEY"] = "test_key"
        
        try:
            result = compute_polymarket_auth_indicator("live")
            
            assert result.is_authorized
            assert result.emoji == "🟡"
            assert "Wallet" in result.label
        finally:
            del os.environ["POLYMARKET_PRIVATE_KEY"]
    
    def test_live_mode_with_api_credentials(self):
        """Live mode with API credentials should show authorized."""
        os.environ["POLYMARKET_API_KEY"] = "key"
        os.environ["POLYMARKET_API_SECRET"] = "secret"
        os.environ["POLYMARKET_PASSPHRASE"] = "pass"
        
        try:
            result = compute_polymarket_auth_indicator("live")
            
            assert result.is_authorized
            assert result.emoji == "🟡"
            assert "API Key" in result.label
        finally:
            del os.environ["POLYMARKET_API_KEY"]
            del os.environ["POLYMARKET_API_SECRET"]
            del os.environ["POLYMARKET_PASSPHRASE"]
    
    def test_wallet_takes_priority_over_api(self):
        """Wallet auth should be used when both are present."""
        os.environ["POLYMARKET_PRIVATE_KEY"] = "test_key"
        os.environ["POLYMARKET_API_KEY"] = "key"
        os.environ["POLYMARKET_API_SECRET"] = "secret"
        os.environ["POLYMARKET_PASSPHRASE"] = "pass"
        
        try:
            result = compute_polymarket_auth_indicator("live")
            
            assert result.is_authorized
            assert result.emoji == "🟡"
            assert "Wallet" in result.label
        finally:
            del os.environ["POLYMARKET_PRIVATE_KEY"]
            del os.environ["POLYMARKET_API_KEY"]
            del os.environ["POLYMARKET_API_SECRET"]
            del os.environ["POLYMARKET_PASSPHRASE"]


class TestIndicatorStringRepresentation:
    """Tests for indicator string representations."""
    
    def test_series_indicator_str(self):
        """SeriesIndicator should have correct string representation."""
        indicator = SeriesIndicator(
            is_active=True,
            emoji="🟢",
            label="Series Active (Streak: 3)",
        )
        
        assert str(indicator) == "🟢 Series Active (Streak: 3)"
    
    def test_polymarket_indicator_str(self):
        """PolymarketAuthIndicator should have correct string representation."""
        indicator = PolymarketAuthIndicator(
            is_authorized=True,
            emoji="🟡",
            label="Polymarket Authorized (Wallet)",
        )
        
        assert str(indicator) == "🟡 Polymarket Authorized (Wallet)"
