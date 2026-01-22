"""
Technical Analysis Engine for MARTIN.

Implements EMA, ADX, signal detection and quality calculation
according to the exact specification.
"""

from dataclasses import dataclass
from typing import Any

from src.adapters.polymarket.binance_client import Candle
from src.domain.enums import Direction
from src.domain.models import QualityBreakdown
from src.common.logging import get_logger
from src.common.exceptions import TAError

logger = get_logger(__name__)


@dataclass
class SignalResult:
    """Result of signal detection."""
    direction: Direction
    signal_ts: int
    signal_price: float
    anchor_bar_ts: int
    anchor_price: float
    signal_bar_index: int


def compute_ema(values: list[float], period: int) -> list[float]:
    """
    Compute Exponential Moving Average.
    
    Args:
        values: List of price values
        period: EMA period
        
    Returns:
        List of EMA values (same length as input, with leading NaN-equivalents as 0)
    """
    if not values or period <= 0:
        return []
    
    if len(values) < period:
        return [0.0] * len(values)
    
    ema: list[float] = []
    multiplier = 2.0 / (period + 1)
    
    # First EMA is SMA of first 'period' values
    sma = sum(values[:period]) / period
    ema = [0.0] * (period - 1) + [sma]
    
    # Calculate subsequent EMAs
    for i in range(period, len(values)):
        prev_ema = ema[-1]
        current_ema = (values[i] - prev_ema) * multiplier + prev_ema
        ema.append(current_ema)
    
    return ema


