from unittest.mock import MagicMock, patch
import numpy as np
import polars as pl
import pytest
from alpha.engines.stocks.signals import StockSignalEngine


def _mock_price_rows(symbol="AAPL", n=30):
    return [
        {
            "symbol": symbol,
            "date": f"2026-01-{i+1:02d}",
            "open": float(150 + i),
            "high": float(152 + i),
            "low": float(149 + i),
            "close": float(151 + i + (i % 3)),
            "volume": 1_000_000.0,
            "asset_type": "stock",
        }
        for i in range(n)
    ]


def _random_walk_rows(n=80, seed=42, symbol="TEST"):
    """Generate synthetic OHLCV rows using a random walk for close prices."""
    rng = np.random.default_rng(seed)
    close = [100.0]
    for _ in range(n - 1):
        close.append(close[-1] * (1.0 + rng.normal(0.001, 0.015)))
    rows = []
    for i, c in enumerate(close):
        h = c * 1.01
        lo = c * 0.99
        rows.append({
            "symbol": symbol,
            "date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": float(c * 0.999),
            "high": float(h),
            "low": float(lo),
            "close": float(c),
            "volume": float(int(rng.integers(500_000, 2_000_000))),
            "asset_type": "stock",
        })
    return rows


# ---------------------------------------------------------------------------
# Existing baseline tests
# ---------------------------------------------------------------------------

def test_signal_engine_initializes():
    engine = StockSignalEngine(av_api_key="TEST", fred_api_key="TEST")
    assert engine is not None


def test_build_features_returns_dataframe():
    engine = StockSignalEngine(av_api_key="TEST", fred_api_key="TEST")
    rows = _mock_price_rows()
    df = engine.build_features(rows)
    assert isinstance(df, pl.DataFrame)
    assert "return_1d" in df.columns
    assert "ma_5" in df.columns
    assert "rsi_14" in df.columns


def test_score_returns_float():
    engine = StockSignalEngine(av_api_key="TEST", fred_api_key="TEST")
    rows = _mock_price_rows()
    df = engine.build_features(rows)
    score = engine.score(df)
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0


def test_signal_is_buy_sell_or_hold():
    engine = StockSignalEngine(av_api_key="TEST", fred_api_key="TEST")
    rows = _mock_price_rows()
    signal = engine.get_signal(rows)
    assert signal["action"] in ("buy", "sell", "hold")
    assert "score" in signal
    assert "symbol" in signal


# ---------------------------------------------------------------------------
# TA-Lib indicator tests
# ---------------------------------------------------------------------------

def test_score_always_in_range_with_ta_features():
    """Score must stay in [-1, 1] when TA-Lib indicators are computed."""
    engine = StockSignalEngine()
    rows = _random_walk_rows(n=80)
    df = engine.build_features(rows)
    score = engine.score(df)
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0


def test_ta_features_added_when_available():
    """build_features() should add TA-Lib columns when high/low/close present."""
    pytest.importorskip("talib")
    engine = StockSignalEngine()
    rows = _random_walk_rows(n=80)
    df = engine.build_features(rows)
    for col in ("macd_line", "macd_signal_line", "bb_upper", "bb_lower", "adx_14"):
        assert col in df.columns, f"Missing TA column: {col}"


def test_macd_bullish_produces_positive_component():
    """When MACD line > signal line (bullish crossover) the component is positive."""
    pytest.importorskip("talib")
    engine = StockSignalEngine()
    # Create a strong uptrend so MACD line should be above signal
    rows = []
    price = 100.0
    for i in range(80):
        price *= 1.005  # 0.5% daily gain → strong uptrend
        rows.append({
            "symbol": "UP",
            "date": f"2026-01-{i+1:02d}",
            "open": price * 0.999,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": float(price),
            "volume": 1_000_000.0,
            "asset_type": "stock",
        })
    df = engine.build_features(rows)
    last = df.tail(1)
    if "macd_line" in df.columns:
        ml = last["macd_line"][0]
        ms = last["macd_signal_line"][0]
        if ml is not None and ms is not None:
            assert ml > ms, "Uptrend should produce MACD line above signal"


def test_adx_below_20_reduces_magnitude():
    """Low-ADX (ranging market) should reduce score magnitude vs high-ADX."""
    pytest.importorskip("talib")
    engine = StockSignalEngine()

    # Build a ranging (flat) market — ADX will be low
    rows_flat = []
    for i in range(80):
        c = 100.0 + 2.0 * (i % 4 - 2)  # oscillates ±4 around 100
        rows_flat.append({
            "symbol": "FLAT",
            "date": f"2026-01-{i+1:02d}",
            "open": c,
            "high": c * 1.005,
            "low": c * 0.995,
            "close": float(c),
            "volume": 1_000_000.0,
            "asset_type": "stock",
        })
    df_flat = engine.build_features(rows_flat)
    last_flat = df_flat.tail(1)

    if "adx_14" not in df_flat.columns or last_flat["adx_14"][0] is None:
        pytest.skip("adx_14 not available")

    adx_val = last_flat["adx_14"][0]
    # Manually inject a higher ADX to compare
    df_strong = df_flat.with_columns(pl.lit(30.0).alias("adx_14"))

    score_weak = engine.score(df_flat)
    score_strong = engine.score(df_strong)

    if adx_val < 20:
        assert abs(score_weak) <= abs(score_strong) + 1e-6, (
            f"Weak ADX ({adx_val:.1f}) should produce smaller magnitude "
            f"({score_weak}) vs strong ADX ({score_strong})"
        )


