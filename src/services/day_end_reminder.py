"""
Day End Reminder Service for MARTIN.

Sends automatic reminders before the day trading window ends.
"""

import asyncio
from datetime import datetime, date
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.enums import TimeMode
from src.common.logging import get_logger

if TYPE_CHECKING:
    from src.services.day_night_config import DayNightConfigService
    from aiogram import Bot

logger = get_logger(__name__)


# Night session mode options
class NightSessionMode:
    """Night session mode options."""
    
    OFF = "OFF"          # No autonomous trading at night
    SOFT_RESET = "SOFT"  # Autonomous with soft reset (night streak only)
    HARD_RESET = "HARD"  # Autonomous with hard reset (all streaks)
    
    @classmethod
    def get_description(cls, mode: str) -> str:
        """Get human-readable description of night session mode."""
        descriptions = {
            cls.OFF: "Night trading disabled. Bot will not trade during night hours.",
            cls.SOFT_RESET: "Autonomous trading at night. Resets night streak only at NIGHT_MAX_WIN_STREAK.",
            cls.HARD_RESET: "Autonomous trading at night. Resets all streaks at NIGHT_MAX_WIN_STREAK.",
        }
        return descriptions.get(mode, "Unknown mode")


@dataclass
class ReminderConfig:
    """Configuration for reminder messages."""
    
    minutes_before: int
    last_reminder_date: date | None = None
    
    def should_send_today(self) -> bool:
        """Check if reminder should be sent today (max once per day)."""
        if self.last_reminder_date is None:
            return True
        return self.last_reminder_date != date.today()


