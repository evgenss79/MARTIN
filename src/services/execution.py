"""
Execution Service for MARTIN.

Handles order placement in paper or live mode.
Default is paper mode (MG-9 safety constraint).
"""

import time
import uuid
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
    Live mode places real orders (requires implementation of signing).
    """
    
    def __init__(
        self,
        mode: str = "paper",
        base_stake_amount: float = 10.0,
        price_cap: float = 0.55,
    ):
        """
        Initialize Execution Service.
        
        Args:
            mode: Execution mode ("paper" or "live")
            base_stake_amount: Default stake amount in USDC
            price_cap: Price cap for orders
        """
        self._mode = mode
        self._base_stake = base_stake_amount
        self._price_cap = price_cap
        
        if mode == "live":
            logger.warning(
                "LIVE execution mode enabled - real orders will be placed. "
                "Ensure credentials are configured."
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
        
        NOTE: This is a placeholder. Real implementation requires:
        - Polymarket API credentials
        - Order signing logic
        - Order placement and confirmation
        
        Args:
            window: Market window
            signal: Trading signal
            token_id: Token ID
            direction: Trade direction
            stake_amount: Stake amount
            
        Returns:
            Tuple of (order_id, token_id, fill_price)
            
        Raises:
            TradeError: If live trading not implemented
        """
        # TODO: Implement live trading when credentials are available
        # This requires:
        # 1. API key authentication
        # 2. Order signing with private key
        # 3. Order placement via CLOB API
        # 4. Order status monitoring
        # 5. Fill confirmation
        
        logger.error(
            "Live trading not fully implemented",
            direction=direction,
            stake_amount=stake_amount,
        )
        
        raise TradeError(
            "Live trading requires API credentials and signing implementation. "
            "Set execution.mode='paper' in config for simulation."
        )
    
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
        
        # TODO: Implement live order status check
        return FillStatus.PENDING, None
    
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
