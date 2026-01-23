"""
TA Snapshot Worker for MARTIN.

Implements the PRIMARY LOOP: Continuous TA Snapshot/Cache (independent of markets).

This worker runs periodically (e.g., every 10-60s) to:
- Fetch Binance 1m and 5m candles for configured assets
- Maintain a TA snapshot cache per asset with freshness tracking
- Provide fresh candle data for SEARCHING_SIGNAL trades
"""

import time
from dataclasses import dataclass, field
from typing import Any

from src.adapters.polymarket.binance_client import BinanceClient, Candle
from src.common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TASnapshot:
    """
    TA Snapshot for an asset.
    
    Contains cached candle data and freshness information.
    """
    asset: str
    ts: int  # Timestamp when snapshot was taken
    candles_1m: list[Candle] = field(default_factory=list)
    candles_5m: list[Candle] = field(default_factory=list)
    freshness: float = 0.0  # Seconds since last update
    
    @property
    def candles_1m_count(self) -> int:
        return len(self.candles_1m)
    
    @property
    def candles_5m_count(self) -> int:
        return len(self.candles_5m)
    
    def is_stale(self, max_age_seconds: int = 120) -> bool:
        """Check if snapshot is stale (older than max_age_seconds)."""
        current_ts = int(time.time())
        return (current_ts - self.ts) > max_age_seconds


class TASnapshotCache:
    """
    Thread-safe cache for TA snapshots.
    
    Maintains one snapshot per asset with TTL-based eviction.
    """
    
    def __init__(self, ttl_seconds: int = 120):
        """
        Initialize cache.
        
        Args:
            ttl_seconds: Time-to-live for cached snapshots
        """
        self._cache: dict[str, TASnapshot] = {}
        self._ttl_seconds = ttl_seconds
    
    def get(self, asset: str) -> TASnapshot | None:
        """
        Get snapshot for asset.
        
        Returns None if not cached or expired.
        """
        snapshot = self._cache.get(asset)
        if snapshot is None:
            return None
        
        if snapshot.is_stale(self._ttl_seconds):
            logger.debug(
                "TA_SNAPSHOT_STALE: Cached snapshot is stale",
                asset=asset,
                age_seconds=int(time.time()) - snapshot.ts,
            )
            return None
        
        return snapshot
    
    def put(self, snapshot: TASnapshot) -> None:
        """Store snapshot in cache."""
        self._cache[snapshot.asset] = snapshot
        logger.debug(
            "TA_SNAPSHOT_CACHED: Snapshot cached",
            asset=snapshot.asset,
            candles_1m_count=snapshot.candles_1m_count,
            candles_5m_count=snapshot.candles_5m_count,
        )
    
    def invalidate(self, asset: str) -> None:
        """Remove snapshot from cache."""
        if asset in self._cache:
            del self._cache[asset]
    
    def clear(self) -> None:
        """Clear all cached snapshots."""
        self._cache.clear()
    
    def get_all_assets(self) -> list[str]:
        """Get list of all cached assets."""
        return list(self._cache.keys())


class TASnapshotWorker:
    """
    Background worker for continuous TA snapshot updates.
    
    Implements the PRIMARY LOOP architecture requirement:
    - Bot continuously maintains up-to-date TA context (indicators/derived metrics)
    - This loop runs even when no Polymarket window exists
    """
    
    DEFAULT_INTERVAL_SECONDS = 30  # Update every 30 seconds
    DEFAULT_WARMUP_SECONDS = 7200  # 2 hours of warmup data
    
    def __init__(
        self,
        binance_client: BinanceClient,
        assets: list[str],
        warmup_seconds: int = DEFAULT_WARMUP_SECONDS,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        cache_ttl_seconds: int = 120,
    ):
        """
        Initialize TA Snapshot Worker.
        
        Args:
            binance_client: Binance client for fetching candles
            assets: List of assets to track (e.g., ["BTC", "ETH"])
            warmup_seconds: Historical data window for indicator warmup
            interval_seconds: Update interval
            cache_ttl_seconds: Cache TTL for snapshots
        """
        self._binance = binance_client
        self._assets = assets
        self._warmup_seconds = warmup_seconds
        self._interval_seconds = interval_seconds
        self._cache = TASnapshotCache(ttl_seconds=cache_ttl_seconds)
        self._running = False
        self._last_update_ts = 0
    
    async def start(self) -> None:
        """Start the worker loop."""
        self._running = True
        logger.info(
            "TA_WORKER_START: TA Snapshot Worker starting",
            assets=self._assets,
            interval_seconds=self._interval_seconds,
            warmup_seconds=self._warmup_seconds,
        )
        
        while self._running:
            await self._update_all_snapshots()
            import asyncio
            await asyncio.sleep(self._interval_seconds)
    
    async def stop(self) -> None:
        """Stop the worker loop."""
        self._running = False
        logger.info("TA_WORKER_STOP: TA Snapshot Worker stopping")
    
    async def _update_all_snapshots(self) -> None:
        """Update snapshots for all configured assets."""
        current_ts = int(time.time())
        
        for asset in self._assets:
            try:
                await self._update_snapshot(asset, current_ts)
            except Exception as e:
                logger.warning(
                    "TA_SNAPSHOT_UPDATE_ERROR: Error updating snapshot",
                    asset=asset,
                    error=str(e),
                )
        
        self._last_update_ts = current_ts
    
    async def _update_snapshot(self, asset: str, current_ts: int) -> None:
        """
        Update snapshot for a single asset.
        
        Fetches 1m and 5m candles from Binance.
        """
        start_ts = current_ts - self._warmup_seconds
        
        # Fetch 1m and 5m candles concurrently
        import asyncio
        candles_1m, candles_5m = await asyncio.gather(
            self._binance.get_klines(
                asset=asset,
                interval="1m",
                start_ts=start_ts,
                end_ts=current_ts,
            ),
            self._binance.get_klines(
                asset=asset,
                interval="5m",
                start_ts=start_ts,
                end_ts=current_ts,
            ),
        )
        
        snapshot = TASnapshot(
            asset=asset,
            ts=current_ts,
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            freshness=0.0,
        )
        
        self._cache.put(snapshot)
        
        logger.info(
            "TA_SNAPSHOT_UPDATED: Asset snapshot updated",
            asset=asset,
            ts=current_ts,
            candles_1m_count=len(candles_1m),
            candles_5m_count=len(candles_5m),
            freshness=0.0,
        )
    
    def get_snapshot(self, asset: str) -> TASnapshot | None:
        """
        Get current snapshot for an asset.
        
        Returns None if not cached or stale.
        """
        snapshot = self._cache.get(asset)
        if snapshot:
            # Update freshness
            snapshot.freshness = int(time.time()) - snapshot.ts
        return snapshot
    
    def get_all_snapshots(self) -> dict[str, TASnapshot]:
        """Get all current snapshots."""
        return {
            asset: snapshot
            for asset in self._cache.get_all_assets()
            if (snapshot := self._cache.get(asset)) is not None
        }
    
    @property
    def cache(self) -> TASnapshotCache:
        """Get the snapshot cache."""
        return self._cache
