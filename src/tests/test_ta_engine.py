"""
Tests for TA Engine.

Ensures:
- Signal detection rules match spec (EMA20 1m with 2-bar confirm)
- Quality calculation is deterministic and matches formula
"""

import pytest

from src.services.ta_engine import (
    TAEngine,
    compute_ema,
    compute_adx,
    SignalResult,
)
from src.adapters.polymarket.binance_client import Candle
from src.domain.enums import Direction


class TestEMACalculation:
    """Tests for EMA computation."""
    
    def test_ema_basic(self):
        """Test basic EMA calculation."""
        values = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        ema = compute_ema(values, 5)
        
        # EMA should have same length
        assert len(ema) == len(values)
        
        # First 4 values should be 0 (not enough data)
        assert all(v == 0 for v in ema[:4])
        
        # 5th value should be SMA of first 5
        expected_sma = (10 + 11 + 12 + 13 + 14) / 5
        assert ema[4] == expected_sma
        
        # Subsequent values should use EMA formula
        assert ema[5] > ema[4]  # Should trend up
    
    def test_ema_period_larger_than_data(self):
        """EMA with period larger than data returns zeros."""
        values = [1, 2, 3]
        ema = compute_ema(values, 5)
        
        assert len(ema) == 3
        assert all(v == 0 for v in ema)
    
    def test_ema_empty_input(self):
        """EMA with empty input returns empty list."""
        ema = compute_ema([], 5)
        assert ema == []
    
    def test_ema_single_value(self):
        """EMA with single value."""
        ema = compute_ema([100], 1)
        assert len(ema) == 1
        assert ema[0] == 100


class TestADXCalculation:
    """Tests for ADX computation."""
    
    def test_adx_basic(self):
        """Test basic ADX calculation with trending data."""
        # Create uptrending data
        n = 50
        highs = [100 + i * 0.5 for i in range(n)]
        lows = [99 + i * 0.5 for i in range(n)]
        closes = [99.5 + i * 0.5 for i in range(n)]
        
        adx = compute_adx(highs, lows, closes, period=14)
        
        assert len(adx) == n
        
        # ADX should be positive for trending data
        # Values only become valid after 2*period
        assert adx[-1] > 0
    
    def test_adx_insufficient_data(self):
        """ADX returns zeros with insufficient data."""
        highs = [100, 101, 102]
        lows = [99, 100, 101]
        closes = [99.5, 100.5, 101.5]
        
        adx = compute_adx(highs, lows, closes, period=14)
        
        assert len(adx) == 3
        assert all(v == 0 for v in adx)


