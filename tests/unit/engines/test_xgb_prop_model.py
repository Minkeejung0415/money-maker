"""Unit tests for XGBoostPropModel (v2 — shared pregame feature schema)."""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("xgboost")

from alpha.engines.sports.prop_features import ALL_FEATURES, FEATURE_SCHEMA_VERSION
from alpha.engines.sports.xgb_prop_model import (
    MODEL_VERSION,
    PropSchemaError,
    XGBoostPropModel,
)


def _make_features(n: int = 50) -> list[dict]:
    rng = np.random.default_rng(42)
    feats = []
    for _ in range(n):
        per_min = float(rng.uniform(0.3, 1.1))
        minutes = float(rng.uniform(20, 38))
        feats.append({
            "roll5_stat_per_min": per_min,
            "roll10_stat_per_min": per_min * float(rng.uniform(0.9, 1.1)),
            "roll20_stat_per_min": per_min * float(rng.uniform(0.85, 1.15)),
            "roll5_minutes": minutes,
            "roll10_minutes": minutes * float(rng.uniform(0.9, 1.1)),
            "minutes_std_last10": float(rng.uniform(0, 8)),
            "projected_minutes": minutes,
            "is_home": float(rng.integers(0, 2)),
            "rest_days": float(rng.integers(0, 5)),
            "back_to_back": 0.0,
            "games_last_4_days": float(rng.integers(0, 3)),
            "opp_def_rtg": float(rng.uniform(105, 120)),
            "opp_pace": float(rng.uniform(95, 108)),
        })
    return feats


def _make_targets(features: list[dict]) -> list[float]:
    """Targets correlated with rate*minutes so XGBoost has signal to learn."""
    rng = np.random.default_rng(99)
    return [
        f["roll5_stat_per_min"] * f["projected_minutes"] + float(rng.normal(0, 2))
        for f in features
    ]


def test_predict_returns_positive_float():
    feats = _make_features(50)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, _make_targets(feats))

    pred = model.predict(feats[0])
    assert isinstance(pred, float)
    assert pred >= 0.0


def test_predict_tracks_input_signal():
    """Higher per-minute rate + minutes → higher prediction."""
    feats = _make_features(200)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, _make_targets(feats))

    low = dict(feats[0])
    low.update({"roll5_stat_per_min": 0.35, "roll10_stat_per_min": 0.35,
                "roll20_stat_per_min": 0.35, "projected_minutes": 22.0})
    high = dict(low)
    high.update({"roll5_stat_per_min": 1.05, "roll10_stat_per_min": 1.05,
                 "roll20_stat_per_min": 1.05, "projected_minutes": 36.0})

    assert model.predict(high) > model.predict(low)


def test_save_load_roundtrip(tmp_path):
    feats = _make_features(50)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, _make_targets(feats))

    path = tmp_path / "model.pkl"
    model.save(path)
    model2 = XGBoostPropModel.load(path)

    assert model2.feature_schema_version == FEATURE_SCHEMA_VERSION
    assert model2.model_version == MODEL_VERSION
    assert model2.feature_names == ALL_FEATURES
    for f in feats[:5]:
        assert abs(model.predict(f) - model2.predict(f)) < 0.001


def test_raises_if_not_fitted():
    model = XGBoostPropModel(target="pts")
    with pytest.raises(RuntimeError, match="not trained"):
        model.predict({"roll5_stat_per_min": 0.8})


def test_raises_on_too_few_samples():
    model = XGBoostPropModel(target="pts")
    with pytest.raises(ValueError, match="20 samples"):
        model.fit(_make_features(5), [20.0] * 5)


def test_feature_importance_sums_to_one():
    feats = _make_features(100)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, _make_targets(feats))

    imp = model.feature_importance()
    assert set(imp) == set(ALL_FEATURES)
    assert all(v >= 0 for v in imp.values())
    assert abs(sum(imp.values()) - 1.0) < 0.01


def test_missing_required_feature_fails_closed():
    feats = _make_features(50)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, _make_targets(feats))

    partial = dict(feats[0])
    del partial["projected_minutes"]
    with pytest.raises(PropSchemaError, match="projected_minutes"):
        model.predict(partial)


def test_missing_optional_feature_is_nan_not_error():
    feats = _make_features(50)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, _make_targets(feats))

    partial = dict(feats[0])
    del partial["opp_def_rtg"]
    del partial["opp_pace"]
    pred = model.predict(partial)  # NaN-filled, no exception
    assert pred >= 0.0


def test_early_stopping_records_validation_metrics():
    feats = _make_features(300)
    targets = _make_targets(feats)
    model = XGBoostPropModel(target="pts")
    model.fit(feats[:240], targets[:240],
              val_features=feats[240:], val_targets=targets[240:])

    vm = model.validation_metrics
    assert vm["val_samples"] == 60
    assert vm["val_mae"] > 0
    assert vm["val_rmse"] >= vm["val_mae"]
    assert model.trained_at is not None
    meta = model.metadata()
    assert meta["model_version"] == MODEL_VERSION
    assert meta["feature_schema_version"] == FEATURE_SCHEMA_VERSION
