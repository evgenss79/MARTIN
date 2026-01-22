"""
Binance API client for market data.

Handles fetching candlestick (kline) data for technical analysis.
"""

import asyncio
from typing import Any
from dataclasses import dataclass
from datetime import datetime

import httpx

from src.common.logging import get_logger
from src.common.exceptions import APIError, RateLimitError, TimeoutError

logger = get_logger(__name__)


@dataclass
class Candle:
    """
    Candlestick data.
    
    Attributes:
        t: Open time (unix seconds)
        o: Open price
        h: High price
        l: Low price
        c: Close price
        v: Volume
        close_time: Close time (unix seconds)
    """
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float
    close_time: int
    
    @property
    def open(self) -> float:
        return self.o
    
    @property
    def high(self) -> float:
        return self.h
    
    @property
    def low(self) -> float:
        return self.l
    
    @property
    def close(self) -> float:
        return self.c
    
    @property
    def volume(self) -> float:
        return self.v


class BinanceClient:
    """
    Client for Binance public API.
    
    Fetches candlestick (kline) data for technical analysis.
    Implements caching to avoid redundant API calls within the same window.
    """
    
    # Asset to Binance symbol mapping
    SYMBOL_MAP = {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
    }
    
    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        timeout: int = 30,
        retries: int = 3,
        backoff: float = 2.0,
    ):
        """
        Initialize Binance client.
        
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
        
        # Cache for klines: (symbol, interval, start_ts, end_ts) -> list[Candle]
        self._cache: dict[tuple[str, str, int, int], list[Candle]] = {}
    
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
    
    def clear_cache(self) -> None:
        """Clear the klines cache."""
        self._cache.clear()
        logger.debug("Cleared Binance klines cache")
    
    def get_symbol(self, asset: str) -> str:
        """Get Binance symbol for asset."""
        return self.SYMBOL_MAP.get(asset.upper(), f"{asset.upper()}USDT")
    
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
                        "Rate limited by Binance API",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    if attempt < self._retries:
                        await asyncio.sleep(retry_after)
                        continue
                    raise RateLimitError(retry_after=retry_after)
                
                if response.status_code >= 400:
                    raise APIError(
                        f"Binance API error: {response.status_code}",
                        status_code=response.status_code,
                        response=response.text,
                    )
                
                return response.json()
                
            except httpx.TimeoutException as e:
                last_error = TimeoutError(f"Request timeout: {e}")
                logger.warning(
                    "Binance API timeout",
                    attempt=attempt + 1,
                    path=path,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff ** attempt)
                    continue
                    
            except httpx.HTTPError as e:
                last_error = APIError(f"HTTP error: {e}")
                logger.warning(
                    "Binance API HTTP error",
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff ** attempt)
                    continue
        
        if last_error:
            raise last_error
        raise APIError("Request failed after all retries")
    
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int | None = None,
        limit: int = 1000,
        use_cache: bool = True,
    ) -> list[Candle]:
        """
        Get candlestick data.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            interval: Candle interval ("1m", "5m", etc.)
            start_time: Start time in unix seconds
            end_time: End time in unix seconds (optional)
            limit: Maximum candles to return (max 1000)
            use_cache: Whether to use cached data
            
        Returns:
            List of Candle objects sorted by time
        """
        # Convert to milliseconds for API
        start_ms = start_time * 1000
        end_ms = (end_time * 1000) if end_time else None
        
        # Check cache
        cache_key = (symbol, interval, start_time, end_time or 0)
        if use_cache and cache_key in self._cache:
            logger.debug("Using cached klines", symbol=symbol, interval=interval)
            return self._cache[cache_key]
        
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ms,
            "limit": limit,
        }
        
        if end_ms:
            params["endTime"] = end_ms
        
        logger.debug(
            "Fetching klines from Binance",
            symbol=symbol,
            interval=interval,
            start_time=start_time,
        )
        
        response = await self._request("GET", "/api/v3/klines", params=params)
        
        candles: list[Candle] = []
        
        for kline in response:
            # Binance kline format:
            # [open_time, open, high, low, close, volume, close_time, ...]
            if len(kline) >= 7:
                candles.append(Candle(
                    t=int(kline[0]) // 1000,  # Convert to seconds
                    o=float(kline[1]),
                    h=float(kline[2]),
                    l=float(kline[3]),
                    c=float(kline[4]),
                    v=float(kline[5]),
                    close_time=int(kline[6]) // 1000,
                ))
        
        # Sort by time
        candles.sort(key=lambda c: c.t)
        
        # Cache the result
        if use_cache:
            self._cache[cache_key] = candles
        
        logger.info(
            "Fetched klines from Binance",
            symbol=symbol,
            interval=interval,
            candles=len(candles),
        )
        
        return candles
    
    async def get_klines_for_window(
        self,
        asset: str,
        interval: str,
        start_ts: int,
        end_ts: int,
        warmup_seconds: int = 7200,
    ) -> list[Candle]:
        """
        Get candles for a market window with warmup period.
        
        Args:
            asset: Asset symbol (e.g., "BTC")
            interval: Candle interval ("1m" or "5m")
            start_ts: Window start timestamp
            end_ts: Window end timestamp
            warmup_seconds: Extra historical data for indicator warmup
            
        Returns:
            List of Candle objects
        """
        symbol = self.get_symbol(asset)
        
        # Include warmup period
        fetch_start = start_ts - warmup_seconds
        
        # Fetch all candles (may need multiple requests for long periods)
        all_candles: list[Candle] = []
        current_start = fetch_start
        
        while current_start < end_ts:
            candles = await self.get_klines(
                symbol=symbol,
                interval=interval,
                start_time=current_start,
                end_time=end_ts,
                limit=1000,
                use_cache=True,
            )
            
            if not candles:
                break
            
            all_candles.extend(candles)
            
            # Move to next batch
            last_time = candles[-1].t
            if last_time <= current_start:
                break
            current_start = last_time + 60  # Move past last candle
            
            # Avoid rate limiting
            await asyncio.sleep(0.1)
        
        # Remove duplicates and sort
        seen_times: set[int] = set()
        unique_candles: list[Candle] = []
        for c in all_candles:
            if c.t not in seen_times:
                seen_times.add(c.t)
                unique_candles.append(c)
        
        unique_candles.sort(key=lambda c: c.t)
        
        logger.info(
            "Fetched klines for window",
            asset=asset,
            interval=interval,
            start_ts=start_ts,
            end_ts=end_ts,
            candles=len(unique_candles),
        )
        
        return unique_candles
