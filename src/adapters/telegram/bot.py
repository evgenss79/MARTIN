"""
Telegram Bot Handler for MARTIN.

Implements the Telegram UX for trading signals and user interaction.

Status Indicators:
- 🟢/🔴 Series Active/Inactive
- 🟡/⚪ Polymarket Authorized/Not Authorized
"""

import asyncio
import os
from typing import Any, TYPE_CHECKING

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ParseMode

from src.domain.models import Trade, Signal, MarketWindow, QualityBreakdown, Stats
from src.domain.enums import TimeMode, PolicyMode, TradeStatus
from src.common.logging import get_logger
from src.services.status_indicator import (
    compute_series_indicator,
    compute_polymarket_auth_indicator,
    SeriesIndicator,
    PolymarketAuthIndicator,
)

if TYPE_CHECKING:
    from src.services.orchestrator import Orchestrator

logger = get_logger(__name__)


class TelegramHandler:
    """
    Telegram bot handler.
    
    Implements:
    - Trade card notifications
    - User confirmation (OK/SKIP)
    - Commands (/start, /status, /settings, etc.)
    - Settings management
    """
    
    def __init__(
        self,
        token: str,
        admin_user_ids: list[int],
        orchestrator: "Orchestrator",
    ):
        """
        Initialize Telegram handler.
        
        Args:
            token: Telegram bot token
            admin_user_ids: List of authorized admin user IDs
            orchestrator: Main orchestrator instance
        """
        self._bot = Bot(token=token)
        self._dp = Dispatcher()
        self._admin_ids = set(admin_user_ids)
        self._orchestrator = orchestrator
        
        # Track sent messages for editing
        self._trade_messages: dict[int, tuple[int, int]] = {}  # trade_id -> (chat_id, msg_id)
        
        # Register handlers
        self._register_handlers()
    
    def _register_handlers(self) -> None:
        """Register command and callback handlers."""
        
        @self._dp.message(Command("start"))
        async def cmd_start(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            await message.answer(
                "🤖 *MARTIN Trading Bot*\n\n"
                "I help you trade Polymarket hourly BTC/ETH markets.\n\n"
                "Commands:\n"
                "/status - Current status and stats\n"
                "/settings - View/edit settings\n"
                "/pause - Pause trading\n"
                "/resume - Resume trading\n"
                "/dayonly - Enable day-only mode\n"
                "/nightonly - Enable night-only mode\n"
                "/report - Performance report\n",
                parse_mode=ParseMode.MARKDOWN,
            )
        
        @self._dp.message(Command("status"))
        async def cmd_status(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            stats = self._orchestrator.get_stats()
            mode_text = self._get_mode_text(stats)
            
            # Get status indicators
            series_indicator = self._get_series_indicator(stats)
            auth_indicator = self._get_polymarket_auth_indicator()
            
            # Get day/night config for display
            dn_config = self._get_day_night_config_service()
            day_start = dn_config.get_day_start_hour()
            day_end = dn_config.get_day_end_hour()
            current_mode = dn_config.get_current_mode()
            current_time = dn_config.get_current_local_time()
            reminder_mins = dn_config.get_reminder_minutes()
            
            mode_emoji = "☀️" if current_mode.value == "DAY" else "🌙"
            
            text = (
                "📊 *MARTIN Status*\n\n"
                f"*Indicators:*\n"
                f"{series_indicator}\n"
                f"{auth_indicator}\n\n"
                f"*Time:*\n"
                f"├ Local: {current_time.strftime('%H:%M %Z')}\n"
                f"├ Mode: {mode_emoji} {current_mode.value}\n"
                f"└ Day Hours: {day_start:02d}:00 → {day_end:02d}:00\n\n"
                f"*Policy:* {stats.policy_mode.value}\n"
                f"*Streaks:*\n"
                f"├ Trade: {stats.trade_level_streak}\n"
                f"└ Night: {stats.night_streak}\n\n"
                f"*Stats:*\n"
                f"├ Trades: {stats.total_trades}\n"
                f"├ Wins: {stats.total_wins}\n"
                f"├ Losses: {stats.total_losses}\n"
                f"└ Win Rate: {stats.win_rate:.1f}%\n\n"
                f"*Controls:*\n"
                f"├ Paused: {'Yes' if stats.is_paused else 'No'}\n"
                f"└ Reminder: {reminder_mins}min {'(Disabled)' if reminder_mins == 0 else ''}\n"
            )
            
            await message.answer(text, parse_mode=ParseMode.MARKDOWN)
        
        @self._dp.message(Command("pause"))
        async def cmd_pause(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            self._orchestrator.pause()
            await message.answer("⏸ Bot paused. Use /resume to continue.")
        
        @self._dp.message(Command("resume"))
        async def cmd_resume(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            self._orchestrator.resume()
            await message.answer("▶️ Bot resumed.")
        
        @self._dp.message(Command("dayonly"))
        async def cmd_dayonly(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            stats = self._orchestrator.get_stats()
            new_value = not stats.day_only
            self._orchestrator.set_day_only(new_value)
            
            if new_value:
                await message.answer("☀️ Day-only mode enabled. Night trading disabled.")
            else:
                await message.answer("🔄 Day-only mode disabled. Both modes active.")
        
        @self._dp.message(Command("nightonly"))
        async def cmd_nightonly(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            stats = self._orchestrator.get_stats()
            new_value = not stats.night_only
            self._orchestrator.set_night_only(new_value)
            
            if new_value:
                await message.answer("🌙 Night-only mode enabled. Day trading disabled.")
            else:
                await message.answer("🔄 Night-only mode disabled. Both modes active.")
        
        @self._dp.message(Command("settings"))
        async def cmd_settings(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            await self._show_settings_menu(message)
        
        @self._dp.message(Command("report"))
        async def cmd_report(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            await self._show_report(message)
        
        @self._dp.callback_query()
        async def handle_callback(callback: types.CallbackQuery):
            if not self._is_authorized(callback.from_user.id):
                await callback.answer("Unauthorized", show_alert=True)
                return
            
            data = callback.data
            
            if data == "noop":
                # No-operation callback (for separator buttons)
                await callback.answer()
                return
            
            if data.startswith("trade_ok_"):
                trade_id = int(data.split("_")[2])
                await self._handle_trade_confirm(callback, trade_id, True)
            
            elif data.startswith("trade_skip_"):
                trade_id = int(data.split("_")[2])
                await self._handle_trade_confirm(callback, trade_id, False)
            
            elif data.startswith("trade_details_"):
                trade_id = int(data.split("_")[2])
                await self._handle_trade_details(callback, trade_id)
            
            elif data == "settings_menu":
                await self._show_settings_menu(callback.message)
            
            elif data == "toggle_night_auto":
                dn_config = self._get_day_night_config_service()
                await self._toggle_night_auto(callback, dn_config)
            
            elif data.startswith("settings_"):
                await self._handle_settings_callback(callback, data)
            
            await callback.answer()
    
    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized."""
        if not self._admin_ids:
            return True  # No restrictions if no admin IDs configured
        return user_id in self._admin_ids
    
    def _get_mode_text(self, stats: Stats) -> str:
        """Get human-readable mode text."""
        if stats.is_paused:
            return "⏸ Paused"
        if stats.day_only:
            return "☀️ Day Only"
        if stats.night_only:
            return "🌙 Night Only"
        return "🔄 All Hours"
    
    def _get_series_indicator(self, stats: Stats) -> SeriesIndicator:
        """
        Get series activity indicator.
        
        Returns:
            SeriesIndicator with current status
        """
        import time
        from src.services.time_mode import TimeModeService
        from src.adapters.storage import get_database, TradeRepository
        from src.common.config import get_config
        
        config = get_config()
        time_svc = TimeModeService()
        current_mode = time_svc.get_current_mode(int(time.time()))
        night_autotrade = config.day_night.get("night_autotrade_enabled", False)
        
        # Get active trades
        db = get_database()
        trade_repo = TradeRepository(db)
        active_trades = trade_repo.get_active()
        
        return compute_series_indicator(
            stats=stats,
            active_trades=active_trades,
            current_time_mode=current_mode,
            night_autotrade_enabled=night_autotrade,
        )
    
    def _get_polymarket_auth_indicator(self) -> PolymarketAuthIndicator:
        """
        Get Polymarket authorization indicator.
        
        Returns:
            PolymarketAuthIndicator with current status
        """
        from src.common.config import get_config
        config = get_config()
        execution_mode = config.execution.get("mode", "paper")
        
        return compute_polymarket_auth_indicator(execution_mode)
    
    def _format_indicators_header(self, stats: Stats) -> str:
        """
        Format status indicators as a header string.
        
        Args:
            stats: Current stats
            
        Returns:
            Formatted header with indicators
        """
        series = self._get_series_indicator(stats)
        auth = self._get_polymarket_auth_indicator()
        return f"{series} | {auth}"
    
    async def start(self) -> None:
        """Start the Telegram bot."""
        logger.info("Starting Telegram bot polling")
        asyncio.create_task(self._dp.start_polling(self._bot))
    
    async def stop(self) -> None:
        """Stop the Telegram bot."""
        await self._dp.stop_polling()
        await self._bot.session.close()
    
    async def send_trade_card(
        self,
        trade: Trade,
        signal: Signal,
        window: MarketWindow,
        quality: QualityBreakdown,
    ) -> None:
        """
        Send trade signal card to all admins.
        
        Args:
            trade: Trade record
            signal: Trading signal
            window: Market window
            quality: Quality breakdown
        """
        if not self._admin_ids:
            logger.warning("No admin IDs configured for Telegram")
            return
        
        from src.services.time_mode import TimeModeService
        time_svc = TimeModeService()
        
        # Format times
        start_local = time_svc.format_local_time(window.start_ts)
        end_local = time_svc.format_local_time(window.end_ts)
        signal_local = time_svc.format_local_time(signal.signal_ts)
        confirm_local = time_svc.format_local_time(signal.confirm_ts)
        
        # Get status indicators for header
        stats = self._orchestrator.get_stats()
        series_indicator = self._get_series_indicator(stats)
        auth_indicator = self._get_polymarket_auth_indicator()
        
        # Build message with indicators header
        direction_emoji = "📈" if signal.direction.value == "UP" else "📉"
        mode_emoji = "☀️" if trade.time_mode == TimeMode.DAY else "🌙"
        policy_emoji = "🔒" if trade.policy_mode == PolicyMode.STRICT else "📋"
        
        text = (
            f"{series_indicator} | {auth_indicator}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*{direction_emoji} {window.asset} {signal.direction.value}*\n\n"
            f"🕐 Window: {start_local} → {end_local}\n"
            f"📍 Signal: {signal_local}\n"
            f"⏳ Confirm: {confirm_local}\n\n"
            f"*Quality: {quality.final_quality:.2f}*\n"
            f"├ Anchor Edge: {quality.w_anchor:.2f}\n"
            f"├ ADX ({quality.adx_value:.1f}): {quality.w_adx:.2f}\n"
            f"├ Slope: {quality.w_slope:.2f}\n"
            f"└ Trend Mult: {quality.trend_mult}x {'✅' if quality.trend_confirms else '⚠️'}\n\n"
            f"{mode_emoji} Mode: {trade.time_mode.value}\n"
            f"{policy_emoji} Policy: {trade.policy_mode.value}\n"
            f"🔥 Streak: Trade={trade.trade_level_streak} Night={trade.night_streak}\n"
        )
        
        # Create inline keyboard
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ OK", callback_data=f"trade_ok_{trade.id}"),
                InlineKeyboardButton(text="❌ SKIP", callback_data=f"trade_skip_{trade.id}"),
            ],
            [
                InlineKeyboardButton(text="📊 Details", callback_data=f"trade_details_{trade.id}"),
                InlineKeyboardButton(text="⚙️ Settings", callback_data="settings_menu"),
            ],
        ])
        
        # Send to all admins
        for user_id in self._admin_ids:
            try:
                msg = await self._bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                )
                self._trade_messages[trade.id] = (user_id, msg.message_id)
            except Exception as e:
                logger.error("Failed to send trade card", user_id=user_id, error=str(e))
    
    async def _handle_trade_confirm(
        self,
        callback: types.CallbackQuery,
        trade_id: int,
        confirm: bool,
    ) -> None:
        """Handle trade confirmation callback."""
        success = self._orchestrator.confirm_trade(trade_id, confirm)
        
        if success:
            action = "confirmed ✅" if confirm else "skipped ❌"
            await callback.message.edit_text(
                callback.message.text + f"\n\n*Trade {action}*",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await callback.answer("Trade no longer available", show_alert=True)
    
    async def _handle_trade_details(
        self,
        callback: types.CallbackQuery,
        trade_id: int,
    ) -> None:
        """Show detailed trade information."""
        from src.adapters.storage import get_database, TradeRepository, SignalRepository
        
        db = get_database()
        trade_repo = TradeRepository(db)
        signal_repo = SignalRepository(db)
        
        trade = trade_repo.get_by_id(trade_id)
        if not trade:
            await callback.answer("Trade not found", show_alert=True)
            return
        
        signal = signal_repo.get_by_id(trade.signal_id) if trade.signal_id else None
        
        text = (
            f"*Trade #{trade.id} Details*\n\n"
            f"Status: {trade.status.value}\n"
            f"Decision: {trade.decision.value}\n"
            f"Fill Status: {trade.fill_status.value}\n"
        )
        
        if signal and signal.quality_breakdown:
            bd = signal.quality_breakdown
            text += (
                f"\n*Quality Breakdown:*\n"
                f"Anchor Price: {bd.anchor_price:.2f}\n"
                f"Signal Price: {bd.signal_price:.2f}\n"
                f"Return from Anchor: {bd.ret_from_anchor:.4f}\n"
                f"Edge Component: {bd.edge_component:.2f}\n"
                f"ADX Value: {bd.adx_value:.2f}\n"
                f"EMA50 Slope: {bd.ema50_slope:.4f}\n"
            )
        
        if trade.pnl is not None:
            pnl_emoji = "💰" if trade.pnl > 0 else "💸"
            text += f"\n{pnl_emoji} P&L: {trade.pnl:.2f} USDC"
        
        await callback.message.answer(text, parse_mode=ParseMode.MARKDOWN)
    
    def _get_day_night_config_service(self):
        """Get or create DayNightConfigService instance."""
        from src.services.day_night_config import DayNightConfigService
        from src.adapters.storage import get_database, SettingsRepository
        from src.common.config import get_config
        
        config = get_config()
        db = get_database()
        settings_repo = SettingsRepository(db)
        
        return DayNightConfigService(
            settings_repo=settings_repo,
            default_day_start=config.day_night.get("day_start_hour", 8),
            default_day_end=config.day_night.get("day_end_hour", 22),
            default_base_day_quality=config.day_night.get("base_day_min_quality", 50.0),
            default_base_night_quality=config.day_night.get("base_night_min_quality", 60.0),
            default_night_autotrade=config.day_night.get("night_autotrade_enabled", False),
            default_night_max_streak=config.day_night.get("night_max_win_streak", 5),
            default_switch_streak_at=config.day_night.get("switch_streak_at", 3),
            default_reminder_minutes=config.day_night.get("reminder_minutes_before_day_end", 30),
        )
    
    async def _show_settings_menu(self, message: types.Message) -> None:
        """Show settings menu with current values from persisted settings."""
        from src.common.config import get_config
        
        config = get_config()
        dn_config = self._get_day_night_config_service()
        
        # Get persisted values (fall back to config defaults)
        day_start = dn_config.get_day_start_hour()
        day_end = dn_config.get_day_end_hour()
        base_day_q = dn_config.get_base_day_quality()
        base_night_q = dn_config.get_base_night_quality()
        night_auto = dn_config.get_night_autotrade_enabled()
        night_max = dn_config.get_night_max_streak()
        switch_at = dn_config.get_switch_streak_at()
        reminder_mins = dn_config.get_reminder_minutes()
        
        # Current mode
        current_mode = dn_config.get_current_mode()
        mode_emoji = "☀️" if current_mode.value == "DAY" else "🌙"
        
        text = (
            "⚙️ *Settings*\n\n"
            f"{mode_emoji} *Current Mode:* {current_mode.value}\n\n"
            f"*Day/Night Hours:*\n"
            f"├ Day Start: {day_start:02d}:00\n"
            f"└ Day End: {day_end:02d}:00\n\n"
            f"*Quality Thresholds:*\n"
            f"├ Base Day: {base_day_q:.1f}\n"
            f"└ Base Night: {base_night_q:.1f}\n\n"
            f"*Night Settings:*\n"
            f"├ Auto-trade: {'✅ Enabled' if night_auto else '❌ Disabled'}\n"
            f"└ Max Streak: {night_max}\n\n"
            f"*Streak Settings:*\n"
            f"└ Switch to STRICT at: {switch_at} wins\n\n"
            f"*Reminders:*\n"
            f"└ Before day end: {reminder_mins} min {'(Disabled)' if reminder_mins == 0 else ''}\n\n"
            f"*Trading:*\n"
            f"├ Price Cap: {config.trading.get('price_cap', 0.55)}\n"
            f"├ Confirm Delay: {config.trading.get('confirm_delay_seconds', 120)}s\n"
            f"└ CAP Min Ticks: {config.trading.get('cap_min_ticks', 3)}\n"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🕐 Day Hours", callback_data="settings_day_hours"),
                InlineKeyboardButton(text="📊 Quality", callback_data="settings_quality"),
            ],
            [
                InlineKeyboardButton(text="🌙 Night Auto", callback_data="settings_night_auto"),
                InlineKeyboardButton(text="🔥 Streaks", callback_data="settings_streaks"),
            ],
            [
                InlineKeyboardButton(text="⏰ Reminder", callback_data="settings_reminder"),
                InlineKeyboardButton(text="💰 Trading", callback_data="settings_trading"),
            ],
        ])
        
        await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def _handle_settings_callback(
        self,
        callback: types.CallbackQuery,
        data: str,
    ) -> None:
        """Handle settings callback with actual edits."""
        setting_name = data.replace("settings_", "")
        dn_config = self._get_day_night_config_service()
        
        if setting_name == "day_hours":
            await self._show_day_hours_settings(callback, dn_config)
        elif setting_name == "night_auto":
            await self._toggle_night_auto(callback, dn_config)
        elif setting_name == "quality":
            await self._show_quality_settings(callback, dn_config)
        elif setting_name == "streaks":
            await self._show_streak_settings(callback, dn_config)
        elif setting_name == "reminder":
            await self._show_reminder_settings(callback, dn_config)
        elif setting_name == "trading":
            await self._show_trading_info(callback)
        elif setting_name.startswith("set_day_start_"):
            hour = int(setting_name.replace("set_day_start_", ""))
            await self._set_day_start(callback, dn_config, hour)
        elif setting_name.startswith("set_day_end_"):
            hour = int(setting_name.replace("set_day_end_", ""))
            await self._set_day_end(callback, dn_config, hour)
        elif setting_name.startswith("set_reminder_"):
            minutes = int(setting_name.replace("set_reminder_", ""))
            await self._set_reminder_minutes(callback, dn_config, minutes)
        elif setting_name == "toggle_night_auto":
            await self._toggle_night_auto(callback, dn_config)
        else:
            await callback.message.answer(
                f"Setting '{setting_name}' edit not yet implemented.\n"
                "Use config/config.json for now.",
            )
    
    async def _show_day_hours_settings(self, callback: types.CallbackQuery, dn_config) -> None:
        """Show day hours settings with edit buttons."""
        day_start = dn_config.get_day_start_hour()
        day_end = dn_config.get_day_end_hour()
        
        text = (
            "🕐 *Day/Night Hours*\n\n"
            f"Current Day Window: {day_start:02d}:00 → {day_end:02d}:00\n\n"
            "Timezone: Europe/Zurich (fixed)\n\n"
            "*Set Day Start Hour:*\n"
            "Select the hour when DAY mode begins:\n"
        )
        
        # Create hour selection buttons for start (0-23)
        start_buttons = []
        for i in range(0, 24, 6):
            row = []
            for h in range(i, min(i + 6, 24)):
                marker = "✓" if h == day_start else ""
                row.append(InlineKeyboardButton(
                    text=f"{h:02d}{marker}",
                    callback_data=f"settings_set_day_start_{h}"
                ))
            start_buttons.append(row)
        
        # Add separator text
        start_buttons.append([InlineKeyboardButton(text="─── Day End Hour ───", callback_data="noop")])
        
        # Create hour selection buttons for end
        for i in range(0, 24, 6):
            row = []
            for h in range(i, min(i + 6, 24)):
                marker = "✓" if h == day_end else ""
                row.append(InlineKeyboardButton(
                    text=f"{h:02d}{marker}",
                    callback_data=f"settings_set_day_end_{h}"
                ))
            start_buttons.append(row)
        
        start_buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="settings_menu")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=start_buttons)
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def _set_day_start(self, callback: types.CallbackQuery, dn_config, hour: int) -> None:
        """Set day start hour."""
        success = dn_config.set_day_start_hour(hour)
        if success:
            await callback.answer(f"✅ Day start set to {hour:02d}:00")
            await self._show_day_hours_settings(callback, dn_config)
        else:
            await callback.answer("❌ Invalid hour", show_alert=True)
    
    async def _set_day_end(self, callback: types.CallbackQuery, dn_config, hour: int) -> None:
        """Set day end hour."""
        success = dn_config.set_day_end_hour(hour)
        if success:
            await callback.answer(f"✅ Day end set to {hour:02d}:00")
            await self._show_day_hours_settings(callback, dn_config)
        else:
            await callback.answer("❌ Invalid hour", show_alert=True)
    
    async def _toggle_night_auto(self, callback: types.CallbackQuery, dn_config) -> None:
        """Toggle night autotrade setting."""
        current = dn_config.get_night_autotrade_enabled()
        new_value = not current
        dn_config.set_night_autotrade_enabled(new_value)
        
        status = "✅ Enabled" if new_value else "❌ Disabled"
        await callback.answer(f"Night Auto-trade: {status}")
        
        # Refresh settings menu
        await self._show_settings_menu(callback.message)
    
    async def _show_quality_settings(self, callback: types.CallbackQuery, dn_config) -> None:
        """Show quality threshold info."""
        base_day = dn_config.get_base_day_quality()
        base_night = dn_config.get_base_night_quality()
        
        text = (
            "📊 *Quality Thresholds*\n\n"
            f"Base Day: {base_day:.1f}\n"
            f"Base Night: {base_night:.1f}\n\n"
            "*Note:* Quality threshold changes require config edit.\n"
            "Edit `config/config.json`:\n"
            "```\n"
            '"day_night": {\n'
            f'  "base_day_min_quality": {base_day},\n'
            f'  "base_night_min_quality": {base_night}\n'
            '}\n'
            "```"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data="settings_menu")],
        ])
        
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def _show_streak_settings(self, callback: types.CallbackQuery, dn_config) -> None:
        """Show streak settings info."""
        switch_at = dn_config.get_switch_streak_at()
        night_max = dn_config.get_night_max_streak()
        
        text = (
            "🔥 *Streak Settings*\n\n"
            f"Switch to STRICT at: {switch_at} wins\n"
            f"Night Max Streak: {night_max}\n\n"
            "*Note:* Streak setting changes require config edit.\n"
            "Edit `config/config.json`:\n"
            "```\n"
            '"day_night": {\n'
            f'  "switch_streak_at": {switch_at},\n'
            f'  "night_max_win_streak": {night_max}\n'
            '}\n'
            "```"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data="settings_menu")],
        ])
        
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def _show_reminder_settings(self, callback: types.CallbackQuery, dn_config) -> None:
        """Show reminder settings with edit buttons."""
        current_mins = dn_config.get_reminder_minutes()
        
        text = (
            "⏰ *Day End Reminder*\n\n"
            f"Current: {current_mins} minutes before day end\n"
            f"{'(Disabled)' if current_mins == 0 else ''}\n\n"
            "Select reminder time:\n"
        )
        
        # Preset options
        presets = [0, 15, 30, 45, 60, 90, 120, 180]
        buttons = []
        for mins in presets:
            label = "Off" if mins == 0 else f"{mins}min"
            marker = " ✓" if mins == current_mins else ""
            buttons.append(InlineKeyboardButton(
                text=f"{label}{marker}",
                callback_data=f"settings_set_reminder_{mins}"
            ))
        
        # Group into rows of 4
        keyboard_rows = [buttons[i:i+4] for i in range(0, len(buttons), 4)]
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="settings_menu")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def _set_reminder_minutes(self, callback: types.CallbackQuery, dn_config, minutes: int) -> None:
        """Set reminder minutes."""
        success = dn_config.set_reminder_minutes(minutes)
        if success:
            if minutes == 0:
                await callback.answer("✅ Reminder disabled")
            else:
                await callback.answer(f"✅ Reminder set to {minutes} minutes")
            await self._show_reminder_settings(callback, dn_config)
        else:
            await callback.answer("❌ Invalid value", show_alert=True)
    
    async def _show_trading_info(self, callback: types.CallbackQuery) -> None:
        """Show trading settings info."""
        from src.common.config import get_config
        config = get_config()
        
        text = (
            "💰 *Trading Settings*\n\n"
            f"Price Cap: {config.trading.get('price_cap', 0.55)}\n"
            f"Confirm Delay: {config.trading.get('confirm_delay_seconds', 120)}s\n"
            f"CAP Min Ticks: {config.trading.get('cap_min_ticks', 3)}\n\n"
            "*Note:* Trading parameter changes require config edit.\n"
            "Edit `config/config.json`:\n"
            "```\n"
            '"trading": {\n'
            f'  "price_cap": {config.trading.get("price_cap", 0.55)},\n'
            f'  "confirm_delay_seconds": {config.trading.get("confirm_delay_seconds", 120)},\n'
            f'  "cap_min_ticks": {config.trading.get("cap_min_ticks", 3)}\n'
            '}\n'
            "```"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data="settings_menu")],
        ])
        
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def _show_report(self, message: types.Message) -> None:
        """Show performance report."""
        stats = self._orchestrator.get_stats()
        
        text = (
            "📈 *Performance Report*\n\n"
            f"*Totals:*\n"
            f"├ Trades: {stats.total_trades}\n"
            f"├ Wins: {stats.total_wins}\n"
            f"├ Losses: {stats.total_losses}\n"
            f"└ Win Rate: {stats.win_rate:.1f}%\n\n"
            f"*Current Streaks:*\n"
            f"├ Trade Level: {stats.trade_level_streak}\n"
            f"└ Night: {stats.night_streak}\n\n"
            f"*Mode:* {stats.policy_mode.value}\n"
        )
        
        if stats.last_strict_day_threshold:
            text += f"Day Strict Threshold: {stats.last_strict_day_threshold:.2f}\n"
        if stats.last_strict_night_threshold:
            text += f"Night Strict Threshold: {stats.last_strict_night_threshold:.2f}\n"
        
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