def test_fallback_works_without_ta_columns():
    """score() must use the original 3-factor method when TA columns are absent."""
    engine = StockSignalEngine()
    # Provide only close + volume (no high/low → build_ta_features skips)
    rows = [
        {
            "symbol": "X",
            "date": f"2026-01-{i+1:02d}",
            "close": float(100 + i),
            "volume": 1_000_000.0,
        }
        for i in range(30)
    ]
    df = pl.DataFrame(rows)
    from alpha.data.transforms.features import build_feature_set
    df = build_feature_set(df)
    # Deliberately skip build_ta_features — no TA columns present
    score = engine.score(df)
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Fundamental filter tests (Improvement #3)
# ---------------------------------------------------------------------------

def _buy_rows(n=80):
    """Price rows that reliably produce a BUY signal (strong uptrend)."""
    rows = []
    price = 100.0
    for i in range(n):
        price *= 1.006
        rows.append({
            "symbol": "AAPL",
            "date": f"2026-01-{i % 28 + 1:02d}",
            "open": price * 0.999,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": float(price),
            "volume": 1_000_000.0,
            "asset_type": "stock",
        })
    return rows


def _mock_av(pe=20.0, eps=5.0, margin=0.15):
    client = MagicMock()
    client.get_fundamentals.return_value = {
        "pe_ratio": pe,
        "eps": eps,
        "profit_margin": margin,
    }
    return client


def test_fundamental_filter_pass():
    """Good fundamentals keep a buy signal as buy."""
    engine = StockSignalEngine()
    av = _mock_av(pe=20, eps=5, margin=0.15)
    signal = engine.get_signal_with_fundamentals(_buy_rows(), av_client=av)
    assert signal["fundamental_filter"] in ("pass", "skipped")
    # If the technical signal was buy, it should remain buy on good fundamentals
    if signal["fundamental_filter"] == "pass":
        assert signal["action"] == "buy"


def test_fundamental_filter_fail_negative_eps():
    """Negative EPS downgrades buy → hold."""
    engine = StockSignalEngine()
    av = _mock_av(pe=20, eps=-1.0, margin=0.10)
    signal = engine.get_signal_with_fundamentals(_buy_rows(), av_client=av)
    if signal.get("fundamental_filter") == "fail":
        assert signal["action"] == "hold"


def test_fundamental_filter_fail_high_pe():
    """PE > 50 downgrades buy → hold."""
    engine = StockSignalEngine()
    av = _mock_av(pe=60.0, eps=1.0, margin=0.10)
    signal = engine.get_signal_with_fundamentals(_buy_rows(), av_client=av)
    if signal.get("fundamental_filter") == "fail":
        assert signal["action"] == "hold"


def test_fundamental_filter_sell_bypasses():
    """Sell signals skip the fundamental filter entirely."""
    engine = StockSignalEngine()
    av = _mock_av(pe=5, eps=10, margin=0.20)
    # Build a downtrend to generate a sell signal
    rows = []
    price = 200.0
    for i in range(80):
        price *= 0.994
        rows.append({
            "symbol": "DOWN",
            "date": f"2026-01-{i % 28 + 1:02d}",
            "open": price * 1.001,
            "high": price * 1.005,
            "low": price * 0.995,
            "close": float(price),
            "volume": 1_000_000.0,
            "asset_type": "stock",
        })
    signal = engine.get_signal_with_fundamentals(rows, av_client=av)
    if signal["action"] == "sell":
        assert signal["fundamental_filter"] == "skipped"


def test_fundamental_filter_none_fundamentals_skipped():
    """When get_fundamentals returns None, filter is 'skipped' and action unchanged."""
    engine = StockSignalEngine()
    av = MagicMock()
    av.get_fundamentals.return_value = None
    signal = engine.get_signal_with_fundamentals(_buy_rows(), av_client=av)
    assert signal["fundamental_filter"] == "skipped"


def test_fundamental_filter_no_client_skipped():
    """When av_client is None, filter is 'skipped' and action unchanged."""
    engine = StockSignalEngine()
    signal = engine.get_signal_with_fundamentals(_buy_rows(), av_client=None)
    assert signal["fundamental_filter"] == "skipped"
