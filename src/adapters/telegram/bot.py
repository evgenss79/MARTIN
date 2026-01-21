"""
Telegram Bot Handler for MARTIN.

Implements the Telegram UX for trading signals and user interaction.
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
            
            text = (
                "📊 *MARTIN Status*\n\n"
                f"Policy: {stats.policy_mode.value}\n"
                f"Mode: {mode_text}\n"
                f"Trade Streak: {stats.trade_level_streak}\n"
                f"Night Streak: {stats.night_streak}\n\n"
                f"Total Trades: {stats.total_trades}\n"
                f"Wins: {stats.total_wins}\n"
                f"Losses: {stats.total_losses}\n"
                f"Win Rate: {stats.win_rate:.1f}%\n\n"
                f"Paused: {'Yes' if stats.is_paused else 'No'}\n"
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
            
            if data.startswith("trade_ok_"):
                trade_id = int(data.split("_")[2])
                await self._handle_trade_confirm(callback, trade_id, True)
            
            elif data.startswith("trade_skip_"):
                trade_id = int(data.split("_")[2])
                await self._handle_trade_confirm(callback, trade_id, False)
            
            elif data.startswith("trade_details_"):
                trade_id = int(data.split("_")[2])
                await self._handle_trade_details(callback, trade_id)
            
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
        
        # Build message
        direction_emoji = "📈" if signal.direction.value == "UP" else "📉"
        mode_emoji = "☀️" if trade.time_mode == TimeMode.DAY else "🌙"
        policy_emoji = "🔒" if trade.policy_mode == PolicyMode.STRICT else "📋"
        
        text = (
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
    
    async def _show_settings_menu(self, message: types.Message) -> None:
        """Show settings menu."""
        from src.common.config import get_config
        config = get_config()
        
        text = (
            "⚙️ *Settings*\n\n"
            f"Price Cap: {config.trading.get('price_cap', 0.55)}\n"
            f"Confirm Delay: {config.trading.get('confirm_delay_seconds', 120)}s\n"
            f"CAP Min Ticks: {config.trading.get('cap_min_ticks', 3)}\n"
            f"Day Start: {config.day_night.get('day_start_hour', 8)}:00\n"
            f"Day End: {config.day_night.get('day_end_hour', 22)}:00\n"
            f"Base Day Quality: {config.day_night.get('base_day_min_quality', 50)}\n"
            f"Base Night Quality: {config.day_night.get('base_night_min_quality', 60)}\n"
            f"Switch Streak At: {config.day_night.get('switch_streak_at', 3)}\n"
            f"Night Max Streak: {config.day_night.get('night_max_win_streak', 5)}\n"
            f"Night Auto-trade: {config.day_night.get('night_autotrade_enabled', False)}\n"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Price Cap", callback_data="settings_price_cap"),
                InlineKeyboardButton(text="Confirm Delay", callback_data="settings_confirm_delay"),
            ],
            [
                InlineKeyboardButton(text="CAP Ticks", callback_data="settings_cap_ticks"),
                InlineKeyboardButton(text="Day Hours", callback_data="settings_day_hours"),
            ],
            [
                InlineKeyboardButton(text="Base Quality", callback_data="settings_base_quality"),
                InlineKeyboardButton(text="Streaks", callback_data="settings_streaks"),
            ],
            [
                InlineKeyboardButton(text="Night Auto", callback_data="settings_night_auto"),
            ],
        ])
        
        await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def _handle_settings_callback(
        self,
        callback: types.CallbackQuery,
        data: str,
    ) -> None:
        """Handle settings callback."""
        setting_name = data.replace("settings_", "")
        
        # For now, just show info about how to change settings
        await callback.message.answer(
            f"To change {setting_name}, update config/config.json or use environment variables.\n"
            "Runtime settings persistence coming soon!",
        )
    
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
