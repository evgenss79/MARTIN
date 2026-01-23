"""
Main Orchestrator for MARTIN.

Coordinates all services and manages the trading workflow.
"""

import asyncio
import time
from typing import Any

from src.common.config import Config
from src.common.logging import get_logger
from src.common.exceptions import MartinError
from src.domain.models import MarketWindow, Signal, Trade, Stats
from src.domain.enums import (
    Direction, TradeStatus, CapStatus, Decision,
    TimeMode, PolicyMode, FillStatus, NightSessionMode
)
from src.adapters.storage import (
    get_database,
    MarketWindowRepository,
    SignalRepository,
    TradeRepository,
    CapCheckRepository,
    StatsRepository,
    SettingsRepository,
)
from src.adapters.polymarket.gamma_client import GammaClient
from src.adapters.polymarket.binance_client import BinanceClient
from src.adapters.polymarket.clob_client import ClobClient
from src.services.ta_engine import TAEngine
from src.services.cap_check import CapCheckService
from src.services.state_machine import TradeStateMachine
from src.services.time_mode import TimeModeService
from src.services.execution import ExecutionService
from src.services.stats_service import StatsService

logger = get_logger(__name__)


def _truncate_id(value: str | None, max_len: int = 16) -> str | None:
    """Truncate an ID string for logging, adding '...' if actually truncated."""
    if value is None:
        return None
    if len(value) <= max_len:
        return value
    return value[:max_len] + "..."