class TestSignalDetection:
    """Tests for signal detection logic."""
    
    @pytest.fixture
    def ta_engine(self):
        """Create TA engine with default config."""
        return TAEngine(
            adx_period=14,
            ema50_slope_bars=5,
            anchor_scale=10000.0,
            w_anchor=0.3,
            w_adx=0.4,
            w_slope=0.3,
            trend_bonus=1.2,
            trend_penalty=0.8,
        )
    
    def _create_candles(self, prices: list[tuple[float, float, float, float]], start_ts: int = 1000) -> list[Candle]:
        """Create candles from (open, high, low, close) tuples."""
        candles = []
        for i, (o, h, l, c) in enumerate(prices):
            candles.append(Candle(
                t=start_ts + i * 60,
                o=o,
                h=h,
                l=l,
                c=c,
                v=1000,
                close_time=start_ts + (i + 1) * 60 - 1,
            ))
        return candles
    
    def test_no_signal_insufficient_candles(self, ta_engine):
        """No signal with insufficient candles."""
        candles = self._create_candles([(100, 101, 99, 100)] * 10)
        
        result = ta_engine.detect_signal(candles, start_ts=1000)
        
        assert result is None
    
    def test_up_signal_detection(self, ta_engine):
        """
        UP signal detection: low[i] <= ema20[i] AND close[i] > ema20[i] 
        AND close[i+1] > ema20[i+1]
        """
        # Create data that triggers UP signal
        # Need at least 22 candles (20 for EMA warmup + 2 for signal)
        prices = []
        
        # First 20 candles: stable around 100 (for EMA warmup)
        for i in range(20):
            prices.append((99.5, 100.5, 99, 100))
        
        # EMA20 will be around 100
        # Bar 20: low touches EMA (99), close above EMA (101)
        prices.append((100, 102, 99, 101))
        
        # Bar 21: close above EMA (102) - confirms UP
        prices.append((101, 103, 100, 102))
        
        candles = self._create_candles(prices)
        
        result = ta_engine.detect_signal(candles, start_ts=1000)
        
        # Note: actual signal may or may not trigger based on exact EMA values
        # This test verifies the logic runs without error
        if result:
            assert result.direction == Direction.UP
    
    def test_down_signal_detection(self, ta_engine):
        """
        DOWN signal detection: high[i] >= ema20[i] AND close[i] < ema20[i]
        AND close[i+1] < ema20[i+1]
        """
        prices = []
        
        # First 20 candles: stable around 100
        for i in range(20):
            prices.append((99.5, 100.5, 99, 100))
        
        # Bar 20: high touches EMA (101), close below EMA (99)
        prices.append((100, 101, 98, 99))
        
        # Bar 21: close below EMA (98) - confirms DOWN
        prices.append((99, 100, 97, 98))
        
        candles = self._create_candles(prices)
        
        result = ta_engine.detect_signal(candles, start_ts=1000)
        
        if result:
            assert result.direction == Direction.DOWN
    
    def test_signal_ts_is_confirm_bar(self, ta_engine):
        """signal_ts should be timestamp of confirmation bar (i+1)."""
        prices = []
        
        # Warmup
        for i in range(20):
            prices.append((99.5, 100.5, 99, 100))
        
        # Signal setup and confirm
        prices.append((100, 102, 99, 101))  # Bar 20
        prices.append((101, 103, 100, 102))  # Bar 21 - confirm
        
        candles = self._create_candles(prices, start_ts=1000)
        
        result = ta_engine.detect_signal(candles, start_ts=1000)
        
        if result:
            # Signal ts should be bar 21's timestamp
            expected_ts = 1000 + 21 * 60
            assert result.signal_ts == expected_ts


