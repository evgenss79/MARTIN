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
    
    CANONICAL Implementation per specification:
    - EMA20 on 1m for signal detection (2-bar confirm + crossover)
    - ADX(14) on 1m for trend strength (normalized 0..1)
    - EMA50 slope over last 6 bars on 1m for momentum (normalized 0..1)
    - EMA20 on 5m for trend confirmation multiplier
    
    Quality Formula (FIXED - no configuration):
    quality = (anchor_component * 1.0 + adx_component * 0.2 + slope_component * 0.2) * trend_multiplier
    
    Trend multiplier: 1.10 (confirm), 0.70 (oppose), 1.00 (else)
    """
    
    # CANONICAL FIXED CONSTANTS (per specification - DO NOT CHANGE)
    ANCHOR_SCALE = 10000.0          # Scale factor for anchor edge
    W_ANCHOR = 1.0                  # Weight for anchor component
    W_ADX = 0.2                     # Weight for ADX component
    W_SLOPE = 0.2                   # Weight for slope component
    TREND_BONUS = 1.10              # Multiplier when trend confirms
    TREND_PENALTY = 0.70            # Multiplier when trend opposes
    TREND_NEUTRAL = 1.00            # Multiplier when neutral
    ADX_PERIOD = 14                 # ADX calculation period
    EMA50_SLOPE_BARS = 6            # Bars for EMA50 slope calculation
    
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
        
        NOTE: The parameters below are IGNORED for quality calculation.
        Quality uses FIXED canonical constants per specification.
        Parameters are retained only for backward compatibility.
        
        Args:
            adx_period: IGNORED - uses canonical ADX_PERIOD=14
            ema50_slope_bars: IGNORED - uses canonical EMA50_SLOPE_BARS=6
            anchor_scale: IGNORED - uses canonical ANCHOR_SCALE=10000.0
            w_anchor: IGNORED - uses canonical W_ANCHOR=1.0
            w_adx: IGNORED - uses canonical W_ADX=0.2
            w_slope: IGNORED - uses canonical W_SLOPE=0.2
            trend_bonus: IGNORED - uses canonical TREND_BONUS=1.10
            trend_penalty: IGNORED - uses canonical TREND_PENALTY=0.70
        """
        # Store for backward compatibility but use class constants in calculations
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
        
        CANONICAL Signal detection rules (EMA20 on 1m):
        Signal is evaluated ONLY at candle close.
        
        UP signal:
        - Close[bar-1] > EMA20 (most recent closed bar)
        - Close[bar-2] > EMA20 (prior bar)
        - Previous bar was below EMA20 (bar-3 was below, indicating crossover)
        
        DOWN signal:
        - Close[bar-1] < EMA20 (most recent closed bar)
        - Close[bar-2] < EMA20 (prior bar)
        - Previous bar was above EMA20 (bar-3 was above, indicating crossover)
        
        Args:
            candles_1m: 1-minute candles (including warmup)
            start_ts: Window start timestamp (anchor bar is first candle >= start_ts)
            
        Returns:
            SignalResult if signal found, None otherwise
        """
        if len(candles_1m) < 23:  # Need at least 20 for EMA + 3 for signal detection
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
        
        if anchor_idx < 0 or anchor_idx >= len(candles_1m) - 2:
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
        # Need at least 3 bars: bar-3 (previous), bar-2, bar-1 (most recent)
        for i in range(anchor_idx + 2, len(candles_1m)):
            # bar-1: candles_1m[i] (most recent closed bar - signal bar)
            # bar-2: candles_1m[i-1] (prior bar)
            # bar-3: candles_1m[i-2] (previous bar - for crossover detection)
            c_bar1 = candles_1m[i]      # Most recent closed bar
            c_bar2 = candles_1m[i - 1]  # Prior bar
            c_bar3 = candles_1m[i - 2]  # Previous bar (crossover detection)
            
            ema_bar1 = ema20[i]
            ema_bar2 = ema20[i - 1]
            ema_bar3 = ema20[i - 2]
            
            # Skip if EMA not yet valid
            if ema_bar1 == 0 or ema_bar2 == 0 or ema_bar3 == 0:
                continue
            
            # CANONICAL UP signal:
            # Close[bar-1] > EMA20, Close[bar-2] > EMA20, Previous bar was below EMA20
            if (c_bar1.close > ema_bar1 and 
                c_bar2.close > ema_bar2 and 
                c_bar3.close < ema_bar3):
                logger.info(
                    "UP signal detected (canonical)",
                    signal_bar=i,
                    signal_ts=c_bar1.t,
                    signal_price=c_bar1.close,
                )
                return SignalResult(
                    direction=Direction.UP,
                    signal_ts=c_bar1.t,
                    signal_price=c_bar1.close,
                    anchor_bar_ts=anchor_bar.t,
                    anchor_price=anchor_price,
                    signal_bar_index=i,
                )
            
            # CANONICAL DOWN signal:
            # Close[bar-1] < EMA20, Close[bar-2] < EMA20, Previous bar was above EMA20
            if (c_bar1.close < ema_bar1 and 
                c_bar2.close < ema_bar2 and 
                c_bar3.close > ema_bar3):
                logger.info(
                    "DOWN signal detected (canonical)",
                    signal_bar=i,
                    signal_ts=c_bar1.t,
                    signal_price=c_bar1.close,
                )
                return SignalResult(
                    direction=Direction.DOWN,
                    signal_ts=c_bar1.t,
                    signal_price=c_bar1.close,
                    anchor_bar_ts=anchor_bar.t,
                    anchor_price=anchor_price,
                    signal_bar_index=i,
                )
        
        logger.info("No signal detected in window")
        return None
    
    def calculate_quality(
        self,
        signal: SignalResult,
        candles_5m: list[Candle],
        candles_1m: list[Candle] | None = None,
    ) -> QualityBreakdown:
        """
        Calculate quality score for a signal using CANONICAL formula.
        
        CANONICAL Quality Formula (FIXED):
        quality = (anchor_component * 1.0 + adx_component * 0.2 + slope_component * 0.2) * trend_multiplier
        
        Components:
        A) anchor_component: distance from EMA20 on 1m, scaled by ANCHOR_SCALE = 10000.0
        B) adx_component: ADX(14) on 1m normalized to [0..1] (ADX / 100)
        C) slope_component: slope of EMA50 over last 6 bars on 1m, normalized to [0..1]
        D) trend_multiplier: 1.10 (confirm), 0.70 (oppose), 1.00 (else) - based on EMA20 on 5m
        
        Args:
            signal: SignalResult from detect_signal
            candles_5m: 5-minute candles (for trend confirmation via EMA20)
            candles_1m: 1-minute candles (for ADX and EMA50 slope) - optional for backward compatibility
            
        Returns:
            QualityBreakdown with all components
        """
        breakdown = QualityBreakdown(
            anchor_price=signal.anchor_price,
            signal_price=signal.signal_price,
        )
        
        # A) CANONICAL anchor_component: distance from EMA20 on 1m, scaled
        # Note: This uses signal_price which is the close at signal bar
        # anchor_component = |close - EMA20| / close * ANCHOR_SCALE (approx distance from EMA20)
        ret_from_anchor = (signal.signal_price - signal.anchor_price) / signal.anchor_price
        breakdown.ret_from_anchor = ret_from_anchor
        
        # Use canonical ANCHOR_SCALE
        anchor_component = abs(ret_from_anchor) * self.ANCHOR_SCALE
        breakdown.edge_component = anchor_component
        
        # Use 1m candles if provided, otherwise fall back to 5m for backward compatibility
        candles_for_adx_slope = candles_1m if candles_1m is not None else candles_5m
        
        # Find signal bar index in candles
        signal_idx = -1
        for i, c in enumerate(candles_for_adx_slope):
            if c.t <= signal.signal_ts:
                signal_idx = i
            else:
                break
        
        if signal_idx < 0:
            signal_idx = len(candles_for_adx_slope) - 1
        
        if signal_idx < 0 or len(candles_for_adx_slope) == 0:
            logger.warning("No candles available for quality calculation")
            breakdown.final_quality = anchor_component * self.W_ANCHOR
            return breakdown
        
        # Extract price series
        highs = [c.high for c in candles_for_adx_slope]
        lows = [c.low for c in candles_for_adx_slope]
        closes = [c.close for c in candles_for_adx_slope]
        
        # B) CANONICAL adx_component: ADX(14) on 1m normalized to [0..1]
        adx_values = compute_adx(highs, lows, closes, self.ADX_PERIOD)
        adx_raw = adx_values[signal_idx] if signal_idx < len(adx_values) else 0.0
        breakdown.adx_value = adx_raw
        # Normalize to [0..1]: ADX typically ranges 0-100
        adx_component = min(adx_raw / 100.0, 1.0)
        breakdown.q_adx = adx_component
        
        # C) CANONICAL slope_component: slope of EMA50 over last 6 bars on 1m, normalized to [0..1]
        ema50 = compute_ema(closes, 50)
        
        slope_start_idx = signal_idx - self.EMA50_SLOPE_BARS
        slope_component = 0.0
        if slope_start_idx >= 0 and signal_idx < len(ema50) and slope_start_idx < len(ema50):
            ema50_now = ema50[signal_idx]
            ema50_prev = ema50[slope_start_idx]
            slope_raw = ema50_now - ema50_prev
            breakdown.ema50_slope = slope_raw
            
            # Normalize slope to [0..1]
            # Using percentage change approach: |slope / ema50_prev|
            if ema50_prev != 0:
                slope_pct = abs(slope_raw / ema50_prev)
                # Scale by 100 and cap at 1.0 (1% change = 1.0)
                slope_component = min(slope_pct * 100, 1.0)
        breakdown.q_slope = slope_component
        
        # D) CANONICAL trend_multiplier: based on EMA20 on 5m
        # 1.10 if confirms, 0.70 if opposes, 1.00 if neutral/unknown
        trend_mult = self.TREND_NEUTRAL
        trend_confirms = None
        
        if len(candles_5m) > 0:
            # Find idx5 (last 5m candle <= signal_ts)
            idx5 = -1
            for i, c in enumerate(candles_5m):
                if c.t <= signal.signal_ts:
                    idx5 = i
                else:
                    break
            
            if idx5 < 0:
                idx5 = len(candles_5m) - 1
            
            closes_5m = [c.close for c in candles_5m]
            ema20_5m = compute_ema(closes_5m, 20)
            
            if idx5 < len(ema20_5m) and ema20_5m[idx5] != 0:
                close5_val = closes_5m[idx5]
                ema20_val = ema20_5m[idx5]
                
                if signal.direction == Direction.UP:
                    if close5_val > ema20_val:
                        trend_mult = self.TREND_BONUS
                        trend_confirms = True
                    else:
                        trend_mult = self.TREND_PENALTY
                        trend_confirms = False
                else:  # DOWN
                    if close5_val < ema20_val:
                        trend_mult = self.TREND_BONUS
                        trend_confirms = True
                    else:
                        trend_mult = self.TREND_PENALTY
                        trend_confirms = False
        
        breakdown.trend_mult = trend_mult
        if trend_confirms is not None:
            breakdown.trend_confirms = trend_confirms
        
        # CANONICAL quality formula (FIXED weights)
        breakdown.w_anchor = self.W_ANCHOR * anchor_component
        breakdown.w_adx = self.W_ADX * adx_component
        breakdown.w_slope = self.W_SLOPE * slope_component
        
        base_quality = (
            self.W_ANCHOR * anchor_component +
            self.W_ADX * adx_component +
            self.W_SLOPE * slope_component
        )
        breakdown.final_quality = base_quality * trend_mult
        
        logger.info(
            "Quality calculated (canonical)",
            quality=breakdown.final_quality,
            anchor=anchor_component,
            adx=adx_component,
            slope=slope_component,
            trend_mult=trend_mult,
        )
        
        return breakdown
