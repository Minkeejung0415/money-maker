"""Unit tests for XGBoostPropModel."""
from __future__ import annotations

import numpy as np
import pytest


def _make_features(n: int = 50) -> list[dict]:
    rng = np.random.default_rng(42)
    return [
        {
            "roll5": float(rng.uniform(10, 35)),
            "roll10": float(rng.uniform(10, 30)),
            "roll20": float(rng.uniform(10, 28)),
            "min_recent": float(rng.uniform(20, 38)),
            "opp_def_rtg": float(rng.uniform(105, 120)),
            "is_home": int(rng.integers(0, 2)),
            "rest_days": int(rng.integers(0, 5)),
            "pace": float(rng.uniform(95, 108)),
        }
        for _ in range(n)
    ]


def _make_targets(features: list[dict]) -> list[float]:
    """Targets correlated with roll5 so XGBoost has signal to learn."""
    rng = np.random.default_rng(99)
    return [f["roll5"] + float(rng.normal(0, 3)) for f in features]


def test_predict_returns_positive_float():
    """Trained model returns a positive float for valid features."""
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

    feats = _make_features(50)
    targets = _make_targets(feats)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, targets)

    pred = model.predict(feats[0])
    assert isinstance(pred, float)
    assert pred >= 0.0


def test_predict_tracks_input_signal():
    """Higher roll5 → higher prediction (model learned the relationship)."""
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

    feats = _make_features(200)
    targets = _make_targets(feats)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, targets)

    low_feat  = {k: 0.0 for k in feats[0]}
    low_feat.update({"roll5": 10.0, "roll10": 10.0, "roll20": 10.0,
                     "min_recent": 25.0, "opp_def_rtg": 112.0,
                     "is_home": 0, "rest_days": 2, "pace": 100.0})
    high_feat = dict(low_feat)
    high_feat.update({"roll5": 30.0, "roll10": 28.0, "roll20": 26.0})

    assert model.predict(high_feat) > model.predict(low_feat)


def test_save_load_roundtrip(tmp_path):
    """Model saves and loads correctly, predictions are identical."""
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

    feats = _make_features(50)
    targets = _make_targets(feats)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, targets)

    path = tmp_path / "model.pkl"
    model.save(path)
    model2 = XGBoostPropModel.load(path)

    for f in feats[:5]:
        assert abs(model.predict(f) - model2.predict(f)) < 0.001


def test_raises_if_not_fitted():
    """Calling predict before fit raises RuntimeError."""
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

    model = XGBoostPropModel(target="pts")
    with pytest.raises(RuntimeError, match="not trained"):
        model.predict({"roll5": 20.0})


def test_raises_on_too_few_samples():
    """fit() raises ValueError when fewer than 20 samples provided."""
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

    model = XGBoostPropModel(target="pts")
    with pytest.raises(ValueError, match="20 samples"):
        model.fit(_make_features(5), [20.0] * 5)


def test_feature_importance_sums_to_one():
    """Feature importances are non-negative and sum to 1."""
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

    feats = _make_features(100)
    model = XGBoostPropModel(target="pts")
    model.fit(feats, _make_targets(feats))

    imp = model.feature_importance()
    assert all(v >= 0 for v in imp.values())
    assert abs(sum(imp.values()) - 1.0) < 0.01
