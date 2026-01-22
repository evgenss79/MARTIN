"""
Gamma API client for Polymarket market discovery.

Handles discovery of hourly BTC/ETH Up or Down markets.
"""

import asyncio
from typing import Any
from datetime import datetime

import httpx

from src.common.logging import get_logger
from src.common.exceptions import APIError, RateLimitError, TimeoutError
from src.domain.models import MarketWindow

logger = get_logger(__name__)


class GammaClient:
    """
    Client for Polymarket Gamma API.
    
    Discovers hourly markets for specified assets.
    """
    
    def __init__(
        self,
        base_url: str = "https://gamma-api.polymarket.com",
        timeout: int = 30,
        retries: int = 3,
        backoff: float = 2.0,
    ):
        """
        Initialize Gamma client.
        
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
            method: HTTP method (GET, POST, etc.)
            path: API path
            params: Query parameters
            
        Returns:
            JSON response data
            
        Raises:
            APIError: On API errors
            RateLimitError: On rate limit (429)
            TimeoutError: On timeout
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
                        "Rate limited by Gamma API",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    if attempt < self._retries:
                        await asyncio.sleep(retry_after)
                        continue
                    raise RateLimitError(retry_after=retry_after)
                
                if response.status_code >= 400:
                    raise APIError(
                        f"Gamma API error: {response.status_code}",
                        status_code=response.status_code,
                        response=response.text,
                    )
                
                return response.json()
                
            except httpx.TimeoutException as e:
                last_error = TimeoutError(f"Request timeout: {e}")
                logger.warning(
                    "Gamma API timeout",
                    attempt=attempt + 1,
                    path=path,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff ** attempt)
                    continue
                    
            except httpx.HTTPError as e:
                last_error = APIError(f"HTTP error: {e}")
                logger.warning(
                    "Gamma API HTTP error",
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff ** attempt)
                    continue
        
        if last_error:
            raise last_error
        raise APIError("Request failed after all retries")
    
    async def search_markets(
        self,
        query: str,
        recurrence: str = "hourly",
        keep_closed: bool = True,
        limit: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Search for markets matching query.
        
        Args:
            query: Search query (e.g., "BTC", "ETH")
            recurrence: Market recurrence type ("hourly")
            keep_closed: Include closed markets
            limit: Results per page
            page: Page number
            
        Returns:
            List of market data dictionaries
        """
        params = {
            "q": query,
            "recurrence": recurrence,
            "keep_closed_markets": 1 if keep_closed else 0,
            "limit_per_type": limit,
            "page": page,
            "sort": "endDate",
            "ascending": "false",
        }
        
        logger.debug("Searching Gamma markets", query=query, params=params)
        response = await self._request("GET", "/public-search", params=params)
        
        # Extract markets from response
        markets = response.get("markets", [])
        logger.info("Found markets from Gamma search", count=len(markets), query=query)
        
        return markets
    
    async def get_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        """
        Get market details by slug.
        
        Args:
            slug: Market slug identifier
            
        Returns:
            Market data dictionary or None if not found
        """
        logger.debug("Fetching market by slug", slug=slug)
        
        try:
            response = await self._request("GET", "/markets", params={"slug": slug})
            
            # Response can be a list or single object
            if isinstance(response, list):
                return response[0] if response else None
            return response
            
        except APIError as e:
            if e.status_code == 404:
                return None
            raise
    
    async def discover_hourly_markets(
        self,
        assets: list[str],
        current_ts: int | None = None,
    ) -> list[MarketWindow]:
        """
        Discover active hourly markets for specified assets.
        
        Args:
            assets: List of asset symbols (e.g., ["BTC", "ETH"])
            current_ts: Current timestamp (for filtering expired markets)
            
        Returns:
            List of MarketWindow objects for active markets
        """
        if current_ts is None:
            current_ts = int(datetime.utcnow().timestamp())
        
        windows: list[MarketWindow] = []
        
        for asset in assets:
            # Search for up/down markets with recurrence=hourly (passed to search_markets)
            # NOTE: Do NOT include "hourly" in query string - it reduces results
            # recurrence=hourly is already a separate query parameter
            queries_to_try = [
                f"{asset} up or down",  # Primary query
                f"{asset.replace('BTC', 'Bitcoin').replace('ETH', 'Ethereum')} up or down",  # Fallback
            ]
            
            for query in queries_to_try:
                markets = await self.search_markets(query, recurrence="hourly")
                
                # Log top results for debugging
                if markets:
                    top_titles = [m.get("title", m.get("slug", "unknown"))[:60] for m in markets[:5]]
                    logger.debug(
                        "Gamma search results",
                        query=query,
                        count=len(markets),
                        top_titles=top_titles,
                    )
                else:
                    logger.debug("Gamma search returned 0 results", query=query)
                
                for market_data in markets:
                    try:
                        window = self._parse_market(market_data, asset)
                        
                        # Skip expired markets and duplicates
                        if window and window.end_ts > current_ts:
                            # Check if not already in list (by slug)
                            if not any(w.slug == window.slug for w in windows):
                                windows.append(window)
                                logger.info(
                                    "Discovered market",
                                    asset=asset,
                                    slug=window.slug,
                                    start_ts=window.start_ts,
                                    end_ts=window.end_ts,
                                )
                    except Exception as e:
                        logger.warning(
                            "Failed to parse market",
                            error=str(e),
                            market_id=market_data.get("id"),
                        )
                
                # If we found markets with primary query, no need to try fallback
                if windows:
                    break
        
        if not windows:
            logger.warning(
                "No hourly markets discovered",
                assets=assets,
                hint="Check Gamma API or try different query terms"
            )
        
        return windows
    
    def _parse_market(self, data: dict[str, Any], asset: str) -> MarketWindow | None:
        """
        Parse market data into MarketWindow.
        
        Args:
            data: Raw market data from API
            asset: Asset symbol
            
        Returns:
            MarketWindow or None if parsing fails
        """
        # Extract required fields
        slug = data.get("slug", "")
        condition_id = data.get("conditionId", "")
        
        # Parse timestamps
        start_ts = self._parse_timestamp(data.get("startDate") or data.get("createdAt"))
        end_ts = self._parse_timestamp(data.get("endDate"))
        
        if not all([slug, condition_id, start_ts, end_ts]):
            return None
        
        # Parse tokens for UP and DOWN outcomes
        tokens = data.get("tokens", [])
        up_token_id = ""
        down_token_id = ""
        
        for token in tokens:
            outcome = token.get("outcome", "").upper()
            token_id = token.get("token_id", "")
            
            if "UP" in outcome or "YES" in outcome:
                up_token_id = token_id
            elif "DOWN" in outcome or "NO" in outcome:
                down_token_id = token_id
        
        # Fallback: check outcomes field
        if not up_token_id or not down_token_id:
            outcomes = data.get("outcomes", [])
            clob_token_ids = data.get("clobTokenIds", [])
            
            for i, outcome in enumerate(outcomes):
                if i < len(clob_token_ids):
                    outcome_upper = outcome.upper()
                    if "UP" in outcome_upper or "YES" in outcome_upper:
                        up_token_id = clob_token_ids[i]
                    elif "DOWN" in outcome_upper or "NO" in outcome_upper:
                        down_token_id = clob_token_ids[i]
        
        if not up_token_id or not down_token_id:
            logger.warning("Could not determine token IDs", slug=slug)
            return None
        
        return MarketWindow(
            asset=asset.upper(),
            slug=slug,
            condition_id=condition_id,
            up_token_id=up_token_id,
            down_token_id=down_token_id,
            start_ts=start_ts,
            end_ts=end_ts,
        )
    
    @staticmethod
    def _parse_timestamp(value: Any) -> int:
        """Parse timestamp from various formats."""
        if value is None:
            return 0
        
        if isinstance(value, (int, float)):
            # Unix timestamp (seconds or milliseconds)
            if value > 1e12:  # Milliseconds
                return int(value / 1000)
            return int(value)
        
        if isinstance(value, str):
            # ISO format string
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return int(dt.timestamp())
            except ValueError:
                return 0
        
        return 0
