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
    
    async def start(self) -> None:
        """Start the orchestrator main loop."""
        self._running = True
        logger.info("Orchestrator starting", assets=self._assets)
        
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
        stats = self._stats_service.get_stats()
        
        # Check if paused
        if stats.is_paused:
            logger.debug("Bot is paused, skipping tick")
            return
        
        # Determine current mode
        time_mode = self._time_mode.get_current_mode(current_ts)
        
        # Check mode restrictions
        if stats.day_only and time_mode == TimeMode.NIGHT:
            logger.debug("Day-only mode, skipping night tick")
            return
        
        if stats.night_only and time_mode == TimeMode.DAY:
            logger.debug("Night-only mode, skipping day tick")
            return
        
        try:
            # 1. Discover new markets
            await self._discover_markets(current_ts)
            
            # 2. Process active trades
            await self._process_active_trades(current_ts, time_mode, stats)
            
            # 3. Check for settlements
            await self._check_settlements()
            
            # 4. Clear Binance cache for next window
            self._binance.clear_cache()
            
        except Exception as e:
            logger.error("Error in tick", error=str(e))
    
    async def _discover_markets(self, current_ts: int) -> None:
        """Discover new market windows."""
        try:
            windows = await self._gamma.discover_hourly_markets(
                assets=self._assets,
                current_ts=current_ts,
            )
            
            for window in windows:
                # Check if already exists
                existing = self._window_repo.get_by_slug(window.slug)
                if existing:
                    continue
                
                # Save new window
                saved = self._window_repo.create(window)
                logger.info(
                    "Discovered new market window",
                    window_id=saved.id,
                    asset=saved.asset,
                    slug=saved.slug,
                )
                
                # Create trade for this window
                await self._create_trade_for_window(saved, current_ts)
                
        except Exception as e:
            logger.error("Error discovering markets", error=str(e))
    
    async def _create_trade_for_window(
        self,
        window: MarketWindow,
        current_ts: int,
    ) -> Trade | None:
        """Create and process a trade for a market window."""
        stats = self._stats_service.get_stats()
        time_mode = self._time_mode.get_current_mode(current_ts)
        
        # Check night trading enabled
        if time_mode == TimeMode.NIGHT and not self._time_mode.is_night_autotrade_enabled():
            logger.info("Night trading disabled, skipping window", window_id=window.id)
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
        
        # Fetch candles concurrently for better performance
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
            logger.error("Error fetching candles", error=str(e), window_id=window.id)
            self._state_machine.on_no_signal(trade)
            return None
        
        # Detect signal
        signal_result = self._ta_engine.detect_signal(candles_1m, window.start_ts)
        
        if signal_result is None:
            self._state_machine.on_no_signal(trade)
            return None
        
        # Calculate quality (pass both 1m and 5m candles per canonical spec)
        quality_breakdown = self._ta_engine.calculate_quality(
            signal_result, 
            candles_5m, 
            candles_1m=candles_1m
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
            self._state_machine.on_low_quality(trade, quality_breakdown.final_quality, threshold)
            return None
        
        # Check for LATE condition (MG-3)
        if confirm_ts >= window.end_ts:
            self._state_machine.on_cap_late(trade)
            return None
        
        # Quality passed - transition to waiting
        self._state_machine.on_quality_pass(trade, confirm_ts)
        
        # Notify via Telegram
        if self._telegram_handler:
            await self._telegram_handler.send_trade_card(trade, signal, window, quality_breakdown)
        
        return trade
    
    async def _process_active_trades(
        self,
        current_ts: int,
        time_mode: TimeMode,
        stats: Stats,
    ) -> None:
        """Process all active (non-terminal) trades."""
        active_trades = self._trade_repo.get_active()
        
        for trade in active_trades:
            try:
                await self._process_trade(trade, current_ts, time_mode, stats)
            except Exception as e:
                logger.error(
                    "Error processing trade",
                    trade_id=trade.id,
                    error=str(e),
                )
    
    async def _process_trade(
        self,
        trade: Trade,
        current_ts: int,
        time_mode: TimeMode,
        stats: Stats,
    ) -> None:
        """Process a single trade based on its current status."""
        window = self._window_repo.get_by_id(trade.window_id)
        if not window:
            return
        
        signal = self._signal_repo.get_by_id(trade.signal_id) if trade.signal_id else None
        
        # Check expiration
        if window.is_expired(current_ts):
            self._state_machine.on_expired(trade)
            return
        
        if trade.status == TradeStatus.WAITING_CONFIRM:
            # Check if confirm_ts reached
            if signal and current_ts >= signal.confirm_ts:
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
        
        elif trade.status == TradeStatus.WAITING_CAP:
            # Check CAP status
            cap_check = self._cap_check_repo.get_by_trade_id(trade.id)
            if cap_check:
                if cap_check.status == CapStatus.LATE:
                    self._state_machine.on_cap_late(trade)
                    return
                
                if cap_check.status == CapStatus.PENDING:
                    cap_check = await self._cap_check_service.check_cap_pass(
                        cap_check, current_ts
                    )
                
                if cap_check.status == CapStatus.PASS:
                    self._state_machine.on_cap_pass(trade, cap_check)
                elif cap_check.status == CapStatus.FAIL:
                    self._state_machine.on_cap_fail(trade)
        
        elif trade.status == TradeStatus.READY:
            # Handle confirmation and execution
            await self._handle_ready_trade(trade, window, signal, time_mode)
    
    async def _handle_ready_trade(
        self,
        trade: Trade,
        window: MarketWindow,
        signal: Signal | None,
        time_mode: TimeMode,
    ) -> None:
        """Handle trade that is READY for execution."""
        if not signal:
            return
        
        # Check if confirmation needed (Day mode)
        if time_mode == TimeMode.DAY:
            # Requires manual confirmation via Telegram
            if trade.decision == Decision.PENDING:
                # Wait for user response
                return
            elif trade.decision == Decision.SKIP:
                # Already handled
                return
            elif trade.decision != Decision.OK:
                return
        else:
            # Night mode - auto-confirm if enabled
            if trade.decision == Decision.PENDING:
                self._state_machine.on_auto_ok(trade)
        
        # Execute trade
        if trade.decision in (Decision.OK, Decision.AUTO_OK):
            stats = self._stats_service.get_stats()
            stake = self._execution.calculate_stake(stats)
            
            try:
                order_id, token_id, fill_price = await self._execution.place_order(
                    window, signal, trade, stake
                )
                
                self._state_machine.on_order_placed(trade, order_id, token_id, stake)
                self._state_machine.on_order_filled(trade, fill_price)
                
            except Exception as e:
                logger.error("Order placement failed", trade_id=trade.id, error=str(e))
    
    async def _check_settlements(self) -> None:
        """Check for trades pending settlement."""
        pending = self._trade_repo.get_pending_settlement()
        
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
                        
                        # Update stats
                        self._stats_service.on_trade_settled(
                            trade, is_win, trade.time_mode or TimeMode.DAY
                        )
                    except Exception as e:
                        logger.error("Settlement failed", trade_id=trade.id, error=str(e))
    
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
            return False
        
        if confirm:
            self._state_machine.on_user_ok(trade)
        else:
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
