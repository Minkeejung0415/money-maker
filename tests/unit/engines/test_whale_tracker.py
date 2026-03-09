import polars as pl
import pytest
from alpha.engines.crypto.whale_tracker import WhaleTracker


def _ohlcv_rows(n=30, base_vol=1_000_000.0):
    rows = []
    for i in range(n):
        rows.append({
            "symbol": "BTC/USDT",
            "date": f"2026-01-{(i % 28) + 1:02d}",
            "open": 42000.0 + i,
            "high": 42500.0 + i,
            "low": 41500.0 + i,
            "close": 42200.0 + i,
            "volume": base_vol,
            "asset_type": "crypto",
        })
    return rows


def test_tracker_initializes():
    wt = WhaleTracker()
    assert wt is not None


def test_volume_zscore_computed():
    rows = _ohlcv_rows()
    # Spike the last row
    rows[-1]["volume"] = 10_000_000.0
    wt = WhaleTracker()
    df = wt.compute_volume_features(rows)
    assert "volume_zscore" in df.columns
    last_z = df["volume_zscore"][-1]
    assert last_z > 2.0  # clearly anomalous


def test_is_whale_activity_detects_spike():
    rows = _ohlcv_rows()
    rows[-1]["volume"] = 15_000_000.0  # 15x normal
    wt = WhaleTracker(zscore_threshold=2.0)
    assert wt.is_whale_activity(rows) is True


def test_is_whale_activity_returns_false_for_normal():
    rows = _ohlcv_rows()
    wt = WhaleTracker(zscore_threshold=2.0)
    assert wt.is_whale_activity(rows) is False


def test_whale_signal_includes_direction():
    rows = _ohlcv_rows()
    rows[-1]["volume"] = 20_000_000.0
    rows[-1]["close"] = 43000.0  # price up with volume → bullish
    rows[-2]["close"] = 42000.0
    wt = WhaleTracker()
    signal = wt.get_signal(rows)
    assert signal["whale_detected"] is True
    assert signal["direction"] in ("bullish", "bearish", "neutral")