class DayEndReminderService:
    """
    Service for sending day end reminders.
    
    Features:
    - Configurable X minutes before day end
    - Rate-limited: max one reminder per day
    - Shows current night session mode with explanation
    - Shows current execution mode and auth status
    - Inline buttons for night mode quick-toggle
    """
    
    def __init__(
        self,
        config_service: "DayNightConfigService",
        bot: "Bot" = None,
        admin_user_ids: list[int] = None,
    ):
        """
        Initialize Day End Reminder Service.
        
        Args:
            config_service: Day/Night configuration service
            bot: Telegram bot instance
            admin_user_ids: List of admin user IDs to notify
        """
        self._config = config_service
        self._bot = bot
        self._admin_ids = admin_user_ids or []
        self._last_reminder_date: date | None = None
        self._running = False
        self._task: asyncio.Task | None = None
    
    def set_bot(self, bot: "Bot") -> None:
        """Set the Telegram bot instance."""
        self._bot = bot
    
    def set_admin_ids(self, admin_ids: list[int]) -> None:
        """Set admin user IDs."""
        self._admin_ids = admin_ids
    
    def get_current_night_mode(self) -> str:
        """
        Get current night session mode.
        
        Returns:
            NightSessionMode value
        """
        night_autotrade = self._config.get_night_autotrade_enabled()
        if not night_autotrade:
            return NightSessionMode.OFF
        
        # Get night session mode from config
        # Supports both new 'night_session_mode' key and legacy 'night_session_resets_trade_streak'
        from src.common.config import get_config
        config = get_config()
        night_mode_str = config.day_night.get("night_session_mode", None)
        
        if night_mode_str is not None:
            # Use new canonical key
            try:
                return NightSessionMode(night_mode_str)
            except ValueError:
                pass
        
        # Legacy fallback: convert boolean to enum
        resets_trade_streak = config.day_night.get("night_session_resets_trade_streak", True)
        if resets_trade_streak:
            return NightSessionMode.HARD_RESET
        return NightSessionMode.SOFT_RESET
    
    def format_reminder_message(
        self,
        current_time: datetime,
        day_end_time: datetime,
        execution_mode: str,
        is_authorized: bool,
    ) -> str:
        """
        Format the reminder message.
        
        Args:
            current_time: Current local time
            day_end_time: Day end local time
            execution_mode: Current execution mode (paper/live)
            is_authorized: Whether Polymarket is authorized
            
        Returns:
            Formatted message text
        """
        night_mode = self.get_current_night_mode()
        night_mode_desc = NightSessionMode.get_description(night_mode)
        
        # Status indicators
        mode_emoji = "🟡" if is_authorized else "⚪"
        exec_text = f"{mode_emoji} {'Live' if execution_mode == 'live' else 'Paper'}"
        
        night_emoji = {
            NightSessionMode.OFF: "🔴",
            NightSessionMode.SOFT_RESET: "🟡",
            NightSessionMode.HARD_RESET: "🟢",
        }.get(night_mode, "⚪")
        
        message = (
            "⏰ *Day Window Ending Soon*\n\n"
            f"🕐 Current time: {current_time.strftime('%H:%M %Z')}\n"
            f"🌙 Day ends at: {day_end_time.strftime('%H:%M %Z')}\n\n"
            f"*Night Session Mode*: {night_emoji} {night_mode}\n"
            f"_{night_mode_desc}_\n\n"
            f"*Execution*: {exec_text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*Quick Actions:*\n"
            "• `/nightonly` - Toggle night-only mode\n"
            "• `/dayonly` - Toggle day-only mode\n"
            "• `/settings` - Adjust night settings\n"
        )
        
        return message
    
    def should_send_reminder(self) -> bool:
        """
        Check if reminder should be sent.
        
        Returns:
            True if reminder should be sent
        """
        # Check if reminder is enabled
        minutes = self._config.get_reminder_minutes()
        if minutes == 0:
            return False
        
        # Check rate limit: max once per day
        today = date.today()
        if self._last_reminder_date == today:
            logger.debug("Reminder already sent today")
            return False
        
        # Check if we're currently in day mode
        current_mode = self._config.get_current_mode()
        if current_mode != TimeMode.DAY:
            logger.debug("Not in day mode, skipping reminder")
            return False
        
        return True
    
    def get_seconds_until_reminder(self) -> int | None:
        """
        Calculate seconds until next reminder should be sent.
        
        Returns:
            Seconds until reminder, or None if disabled/already sent today
        """
        if not self.should_send_reminder():
            return None
        
        reminder_ts = self._config.get_reminder_ts()
        if reminder_ts is None:
            return None
        
        import time
        now = int(time.time())
        delta = reminder_ts - now
        
        if delta <= 0:
            # Time to send now
            return 0
        
        return delta
    
    async def send_reminder(self) -> bool:
        """
        Send the reminder message to all admins.
        
        Returns:
            True if reminder was sent successfully
        """
        if not self._bot:
            logger.warning("Bot not configured, cannot send reminder")
            return False
        
        if not self._admin_ids:
            logger.warning("No admin IDs configured, cannot send reminder")
            return False
        
        # Get current status
        from src.common.config import get_config
        import time
        
        config = get_config()
        execution_mode = config.execution.get("mode", "paper")
        
        # Check auth status
        from src.services.status_indicator import compute_polymarket_auth_indicator
        auth_indicator = compute_polymarket_auth_indicator(execution_mode)
        is_authorized = auth_indicator.is_authorized
        
        # Get times
        current_time = self._config.get_current_local_time()
        day_end_ts = self._config.get_next_day_end_ts()
        day_end_time = self._config.get_current_local_time(day_end_ts)
        
        # Format message
        message = self.format_reminder_message(
            current_time=current_time,
            day_end_time=day_end_time,
            execution_mode=execution_mode,
            is_authorized=is_authorized,
        )
        
        # Create inline keyboard for quick actions
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🌙 Toggle Night Auto", callback_data="toggle_night_auto"),
                InlineKeyboardButton(text="⚙️ Settings", callback_data="settings_menu"),
            ],
        ])
        
        # Send to all admins
        success_count = 0
        for user_id in self._admin_ids:
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                success_count += 1
            except Exception as e:
                logger.error("Failed to send reminder", user_id=user_id, error=str(e))
        
        if success_count > 0:
            self._last_reminder_date = date.today()
            logger.info(
                "Sent day end reminder",
                recipients=success_count,
                minutes_before=self._config.get_reminder_minutes(),
            )
            return True
        
        return False
    
    async def check_and_send(self) -> bool:
        """
        Check if reminder should be sent and send if due.
        
        This method is designed to be called periodically by a scheduler.
        
        Returns:
            True if reminder was sent
        """
        seconds = self.get_seconds_until_reminder()
        
        if seconds is None:
            return False
        
        if seconds <= 0:
            return await self.send_reminder()
        
        return False
    
    async def start_background_checker(self, check_interval: int = 60) -> None:
        """
        Start background task that checks for reminders periodically.
        
        Args:
            check_interval: Seconds between checks
        """
        if self._running:
            logger.warning("Reminder checker already running")
            return
        
        self._running = True
        
        async def checker():
            while self._running:
                try:
                    await self.check_and_send()
                except Exception as e:
                    logger.error("Error in reminder checker", error=str(e))
                
                await asyncio.sleep(check_interval)
        
        self._task = asyncio.create_task(checker())
        logger.info("Started day end reminder checker", interval=check_interval)
    
    async def stop_background_checker(self) -> None:
        """Stop the background reminder checker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Stopped day end reminder checker")
    
    def reset_daily_limit(self) -> None:
        """Reset the daily reminder limit (for testing)."""
        self._last_reminder_date = None