def compute_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """
    Compute Average Directional Index (ADX).
    
    Uses Wilder's smoothing method as per standard ADX calculation.
    
    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        period: ADX period
        
    Returns:
        List of ADX values
    """
    n = len(closes)
    if n < period * 2:
        return [0.0] * n
    
    # Calculate True Range, +DM, -DM
    tr_list: list[float] = []
    plus_dm_list: list[float] = []
    minus_dm_list: list[float] = []
    
    for i in range(1, n):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]
        prev_high = highs[i - 1]
        prev_low = lows[i - 1]
        
        # True Range
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        tr_list.append(tr)
        
        # +DM and -DM
        up_move = high - prev_high
        down_move = prev_low - low
        
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0
        
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    
    # Add leading zero for alignment
    tr_list = [0.0] + tr_list
    plus_dm_list = [0.0] + plus_dm_list
    minus_dm_list = [0.0] + minus_dm_list
    
    # Wilder's smoothing for ATR, +DM, -DM
    def wilder_smooth(values: list[float], period: int) -> list[float]:
        result = [0.0] * len(values)
        if len(values) < period:
            return result
        
        # First smoothed value is sum of first period values
        first_sum = sum(values[1:period + 1])
        result[period] = first_sum
        
        # Subsequent values use Wilder's smoothing
        for i in range(period + 1, len(values)):
            result[i] = result[i - 1] - (result[i - 1] / period) + values[i]
        
        return result
    
    atr = wilder_smooth(tr_list, period)
    smoothed_plus_dm = wilder_smooth(plus_dm_list, period)
    smoothed_minus_dm = wilder_smooth(minus_dm_list, period)
    
    # Calculate +DI and -DI
    plus_di: list[float] = [0.0] * n
    minus_di: list[float] = [0.0] * n
    
    for i in range(period, n):
        if atr[i] != 0:
            plus_di[i] = 100 * smoothed_plus_dm[i] / atr[i]
            minus_di[i] = 100 * smoothed_minus_dm[i] / atr[i]
    
    # Calculate DX
    dx: list[float] = [0.0] * n
    for i in range(period, n):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum != 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum
    
    # Calculate ADX using Wilder's smoothing on DX
    adx: list[float] = [0.0] * n
    
    # First ADX is average of first period DX values after they become valid
    start_idx = period * 2 - 1
    if start_idx < n:
        first_adx = sum(dx[period:start_idx + 1]) / period if period > 0 else 0
        adx[start_idx] = first_adx
        
        for i in range(start_idx + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    
    return adx


class TAEngine:
    """
    Technical Analysis Engine.
    
    Implements signal detection and quality calculation per specification:
    - EMA20 on 1m for signal detection (2-bar confirm)
    - ADX on 5m for trend strength
    - EMA50 slope on 5m for momentum
    - EMA20 on 5m for trend confirmation multiplier
    """
    
    def __init__(
        self,
        adx_period: int = 14,
        ema50_slope_bars: int = 5,
        anchor_scale: float = 10000.0,
        w_anchor: float = 0.3,
        w_adx: float = 0.4,
        w_slope: float = 0.3,
        trend_bonus: float = 1.2,
        trend_penalty: float = 0.8,
    ):
        """
        Initialize TA Engine.
        
        Args:
            adx_period: Period for ADX calculation
            ema50_slope_bars: Bars to measure EMA50 slope
            anchor_scale: Scale factor for anchor edge component
            w_anchor: Weight for anchor edge in quality
            w_adx: Weight for ADX in quality
            w_slope: Weight for slope in quality
            trend_bonus: Multiplier when trend confirms
            trend_penalty: Multiplier when trend opposes
        """
        self._adx_period = adx_period
        self._ema50_slope_bars = ema50_slope_bars
        self._anchor_scale = anchor_scale
        self._w_anchor = w_anchor
        self._w_adx = w_adx
        self._w_slope = w_slope
        self._trend_bonus = trend_bonus
        self._trend_penalty = trend_penalty
    
    def detect_signal(
        self,
        candles_1m: list[Candle],
        start_ts: int,
    ) -> SignalResult | None:
        """
        Detect trading signal from 1m candles.
        
        Signal detection rules (EMA20 on 1m with 2-bar confirm):
        - UP: low[i] <= ema20[i] AND close[i] > ema20[i] AND close[i+1] > ema20[i+1]
        - DOWN: high[i] >= ema20[i] AND close[i] < ema20[i] AND close[i+1] < ema20[i+1]
        
        Args:
            candles_1m: 1-minute candles (including warmup)
            start_ts: Window start timestamp (anchor bar is first candle >= start_ts)
            
        Returns:
            SignalResult if signal found, None otherwise
        """
        if len(candles_1m) < 22:  # Need at least 20 for EMA + 2 for signal
            logger.warning("Insufficient candles for signal detection", count=len(candles_1m))
            return None
        
        # Calculate EMA20 on close prices
        closes = [c.close for c in candles_1m]
        ema20 = compute_ema(closes, 20)
        
        # Find anchor bar (first candle with t >= start_ts)
        anchor_idx = -1
        for i, c in enumerate(candles_1m):
            if c.t >= start_ts:
                anchor_idx = i
                break
        
        if anchor_idx < 0 or anchor_idx >= len(candles_1m) - 1:
            logger.warning("Could not find anchor bar", start_ts=start_ts)
            return None
        
        anchor_bar = candles_1m[anchor_idx]
        anchor_price = anchor_bar.close
        
        logger.debug(
            "Signal detection starting",
            anchor_idx=anchor_idx,
            anchor_ts=anchor_bar.t,
            anchor_price=anchor_price,
            total_candles=len(candles_1m),
        )
        
        # Scan from anchor for signal
        for i in range(anchor_idx, len(candles_1m) - 1):
            c_i = candles_1m[i]
            c_i1 = candles_1m[i + 1]
            ema_i = ema20[i]
            ema_i1 = ema20[i + 1]
            
            # Skip if EMA not yet valid
            if ema_i == 0 or ema_i1 == 0:
                continue
            
            # Check UP signal
            if c_i.low <= ema_i and c_i.close > ema_i and c_i1.close > ema_i1:
                logger.info(
                    "UP signal detected",
                    signal_bar=i,
                    signal_ts=c_i1.t,
                    signal_price=c_i1.close,
                )
                return SignalResult(
                    direction=Direction.UP,
                    signal_ts=c_i1.t,
                    signal_price=c_i1.close,
                    anchor_bar_ts=anchor_bar.t,
                    anchor_price=anchor_price,
                    signal_bar_index=i + 1,
                )
            
            # Check DOWN signal
            if c_i.high >= ema_i and c_i.close < ema_i and c_i1.close < ema_i1:
                logger.info(
                    "DOWN signal detected",
                    signal_bar=i,
                    signal_ts=c_i1.t,
                    signal_price=c_i1.close,
                )
                return SignalResult(
                    direction=Direction.DOWN,
                    signal_ts=c_i1.t,
                    signal_price=c_i1.close,
                    anchor_bar_ts=anchor_bar.t,
                    anchor_price=anchor_price,
                    signal_bar_index=i + 1,
                )
        
        logger.info("No signal detected in window")
        return None
    
    def calculate_quality(
        self,
        signal: SignalResult,
        candles_5m: list[Candle],
    ) -> QualityBreakdown:
        """
        Calculate quality score for a signal.
        
        Quality = (W_ANCHOR*edge_component + W_ADX*q_adx + W_SLOPE*q_slope) * trend_mult
        
        Components:
        A) Anchor edge: ret_from_anchor * ANCHOR_SCALE (with penalty for counter-signal)
        B) ADX: value at idx5 (last 5m candle <= signal_ts)
        C) EMA50 slope: 1000 * abs(slope50 / close5[idx5])
        D) Trend mult: TREND_BONUS if trend confirms, TREND_PENALTY otherwise
        
        Args:
            signal: SignalResult from detect_signal
            candles_5m: 5-minute candles (including warmup)
            
        Returns:
            QualityBreakdown with all components
        """
        breakdown = QualityBreakdown(
            anchor_price=signal.anchor_price,
            signal_price=signal.signal_price,
        )
        
        # A) Anchor edge component
        ret_from_anchor = (signal.signal_price - signal.anchor_price) / signal.anchor_price
        breakdown.ret_from_anchor = ret_from_anchor
        
        edge_component = abs(ret_from_anchor) * self._anchor_scale
        
        # Apply penalty for counter-signal direction
        if signal.direction == Direction.UP and ret_from_anchor < 0:
            edge_component *= 0.25
            breakdown.edge_penalty_applied = True
        elif signal.direction == Direction.DOWN and ret_from_anchor > 0:
            edge_component *= 0.25
            breakdown.edge_penalty_applied = True
        
        breakdown.edge_component = edge_component
        
        # Find idx5 (last 5m candle <= signal_ts)
        idx5 = -1
        for i, c in enumerate(candles_5m):
            if c.t <= signal.signal_ts:
                idx5 = i
            else:
                break
        
        if idx5 < 0:
            # Use last candle if none match
            idx5 = len(candles_5m) - 1
        
        if idx5 < 0 or len(candles_5m) == 0:
            logger.warning("No 5m candles available for quality calculation")
            breakdown.final_quality = edge_component * self._w_anchor
            return breakdown
        
        # Extract price series for 5m
        highs_5m = [c.high for c in candles_5m]
        lows_5m = [c.low for c in candles_5m]
        closes_5m = [c.close for c in candles_5m]
        
        # B) ADX component
        adx_values = compute_adx(highs_5m, lows_5m, closes_5m, self._adx_period)
        adx_value = adx_values[idx5] if idx5 < len(adx_values) else 0.0
        breakdown.adx_value = adx_value
        breakdown.q_adx = adx_value
        
        # C) EMA50 slope component
        ema50 = compute_ema(closes_5m, 50)
        
        slope_idx = idx5 - self._ema50_slope_bars
        if slope_idx >= 0 and idx5 < len(ema50) and slope_idx < len(ema50):
            slope50 = ema50[idx5] - ema50[slope_idx]
            breakdown.ema50_slope = slope50
            
            close5_idx5 = closes_5m[idx5]
            if close5_idx5 != 0:
                breakdown.q_slope = 1000 * abs(slope50 / close5_idx5)
        
        # D) Trend confirmation multiplier (EMA20 on 5m)
        ema20_5m = compute_ema(closes_5m, 20)
        
        if idx5 < len(ema20_5m) and ema20_5m[idx5] != 0:
            close5_idx5 = closes_5m[idx5]
            ema20_val = ema20_5m[idx5]
            
            if signal.direction == Direction.UP:
                if close5_idx5 > ema20_val:
                    breakdown.trend_mult = self._trend_bonus
                    breakdown.trend_confirms = True
                else:
                    breakdown.trend_mult = self._trend_penalty
                    breakdown.trend_confirms = False
            else:  # DOWN
                if close5_idx5 < ema20_val:
                    breakdown.trend_mult = self._trend_bonus
                    breakdown.trend_confirms = True
                else:
                    breakdown.trend_mult = self._trend_penalty
                    breakdown.trend_confirms = False
        
        # Calculate weighted components
        breakdown.w_anchor = self._w_anchor * edge_component
        breakdown.w_adx = self._w_adx * breakdown.q_adx
        breakdown.w_slope = self._w_slope * breakdown.q_slope
        
        # Final quality
        base_quality = (
            self._w_anchor * edge_component +
            self._w_adx * breakdown.q_adx +
            self._w_slope * breakdown.q_slope
        )
        breakdown.final_quality = base_quality * breakdown.trend_mult
        
        logger.info(
            "Quality calculated",
            quality=breakdown.final_quality,
            edge=edge_component,
            adx=breakdown.q_adx,
            slope=breakdown.q_slope,
            trend_mult=breakdown.trend_mult,
        )
        
        return breakdown
