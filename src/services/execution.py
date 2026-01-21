"""
Execution Service for MARTIN.

Handles order placement in paper or live mode.
Default is paper mode (MG-9 safety constraint).

Live mode requires wallet credentials configured via environment variables:
- POLYMARKET_PRIVATE_KEY: Wallet private key for signing (MetaMask export)

OR

- POLYMARKET_API_KEY: API key
- POLYMARKET_API_SECRET: API secret
- POLYMARKET_PASSPHRASE: Passphrase
"""

import time
import uuid
import os
from typing import Any

from src.domain.models import Trade, Signal, MarketWindow
from src.domain.enums import Direction, FillStatus
from src.common.logging import get_logger
from src.common.exceptions import TradeError

logger = get_logger(__name__)


class ExecutionService:
    """
    Service for trade execution.
    
    Supports paper mode (default) and live mode.
    Paper mode simulates fills when CAP_PASS is found.
    Live mode places real orders via Polymarket CLOB.
    
    Live Mode Requirements:
        Either wallet-based auth (MetaMask compatible):
            - Set POLYMARKET_PRIVATE_KEY environment variable
            
        Or API key-based auth:
            - Set POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE
    """
    
    def __init__(
        self,
        mode: str = "paper",
        base_stake_amount: float = 10.0,
        price_cap: float = 0.55,
        clob_client: Any = None,
    ):
        """
        Initialize Execution Service.
        
        Args:
            mode: Execution mode ("paper" or "live")
            base_stake_amount: Default stake amount in USDC
            price_cap: Price cap for orders
            clob_client: CLOB client for live trading
        """
        self._mode = mode
        self._base_stake = base_stake_amount
        self._price_cap = price_cap
        self._clob_client = clob_client
        self._signer = None
        
        if mode == "live":
            self._init_live_mode()
    
    def _init_live_mode(self) -> None:
        """Initialize live mode with signer."""
        logger.warning(
            "LIVE execution mode enabled - real orders will be placed. "
            "Ensure credentials are configured."
        )
        
        # Try wallet-based auth first
        if os.environ.get("POLYMARKET_PRIVATE_KEY"):
            try:
                from src.adapters.polymarket.signer import WalletSigner
                self._signer = WalletSigner()
                self._auth_type = "wallet"
                logger.info(
                    "Using wallet-based authentication",
                    address=self._signer.address,
                )
                return
            except Exception as e:
                logger.warning(f"Failed to init wallet signer: {e}")
        
        # Fall back to API key auth
        if os.environ.get("POLYMARKET_API_KEY"):
            try:
                from src.adapters.polymarket.signer import ApiKeySigner
                self._signer = ApiKeySigner()
                self._auth_type = "api_key"
                logger.info("Using API key-based authentication")
                return
            except Exception as e:
                logger.warning(f"Failed to init API key signer: {e}")
        
        # No valid credentials
        raise TradeError(
            "Live mode requires authentication credentials. "
            "Set POLYMARKET_PRIVATE_KEY (wallet) or "
            "POLYMARKET_API_KEY/SECRET/PASSPHRASE (API key)."
        )
    
    @property
    def is_paper_mode(self) -> bool:
        """Check if running in paper mode."""
        return self._mode == "paper"
    
    def calculate_stake(self, stats: Any) -> float:
        """
        Calculate stake amount for trade.
        
        Currently uses fixed mode only (per spec).
        
        Args:
            stats: Current stats (unused in fixed mode)
            
        Returns:
            Stake amount in USDC
        """
        return self._base_stake
    
    async def place_order(
        self,
        window: MarketWindow,
        signal: Signal,
        trade: Trade,
        stake_amount: float,
    ) -> tuple[str, str, float]:
        """
        Place an order for a trade.
        
        Args:
            window: Market window
            signal: Trading signal
            trade: Trade record
            stake_amount: Amount to stake
            
        Returns:
            Tuple of (order_id, token_id, fill_price)
            
        Raises:
            TradeError: If order placement fails
        """
        # Determine token based on direction
        if signal.direction == Direction.UP:
            token_id = window.up_token_id
            direction_str = "UP"
        else:
            token_id = window.down_token_id
            direction_str = "DOWN"
        
        if self.is_paper_mode:
            return await self._place_paper_order(
                token_id, direction_str, stake_amount
            )
        else:
            return await self._place_live_order(
                window, signal, token_id, direction_str, stake_amount
            )
    
    async def _place_paper_order(
        self,
        token_id: str,
        direction: str,
        stake_amount: float,
    ) -> tuple[str, str, float]:
        """
        Simulate order placement in paper mode.
        
        Args:
            token_id: Token ID
            direction: Trade direction
            stake_amount: Stake amount
            
        Returns:
            Tuple of (order_id, token_id, fill_price)
        """
        # Generate paper order ID
        order_id = f"PAPER_{uuid.uuid4().hex[:12].upper()}"
        
        # Simulate fill at price cap
        fill_price = self._price_cap
        
        logger.info(
            "Paper order placed",
            order_id=order_id,
            direction=direction,
            token_id=token_id[:16] + "...",
            stake_amount=stake_amount,
            fill_price=fill_price,
        )
        
        return order_id, token_id, fill_price
    
    async def _place_live_order(
        self,
        window: MarketWindow,
        signal: Signal,
        token_id: str,
        direction: str,
        stake_amount: float,
    ) -> tuple[str, str, float]:
        """
        Place real order in live mode.
        
        Uses CLOB API with wallet/API key authentication.
        
        Args:
            window: Market window
            signal: Trading signal
            token_id: Token ID
            direction: Trade direction
            stake_amount: Stake amount
            
        Returns:
            Tuple of (order_id, token_id, fill_price)
            
        Raises:
            TradeError: If order placement fails
        """
        if not self._clob_client:
            raise TradeError("CLOB client not initialized for live trading")
        
        if not self._signer:
            raise TradeError("Signer not initialized for live trading")
        
        # Calculate order size based on stake and price cap
        # size = stake / price (number of contracts)
        order_price = self._price_cap
        order_size = stake_amount / order_price
        
        logger.info(
            "Placing live order",
            token_id=token_id[:16] + "...",
            side="BUY",  # Always BUY the predicted outcome
            price=order_price,
            size=order_size,
            stake=stake_amount,
        )
        
        # Get auth headers
        auth_headers = self._signer.generate_auth_headers()
        
        # Place the order
        from src.adapters.polymarket.clob_client import OrderStatus
        
        result = await self._clob_client.place_limit_order(
            token_id=token_id,
            side="BUY",
            price=order_price,
            size=order_size,
            auth_headers=auth_headers,
        )
        
        if result.error or result.status == OrderStatus.CANCELLED:
            logger.error(
                "Live order failed",
                error=result.error,
                token_id=token_id[:16] + "...",
            )
            raise TradeError(f"Order placement failed: {result.error}")
        
        # Log success
        logger.info(
            "Live order placed",
            order_id=result.order_id,
            direction=direction,
            token_id=token_id[:16] + "...",
            stake_amount=stake_amount,
            status=result.status.value,
        )
        
        # Determine fill price
        fill_price = result.filled_price if result.filled_price else order_price
        
        return result.order_id, token_id, fill_price
    
    async def check_order_status(self, order_id: str) -> tuple[FillStatus, float | None]:
        """
        Check status of an order.
        
        Args:
            order_id: Order ID to check
            
        Returns:
            Tuple of (fill_status, fill_price)
        """
        if self.is_paper_mode:
            # Paper orders are always filled immediately
            return FillStatus.FILLED, self._price_cap
        
        if not self._clob_client or not self._signer:
            logger.warning("Cannot check order status: no CLOB client/signer")
            return FillStatus.PENDING, None
        
        from src.adapters.polymarket.clob_client import OrderStatus
        
        auth_headers = self._signer.generate_auth_headers()
        result = await self._clob_client.get_order_status(order_id, auth_headers)
        
        # Map CLOB status to FillStatus
        status_map = {
            OrderStatus.FILLED: FillStatus.FILLED,
            OrderStatus.PARTIAL: FillStatus.PARTIAL,
            OrderStatus.CANCELLED: FillStatus.CANCELLED,
            OrderStatus.EXPIRED: FillStatus.CANCELLED,
            OrderStatus.LIVE: FillStatus.PENDING,
        }
        
        fill_status = status_map.get(result.status, FillStatus.PENDING)
        return fill_status, result.filled_price
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        if self.is_paper_mode:
            logger.info("Paper order cancelled", order_id=order_id)
            return True
        
        if not self._clob_client or not self._signer:
            logger.warning("Cannot cancel order: no CLOB client/signer")
            return False
        
        auth_headers = self._signer.generate_auth_headers()
        return await self._clob_client.cancel_order(order_id, auth_headers)
    
    async def settle_trade(
        self,
        trade: Trade,
        window: MarketWindow,
        signal: Signal,
    ) -> tuple[bool, float]:
        """
        Settle a trade based on market outcome.
        
        Args:
            trade: Trade to settle
            window: Associated market window
            signal: Trading signal
            
        Returns:
            Tuple of (is_win, pnl)
            
        Raises:
            TradeError: If outcome not available
        """
        if window.outcome is None:
            raise TradeError("Market outcome not yet available")
        
        # Compare signal direction to outcome
        outcome_direction = window.outcome.upper()
        signal_direction = signal.direction.value.upper() if signal.direction else ""
        
        is_win = outcome_direction == signal_direction
        
        # Calculate PnL
        # If win: payout = stake / fill_price (approximately, simplified)
        # If loss: lose stake
        if is_win:
            fill_price = trade.fill_price or self._price_cap
            pnl = trade.stake_amount * (1 / fill_price - 1)
        else:
            pnl = -trade.stake_amount
        
        logger.info(
            "Trade settled",
            trade_id=trade.id,
            signal_direction=signal_direction,
            outcome=outcome_direction,
            is_win=is_win,
            pnl=pnl,
        )
        
        return is_win, pnl
