"""
CLOB API client for Polymarket price history.

Handles fetching price history for CAP check validation.
"""

import asyncio
from typing import Any

import httpx

from src.common.logging import get_logger
from src.common.exceptions import APIError, RateLimitError, TimeoutError

logger = get_logger(__name__)


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
