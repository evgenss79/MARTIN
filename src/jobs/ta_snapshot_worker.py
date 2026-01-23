"""
TA Snapshot Worker for MARTIN.

Implements continuous TA context maintenance (PRIMARY LOOP).
This worker maintains up-to-date candle data and TA context for configured
assets even when no Polymarket window exists.

The snapshot cache provides the data source for SEARCHING_SIGNAL trades
to re-evaluate signals each tick without unbounded candle growth.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from src.common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TASnapshot:
    """
    Snapshot of TA context for an asset.
    
    Contains cached candle data with bounded sliding window.
    Freshness tracking ensures stale data is refreshed.
    """
    asset: str
    updated_ts: int = 0
    candles_1m: list[Any] = field(default_factory=list)
    candles_5m: list[Any] = field(default_factory=list)
    freshness_seconds: int = 0
    
    @property
    def is_fresh(self) -> bool:
        """Check if snapshot is fresh enough for use."""
        now = int(time.time())
        # Consider fresh if updated within last 120 seconds
        return (now - self.updated_ts) < 120


class TASnapshotCache:
    """
    Cache for TA snapshots.
    
    Provides thread-safe access to TA context for multiple assets.
    Implements bounded sliding window to prevent unbounded memory growth.
    """
    
    # Maximum candles to retain per asset/interval
    MAX_1M_CANDLES = 240  # 4 hours of 1m data
    MAX_5M_CANDLES = 48   # 4 hours of 5m data
    
    def __init__(self):
        """Initialize empty cache."""
        self._snapshots: dict[str, TASnapshot] = {}
    
    def get(self, asset: str) -> TASnapshot | None:
        """
        Get snapshot for asset.
        
        Args:
            asset: Asset symbol (BTC, ETH)
            
        Returns:
            TASnapshot or None if not cached
        """
        return self._snapshots.get(asset)
    
    def update(
        self,
        asset: str,
        candles_1m: list[Any],
        candles_5m: list[Any],
    ) -> TASnapshot:
        """
        Update snapshot for asset.
        
        Applies bounded sliding window to prevent unbounded growth.
        
        Args:
            asset: Asset symbol
            candles_1m: 1-minute candle data
            candles_5m: 5-minute candle data
            
        Returns:
            Updated TASnapshot
        """
        now = int(time.time())
        
        # Apply sliding window bounds
        bounded_1m = candles_1m[-self.MAX_1M_CANDLES:] if len(candles_1m) > self.MAX_1M_CANDLES else candles_1m
        bounded_5m = candles_5m[-self.MAX_5M_CANDLES:] if len(candles_5m) > self.MAX_5M_CANDLES else candles_5m
        
        snapshot = TASnapshot(
            asset=asset,
            updated_ts=now,
            candles_1m=bounded_1m,
            candles_5m=bounded_5m,
            freshness_seconds=0,
        )
        
        self._snapshots[asset] = snapshot
        
        logger.info(
            "TA_SNAPSHOT_UPDATED: Snapshot cache updated",
            asset=asset,
            ts=now,
            candles_1m_count=len(bounded_1m),
            candles_5m_count=len(bounded_5m),
            freshness="fresh",
        )
        
        return snapshot
    
    def get_all_assets(self) -> list[str]:
        """Get list of all cached assets."""
        return list(self._snapshots.keys())
    
    def clear(self, asset: str | None = None) -> None:
        """
        Clear cache.
        
        Args:
            asset: Specific asset to clear, or None for all
        """
        if asset:
            self._snapshots.pop(asset, None)
        else:
            self._snapshots.clear()


class TASnapshotWorker:
    """
    Background worker for continuous TA snapshot maintenance.
    
    Runs independently of Polymarket windows to ensure TA context
    is always available for signal detection.
    """
    
    def __init__(
        self,
        binance_client: Any,
        assets: list[str],
        warmup_seconds: int = 7200,
        update_interval_seconds: int = 30,
    ):
        """
        Initialize TA snapshot worker.
        
        Args:
            binance_client: Binance API client for fetching candles
            assets: List of assets to track (e.g., ["BTC", "ETH"])
            warmup_seconds: Historical data to fetch (default 2 hours)
            update_interval_seconds: How often to refresh snapshots
        """
        self._binance = binance_client
        self._assets = assets
        self._warmup_seconds = warmup_seconds
        self._update_interval = update_interval_seconds
        self._cache = TASnapshotCache()
        self._running = False
    
    @property
    def cache(self) -> TASnapshotCache:
        """Access the snapshot cache."""
        return self._cache
    
    async def start(self) -> None:
        """Start the background worker loop."""
        self._running = True
        logger.info(
            "TA_WORKER_START: TA Snapshot Worker starting",
            assets=self._assets,
            update_interval=self._update_interval,
            warmup_seconds=self._warmup_seconds,
        )
        
        while self._running:
            try:
                await self._update_all_snapshots()
            except Exception as e:
                logger.exception("TA_WORKER_ERROR: Error updating snapshots", error=str(e))
            
            await asyncio.sleep(self._update_interval)
    
    async def stop(self) -> None:
        """Stop the background worker."""
        self._running = False
        logger.info("TA_WORKER_STOP: TA Snapshot Worker stopping")
    
    async def _update_all_snapshots(self) -> None:
        """Update snapshots for all configured assets."""
        current_ts = int(time.time())
        
        for asset in self._assets:
            try:
                await self._update_asset_snapshot(asset, current_ts)
            except Exception as e:
                logger.warning(
                    "TA_SNAPSHOT_ERROR: Failed to update snapshot",
                    asset=asset,
                    error=str(e),
                )
    
    async def _update_asset_snapshot(self, asset: str, current_ts: int) -> None:
        """Update snapshot for a single asset."""
        # Fetch candles (use current time as window end)
        # The warmup gives us historical context
        start_ts = current_ts - self._warmup_seconds
        
        candles_1m, candles_5m = await asyncio.gather(
            self._binance.get_klines_for_window(
                asset=asset,
                interval="1m",
                start_ts=start_ts,
                end_ts=current_ts,
                warmup_seconds=0,  # Already included in calculation
            ),
            self._binance.get_klines_for_window(
                asset=asset,
                interval="5m",
                start_ts=start_ts,
                end_ts=current_ts,
                warmup_seconds=0,
            ),
        )
        
        self._cache.update(asset, candles_1m, candles_5m)
    
    async def ensure_fresh_snapshot(self, asset: str, current_ts: int) -> TASnapshot | None:
        """
        Ensure a fresh snapshot is available for the asset.
        
        If the cached snapshot is stale, refresh it immediately.
        
        Args:
            asset: Asset symbol
            current_ts: Current timestamp
            
        Returns:
            Fresh TASnapshot or None if fetch failed
        """
        snapshot = self._cache.get(asset)
        
        if snapshot and snapshot.is_fresh:
            return snapshot
        
        # Refresh if stale or missing
        try:
            await self._update_asset_snapshot(asset, current_ts)
            return self._cache.get(asset)
        except Exception as e:
            logger.warning(
                "TA_SNAPSHOT_REFRESH_FAILED: Could not refresh snapshot",
                asset=asset,
                error=str(e),
            )
            return snapshot  # Return stale data rather than nothing