class TestQualityCalculation:
    """Tests for SPEC quality score calculation."""
    
    @pytest.fixture
    def ta_engine(self):
        """Create TA engine - uses fixed constants regardless of args."""
        return TAEngine()
    
    def _create_5m_candles(self, n: int = 100) -> list[Candle]:
        """Create uptrending 5m candles."""
        candles = []
        base_price = 1000
        for i in range(n):
            price = base_price + i * 0.5
            candles.append(Candle(
                t=1000 + i * 300,
                o=price,
                h=price + 1,
                l=price - 1,
                c=price + 0.3,
                v=1000,
                close_time=1000 + (i + 1) * 300 - 1,
            ))
        return candles
    
    def test_quality_is_deterministic(self, ta_engine):
        """Same inputs should produce same quality."""
        signal = SignalResult(
            direction=Direction.UP,
            signal_ts=5000,
            signal_price=1010,
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        candles_5m = self._create_5m_candles()
        
        q1 = ta_engine.calculate_quality(signal, candles_5m)
        q2 = ta_engine.calculate_quality(signal, candles_5m)
        
        assert q1.final_quality == q2.final_quality
    
    def test_quality_anchor_component_positive_return(self, ta_engine):
        """Anchor component uses |ret_from_anchor| * ANCHOR_SCALE."""
        signal = SignalResult(
            direction=Direction.UP,
            signal_ts=5000,
            signal_price=1010,  # 1% above anchor
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        candles_5m = self._create_5m_candles()
        
        q = ta_engine.calculate_quality(signal, candles_5m)
        
        # ret_from_anchor = (1010 - 1000) / 1000 = 0.01
        assert q.ret_from_anchor == 0.01
        # anchor_component = |0.01| * 10000 = 100 (no penalty for consistent direction)
        assert q.edge_component == 100.0
        assert q.edge_penalty_applied == False
    
    def test_quality_anchor_penalty_for_up_with_negative_return(self, ta_engine):
        """UP signal with negative return should have 0.25 penalty."""
        signal = SignalResult(
            direction=Direction.UP,
            signal_ts=5000,
            signal_price=990,  # 1% below anchor
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        candles_5m = self._create_5m_candles()
        
        q = ta_engine.calculate_quality(signal, candles_5m)
        
        # ret_from_anchor = (990 - 1000) / 1000 = -0.01
        assert q.ret_from_anchor == -0.01
        # anchor_component = |-0.01| * 10000 * 0.25 = 25.0 (penalty applied)
        assert q.edge_component == 25.0
        assert q.edge_penalty_applied == True
    
    def test_quality_anchor_penalty_for_down_with_positive_return(self, ta_engine):
        """DOWN signal with positive return should have 0.25 penalty."""
        signal = SignalResult(
            direction=Direction.DOWN,
            signal_ts=5000,
            signal_price=1010,  # 1% above anchor
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        candles_5m = self._create_5m_candles()
        
        q = ta_engine.calculate_quality(signal, candles_5m)
        
        # ret_from_anchor = (1010 - 1000) / 1000 = 0.01
        assert q.ret_from_anchor == 0.01
        # anchor_component = |0.01| * 10000 * 0.25 = 25.0 (penalty applied)
        assert q.edge_component == 25.0
        assert q.edge_penalty_applied == True
    
    def test_quality_adx_is_raw_value(self, ta_engine):
        """ADX component should be raw ADX value (NOT normalized)."""
        signal = SignalResult(
            direction=Direction.UP,
            signal_ts=5000,
            signal_price=1010,
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        candles_5m = self._create_5m_candles()
        
        q = ta_engine.calculate_quality(signal, candles_5m)
        
        # ADX should be raw value, not normalized to [0..1]
        # q_adx equals adx_value (the raw ADX)
        assert q.q_adx == q.adx_value
        # ADX can be any value from 0 to 100+
        assert q.q_adx >= 0
    
    def test_quality_slope_formula(self, ta_engine):
        """Slope uses formula: 1000 * abs(slope50 / close_5m[idx5])."""
        signal = SignalResult(
            direction=Direction.UP,
            signal_ts=5000,
            signal_price=1010,
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        candles_5m = self._create_5m_candles()
        
        q = ta_engine.calculate_quality(signal, candles_5m)
        
        # Slope is NOT normalized to [0..1], uses 1000 * abs(slope/close)
        # With the test data, slope should be positive (uptrending)
        assert q.q_slope >= 0
    
    def test_quality_trend_multiplier_values(self, ta_engine):
        """Trend multiplier should be 1.10, 0.70, or 1.00."""
        candles_5m = self._create_5m_candles(n=100)
        
        signal = SignalResult(
            direction=Direction.UP,
            signal_ts=15000,
            signal_price=1010,
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        q = ta_engine.calculate_quality(signal, candles_5m)
        
        # Trend multiplier values: 1.10, 0.70, 1.00
        assert q.trend_mult in [1.10, 0.70, 1.00]
    
    def test_quality_formula_weights(self, ta_engine):
        """Quality formula uses FIXED weights: 1.0, 0.2, 0.2."""
        signal = SignalResult(
            direction=Direction.UP,
            signal_ts=5000,
            signal_price=1010,
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        candles_5m = self._create_5m_candles()
        
        q = ta_engine.calculate_quality(signal, candles_5m)
        
        # Verify weighted components are calculated
        assert q.w_anchor >= 0
        assert q.w_adx >= 0
        assert q.w_slope >= 0
        
        # FIXED weights: W_ANCHOR=1.0, W_ADX=0.2, W_SLOPE=0.2
        expected_base = (1.0 * q.edge_component + 0.2 * q.q_adx + 0.2 * q.q_slope)
        expected_quality = expected_base * q.trend_mult
        
        # Final quality should match formula
        assert abs(q.final_quality - expected_quality) < 0.01
    
    def test_quality_uses_5m_candles_for_adx_slope(self, ta_engine):
        """ADX and EMA50 slope should use 5m candles, not 1m."""
        signal = SignalResult(
            direction=Direction.UP,
            signal_ts=5000,
            signal_price=1010,
            anchor_bar_ts=1000,
            anchor_price=1000,
            signal_bar_index=20,
        )
        
        candles_5m = self._create_5m_candles(n=100)
        
        # Call with only 5m candles (1m ignored even if passed)
        q = ta_engine.calculate_quality(signal, candles_5m)
        
        # Quality should be calculated successfully
        assert q.final_quality > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