class Orchestrator:
    """
    Main orchestrator for MARTIN trading bot.
    
    Coordinates:
    - Market discovery (Gamma API)
    - Signal detection (TA Engine)
    - CAP validation (CLOB API)
    - Trade execution (paper/live)
    - Settlement and stats tracking
    - Telegram notifications
    """
    
    def __init__(self, config: Config):
        """
        Initialize orchestrator with configuration.
        
        Args:
            config: Application configuration
        """
        self._config = config
        self._running = False
        self._cycle_counter = 0  # Cycle counter for logging
        
        # Initialize repositories
        db = get_database()
        self._window_repo = MarketWindowRepository(db)
        self._signal_repo = SignalRepository(db)
        self._trade_repo = TradeRepository(db)
        self._cap_check_repo = CapCheckRepository(db)
        self._stats_repo = StatsRepository(db)
        self._settings_repo = SettingsRepository(db)
        
        # Initialize API clients
        self._gamma = GammaClient(
            base_url=config.apis.get("gamma", {}).get("base_url", "https://gamma-api.polymarket.com"),
            timeout=config.apis.get("gamma", {}).get("timeout", 30),
            retries=config.apis.get("gamma", {}).get("retries", 3),
            backoff=config.apis.get("gamma", {}).get("backoff", 2.0),
        )
        
        self._binance = BinanceClient(
            base_url=config.apis.get("binance", {}).get("base_url", "https://api.binance.com"),
            timeout=config.apis.get("binance", {}).get("timeout", 30),
            retries=config.apis.get("binance", {}).get("retries", 3),
            backoff=config.apis.get("binance", {}).get("backoff", 2.0),
        )
        
        self._clob = ClobClient(
            base_url=config.apis.get("clob", {}).get("base_url", "https://clob.polymarket.com"),
            timeout=config.apis.get("clob", {}).get("timeout", 30),
            retries=config.apis.get("clob", {}).get("retries", 3),
            backoff=config.apis.get("clob", {}).get("backoff", 2.0),
        )
        
        # Initialize services
        ta_config = config.ta
        self._ta_engine = TAEngine(
            adx_period=ta_config.get("adx_period", 14),
            ema50_slope_bars=ta_config.get("ema50_slope_bars", 5),
            anchor_scale=ta_config.get("anchor_scale", 10000.0),
            w_anchor=ta_config.get("w_anchor", 0.3),
            w_adx=ta_config.get("w_adx", 0.4),
            w_slope=ta_config.get("w_slope", 0.3),
            trend_bonus=ta_config.get("trend_bonus", 1.2),
            trend_penalty=ta_config.get("trend_penalty", 0.8),
        )
        
        self._state_machine = TradeStateMachine(self._trade_repo)
        
        dn_config = config.day_night
        self._time_mode = TimeModeService(
            timezone=config.app.get("timezone", "Europe/Zurich"),
            day_start_hour=dn_config.get("day_start_hour", 8),
            day_end_hour=dn_config.get("day_end_hour", 22),
            base_day_min_quality=dn_config.get("base_day_min_quality", 50.0),
            base_night_min_quality=dn_config.get("base_night_min_quality", 60.0),
            night_autotrade_enabled=dn_config.get("night_autotrade_enabled", False),
        )
        
        trading_config = config.trading
        self._cap_check_service = CapCheckService(
            clob_client=self._clob,
            cap_check_repo=self._cap_check_repo,
            price_cap=trading_config.get("price_cap", 0.55),
            cap_min_ticks=trading_config.get("cap_min_ticks", 3),
        )
        
        self._execution = ExecutionService(
            mode=config.execution.get("mode", "paper"),
            base_stake_amount=config.risk.get("stake", {}).get("base_amount_usdc", 10.0),
            price_cap=trading_config.get("price_cap", 0.55),
        )
        
        rq_config = config.rolling_quantile
        
        # Convert night_session_mode config string to enum
        # Supports both new 'night_session_mode' key and legacy 'night_session_resets_trade_streak'
        night_mode_str = dn_config.get("night_session_mode", None)
        if night_mode_str is not None:
            # Use new canonical key
            night_session_mode = NightSessionMode(night_mode_str)
        else:
            # Legacy fallback: convert boolean to enum
            resets_trade_streak = dn_config.get("night_session_resets_trade_streak", True)
            night_session_mode = NightSessionMode.HARD_RESET if resets_trade_streak else NightSessionMode.SOFT_RESET
        
        self._stats_service = StatsService(
            stats_repo=self._stats_repo,
            trade_repo=self._trade_repo,
            switch_streak_at=dn_config.get("switch_streak_at", 3),
            night_max_win_streak=dn_config.get("night_max_win_streak", 5),
            night_session_mode=night_session_mode,
            strict_day_q=dn_config.get("strict_day_q", "p95"),
            strict_night_q=dn_config.get("strict_night_q", "p95"),
            rolling_days=rq_config.get("rolling_days", 14),
            max_samples=rq_config.get("max_samples", 500),
            min_samples=rq_config.get("min_samples", 50),
            strict_fallback_mult=rq_config.get("strict_fallback_mult", 1.25),
            base_day_min_quality=dn_config.get("base_day_min_quality", 50.0),
            base_night_min_quality=dn_config.get("base_night_min_quality", 60.0),
        )
        
        self._telegram_handler = None  # Will be set if Telegram is configured
        
        # Config values
        self._assets = trading_config.get("assets", ["BTC", "ETH"])
        self._window_seconds = trading_config.get("window_seconds", 3600)
        self._confirm_delay = trading_config.get("confirm_delay_seconds", 120)
        self._warmup_seconds = ta_config.get("warmup_seconds", 7200)
        self._max_response_seconds = dn_config.get("max_response_seconds", 600)  # E: Day mode auto-skip timeout
    
    async def start(self) -> None:
        """Start the orchestrator main loop."""
        self._running = True
        
        # STARTUP LOGGING: execution mode, enabled modules, thresholds, TA loaded confirmation
        execution_mode = self._config.execution.get("mode", "paper")
        dn_config = self._config.day_night
        trading_config = self._config.trading
        
        logger.info(
            "STARTUP: MARTIN Orchestrator initializing",
            execution_mode=execution_mode,
            assets=self._assets,
            window_seconds=self._window_seconds,
            warmup_seconds=self._warmup_seconds,
            confirm_delay_seconds=self._confirm_delay,
        )
        logger.info(
            "STARTUP: Trading thresholds loaded",
            price_cap=trading_config.get("price_cap", 0.55),
            cap_min_ticks=trading_config.get("cap_min_ticks", 3),
            base_day_min_quality=dn_config.get("base_day_min_quality", 35.0),
            base_night_min_quality=dn_config.get("base_night_min_quality", 35.0),
        )
        logger.info(
            "STARTUP: Day/Night configuration loaded",
            day_start_hour=dn_config.get("day_start_hour", 8),
            day_end_hour=dn_config.get("day_end_hour", 22),
            night_autotrade_enabled=dn_config.get("night_autotrade_enabled", False),
            night_max_win_streak=dn_config.get("night_max_win_streak", 5),
            switch_streak_at=dn_config.get("switch_streak_at", 3),
        )
        logger.info(
            "STARTUP: TA Engine LOADED (black box - no modifications)",
            ta_module="src.services.ta_engine.TAEngine",
            signal_detection="EMA20 on 1m with touch + 2-bar confirm",
            quality_calculation="SPEC formula (W_ANCHOR=1.0, W_ADX=0.2, W_SLOPE=0.2)",
        )
        
        # Initialize Telegram if configured
        await self._init_telegram()
        
        # Update quantiles on startup
        self._stats_service.update_rolling_quantiles()
        
        # Main loop
        try:
            while self._running:
                await self._tick()
                await asyncio.sleep(60)  # Check every minute
        except asyncio.CancelledError:
            logger.info("Orchestrator cancelled")
        finally:
            await self._cleanup()
    
    async def stop(self) -> None:
        """Stop the orchestrator."""
        self._running = False
        logger.info("Orchestrator stopping")
    
    async def _init_telegram(self) -> None:
        """Initialize Telegram bot if configured."""
        import os
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        
        if bot_token:
            try:
                from src.adapters.telegram.bot import TelegramHandler
                self._telegram_handler = TelegramHandler(
                    token=bot_token,
                    admin_user_ids=self._config.telegram.get("admin_user_ids", []),
                    orchestrator=self,
                )
                await self._telegram_handler.start()
                logger.info("Telegram bot initialized")
            except Exception as e:
                logger.warning("Failed to initialize Telegram bot", error=str(e))
        else:
            logger.info("Telegram bot not configured (no TELEGRAM_BOT_TOKEN)")
    
    async def _cleanup(self) -> None:
        """Cleanup resources."""
        await self._gamma.close()
        await self._binance.close()
        await self._clob.close()
        
        if self._telegram_handler:
            await self._telegram_handler.stop()
    
    async def _tick(self) -> None:
        """Main processing tick."""
        current_ts = int(time.time())
        self._cycle_counter += 1
        cycle_id = self._cycle_counter
        
        stats = self._stats_service.get_stats()
        
        # CYCLE LOGGING: cycle_start
        logger.info(
            "CYCLE_START: Beginning trading cycle",
            cycle_id=cycle_id,
            timestamp=current_ts,
            is_paused=stats.is_paused,
            policy_mode=stats.policy_mode.value,
            trade_level_streak=stats.trade_level_streak,
            night_streak=stats.night_streak,
        )
        
        # Check if paused
        if stats.is_paused:
            logger.info("CYCLE_SKIP: Bot is paused", cycle_id=cycle_id)
            return
        
        # Determine current mode
        time_mode = self._time_mode.get_current_mode(current_ts)
        
        # Check mode restrictions
        if stats.day_only and time_mode == TimeMode.NIGHT:
            logger.info("CYCLE_SKIP: Day-only mode, skipping night tick", cycle_id=cycle_id, time_mode=time_mode.value)
            return
        
        if stats.night_only and time_mode == TimeMode.DAY:
            logger.info("CYCLE_SKIP: Night-only mode, skipping day tick", cycle_id=cycle_id, time_mode=time_mode.value)
            return
        
        logger.info(
            "CYCLE_ACTIVE: Processing cycle",
            cycle_id=cycle_id,
            time_mode=time_mode.value,
        )
        
        try:
            # 1. Discover new markets
            await self._discover_markets(current_ts, cycle_id)
            
            # 2. Process active trades
            await self._process_active_trades(current_ts, time_mode, stats, cycle_id)
            
            # 3. Check for settlements
            await self._check_settlements(cycle_id)
            
            # 4. Clear Binance cache for next window
            self._binance.clear_cache()
            
            logger.info("CYCLE_END: Cycle completed successfully", cycle_id=cycle_id)
            
        except Exception as e:
            logger.exception("CYCLE_ERROR: Error in tick", cycle_id=cycle_id, error=str(e))
    
    async def _discover_markets(self, current_ts: int, cycle_id: int = 0) -> None:
        """
        Discover new market windows and ensure active windows have trades.
        
        This implements the dual-loop architecture:
        1. Discover new windows from Polymarket and create trades
        2. Check existing active windows that have no non-terminal trade and create SEARCHING_SIGNAL trades
        """
        logger.info(
            "DISCOVERY_START: Beginning Polymarket discovery",
            cycle_id=cycle_id,
            assets=self._assets,
            current_ts=current_ts,
        )
        
        try:
            windows = await self._gamma.discover_hourly_markets(
                assets=self._assets,
                current_ts=current_ts,
            )
            
            logger.info(
                "DISCOVERY_SUMMARY: Polymarket windows discovered",
                cycle_id=cycle_id,
                total_windows=len(windows),
                assets=self._assets,
            )
            
            for window in windows:
                # Check if already exists
                existing = self._window_repo.get_by_slug(window.slug)
                if existing:
                    # Check if existing window has a non-terminal trade
                    existing_trade = self._trade_repo.get_non_terminal_by_window_id(existing.id)
                    if existing_trade:
                        logger.info(
                            "TRADE_DEDUPED: Active trade exists for window",
                            cycle_id=cycle_id,
                            slug=window.slug,
                            trade_id=existing_trade.id,
                            trade_status=existing_trade.status.value,
                        )
                    else:
                        # Active window but no non-terminal trade - create SEARCHING_SIGNAL trade
                        if not existing.is_expired(current_ts):
                            logger.info(
                                "TRADE_CREATED_FOR_EXISTING_WINDOW: Creating trade for active window without trade",
                                cycle_id=cycle_id,
                                window_id=existing.id,
                                slug=existing.slug,
                            )
                            await self._create_searching_signal_trade(existing, current_ts, cycle_id)
                        else:
                            logger.info(
                                "WINDOW_SKIP: Window already exists and expired",
                                cycle_id=cycle_id,
                                slug=window.slug,
                            )
                    continue
                
                # Save new window
                saved = self._window_repo.create(window)
                logger.info(
                    "WINDOW_SELECTED: New market window saved",
                    cycle_id=cycle_id,
                    window_id=saved.id,
                    asset=saved.asset,
                    slug=saved.slug,
                    start_ts=saved.start_ts,
                    end_ts=saved.end_ts,
                    up_token_id=_truncate_id(saved.up_token_id),
                    down_token_id=_truncate_id(saved.down_token_id),
                )
                
                # Create SEARCHING_SIGNAL trade for this window
                await self._create_searching_signal_trade(saved, current_ts, cycle_id)
                
        except Exception as e:
            logger.exception("DISCOVERY_ERROR: Error discovering markets", cycle_id=cycle_id, error=str(e))
        
        # Also check for any active windows in DB that somehow have no non-terminal trade
        await self._ensure_trades_for_active_windows(current_ts, cycle_id)
    
    async def _ensure_trades_for_active_windows(self, current_ts: int, cycle_id: int = 0) -> None:
        """
        Ensure all active windows have at least one non-terminal trade.
        
        This handles the case where windows exist but no trade was created,
        or where previous trades were all cancelled/expired.
        """
        active_windows = self._window_repo.get_active(current_ts)
        
        for window in active_windows:
            existing_trade = self._trade_repo.get_non_terminal_by_window_id(window.id)
            if not existing_trade:
                logger.info(
                    "TRADE_CREATED_FOR_EXISTING_WINDOW: Creating trade for orphaned active window",
                    cycle_id=cycle_id,
                    window_id=window.id,
                    slug=window.slug,
                )
                await self._create_searching_signal_trade(window, current_ts, cycle_id)
    
    async def _create_searching_signal_trade(
        self,
        window: MarketWindow,
        current_ts: int,
        cycle_id: int = 0,
    ) -> Trade | None:
        """
        Create a trade in SEARCHING_SIGNAL state for continuous in-window signal scanning.
        
        This implements the owner-required architecture where signals are continuously
        evaluated during the window, not just at discovery.
        """
        stats = self._stats_service.get_stats()
        time_mode = self._time_mode.get_current_mode(current_ts)
        
        # Check night trading enabled
        if time_mode == TimeMode.NIGHT and not self._time_mode.is_night_autotrade_enabled():
            logger.info(
                "DECISION_REJECTED: Night trading disabled, not creating trade",
                cycle_id=cycle_id,
                window_id=window.id,
                reason="NIGHT_DISABLED",
            )
            return None
        
        # Prevent duplicates
        existing_trade = self._trade_repo.get_non_terminal_by_window_id(window.id)
        if existing_trade:
            logger.info(
                "TRADE_DEDUPED: Non-terminal trade already exists",
                cycle_id=cycle_id,
                window_id=window.id,
                trade_id=existing_trade.id,
            )
            return existing_trade
        
        # Create trade in SEARCHING_SIGNAL state
        trade = Trade(
            window_id=window.id,
            time_mode=time_mode,
            policy_mode=stats.policy_mode,
            trade_level_streak=stats.trade_level_streak,
            night_streak=stats.night_streak,
        )
        trade = self._trade_repo.create(trade)
        
        logger.info(
            "TRADE_CREATED: Trade record created in SEARCHING_SIGNAL state",
            cycle_id=cycle_id,
            window_id=window.id,
            trade_id=trade.id,
            status="NEW->SEARCHING_SIGNAL",
        )
        
        # Transition to SEARCHING_SIGNAL
        self._state_machine.on_start_searching(trade)
        
        return trade
    
    async def _process_searching_signal_trade(
        self,
        trade: Trade,
        window: MarketWindow,
        current_ts: int,
        time_mode: TimeMode,
        stats: Stats,
        cycle_id: int = 0,
    ) -> None:
        """
        Process a trade in SEARCHING_SIGNAL state.
        
        This implements continuous in-window signal scanning:
        - Re-evaluate TA each tick for SEARCHING_SIGNAL trades
        - Transition to SIGNALLED only when a signal is detected AND quality >= threshold
        - Remain in SEARCHING_SIGNAL if no signal or quality < threshold (a better signal may appear)
        - No Telegram notification until qualifying signal is found
        """
        logger.info(
            "SEARCHING_SIGNAL_TICK: Re-evaluating TA for trade in searching state",
            cycle_id=cycle_id,
            trade_id=trade.id,
            window_id=window.id,
            asset=window.asset,
            time_remaining=window.time_remaining(current_ts),
        )
        
        # Fetch fresh candle data
        try:
            candles_1m, candles_5m = await asyncio.gather(
                self._binance.get_klines_for_window(
                    asset=window.asset,
                    interval="1m",
                    start_ts=window.start_ts,
                    end_ts=window.end_ts,
                    warmup_seconds=self._warmup_seconds,
                ),
                self._binance.get_klines_for_window(
                    asset=window.asset,
                    interval="5m",
                    start_ts=window.start_ts,
                    end_ts=window.end_ts,
                    warmup_seconds=self._warmup_seconds,
                ),
            )
        except Exception as e:
            logger.warning(
                "SEARCHING_SIGNAL_KLINES_ERROR: Error fetching candles for SEARCHING_SIGNAL trade",
                cycle_id=cycle_id,
                trade_id=trade.id,
                error=str(e),
            )
            # Stay in SEARCHING_SIGNAL, will retry next tick
            return
        
        logger.debug(
            "SEARCHING_SIGNAL_KLINES_LOADED: Candle data retrieved",
            cycle_id=cycle_id,
            trade_id=trade.id,
            candles_1m_count=len(candles_1m),
            candles_5m_count=len(candles_5m),
        )
        
        # Run signal detection (BLACK BOX - no changes to TA logic)
        signal_result = self._ta_engine.detect_signal(candles_1m, window.start_ts)
        
        if signal_result is None:
            logger.info(
                "DECISION_NO_SIGNAL: No signal detected this tick, remaining in SEARCHING_SIGNAL",
                cycle_id=cycle_id,
                trade_id=trade.id,
                window_id=window.id,
            )
            return  # Stay in SEARCHING_SIGNAL, will retry next tick
        
        logger.info(
            "TA_SIGNAL_DETECTED: Signal found during SEARCHING_SIGNAL",
            cycle_id=cycle_id,
            trade_id=trade.id,
            direction=signal_result.direction.value,
            signal_ts=signal_result.signal_ts,
            signal_price=signal_result.signal_price,
        )
        
        # Calculate quality (BLACK BOX - no changes to quality formula)
        quality_breakdown = self._ta_engine.calculate_quality(signal_result, candles_5m)
        
        logger.info(
            "QUALITY_COMPUTED: Quality calculation complete",
            cycle_id=cycle_id,
            trade_id=trade.id,
            final_quality=quality_breakdown.final_quality,
            edge_component=quality_breakdown.edge_component,
            q_adx=quality_breakdown.q_adx,
            q_slope=quality_breakdown.q_slope,
            trend_mult=quality_breakdown.trend_mult,
        )
        
        # Get current threshold
        threshold = self._stats_service.get_current_threshold(time_mode, stats.policy_mode)
        
        # Check quality threshold
        if quality_breakdown.final_quality < threshold:
            logger.info(
                "DECISION_REJECTED_LOW_QUALITY: Signal quality below threshold, remaining in SEARCHING_SIGNAL",
                cycle_id=cycle_id,
                trade_id=trade.id,
                window_id=window.id,
                reason="LOW_QUALITY",
                actual_quality=quality_breakdown.final_quality,
                required_threshold=threshold,
                quality_deficit=threshold - quality_breakdown.final_quality,
            )
            # Stay in SEARCHING_SIGNAL - a better signal may appear later
            return
        
        # Check for LATE condition (MG-3)
        confirm_ts = signal_result.signal_ts + self._confirm_delay
        if confirm_ts >= window.end_ts:
            logger.info(
                "DECISION_REJECTED: Signal too late (MG-3), remaining in SEARCHING_SIGNAL",
                cycle_id=cycle_id,
                trade_id=trade.id,
                reason="LATE",
                confirm_ts=confirm_ts,
                window_end_ts=window.end_ts,
            )
            # Stay in SEARCHING_SIGNAL - still time for another signal potentially
            return
        
        # QUALIFYING SIGNAL FOUND - persist and transition
        logger.info(
            "DECISION_ACCEPTED_SIGNALLED: Qualifying signal found, transitioning to SIGNALLED",
            cycle_id=cycle_id,
            trade_id=trade.id,
            direction=signal_result.direction.value,
            quality=quality_breakdown.final_quality,
            threshold=threshold,
        )
        
        # Create signal record
        signal = Signal(
            window_id=window.id,
            direction=signal_result.direction,
            signal_ts=signal_result.signal_ts,
            confirm_ts=confirm_ts,
            quality=quality_breakdown.final_quality,
            quality_breakdown=quality_breakdown,
            anchor_bar_ts=signal_result.anchor_bar_ts,
        )
        signal = self._signal_repo.create(signal)
        
        # Transition SEARCHING_SIGNAL -> SIGNALLED
        self._state_machine.on_qualifying_signal_found(trade, signal)
        
        # Immediately proceed to quality pass and waiting confirm
        self._state_machine.on_quality_pass(trade, confirm_ts)
        
        # Send Telegram notification (only now, after qualifying signal found)
        if self._telegram_handler:
            logger.info(
                "TELEGRAM_SIGNAL_SENT: Sending trade card (qualifying signal found)",
                cycle_id=cycle_id,
                trade_id=trade.id,
                direction=signal.direction.value,
                quality=quality_breakdown.final_quality,
            )
            await self._telegram_handler.send_trade_card(trade, signal, window, quality_breakdown)
    
    async def _create_trade_for_window(
        self,
        window: MarketWindow,
        current_ts: int,
        cycle_id: int = 0,
    ) -> Trade | None:
        """Create and process a trade for a market window."""
        stats = self._stats_service.get_stats()
        time_mode = self._time_mode.get_current_mode(current_ts)
        
        logger.info(
            "WINDOW_PROCESSING: Starting signal pipeline for window",
            cycle_id=cycle_id,
            window_id=window.id,
            asset=window.asset,
            time_mode=time_mode.value,
            policy_mode=stats.policy_mode.value,
        )
        
        # Check night trading enabled
        if time_mode == TimeMode.NIGHT and not self._time_mode.is_night_autotrade_enabled():
            logger.info(
                "DECISION_REJECTED: Night trading disabled",
                cycle_id=cycle_id,
                window_id=window.id,
                reason="NIGHT_DISABLED",
                night_autotrade_enabled=False,
            )
            return None
        
        # Create trade
        trade = Trade(
            window_id=window.id,
            time_mode=time_mode,
            policy_mode=stats.policy_mode,
            trade_level_streak=stats.trade_level_streak,
            night_streak=stats.night_streak,
        )
        trade = self._trade_repo.create(trade)
        
        logger.info(
            "TRADE_CREATED: Trade record created",
            cycle_id=cycle_id,
            window_id=window.id,
            trade_id=trade.id,
        )
        
        # Fetch candles concurrently for better performance
        logger.info(
            "BINANCE_KLINES_LOADING: Fetching 1m and 5m candles from Binance",
            cycle_id=cycle_id,
            window_id=window.id,
            asset=window.asset,
            warmup_seconds=self._warmup_seconds,
        )
        
        try:
            candles_1m, candles_5m = await asyncio.gather(
                self._binance.get_klines_for_window(
                    asset=window.asset,
                    interval="1m",
                    start_ts=window.start_ts,
                    end_ts=window.end_ts,
                    warmup_seconds=self._warmup_seconds,
                ),
                self._binance.get_klines_for_window(
                    asset=window.asset,
                    interval="5m",
                    start_ts=window.start_ts,
                    end_ts=window.end_ts,
                    warmup_seconds=self._warmup_seconds,
                ),
            )
        except Exception as e:
            logger.exception(
                "BINANCE_KLINES_ERROR: Error fetching candles",
                cycle_id=cycle_id,
                window_id=window.id,
                error=str(e),
            )
            self._state_machine.on_no_signal(trade)
            return None
        
        logger.info(
            "BINANCE_KLINES_LOADED: Candle data retrieved",
            cycle_id=cycle_id,
            window_id=window.id,
            candles_1m_count=len(candles_1m),
            candles_5m_count=len(candles_5m),
        )
        
        # ANCHOR_RESOLVED: The anchor is resolved within detect_signal
        logger.info(
            "ANCHOR_RESOLVING: Resolving auction anchor/reference price",
            cycle_id=cycle_id,
            window_id=window.id,
            start_ts=window.start_ts,
        )
        
        # Detect signal
        logger.info(
            "TA_EXECUTING: Running signal detection (EMA20 1m touch + 2-bar confirm)",
            cycle_id=cycle_id,
            window_id=window.id,
        )
        signal_result = self._ta_engine.detect_signal(candles_1m, window.start_ts)
        
        if signal_result is None:
            logger.info(
                "DECISION_REJECTED: No signal detected",
                cycle_id=cycle_id,
                window_id=window.id,
                trade_id=trade.id,
                reason="NO_SIGNAL",
            )
            self._state_machine.on_no_signal(trade)
            return None
        
        logger.info(
            "ANCHOR_RESOLVED: Anchor price determined",
            cycle_id=cycle_id,
            window_id=window.id,
            anchor_bar_ts=signal_result.anchor_bar_ts,
            anchor_price=signal_result.anchor_price,
        )
        
        logger.info(
            "TA_SIGNAL_DETECTED: Signal found",
            cycle_id=cycle_id,
            window_id=window.id,
            direction=signal_result.direction.value,
            signal_ts=signal_result.signal_ts,
            signal_price=signal_result.signal_price,
        )
        
        # Calculate quality (uses 5m candles for ADX, EMA50 slope, trend confirmation)
        logger.info(
            "QUALITY_CALCULATING: Running quality score calculation on 5m candles",
            cycle_id=cycle_id,
            window_id=window.id,
        )
        quality_breakdown = self._ta_engine.calculate_quality(signal_result, candles_5m)
        
        logger.info(
            "SCORE_COMPUTED: Quality calculation complete",
            cycle_id=cycle_id,
            window_id=window.id,
            final_quality=quality_breakdown.final_quality,
            edge_component=quality_breakdown.edge_component,
            q_adx=quality_breakdown.q_adx,
            q_slope=quality_breakdown.q_slope,
            trend_mult=quality_breakdown.trend_mult,
            trend_confirms=quality_breakdown.trend_confirms,
            edge_penalty_applied=quality_breakdown.edge_penalty_applied,
        )
        
        # Create signal record
        confirm_ts = signal_result.signal_ts + self._confirm_delay
        signal = Signal(
            window_id=window.id,
            direction=signal_result.direction,
            signal_ts=signal_result.signal_ts,
            confirm_ts=confirm_ts,
            quality=quality_breakdown.final_quality,
            quality_breakdown=quality_breakdown,
            anchor_bar_ts=signal_result.anchor_bar_ts,
        )
        signal = self._signal_repo.create(signal)
        
        # Update trade with signal
        self._state_machine.on_signal(trade, signal)
        
        # Check quality threshold
        threshold = self._stats_service.get_current_threshold(time_mode, stats.policy_mode)
        
        if quality_breakdown.final_quality < threshold:
            logger.info(
                "DECISION_REJECTED: Quality below threshold",
                cycle_id=cycle_id,
                window_id=window.id,
                trade_id=trade.id,
                reason="LOW_QUALITY",
                actual_quality=quality_breakdown.final_quality,
                required_threshold=threshold,
                time_mode=time_mode.value,
                policy_mode=stats.policy_mode.value,
                quality_deficit=threshold - quality_breakdown.final_quality,
            )
            self._state_machine.on_low_quality(trade, quality_breakdown.final_quality, threshold)
            return None
        
        # Check for LATE condition (MG-3)
        if confirm_ts >= window.end_ts:
            logger.info(
                "DECISION_REJECTED: Signal too late (MG-3)",
                cycle_id=cycle_id,
                window_id=window.id,
                trade_id=trade.id,
                reason="LATE",
                confirm_ts=confirm_ts,
                window_end_ts=window.end_ts,
                seconds_past_deadline=confirm_ts - window.end_ts,
            )
            self._state_machine.on_cap_late(trade)
            return None
        
        # Quality passed - transition to waiting
        logger.info(
            "DECISION_ACCEPTED: Signal passed all quality gates",
            cycle_id=cycle_id,
            window_id=window.id,
            trade_id=trade.id,
            signal_id=signal.id,
            direction=signal.direction.value,
            quality=quality_breakdown.final_quality,
            threshold=threshold,
            confirm_ts=confirm_ts,
            time_mode=time_mode.value,
        )
        self._state_machine.on_quality_pass(trade, confirm_ts)
        
        # Notify via Telegram
        if self._telegram_handler:
            logger.info(
                "TELEGRAM_SIGNAL_SENDING: Sending trade card to user",
                cycle_id=cycle_id,
                window_id=window.id,
                trade_id=trade.id,
                direction=signal.direction.value,
                quality=quality_breakdown.final_quality,
            )
            await self._telegram_handler.send_trade_card(trade, signal, window, quality_breakdown)
            logger.info(
                "TELEGRAM_SIGNAL_SENT: Trade card sent to user",
                cycle_id=cycle_id,
                window_id=window.id,
                trade_id=trade.id,
            )
        
        return trade
    
    async def _process_active_trades(
        self,
        current_ts: int,
        time_mode: TimeMode,
        stats: Stats,
        cycle_id: int = 0,
    ) -> None:
        """Process all active (non-terminal) trades."""
        active_trades = self._trade_repo.get_active()
        
        logger.info(
            "ACTIVE_TRADES_PROCESSING: Processing active trades",
            cycle_id=cycle_id,
            active_trade_count=len(active_trades),
        )
        
        for trade in active_trades:
            try:
                await self._process_trade(trade, current_ts, time_mode, stats, cycle_id)
            except Exception as e:
                logger.exception(
                    "TRADE_PROCESSING_ERROR: Error processing trade",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    error=str(e),
                )
    
    async def _process_trade(
        self,
        trade: Trade,
        current_ts: int,
        time_mode: TimeMode,
        stats: Stats,
        cycle_id: int = 0,
    ) -> None:
        """Process a single trade based on its current status."""
        window = self._window_repo.get_by_id(trade.window_id)
        if not window:
            return
        
        signal = self._signal_repo.get_by_id(trade.signal_id) if trade.signal_id else None
        
        # Check expiration
        if window.is_expired(current_ts):
            if trade.status == TradeStatus.SEARCHING_SIGNAL:
                # Special handling: no qualifying signal found before window end
                logger.info(
                    "SEARCHING_SIGNAL_EXPIRED: Window expired without qualifying signal",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    window_id=window.id,
                )
                self._state_machine.on_no_qualifying_signal(trade)
            else:
                logger.info(
                    "TRADE_EXPIRED: Window has expired",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    window_id=window.id,
                )
                self._state_machine.on_expired(trade)
            return
        
        # Handle SEARCHING_SIGNAL: continuous in-window signal scanning
        if trade.status == TradeStatus.SEARCHING_SIGNAL:
            await self._process_searching_signal_trade(trade, window, current_ts, time_mode, stats, cycle_id)
            return
        
        if trade.status == TradeStatus.WAITING_CONFIRM:
            # Check if confirm_ts reached
            if signal and current_ts >= signal.confirm_ts:
                logger.info(
                    "CONFIRM_TIME_REACHED: Starting CAP check",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    confirm_ts=signal.confirm_ts,
                    current_ts=current_ts,
                )
                self._state_machine.on_confirm_reached(trade)
                
                # Create CAP check
                token_id = (
                    window.up_token_id if signal.direction == Direction.UP
                    else window.down_token_id
                )
                self._cap_check_service.create_cap_check(
                    trade=trade,
                    token_id=token_id,
                    confirm_ts=signal.confirm_ts,
                    end_ts=window.end_ts,
                )
                logger.info(
                    "CAP_CHECK_CREATED: CAP check initialized",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    direction=signal.direction.value,
                    token_id=_truncate_id(token_id),
                )
        
        elif trade.status == TradeStatus.WAITING_CAP:
            # Check CAP status
            cap_check = self._cap_check_repo.get_by_trade_id(trade.id)
            if cap_check:
                if cap_check.status == CapStatus.LATE:
                    logger.info(
                        "CAP_CHECK_LATE: CAP check too late",
                        cycle_id=cycle_id,
                        trade_id=trade.id,
                    )
                    self._state_machine.on_cap_late(trade)
                    return
                
                if cap_check.status == CapStatus.PENDING:
                    cap_check = await self._cap_check_service.check_cap_pass(
                        cap_check, current_ts
                    )
                
                if cap_check.status == CapStatus.PASS:
                    logger.info(
                        "CAP_CHECK_PASSED: Price cap validated",
                        cycle_id=cycle_id,
                        trade_id=trade.id,
                        consecutive_ticks=cap_check.consecutive_ticks,
                        price_at_pass=cap_check.price_at_pass,
                    )
                    self._state_machine.on_cap_pass(trade, cap_check)
                elif cap_check.status == CapStatus.FAIL:
                    logger.info(
                        "CAP_CHECK_FAILED: Price cap validation failed",
                        cycle_id=cycle_id,
                        trade_id=trade.id,
                        consecutive_ticks=cap_check.consecutive_ticks,
                    )
                    self._state_machine.on_cap_fail(trade)
        
        elif trade.status == TradeStatus.READY:
            # Handle confirmation and execution
            await self._handle_ready_trade(trade, window, signal, time_mode, cycle_id)
    
    async def _handle_ready_trade(
        self,
        trade: Trade,
        window: MarketWindow,
        signal: Signal | None,
        time_mode: TimeMode,
        cycle_id: int = 0,
    ) -> None:
        """Handle trade that is READY for execution."""
        if not signal:
            return
        
        current_ts = int(time.time())
        
        # Check if confirmation needed (Day mode)
        if time_mode == TimeMode.DAY:
            # Requires manual confirmation via Telegram
            if trade.decision == Decision.PENDING:
                # Check for auto-skip due to user not responding (E: Day mode auto-skip)
                max_response_seconds = self._get_max_response_seconds()
                elapsed_since_ready = current_ts - signal.confirm_ts
                
                if max_response_seconds > 0 and elapsed_since_ready >= max_response_seconds:
                    # User did not respond in time - auto-skip
                    logger.info(
                        "DAY_NO_RESPONSE_SKIP: User did not respond within max_response_seconds",
                        cycle_id=cycle_id,
                        trade_id=trade.id,
                        elapsed_seconds=elapsed_since_ready,
                        max_response_seconds=max_response_seconds,
                    )
                    self._state_machine.on_user_no_response_skip(trade)
                    return
                
                # Still waiting for user response
                logger.info(
                    "ENTRY_AWAITING_CONFIRMATION: Waiting for user confirmation (Day mode)",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    time_mode=time_mode.value,
                    elapsed_seconds=elapsed_since_ready,
                    remaining_seconds=max_response_seconds - elapsed_since_ready if max_response_seconds > 0 else None,
                )
                return
            elif trade.decision == Decision.SKIP:
                # Already handled
                logger.info(
                    "ENTRY_SKIPPED: User skipped trade",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                )
                return
            elif trade.decision != Decision.OK:
                return
        else:
            # Night mode - auto-confirm if enabled
            if trade.decision == Decision.PENDING:
                logger.info(
                    "ENTRY_AUTO_CONFIRM: Auto-confirming trade (Night mode)",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    time_mode=time_mode.value,
                )
                self._state_machine.on_auto_ok(trade)
        
        # Execute trade
        if trade.decision in (Decision.OK, Decision.AUTO_OK):
            logger.info(
                "ENTRY_LOGIC_STARTED: Beginning order execution",
                cycle_id=cycle_id,
                trade_id=trade.id,
                decision=trade.decision.value,
                direction=signal.direction.value,
            )
            
            stats = self._stats_service.get_stats()
            stake = self._execution.calculate_stake(stats)
            
            logger.info(
                "ENTRY_STAKE_CALCULATED: Stake amount determined",
                cycle_id=cycle_id,
                trade_id=trade.id,
                stake_amount=stake,
                execution_mode=self._config.execution.get("mode", "paper"),
            )
            
            try:
                order_id, token_id, fill_price = await self._execution.place_order(
                    window, signal, trade, stake
                )
                
                logger.info(
                    "ORDER_SUBMITTED: Order placed successfully",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    order_id=order_id,
                    token_id=_truncate_id(token_id),
                    fill_price=fill_price,
                    stake=stake,
                )
                
                self._state_machine.on_order_placed(trade, order_id, token_id, stake)
                self._state_machine.on_order_filled(trade, fill_price)
                
                logger.info(
                    "ORDER_FILLED: Order execution complete",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    order_id=order_id,
                    fill_price=fill_price,
                )
                
            except Exception as e:
                logger.exception(
                    "ORDER_FAILED: Order placement failed",
                    cycle_id=cycle_id,
                    trade_id=trade.id,
                    error=str(e),
                )
    
    async def _check_settlements(self, cycle_id: int = 0) -> None:
        """Check for trades pending settlement."""
        pending = self._trade_repo.get_pending_settlement()
        
        if pending:
            logger.info(
                "SETTLEMENT_CHECK: Checking pending settlements",
                cycle_id=cycle_id,
                pending_count=len(pending),
            )
        
        for trade in pending:
            window = self._window_repo.get_by_id(trade.window_id)
            if not window:
                continue
            
            # Check if market resolved
            if window.outcome is None:
                # Try to fetch outcome
                try:
                    market_data = await self._gamma.get_market_by_slug(window.slug)
                    if market_data:
                        outcome = market_data.get("outcome")
                        if outcome:
                            logger.info(
                                "SETTLEMENT_OUTCOME_FOUND: Market outcome resolved",
                                cycle_id=cycle_id,
                                trade_id=trade.id,
                                slug=window.slug,
                                outcome=outcome.upper(),
                            )
                            self._window_repo.update_outcome(window.id, outcome.upper())
                            window.outcome = outcome.upper()
                except Exception as e:
                    logger.debug("Could not fetch outcome", slug=window.slug, error=str(e))
            
            if window.outcome:
                signal = self._signal_repo.get_by_id(trade.signal_id) if trade.signal_id else None
                if signal:
                    try:
                        is_win, pnl = await self._execution.settle_trade(trade, window, signal)
                        self._state_machine.on_settled(trade, is_win, pnl)
                        
                        logger.info(
                            "SETTLEMENT_COMPLETE: Trade settled",
                            cycle_id=cycle_id,
                            trade_id=trade.id,
                            direction=signal.direction.value,
                            market_outcome=window.outcome,
                            is_win=is_win,
                            pnl=pnl,
                        )
                        
                        # Update stats
                        self._stats_service.on_trade_settled(
                            trade, is_win, trade.time_mode or TimeMode.DAY
                        )
                    except Exception as e:
                        logger.exception("SETTLEMENT_FAILED: Settlement failed", cycle_id=cycle_id, trade_id=trade.id, error=str(e))
    
    # Public methods for Telegram interaction
    
    def get_stats(self) -> Stats:
        """Get current stats."""
        return self._stats_service.get_stats()
    
    def confirm_trade(self, trade_id: int, confirm: bool) -> bool:
        """
        Confirm or skip a trade (Day mode).
        
        Args:
            trade_id: Trade ID
            confirm: True for OK, False for SKIP
            
        Returns:
            True if successful
        """
        trade = self._trade_repo.get_by_id(trade_id)
        if not trade or trade.status != TradeStatus.READY:
            logger.info(
                "TELEGRAM_CONFIRMATION_INVALID: Invalid trade for confirmation",
                trade_id=trade_id,
                trade_found=trade is not None,
                trade_status=trade.status.value if trade else None,
            )
            return False
        
        if confirm:
            logger.info(
                "TELEGRAM_USER_CONFIRMED: User confirmed trade (OK)",
                trade_id=trade_id,
            )
            self._state_machine.on_user_ok(trade)
        else:
            logger.info(
                "TELEGRAM_USER_SKIPPED: User skipped trade (SKIP)",
                trade_id=trade_id,
            )
            self._state_machine.on_user_skip(trade)
        
        return True
    
    def pause(self) -> None:
        """Pause the bot."""
        stats = self.get_stats()
        stats.is_paused = True
        self._stats_repo.update(stats)
        logger.info("Bot paused")
    
    def resume(self) -> None:
        """Resume the bot."""
        stats = self.get_stats()
        stats.is_paused = False
        self._stats_repo.update(stats)
        logger.info("Bot resumed")
    
    def set_day_only(self, enabled: bool) -> None:
        """Set day-only mode."""
        stats = self.get_stats()
        stats.day_only = enabled
        if enabled:
            stats.night_only = False
        self._stats_repo.update(stats)
    
    def set_night_only(self, enabled: bool) -> None:
        """Set night-only mode."""
        stats = self.get_stats()
        stats.night_only = enabled
        if enabled:
            stats.day_only = False
        self._stats_repo.update(stats)
    
    def update_setting(self, key: str, value: str) -> None:
        """Update a runtime setting."""
        self._settings_repo.set(key, value)
        logger.info("Setting updated", key=key, value=value)
    
    def _get_max_response_seconds(self) -> int:
        """
        Get maximum response time for day mode user confirmation.
        
        If user does not respond within this time, trade is auto-skipped.
        Returns 0 to disable auto-skip.
        
        Reads from settings repository first, then falls back to config.
        """
        # Check settings repository for runtime override
        stored = self._settings_repo.get("day_night.max_response_seconds")
        if stored is not None:
            try:
                return int(stored)
            except ValueError:
                pass
        return self._max_response_seconds
