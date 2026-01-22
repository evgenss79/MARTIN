"""
Status Indicator Service for MARTIN.

Provides visual status indicators for:
1. Series Activity (🟢/🔴) - Whether a trading series is active
2. Polymarket Auth (🟡/⚪) - Whether live trading is authorized
3. Encryption Status (🔒/🔓) - Whether secrets are encrypted at rest

These indicators are shown in Telegram UI (/status, trade cards).
"""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.enums import TradeStatus, TimeMode, Decision, FillStatus
from src.domain.models import Stats, Trade
from src.common.logging import get_logger
from src.common.crypto import is_master_key_configured, validate_master_key

if TYPE_CHECKING:
    from src.services.orchestrator import Orchestrator

logger = get_logger(__name__)


@dataclass
class SeriesIndicator:
    """
    Series activity indicator.
    
    Attributes:
        is_active: Whether a trading series is active
        emoji: 🟢 for active, 🔴 for inactive
        label: Human-readable status text
    """
    is_active: bool
    emoji: str
    label: str
    
    def __str__(self) -> str:
        return f"{self.emoji} {self.label}"


@dataclass
class PolymarketAuthIndicator:
    """
    Polymarket authorization indicator.
    
    Attributes:
        is_authorized: Whether bot can place live orders
        emoji: 🟡 for authorized, ⚪ for not authorized
        label: Human-readable status text
    """
    is_authorized: bool
    emoji: str
    label: str
    
    @property
    def authorized(self) -> bool:
        """Alias for is_authorized for backward compatibility."""
        return self.is_authorized
    
    def __str__(self) -> str:
        return f"{self.emoji} {self.label}"


# In-progress trade statuses (series is active if any trade in these states)
IN_PROGRESS_STATUSES = {
    TradeStatus.WAITING_CONFIRM,
    TradeStatus.WAITING_CAP,
    TradeStatus.READY,
    TradeStatus.ORDER_PLACED,
}


def compute_series_indicator(
    stats: Stats,
    active_trades: list[Trade],
    current_time_mode: TimeMode,
    night_autotrade_enabled: bool,
) -> SeriesIndicator:
    """
    Compute series activity indicator.
    
    A series is ACTIVE if:
    a) trading is not paused, AND
    b) there is at least one "in-progress" trade OR trade_level_streak > 0, AND
    c) the bot is allowed to trade in current mode
    
    Args:
        stats: Current stats
        active_trades: List of non-terminal trades
        current_time_mode: Current time mode (DAY/NIGHT)
        night_autotrade_enabled: Whether night auto-trading is enabled
        
    Returns:
        SeriesIndicator with status
    """
    # Condition a: Not paused
    if stats.is_paused:
        return SeriesIndicator(
            is_active=False,
            emoji="🔴",
            label="Series Inactive (Paused)",
        )
    
    # Check mode restrictions
    if stats.day_only and current_time_mode == TimeMode.NIGHT:
        return SeriesIndicator(
            is_active=False,
            emoji="🔴",
            label="Series Inactive (Day Only)",
        )
    
    if stats.night_only and current_time_mode == TimeMode.DAY:
        return SeriesIndicator(
            is_active=False,
            emoji="🔴",
            label="Series Inactive (Night Only)",
        )
    
    # Condition c: Bot allowed to trade in current mode
    if current_time_mode == TimeMode.NIGHT and not night_autotrade_enabled:
        return SeriesIndicator(
            is_active=False,
            emoji="🔴",
            label="Series Inactive (Night Auto Disabled)",
        )
    
    # Condition b: In-progress trade OR streak > 0
    has_in_progress = any(
        trade.status in IN_PROGRESS_STATUSES
        for trade in active_trades
    )
    
    has_streak = stats.trade_level_streak > 0
    
    if has_in_progress or has_streak:
        streak_text = f" (Streak: {stats.trade_level_streak})" if has_streak else ""
        return SeriesIndicator(
            is_active=True,
            emoji="🟢",
            label=f"Series Active{streak_text}",
        )
    
    return SeriesIndicator(
        is_active=False,
        emoji="🔴",
        label="Series Inactive",
    )


