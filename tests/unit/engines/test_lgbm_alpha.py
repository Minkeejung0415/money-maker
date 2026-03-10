"""
Tests for LGBMAlphaModel — feature building, training, prediction, and
is_trained() lifecycle.
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from alpha.engines.stocks.lgbm_alpha import LGBMAlphaModel, _FEATURE_COLS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 130, seed: int = 0) -> pl.DataFrame:
    """
    Generate *n* rows of synthetic OHLCV data using a random walk for close.
    high = close * 1.01, low = close * 0.99, volume = random integers.
    """
    rng = np.random.default_rng(seed)
    close = np.empty(n)
    close[0] = 100.0
    for i in range(1, n):
        close[i] = close[i - 1] * (1.0 + rng.normal(0.001, 0.015))
    high = close * 1.01
    low = close * 0.99
    volume = rng.integers(500_000, 2_000_000, size=n).astype(float)
    return pl.DataFrame({
        "symbol": ["SYN"] * n,
        "date": [f"2025-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)],
        "close": close.tolist(),
        "high": high.tolist(),
        "low": low.tolist(),
        "volume": volume.tolist(),
    })


@pytest.fixture()
def ohlcv():
    return _make_ohlcv(130)


@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    """Redirect all PKL writes to a temp directory."""
    import alpha.engines.stocks.lgbm_alpha as mod
    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    yield tmp_path


# ---------------------------------------------------------------------------
# build_features tests
# ---------------------------------------------------------------------------

def test_build_features_returns_dataframe(ohlcv):
    model = LGBMAlphaModel()
    feat = model.build_features(ohlcv)
    import pandas as pd
    assert isinstance(feat, pd.DataFrame)


def test_build_features_has_all_columns(ohlcv):
    model = LGBMAlphaModel()
    feat = model.build_features(ohlcv)
    for col in _FEATURE_COLS:
        assert col in feat.columns, f"Missing feature column: {col}"


def test_build_features_no_nan(ohlcv):
    model = LGBMAlphaModel()
    feat = model.build_features(ohlcv)
    assert not feat.isnull().any().any(), "build_features should drop all NaN rows"


def test_build_features_at_least_one_row(ohlcv):
    model = LGBMAlphaModel()
    feat = model.build_features(ohlcv)
    assert len(feat) > 0


# ---------------------------------------------------------------------------
# train + is_trained tests
# ---------------------------------------------------------------------------

def test_is_trained_false_before_train(ohlcv):
    model = LGBMAlphaModel()
    assert not model.is_trained("SYN")


def test_train_creates_pkl(ohlcv):
    pytest.importorskip("lightgbm")
    pytest.importorskip("joblib")
    model = LGBMAlphaModel()
    model.train(ohlcv, "SYN")
    assert model.is_trained("SYN")


def test_is_trained_true_after_train(ohlcv):
    pytest.importorskip("lightgbm")
    pytest.importorskip("joblib")
    model = LGBMAlphaModel()
    model.train(ohlcv, "SYN")
    assert model.is_trained("SYN")


def test_train_skips_if_too_few_rows():
    """Training on < 60 clean rows should not create a pkl file."""
    pytest.importorskip("lightgbm")
    model = LGBMAlphaModel()
    tiny = _make_ohlcv(n=10)
    model.train(tiny, "TINY")
    assert not model.is_trained("TINY")


# ---------------------------------------------------------------------------
# predict tests
# ---------------------------------------------------------------------------

def test_predict_returns_zero_without_model(ohlcv):
    model = LGBMAlphaModel()
    result = model.predict(ohlcv, "NOTRAINED")
    assert result == 0.0


def test_predict_returns_float_after_training(ohlcv):
    pytest.importorskip("lightgbm")
    pytest.importorskip("joblib")
    model = LGBMAlphaModel()
    model.train(ohlcv, "SYN")
    result = model.predict(ohlcv, "SYN")
    assert isinstance(result, float)


def test_predict_is_finite_after_training(ohlcv):
    pytest.importorskip("lightgbm")
    pytest.importorskip("joblib")
    model = LGBMAlphaModel()
    model.train(ohlcv, "SYN")
    result = model.predict(ohlcv, "SYN")
    assert np.isfinite(result)
