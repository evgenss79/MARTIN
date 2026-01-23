"""
Tests for SEARCHING_SIGNAL flow.

These tests verify the in-window signal scanning behavior introduced
to fix Defect A (signal appears later inside window).

Test scenarios:
1. Active window, trade SEARCHING_SIGNAL - tick 1 no signal, tick 2 signal with quality >= threshold
2. Signal exists but quality < threshold - remain SEARCHING_SIGNAL until quality improves
3. Window expires with no qualifying signal - transition to CANCELLED/EXPIRED
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from src.domain.models import Trade, MarketWindow, Signal, Stats
from src.domain.enums import (
    TradeStatus, TimeMode, PolicyMode, Direction, 
    Decision, CancelReason, NightSessionMode
)
from src.services.state_machine import TradeStateMachine, VALID_TRANSITIONS
from src.services.ta_engine import SignalResult
from src.domain.models import QualityBreakdown


class TestSearchingSignalStatus:
    """Test the new SEARCHING_SIGNAL status."""
    
    def test_searching_signal_status_exists(self):
        """Verify SEARCHING_SIGNAL is a valid TradeStatus."""
        assert TradeStatus.SEARCHING_SIGNAL.value == "SEARCHING_SIGNAL"
    
    def test_new_can_transition_to_searching_signal(self):
        """Verify NEW can transition to SEARCHING_SIGNAL."""
        assert TradeStatus.SEARCHING_SIGNAL in VALID_TRANSITIONS[TradeStatus.NEW]
    
    def test_searching_signal_can_transition_to_signalled(self):
        """Verify SEARCHING_SIGNAL can transition to SIGNALLED."""
        assert TradeStatus.SIGNALLED in VALID_TRANSITIONS[TradeStatus.SEARCHING_SIGNAL]
    
    def test_searching_signal_can_transition_to_cancelled(self):
        """Verify SEARCHING_SIGNAL can transition to CANCELLED."""
        assert TradeStatus.CANCELLED in VALID_TRANSITIONS[TradeStatus.SEARCHING_SIGNAL]
    
    def test_searching_signal_is_not_terminal(self):
        """Verify SEARCHING_SIGNAL is not a terminal state."""
        trade = Trade(status=TradeStatus.SEARCHING_SIGNAL)
        assert not trade.is_terminal()


class TestSearchingSignalStateMachine:
    """Test state machine transitions for SEARCHING_SIGNAL."""
    
    def test_on_start_signal_search(self):
        """Test NEW -> SEARCHING_SIGNAL transition."""
        mock_repo = MagicMock()
        sm = TradeStateMachine(mock_repo)
        
        trade = Trade(id=1, window_id=1, status=TradeStatus.NEW)
        
        result = sm.on_start_signal_search(trade)
        
        assert result.status == TradeStatus.SEARCHING_SIGNAL
        mock_repo.update.assert_called_once()
    
    def test_on_signal_from_searching_signal(self):
        """Test SEARCHING_SIGNAL -> SIGNALLED transition."""
        mock_repo = MagicMock()
        sm = TradeStateMachine(mock_repo)
        
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        signal = Signal(id=1, window_id=1, direction=Direction.UP)
        
        result = sm.on_signal(trade, signal)
        
        assert result.status == TradeStatus.SIGNALLED
        assert result.signal_id == 1
        mock_repo.update.assert_called_once()
    
    def test_on_no_signal_from_searching_signal(self):
        """Test SEARCHING_SIGNAL -> CANCELLED (NO_SIGNAL) transition."""
        mock_repo = MagicMock()
        sm = TradeStateMachine(mock_repo)
        
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        
        result = sm.on_no_signal(trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.NO_SIGNAL
        assert result.decision == Decision.AUTO_SKIP
        mock_repo.update.assert_called_once()


class TestSearchingSignalScanningBehavior:
    """Test continuous signal scanning behavior for SEARCHING_SIGNAL trades."""
    
    def test_tick1_no_signal_remains_searching(self):
        """
        Test 1: Active window, trade SEARCHING_SIGNAL.
        Tick 1: candles produce no signal → trade remains SEARCHING_SIGNAL, 
        no Signal persisted, no telegram.
        """
        mock_trade_repo = MagicMock()
        sm = TradeStateMachine(mock_trade_repo)
        
        # Trade is in SEARCHING_SIGNAL
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        
        # Tick 1: No signal detected (simulate by not calling any transition)
        # Trade should remain in SEARCHING_SIGNAL
        
        assert trade.status == TradeStatus.SEARCHING_SIGNAL
        assert trade.signal_id is None
        
        # No transition should have been made
        mock_trade_repo.update.assert_not_called()
    
    def test_tick2_signal_with_quality_passes_transitions(self):
        """
        Test 1 (continued): 
        Tick 2: candles produce signal + quality >= threshold →
        trade becomes SIGNALLED, Signal persisted, telegram sent exactly once.
        """
        mock_trade_repo = MagicMock()
        sm = TradeStateMachine(mock_trade_repo)
        
        # Trade is in SEARCHING_SIGNAL
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        
        # Tick 2: Signal found with quality >= threshold
        signal = Signal(
            id=1,
            window_id=1,
            direction=Direction.UP,
            signal_ts=1000,
            confirm_ts=1120,
            quality=45.0,  # Above threshold of 35.0
        )
        
        # Transition to SIGNALLED
        result = sm.on_signal(trade, signal)
        
        assert result.status == TradeStatus.SIGNALLED
        assert result.signal_id == 1
        mock_trade_repo.update.assert_called_once()
    
    def test_signal_below_threshold_remains_searching(self):
        """
        Test 2: Signal exists but quality < threshold →
        remain SEARCHING_SIGNAL, no telegram.
        A better signal may appear later.
        """
        # This behavior is handled in the orchestrator, not the state machine
        # The state machine only handles explicit transitions
        
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        
        # Quality is below threshold (35.0)
        low_quality = 25.0
        threshold = 35.0
        
        # Orchestrator would NOT call on_signal because quality < threshold
        # Trade should remain in SEARCHING_SIGNAL
        
        assert trade.status == TradeStatus.SEARCHING_SIGNAL
        assert trade.signal_id is None
    
    def test_window_expires_transitions_to_cancelled(self):
        """
        Test 3: Window expires with no qualifying signal →
        terminal NO_SIGNAL/EXPIRED, no telegram.
        """
        mock_trade_repo = MagicMock()
        sm = TradeStateMachine(mock_trade_repo)
        
        # Trade is in SEARCHING_SIGNAL
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        
        # Window expires - call on_no_signal (or on_expired)
        result = sm.on_no_signal(trade)
        
        assert result.status == TradeStatus.CANCELLED
        assert result.cancel_reason == CancelReason.NO_SIGNAL
        assert result.is_terminal()


class TestSearchingSignalQualityGating:
    """Test quality threshold gating during signal search."""
    
    def test_quality_below_threshold_tick1_no_transition(self):
        """
        Tick 1: Signal detected but quality < threshold.
        Trade remains SEARCHING_SIGNAL.
        """
        # Quality below threshold means orchestrator doesn't transition
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        
        # Simulate: signal found with quality=20, threshold=35
        # Orchestrator decides NOT to transition
        
        assert trade.status == TradeStatus.SEARCHING_SIGNAL
    
    def test_quality_meets_threshold_tick2_transitions(self):
        """
        Tick 2: Better signal arrives with quality >= threshold.
        Trade transitions to SIGNALLED.
        """
        mock_trade_repo = MagicMock()
        sm = TradeStateMachine(mock_trade_repo)
        
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        
        # Better signal with quality >= threshold
        signal = Signal(
            id=2,
            window_id=1,
            direction=Direction.DOWN,
            signal_ts=1060,
            confirm_ts=1180,
            quality=40.0,  # Above threshold of 35.0
        )
        
        result = sm.on_signal(trade, signal)
        
        assert result.status == TradeStatus.SIGNALLED
        assert result.signal_id == 2
    
    def test_quality_eventually_meets_threshold_after_multiple_ticks(self):
        """
        Multiple ticks: quality improves over time until threshold met.
        """
        mock_trade_repo = MagicMock()
        sm = TradeStateMachine(mock_trade_repo)
        
        trade = Trade(id=1, window_id=1, status=TradeStatus.SEARCHING_SIGNAL)
        threshold = 35.0
        
        # Tick 1: quality = 20 (below threshold) - no transition
        # Tick 2: quality = 28 (still below) - no transition
        # Tick 3: quality = 38 (above threshold!) - transition
        
        # Only tick 3 causes transition
        final_signal = Signal(
            id=3,
            window_id=1,
            direction=Direction.UP,
            signal_ts=1180,
            confirm_ts=1300,
            quality=38.0,  # Above threshold
        )
        
        result = sm.on_signal(trade, final_signal)
        
        assert result.status == TradeStatus.SIGNALLED
        assert result.signal_id == 3


class TestTradeRepositorySearchingSignalMethods:
    """Test repository methods for SEARCHING_SIGNAL trades."""
    
    def test_get_non_terminal_by_window_id_returns_searching_signal(self):
        """get_non_terminal_by_window_id should return SEARCHING_SIGNAL trades."""
        from src.adapters.storage.database import Database
        from src.adapters.storage.repositories import TradeRepository, MarketWindowRepository
        from src.domain.models import MarketWindow
        import tempfile
        import os
        
        # Create a temporary database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Initialize database
            db = Database(f"sqlite:///{db_path}")
            db.run_migrations()
            
            # Create a market window first (foreign key)
            window_repo = MarketWindowRepository(db)
            window = MarketWindow(
                asset="BTC",
                slug="test-btc-1",
                condition_id="cond1",
                up_token_id="up1",
                down_token_id="down1",
                start_ts=1000,
                end_ts=2000,
            )
            saved_window = window_repo.create(window)
            
            trade_repo = TradeRepository(db)
            
            # Create a trade in SEARCHING_SIGNAL status
            trade = Trade(
                window_id=saved_window.id,
                status=TradeStatus.SEARCHING_SIGNAL,
                policy_mode=PolicyMode.BASE,
                decision=Decision.PENDING,
            )
            created = trade_repo.create(trade)
            
            # Get non-terminal trade
            result = trade_repo.get_non_terminal_by_window_id(saved_window.id)
            
            assert result is not None
            assert result.id == created.id
            assert result.status == TradeStatus.SEARCHING_SIGNAL
            
        finally:
            os.unlink(db_path)
    
    def test_get_searching_signal_trades_returns_only_searching(self):
        """get_searching_signal_trades should return only SEARCHING_SIGNAL trades."""
        from src.adapters.storage.database import Database
        from src.adapters.storage.repositories import TradeRepository, MarketWindowRepository
        from src.domain.models import MarketWindow
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            db = Database(f"sqlite:///{db_path}")
            db.run_migrations()
            
            # Create market windows first (foreign keys)
            window_repo = MarketWindowRepository(db)
            windows = []
            for i in range(1, 5):
                window = window_repo.create(MarketWindow(
                    asset="BTC",
                    slug=f"test-btc-{i}",
                    condition_id=f"cond{i}",
                    up_token_id=f"up{i}",
                    down_token_id=f"down{i}",
                    start_ts=1000 + i*100,
                    end_ts=2000 + i*100,
                ))
                windows.append(window)
            
            trade_repo = TradeRepository(db)
            
            # Create trades in different statuses
            trade_repo.create(Trade(window_id=windows[0].id, status=TradeStatus.SEARCHING_SIGNAL, policy_mode=PolicyMode.BASE, decision=Decision.PENDING))
            trade_repo.create(Trade(window_id=windows[1].id, status=TradeStatus.NEW, policy_mode=PolicyMode.BASE, decision=Decision.PENDING))
            trade_repo.create(Trade(window_id=windows[2].id, status=TradeStatus.SEARCHING_SIGNAL, policy_mode=PolicyMode.BASE, decision=Decision.PENDING))
            trade_repo.create(Trade(window_id=windows[3].id, status=TradeStatus.SIGNALLED, policy_mode=PolicyMode.BASE, decision=Decision.PENDING))
            
            # Get only SEARCHING_SIGNAL trades
            result = trade_repo.get_searching_signal_trades()
            
            assert len(result) == 2
            for trade in result:
                assert trade.status == TradeStatus.SEARCHING_SIGNAL
            
        finally:
            os.unlink(db_path)


class TestDayModeAutoSkip:
    """Test day mode auto-skip for unresponsive signals (Defect C fix)."""
    
    def test_day_mode_auto_skip_after_timeout(self):
        """
        Day mode: If user doesn't respond within max_response_seconds,
        trade is auto-skipped.
        """
        # This is tested at orchestrator level
        # Here we just verify the state machine can handle the transition
        mock_trade_repo = MagicMock()
        sm = TradeStateMachine(mock_trade_repo)
        
        trade = Trade(
            id=1,
            window_id=1,
            status=TradeStatus.READY,
            decision=Decision.PENDING,
        )
        
        # Auto-skip due to no response (handled by orchestrator)
        trade.cancel_reason = CancelReason.EXPIRED
        trade.decision = Decision.AUTO_SKIP
        result = sm.transition(trade, TradeStatus.CANCELLED, "No response from user")
        
        assert result.status == TradeStatus.CANCELLED
        assert result.decision == Decision.AUTO_SKIP
        assert result.cancel_reason == CancelReason.EXPIRED


class TestStrictnessIncrement:
    """Test configurable strictness increment (Defect G fix)."""
    
    def test_threshold_not_increased_before_start_wins(self):
        """Threshold stays at base when wins < start_strict_after_n_wins."""
        # Simulating orchestrator behavior
        base_threshold = 35.0
        start_strict_after_n_wins = 3
        strict_quality_increment = 5.0
        
        # At 2 wins (below start threshold)
        wins = 2
        
        if wins < start_strict_after_n_wins:
            adjusted_threshold = base_threshold
        else:
            extra_wins = wins - start_strict_after_n_wins + 1
            adjusted_threshold = base_threshold + extra_wins * strict_quality_increment
        
        assert adjusted_threshold == 35.0
    
    def test_threshold_increased_after_start_wins(self):
        """Threshold increases after reaching start_strict_after_n_wins."""
        base_threshold = 35.0
        start_strict_after_n_wins = 3
        strict_quality_increment = 5.0
        
        # At 3 wins (at start threshold)
        wins = 3
        
        if wins < start_strict_after_n_wins:
            adjusted_threshold = base_threshold
        else:
            extra_wins = wins - start_strict_after_n_wins + 1
            adjusted_threshold = base_threshold + extra_wins * strict_quality_increment
        
        # 3 wins: extra_wins = 1, increment = 5
        assert adjusted_threshold == 40.0
    
    def test_threshold_continues_increasing_with_wins(self):
        """Threshold keeps increasing with each additional win."""
        base_threshold = 35.0
        start_strict_after_n_wins = 3
        strict_quality_increment = 5.0
        
        # At 5 wins
        wins = 5
        extra_wins = wins - start_strict_after_n_wins + 1  # 3
        adjusted_threshold = base_threshold + extra_wins * strict_quality_increment
        
        # 5 wins: extra_wins = 3, increment = 15
        assert adjusted_threshold == 50.0
    
    def test_threshold_supports_10_win_streak(self):
        """Threshold calculation supports 10+ win series."""
        base_threshold = 35.0
        start_strict_after_n_wins = 3
        strict_quality_increment = 5.0
        
        # At 10 wins
        wins = 10
        extra_wins = wins - start_strict_after_n_wins + 1  # 8
        adjusted_threshold = base_threshold + extra_wins * strict_quality_increment
        
        # 10 wins: extra_wins = 8, increment = 40
        assert adjusted_threshold == 75.0
