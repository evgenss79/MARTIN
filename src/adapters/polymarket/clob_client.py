"""
CLOB API client for Polymarket.

Handles:
- Fetching price history for CAP check validation
- Placing limit orders (live mode)
- Checking order status
- Cancelling orders

Supports both paper mode (simulation) and live mode (real orders).
"""

import asyncio
import json
import time
from typing import Any
from dataclasses import dataclass
from enum import Enum

import httpx

from src.common.logging import get_logger
from src.common.exceptions import APIError, RateLimitError, TimeoutError, TradeError

logger = get_logger(__name__)


class OrderStatus(Enum):
    """Order status from CLOB API."""
    LIVE = "LIVE"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    PARTIAL = "PARTIAL"


@dataclass
class OrderResult:
    """
    Result of order placement.
    
    Attributes:
        order_id: Exchange order ID
        status: Order status
        filled_size: Amount filled
        filled_price: Average fill price
        error: Error message if failed
    """
    order_id: str
    status: OrderStatus
    filled_size: float = 0.0
    filled_price: float | None = None
    error: str | None = None


class ClobClient:
    """
    Client for Polymarket CLOB API.
    
    Fetches price history for token IDs to validate CAP check.
    """
    
    def __init__(
        self,
        base_url: str = "https://clob.polymarket.com",
        timeout: int = 30,
        retries: int = 3,
        backoff: float = 2.0,
    ):
        """
        Initialize CLOB client.
        
        Args:
            base_url: API base URL
            timeout: Request timeout in seconds
            retries: Number of retry attempts
            backoff: Backoff multiplier for retries
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retries = retries
        self._backoff = backoff
        self._client: httpx.AsyncClient | None = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"Accept": "application/json"},
            )
        return self._client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """
        Make HTTP request with retry logic.
        
        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            
        Returns:
            JSON response data
        """
        client = await self._get_client()
        url = f"{self._base_url}{path}"
        
        last_error: Exception | None = None
        
        for attempt in range(self._retries + 1):
            try:
                response = await client.request(method, url, params=params)
                
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(
                        "Rate limited by CLOB API",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    if attempt < self._retries:
                        await asyncio.sleep(retry_after)
                        continue
                    raise RateLimitError(retry_after=retry_after)
                
                if response.status_code >= 400:
                    raise APIError(
                        f"CLOB API error: {response.status_code}",
                        status_code=response.status_code,
                        response=response.text,
                    )
                
                return response.json()
                
            except httpx.TimeoutException as e:
                last_error = TimeoutError(f"Request timeout: {e}")
                logger.warning(
                    "CLOB API timeout",
                    attempt=attempt + 1,
                    path=path,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff ** attempt)
                    continue
                    
            except httpx.HTTPError as e:
                last_error = APIError(f"HTTP error: {e}")
                logger.warning(
                    "CLOB API HTTP error",
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff ** attempt)
                    continue
        
        if last_error:
            raise last_error
        raise APIError("Request failed after all retries")
    
    async def get_prices_history(
        self,
        token_id: str,
        start_ts: int,
        end_ts: int,
    ) -> list[dict[str, Any]]:
        """
        Get price history for a token.
        
        Args:
            token_id: Token ID to fetch prices for
            start_ts: Start timestamp (unix seconds)
            end_ts: End timestamp (unix seconds)
            
        Returns:
            List of price data points with timestamp and price
        """
        params = {
            "market": token_id,
            "startTs": start_ts,
            "endTs": end_ts,
        }
        
        logger.debug(
            "Fetching price history",
            token_id=token_id[:16] + "...",
            start_ts=start_ts,
            end_ts=end_ts,
        )
        
        response = await self._request("GET", "/prices-history", params=params)
        
        # Response should be a list of price points
        prices = response if isinstance(response, list) else response.get("history", [])
        
        logger.info(
            "Fetched price history",
            token_id=token_id[:16] + "...",
            price_points=len(prices),
        )
        
        return prices
    
    async def get_prices_in_range(
        self,
        token_id: str,
        start_ts: int,
        end_ts: int,
    ) -> list[tuple[int, float]]:
        """
        Get price history as (timestamp, price) tuples.
        
        This is a convenience method that normalizes the API response
        into a consistent format for CAP check processing.
        
        Args:
            token_id: Token ID to fetch prices for
            start_ts: Start timestamp (unix seconds)
            end_ts: End timestamp (unix seconds)
            
        Returns:
            List of (timestamp, price) tuples sorted by timestamp
        """
        raw_prices = await self.get_prices_history(token_id, start_ts, end_ts)
        
        prices: list[tuple[int, float]] = []
        
        for point in raw_prices:
            # Handle various response formats
            if isinstance(point, dict):
                ts = point.get("t") or point.get("timestamp") or point.get("ts")
                price = point.get("p") or point.get("price")
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                ts, price = point[0], point[1]
            else:
                continue
            
            if ts is not None and price is not None:
                # Normalize timestamp to seconds
                if ts > 1e12:
                    ts = int(ts / 1000)
                prices.append((int(ts), float(price)))
        
        # Sort by timestamp
        prices.sort(key=lambda x: x[0])
        
        return prices
    
    # =========================================================================
    # Order Placement Methods (Live Mode)
    # =========================================================================
    
    async def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        auth_headers: dict[str, str],
    ) -> OrderResult:
        """
        Place a limit order on the CLOB.
        
        Args:
            token_id: Token ID to trade
            side: "BUY" or "SELL"
            price: Order price (0.0 to 1.0)
            size: Order size in contracts
            auth_headers: Authentication headers from signer
            
        Returns:
            OrderResult with order details
            
        Raises:
            TradeError: If order placement fails
        """
        order_data = {
            "tokenId": token_id,
            "side": side,
            "price": str(price),
            "size": str(size),
            "type": "LIMIT",
            "timeInForce": "GTC",  # Good Till Cancelled
        }
        
        logger.info(
            "Placing limit order",
            token_id=token_id[:16] + "...",
            side=side,
            price=price,
            size=size,
        )
        
        try:
            response = await self._request_with_auth(
                "POST",
                "/order",
                json_data=order_data,
                auth_headers=auth_headers,
            )
            
            order_id = response.get("id") or response.get("orderId", "")
            status_str = response.get("status", "LIVE")
            
            result = OrderResult(
                order_id=order_id,
                status=OrderStatus(status_str),
                filled_size=float(response.get("filledSize", 0)),
                filled_price=float(response.get("avgPrice")) if response.get("avgPrice") else None,
            )
            
            logger.info(
                "Order placed successfully",
                order_id=order_id,
                status=status_str,
            )
            
            return result
            
        except APIError as e:
            logger.error("Order placement failed", error=str(e))
            return OrderResult(
                order_id="",
                status=OrderStatus.CANCELLED,
                error=str(e),
            )
    
    async def get_order_status(
        self,
        order_id: str,
        auth_headers: dict[str, str],
    ) -> OrderResult:
        """
        Get the status of an order.
        
        Args:
            order_id: Order ID to check
            auth_headers: Authentication headers
            
        Returns:
            OrderResult with current status
        """
        try:
            response = await self._request_with_auth(
                "GET",
                f"/order/{order_id}",
                auth_headers=auth_headers,
            )
            
            status_str = response.get("status", "LIVE")
            
            return OrderResult(
                order_id=order_id,
                status=OrderStatus(status_str),
                filled_size=float(response.get("filledSize", 0)),
                filled_price=float(response.get("avgPrice")) if response.get("avgPrice") else None,
            )
            
        except APIError as e:
            logger.error("Failed to get order status", order_id=order_id, error=str(e))
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.CANCELLED,
                error=str(e),
            )
    
    async def cancel_order(
        self,
        order_id: str,
        auth_headers: dict[str, str],
    ) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            auth_headers: Authentication headers
            
        Returns:
            True if cancelled successfully
        """
        try:
            await self._request_with_auth(
                "DELETE",
                f"/order/{order_id}",
                auth_headers=auth_headers,
            )
            
            logger.info("Order cancelled", order_id=order_id)
            return True
            
        except APIError as e:
            logger.error("Failed to cancel order", order_id=order_id, error=str(e))
            return False
    
    async def get_open_orders(
        self,
        auth_headers: dict[str, str],
        token_id: str | None = None,
    ) -> list[OrderResult]:
        """
        Get all open orders.
        
        Args:
            auth_headers: Authentication headers
            token_id: Optional filter by token ID
            
        Returns:
            List of open orders
        """
        params = {}
        if token_id:
            params["tokenId"] = token_id
        
        try:
            response = await self._request_with_auth(
                "GET",
                "/orders",
                params=params,
                auth_headers=auth_headers,
            )
            
            orders = response if isinstance(response, list) else response.get("orders", [])
            
            return [
                OrderResult(
                    order_id=o.get("id", ""),
                    status=OrderStatus(o.get("status", "LIVE")),
                    filled_size=float(o.get("filledSize", 0)),
                    filled_price=float(o.get("avgPrice")) if o.get("avgPrice") else None,
                )
                for o in orders
            ]
            
        except APIError as e:
            logger.error("Failed to get open orders", error=str(e))
            return []
    
    async def _request_with_auth(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        auth_headers: dict[str, str] | None = None,
    ) -> Any:
        """
        Make authenticated HTTP request.
        
        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            json_data: JSON body data
            auth_headers: Authentication headers
            
        Returns:
            JSON response data
        """
        client = await self._get_client()
        url = f"{self._base_url}{path}"
        
        headers = dict(auth_headers or {})
        headers["Content-Type"] = "application/json"
        
        body = json.dumps(json_data) if json_data else None
        
        last_error: Exception | None = None
        
        for attempt in range(self._retries + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    content=body,
                    headers=headers,
                )
                
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(
                        "Rate limited by CLOB API",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    if attempt < self._retries:
                        await asyncio.sleep(retry_after)
                        continue
                    raise RateLimitError(retry_after=retry_after)
                
                if response.status_code >= 400:
                    raise APIError(
                        f"CLOB API error: {response.status_code}",
                        status_code=response.status_code,
                        response=response.text,
                    )
                
                return response.json() if response.text else {}
                
            except httpx.TimeoutException as e:
                last_error = TimeoutError(f"Request timeout: {e}")
                logger.warning(
                    "CLOB API timeout",
                    attempt=attempt + 1,
                    path=path,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff ** attempt)
                    continue
                    
            except httpx.HTTPError as e:
                last_error = APIError(f"HTTP error: {e}")
                logger.warning(
                    "CLOB API HTTP error",
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff ** attempt)
                    continue
        
        if last_error:
            raise last_error
        raise APIError("Request failed after all retries")
