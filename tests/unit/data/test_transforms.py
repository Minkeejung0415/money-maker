import polars as pl
import pytest
from alpha.data.transforms.features import add_returns, add_moving_averages, add_rsi
from alpha.data.transforms.normalizers import zscore_normalize


def _sample_df():
    return pl.DataFrame({
        "symbol": ["AAPL"] * 30,
        "date": [f"2026-01-{i+1:02d}" for i in range(30)],
        "close": [float(100 + i + (i % 3)) for i in range(30)],
    })


def test_add_returns():
    df = add_returns(_sample_df())
    assert "return_1d" in df.columns
    assert df["return_1d"][0] is None  # first row has no prior


def test_add_moving_averages():
    df = add_moving_averages(_sample_df(), windows=[5, 10])
    assert "ma_5" in df.columns
    assert "ma_10" in df.columns


def test_add_rsi():
    df = add_rsi(_sample_df(), period=14)
    assert "rsi_14" in df.columns
    # RSI must be between 0 and 100 for valid rows
    valid = df.filter(pl.col("rsi_14").is_not_null())["rsi_14"]
    assert (valid >= 0).all() and (valid <= 100).all()


def test_zscore_normalize():
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
    norm = zscore_normalize(df, "close")
    assert "close_z" in norm.columns
    # mean of z-scores should be ~0
    assert abs(norm["close_z"].mean()) < 1e-10
