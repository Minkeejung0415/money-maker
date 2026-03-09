import polars as pl
import pytest
from alpha.engines.stocks.alpha_factory import AlphaFactory


def _ohlcv_df(n=60):
    import random
    random.seed(7)
    closes = [150.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + random.gauss(0.001, 0.015)))
    return pl.DataFrame({
        "symbol": ["AAPL"] * n,
        "date": [f"2026-01-{(i % 28) + 1:02d}" for i in range(n)],
        "close": closes,
        "volume": [1_000_000.0 + i * 1000 for i in range(n)],
    })


def test_alpha_factory_initializes():
    af = AlphaFactory()
    assert af is not None


def test_compute_factors_returns_dataframe():
    af = AlphaFactory()
    df = af.compute_factors(_ohlcv_df())
    assert isinstance(df, pl.DataFrame)


def test_factors_include_expected_columns():
    af = AlphaFactory()
    df = af.compute_factors(_ohlcv_df())
    for col in ("momentum_5d", "momentum_20d", "vol_20d", "volume_zscore"):
        assert col in df.columns, f"Missing factor: {col}"


def test_alpha_scores_are_finite():
    af = AlphaFactory()
    df = af.compute_factors(_ohlcv_df())
    scores = df.filter(pl.col("alpha_score").is_not_null())["alpha_score"]
    assert len(scores) > 0
    assert (scores.is_finite()).all()
