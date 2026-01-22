"""
Gamma API client for Polymarket market discovery.

Handles discovery of hourly BTC/ETH Up or Down markets.

DISCOVERY MODEL (Event-Driven):
- Gamma returns a list of EVENTS
- Each event contains one or more MARKETS
- Filtering must be applied at MARKET level, not EVENT level

MARKET FILTERING RULES:
- A market is eligible if its title or question contains (case-insensitive):
  - "up or down"
  - "up/down"  
  - "updown"
"""

import asyncio
import re
from typing import Any
from datetime import datetime, timezone

import httpx

from src.common.logging import get_logger
from src.common.exceptions import APIError, RateLimitError, TimeoutError
from src.domain.models import MarketWindow

logger = get_logger(__name__)

# Patterns to match "up or down" market titles
UP_OR_DOWN_PATTERNS = [
    re.compile(r"up\s+or\s+down", re.IGNORECASE),  # "up or down"
    re.compile(r"up/down", re.IGNORECASE),          # "up/down"
    re.compile(r"updown", re.IGNORECASE),           # "updown"
]


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
        recurrence: str | None = None,
        keep_closed: bool = True,
        limit: int = 100,
        page: int = 1,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Search for markets matching query.
        
        The Gamma API returns EVENTS with nested MARKETS. This method returns both.
        
        Args:
            query: Search query (e.g., "BTC up or down")
            recurrence: Market recurrence type ("hourly") or None for all
            keep_closed: Include closed markets
            limit: Results per page
            page: Page number
            
        Returns:
            Tuple of (events_list, all_markets_list)
            - events_list: Raw events from API
            - all_markets_list: All markets extracted from all events
        """
        params = {
            "q": query,
            "keep_closed_markets": 1 if keep_closed else 0,
            "limit_per_type": limit,
            "page": page,
            "sort": "endDate",
            "ascending": "false",
        }
        
        # Only add recurrence if specified
        if recurrence:
            params["recurrence"] = recurrence
        
        logger.debug("Searching Gamma markets", query=query, params=params)
        response = await self._request("GET", "/public-search", params=params)
        
        # CRITICAL: Gamma API returns EVENTS with nested MARKETS
        # Response structure: { "events": [...], "markets": [...], ... }
        # We need to check BOTH top-level events/markets AND nested markets within events
        
        events = response.get("events", [])
        top_level_markets = response.get("markets", [])
        
        # Extract all markets from events
        nested_markets = []
        for event in events:
            event_markets = event.get("markets", [])
            for market in event_markets:
                # Add event-level info to market for fallback timestamp handling
                if "endDate" not in market and "endDate" in event:
                    market["_event_end_date"] = event.get("endDate")
                if "startDate" not in market and "startDate" in event:
                    market["_event_start_date"] = event.get("startDate")
                # Add event title for context
                market["_event_title"] = event.get("title", "")
                nested_markets.append(market)
        
        # Combine top-level markets and nested markets
        all_markets = top_level_markets + nested_markets
        
        logger.info(
            "Gamma search results",
            query=query,
            events_count=len(events),
            top_level_markets=len(top_level_markets),
            nested_markets=len(nested_markets),
            total_markets=len(all_markets),
        )
        
        return events, all_markets
    
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
        forward_horizon_seconds: int = 7200,  # Look 2 hours ahead
        grace_period_seconds: int = 300,  # 5 minute grace period for recently expired
    ) -> list[MarketWindow]:
        """
        Discover active hourly markets for specified assets.
        
        Discovery is EVENT-DRIVEN:
        - Gamma returns events[] with nested markets[]
        - Filtering is applied at MARKET level, not event level
        
        MARKET FILTERING RULES:
        - Market title or question must contain "up or down", "up/down", or "updown"
        - Market must be for the specified asset
        
        TIME WINDOW HANDLING:
        - Derive end timestamp from available fields (endDate, closeTime, resolvedAt)
        - Fall back to event-level timestamp if market-level is missing
        - Apply grace periods and forward horizons (configurable)
        
        Args:
            assets: List of asset symbols (e.g., ["BTC", "ETH"])
            current_ts: Current timestamp (for filtering expired markets)
            forward_horizon_seconds: How far ahead to look (default 2 hours)
            grace_period_seconds: Grace period for recently expired (default 5 min)
            
        Returns:
            List of MarketWindow objects for active markets
        """
        if current_ts is None:
            current_ts = int(datetime.now(timezone.utc).timestamp())
        
        windows: list[MarketWindow] = []
        
        # Diagnostic counters
        total_events_scanned = 0
        total_markets_scanned = 0
        title_matches_before_time = 0
        title_matches_after_time = 0
        
        for asset in assets:
            asset_upper = asset.upper()
            
            # Search strategies - try multiple query approaches
            queries_to_try = [
                f"{asset} up or down",
                f"{asset_upper} up or down",
            ]
            
            # Add full names as fallback
            asset_name_map = {
                "BTC": "Bitcoin",
                "ETH": "Ethereum",
            }
            if asset_upper in asset_name_map:
                queries_to_try.append(f"{asset_name_map[asset_upper]} up or down")
            
            # Also try a broader search without "up or down" in query
            queries_to_try.append(asset_upper)
            
            for query in queries_to_try:
                logger.debug("Trying Gamma query", asset=asset, query=query)
                
                # Search with pagination
                all_events = []
                all_markets = []
                page = 1
                max_pages = 5  # Safety limit
                
                while page <= max_pages:
                    # Try with recurrence=hourly first, then without
                    for recurrence in ["hourly", None]:
                        try:
                            events, markets = await self.search_markets(
                                query=query,
                                recurrence=recurrence,
                                limit=100,
                                page=page,
                            )
                            
                            all_events.extend(events)
                            all_markets.extend(markets)
                            
                            # If we got results with recurrence filter, use them
                            if markets:
                                break
                                
                        except Exception as e:
                            logger.warning("Gamma search failed", query=query, recurrence=recurrence, error=str(e))
                    
                    # Check if we need more pages
                    if len(markets) < 100:
                        break
                    page += 1
                
                total_events_scanned += len(all_events)
                total_markets_scanned += len(all_markets)
                
                # Log sample results for debugging
                if all_markets:
                    sample_titles = []
                    for m in all_markets[:5]:
                        title = m.get("title") or m.get("question") or m.get("slug", "unknown")
                        sample_titles.append(title[:80])
                    logger.debug(
                        "Gamma query returned markets",
                        query=query,
                        count=len(all_markets),
                        sample_titles=sample_titles,
                    )
                
                # Filter markets at MARKET level
                for market_data in all_markets:
                    # Check if market title/question matches "up or down" pattern
                    title = market_data.get("title", "") or ""
                    question = market_data.get("question", "") or ""
                    event_title = market_data.get("_event_title", "") or ""
                    
                    combined_text = f"{title} {question} {event_title}"
                    
                    # Check for asset match
                    if not self._market_matches_asset(combined_text, asset_upper, asset_name_map.get(asset_upper)):
                        continue
                    
                    # Check for up/down pattern match
                    if not self._is_up_or_down_market(combined_text):
                        continue
                    
                    title_matches_before_time += 1
                    
                    try:
                        window = self._parse_market(market_data, asset_upper)
                        
                        if window is None:
                            continue
                        
                        # Time filter with grace period and forward horizon
                        min_end_ts = current_ts - grace_period_seconds
                        max_end_ts = current_ts + forward_horizon_seconds
                        
                        # Accept if end_ts is within our window
                        # (not too far in the past, not too far in the future)
                        if window.end_ts >= min_end_ts:
                            # Check for duplicates by slug
                            if not any(w.slug == window.slug for w in windows):
                                windows.append(window)
                                title_matches_after_time += 1
                                logger.info(
                                    "Discovered market",
                                    asset=asset_upper,
                                    slug=window.slug,
                                    start_ts=window.start_ts,
                                    end_ts=window.end_ts,
                                    time_remaining=window.end_ts - current_ts,
                                    title=title[:60],
                                )
                        else:
                            logger.debug(
                                "Market expired",
                                slug=window.slug,
                                end_ts=window.end_ts,
                                current_ts=current_ts,
                            )
                                
                    except Exception as e:
                        logger.warning(
                            "Failed to parse market",
                            error=str(e),
                            market_id=market_data.get("id"),
                            title=title[:60] if title else "unknown",
                        )
                
                # If we found markets with this query, don't try fallbacks
                if windows:
                    break
        
        # Summary logging
        logger.info(
            "Gamma discovery complete",
            assets=assets,
            events_scanned=total_events_scanned,
            markets_scanned=total_markets_scanned,
            title_matches_before_time_filter=title_matches_before_time,
            markets_after_time_filter=title_matches_after_time,
            final_windows=len(windows),
        )
        
        if not windows:
            logger.warning(
                "No hourly markets discovered",
                assets=assets,
                total_events=total_events_scanned,
                total_markets=total_markets_scanned,
                hint="Check Gamma API response structure or filter criteria"
            )
        
        return windows
    
    def _is_up_or_down_market(self, text: str) -> bool:
        """
        Check if text matches "up or down" pattern.
        
        Matches:
        - "up or down" (case-insensitive)
        - "up/down"
        - "updown"
        """
        for pattern in UP_OR_DOWN_PATTERNS:
            if pattern.search(text):
                return True
        return False
    
    def _market_matches_asset(self, text: str, asset_symbol: str, asset_name: str | None) -> bool:
        """
        Check if market text contains the asset symbol or name.
        
        Args:
            text: Market title/question/event title
            asset_symbol: Asset symbol (e.g., "BTC")
            asset_name: Full asset name (e.g., "Bitcoin")
            
        Returns:
            True if asset is mentioned in the text
        """
        text_upper = text.upper()
        
        if asset_symbol in text_upper:
            return True
        
        if asset_name and asset_name.upper() in text_upper:
            return True
        
        return False
    
    def _parse_market(self, data: dict[str, Any], asset: str) -> MarketWindow | None:
        """
        Parse market data into MarketWindow.
        
        Handles timestamp fallback:
        - First try market-level fields (endDate, closeTime)
        - Fall back to event-level timestamps if available (_event_end_date)
        
        Args:
            data: Raw market data from API
            asset: Asset symbol
            
        Returns:
            MarketWindow or None if parsing fails
        """
        # Extract required fields
        slug = data.get("slug", "") or data.get("id", "")
        condition_id = data.get("conditionId", "") or data.get("condition_id", "")
        
        # Parse timestamps with fallback chain
        # Market-level: endDate, closeTime, resolvedAt
        # Event-level fallback: _event_end_date
        end_ts = (
            self._parse_timestamp(data.get("endDate")) or
            self._parse_timestamp(data.get("closeTime")) or
            self._parse_timestamp(data.get("resolvedAt")) or
            self._parse_timestamp(data.get("_event_end_date")) or
            0
        )
        
        # Start timestamp with fallback
        start_ts = (
            self._parse_timestamp(data.get("startDate")) or
            self._parse_timestamp(data.get("createdAt")) or
            self._parse_timestamp(data.get("_event_start_date")) or
            0
        )
        
        if not slug:
            logger.debug("Market missing slug", data_keys=list(data.keys())[:10])
            return None
        
        if not condition_id:
            logger.debug("Market missing conditionId", slug=slug)
            # Don't fail - we can still use the market if we have token IDs
        
        if end_ts == 0:
            logger.debug("Market missing end timestamp", slug=slug)
            return None
        
        # Parse tokens for UP and DOWN outcomes
        up_token_id, down_token_id = self._extract_token_ids(data)
        
        if not up_token_id or not down_token_id:
            logger.warning(
                "Could not determine token IDs",
                slug=slug,
                outcomes=data.get("outcomes"),
                tokens_count=len(data.get("tokens", [])),
            )
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
    
    def _extract_token_ids(self, data: dict[str, Any]) -> tuple[str, str]:
        """
        Extract UP and DOWN token IDs from market data.
        
        Tries multiple field locations:
        1. tokens[] array with outcome field
        2. outcomes[] + clobTokenIds[] arrays
        3. outcomePrices with token mapping
        
        Returns:
            Tuple of (up_token_id, down_token_id)
        """
        up_token_id = ""
        down_token_id = ""
        
        # Method 1: tokens array
        tokens = data.get("tokens", [])
        for token in tokens:
            outcome = str(token.get("outcome", "")).upper()
            token_id = token.get("token_id", "") or token.get("tokenId", "")
            
            if "UP" in outcome or "YES" in outcome:
                up_token_id = token_id
            elif "DOWN" in outcome or "NO" in outcome:
                down_token_id = token_id
        
        if up_token_id and down_token_id:
            return up_token_id, down_token_id
        
        # Method 2: outcomes + clobTokenIds
        outcomes = data.get("outcomes", [])
        clob_token_ids = data.get("clobTokenIds", [])
        
        # Handle outcomes as string (JSON) or list
        if isinstance(outcomes, str):
            try:
                import json
                outcomes = json.loads(outcomes)
            except:
                outcomes = []
        
        # Handle clobTokenIds as string (JSON) or list
        if isinstance(clob_token_ids, str):
            try:
                import json
                clob_token_ids = json.loads(clob_token_ids)
            except:
                clob_token_ids = []
        
        for i, outcome in enumerate(outcomes):
            if i < len(clob_token_ids):
                outcome_upper = str(outcome).upper()
                if "UP" in outcome_upper or "YES" in outcome_upper:
                    up_token_id = clob_token_ids[i]
                elif "DOWN" in outcome_upper or "NO" in outcome_upper:
                    down_token_id = clob_token_ids[i]
        
        return up_token_id, down_token_id
    
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