def compute_polymarket_auth_indicator(
    execution_mode: str,
) -> PolymarketAuthIndicator:
    """
    Compute Polymarket authorization indicator.
    
    YELLOW (🟡) = Authorized if:
    - execution.mode == "live" AND
    - Required credentials exist (POLYMARKET_PRIVATE_KEY or API key set)
    
    GRAY (⚪) = Not authorized if:
    - execution.mode != "live" OR
    - Missing credentials
    
    Args:
        execution_mode: Current execution mode ("paper" or "live")
        
    Returns:
        PolymarketAuthIndicator with status
    """
    # If not in live mode, show paper mode status
    if execution_mode != "live":
        return PolymarketAuthIndicator(
            is_authorized=False,
            emoji="⚪",
            label="Polymarket Live Disabled (Paper Mode)",
        )
    
    # Check for wallet-based auth
    has_wallet_key = bool(os.environ.get("POLYMARKET_PRIVATE_KEY"))
    
    # Check for API key auth
    has_api_key = (
        bool(os.environ.get("POLYMARKET_API_KEY")) and
        bool(os.environ.get("POLYMARKET_API_SECRET")) and
        bool(os.environ.get("POLYMARKET_PASSPHRASE"))
    )
    
    if has_wallet_key:
        return PolymarketAuthIndicator(
            is_authorized=True,
            emoji="🟡",
            label="Polymarket Authorized (Wallet)",
        )
    
    if has_api_key:
        return PolymarketAuthIndicator(
            is_authorized=True,
            emoji="🟡",
            label="Polymarket Authorized (API Key)",
        )
    
    # Live mode but no credentials
    return PolymarketAuthIndicator(
        is_authorized=False,
        emoji="⚪",
        label="Polymarket Not Authorized (Missing Credentials)",
    )


def validate_live_auth() -> tuple[bool, str]:
    """
    Validate that live trading credentials are properly configured.
    
    Returns:
        Tuple of (is_valid, message)
    """
    # Check wallet key
    wallet_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    if wallet_key:
        # Basic validation - should be hex string
        key = wallet_key.strip()
        if key.startswith("0x"):
            key = key[2:]
        if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
            return True, "Wallet key validated"
        return False, "Invalid wallet key format (must be 64 hex chars)"
    
    # Check API keys
    api_key = os.environ.get("POLYMARKET_API_KEY")
    api_secret = os.environ.get("POLYMARKET_API_SECRET")
    passphrase = os.environ.get("POLYMARKET_PASSPHRASE")
    
    if api_key and api_secret and passphrase:
        return True, "API credentials validated"
    
    missing = []
    if not api_key:
        missing.append("POLYMARKET_API_KEY")
    if not api_secret:
        missing.append("POLYMARKET_API_SECRET")
    if not passphrase:
        missing.append("POLYMARKET_PASSPHRASE")
    
    if missing:
        return False, f"Missing credentials: {', '.join(missing)}"
    
    return False, "No credentials configured"


@dataclass
class EncryptionIndicator:
    """
    Encryption status indicator.
    
    Attributes:
        is_encrypted: Whether secrets are encrypted at rest
        emoji: 🔒 for encrypted, 🔓 for not encrypted
        label: Human-readable status text
    """
    is_encrypted: bool
    emoji: str
    label: str
    
    def __str__(self) -> str:
        return f"{self.emoji} {self.label}"


def compute_encryption_indicator() -> EncryptionIndicator:
    """
    Compute encryption status indicator.
    
    Shows whether MASTER_ENCRYPTION_KEY is configured for
    encrypting secrets at rest (SEC-1 compliance).
    
    Returns:
        EncryptionIndicator with status
    """
    if is_master_key_configured():
        # Validate the key format
        is_valid, msg = validate_master_key()
        if is_valid:
            return EncryptionIndicator(
                is_encrypted=True,
                emoji="🔒",
                label="Secrets Encrypted",
            )
        else:
            return EncryptionIndicator(
                is_encrypted=False,
                emoji="🔓",
                label=f"Encryption Error ({msg})",
            )
    
    return EncryptionIndicator(
        is_encrypted=False,
        emoji="🔓",
        label="Secrets Not Encrypted (MASTER_ENCRYPTION_KEY missing)",
    )


def get_security_summary(execution_mode: str) -> dict[str, str]:
    """
    Get comprehensive security status summary.
    
    Args:
        execution_mode: Current execution mode ("paper" or "live")
        
    Returns:
        Dict with all security indicators
    """
    auth = compute_polymarket_auth_indicator(execution_mode)
    encryption = compute_encryption_indicator()
    
    summary = {
        "auth_status": str(auth),
        "encryption_status": str(encryption),
        "execution_mode": execution_mode,
    }
    
    # Add warning if live mode without encryption
    if execution_mode == "live" and not encryption.is_encrypted:
        summary["security_warning"] = (
            "⚠️ Live mode without encryption. "
            "Set MASTER_ENCRYPTION_KEY for better security."
        )
    
    return summary
