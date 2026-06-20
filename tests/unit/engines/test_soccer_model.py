"""Unit tests for SoccerModel EPL artifact gate and model_name field.

Tests verify:
1. Valid EPL artifact is accepted and _epl_artifact_loaded=True
2. Various invalid bundles are rejected
3. predict() always returns model_name field
4. Backward compatibility when no artifact present

All tests avoid live network calls.
"""
from __future__ import annotations

import joblib
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

import alpha.engines.sports.soccer_model as soccer_model_module
from alpha.engines.sports.epl_training import EPL_FEATURE_NAMES


# ---------------------------------------------------------------------------
# Helper: build a minimal valid EPL bundle
# ---------------------------------------------------------------------------

def _make_valid_bundle(feature_names=None, validated=True, kind="epl_win_probability_bundle"):
    """Return a valid-schema EPL bundle using a LogisticRegression stub."""
    if feature_names is None:
        feature_names = list(EPL_FEATURE_NAMES)

    # Stub model: LogisticRegression trained on 2 synthetic samples
    n_features = len(EPL_FEATURE_NAMES)
    X_dummy = np.zeros((4, n_features))
    X_dummy[0, 0] = 1.0
    X_dummy[2, 0] = -1.0
    y_dummy = [0, 1, 0, 1]
    model = LogisticRegression(max_iter=100)
    model.fit(X_dummy, y_dummy)
    calibrator = LogisticRegression(max_iter=100)
    calibrator.fit(X_dummy, y_dummy)

    return {
        "kind": kind,
        "validated": validated,
        "feature_names": feature_names,
        "model": model,
        "calibrator": calibrator,
        "team_state": {},
    }


def _make_soccer_model_no_xgb(monkeypatch):
    """Create SoccerModel with XGBoost loading suppressed."""
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)
    from alpha.engines.sports.soccer_model import SoccerModel
    return SoccerModel


# ---------------------------------------------------------------------------
# Test 1: valid bundle accepted
# ---------------------------------------------------------------------------

def test_valid_bundle_accepted(tmp_path, monkeypatch):
    """SoccerModel with a valid EPL bundle sets _epl_artifact_loaded=True."""
    bundle_path = tmp_path / "epl_win_probability.pkl"
    joblib.dump(_make_valid_bundle(), bundle_path)

    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", bundle_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()
    assert model._epl_artifact_loaded is True


# ---------------------------------------------------------------------------
# Test 2: unvalidated bundle rejected
# ---------------------------------------------------------------------------

def test_unvalidated_bundle_rejected(tmp_path, monkeypatch):
    """Bundle with validated=False → _epl_artifact_loaded=False."""
    bundle_path = tmp_path / "epl_win_probability.pkl"
    joblib.dump(_make_valid_bundle(validated=False), bundle_path)

    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", bundle_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()
    assert model._epl_artifact_loaded is False


# ---------------------------------------------------------------------------
# Test 3: wrong kind rejected
# ---------------------------------------------------------------------------

def test_wrong_kind_rejected(tmp_path, monkeypatch):
    """Bundle with wrong kind → _epl_artifact_loaded=False."""
    bundle_path = tmp_path / "epl_win_probability.pkl"
    joblib.dump(_make_valid_bundle(kind="mlb_win_probability_bundle"), bundle_path)

    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", bundle_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()
    assert model._epl_artifact_loaded is False


# ---------------------------------------------------------------------------
# Test 4: feature name mismatch rejected
# ---------------------------------------------------------------------------

def test_feature_mismatch_rejected(tmp_path, monkeypatch):
    """Bundle with mismatched feature_names → _epl_artifact_loaded=False."""
    bundle_path = tmp_path / "epl_win_probability.pkl"
    joblib.dump(_make_valid_bundle(feature_names=["bad_feature_1", "bad_feature_2"]), bundle_path)

    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", bundle_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()
    assert model._epl_artifact_loaded is False


# ---------------------------------------------------------------------------
# Test 5: missing artifact → no crash
# ---------------------------------------------------------------------------

def test_missing_artifact_no_crash(tmp_path, monkeypatch):
    """When artifact file is absent, _epl_artifact_loaded=False (no exception)."""
    missing_path = tmp_path / "does_not_exist.pkl"
    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", missing_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()  # must not raise
    assert model._epl_artifact_loaded is False


# ---------------------------------------------------------------------------
# Test 6: predict() fallback returns model_name="market_implied"
# ---------------------------------------------------------------------------

def test_predict_fallback_has_model_name(tmp_path, monkeypatch):
    """Without artifact, predict() output has model_name='market_implied'."""
    missing_path = tmp_path / "absent.pkl"
    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", missing_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()
    result = model.predict({"home_team": "Arsenal", "away_team": "Chelsea", "home_odds": -110, "draw_odds": 300, "away_odds": 250})
    assert "model_name" in result
    assert result["model_name"] == "market_implied"


# ---------------------------------------------------------------------------
# Test 7: predict() with artifact loaded returns model_name="epl_xgboost_v1"
# ---------------------------------------------------------------------------

def test_predict_artifact_model_name(tmp_path, monkeypatch):
    """With valid artifact loaded, predict() returns model_name='epl_xgboost_v1'."""
    bundle_path = tmp_path / "epl_win_probability.pkl"
    joblib.dump(_make_valid_bundle(), bundle_path)

    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", bundle_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    # Stub _predict_epl_bundle to return known probs so we don't need live data
    def fake_epl_bundle(self, game):
        return (0.55, 0.20, 0.25)

    monkeypatch.setattr(soccer_model_module.SoccerModel, "_predict_epl_bundle", fake_epl_bundle)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()
    assert model._epl_artifact_loaded is True

    result = model.predict({"home_team": "Arsenal", "away_team": "Chelsea", "home_odds": -110, "draw_odds": 300, "away_odds": 250})
    assert result.get("model_name") == "epl_xgboost_v1"


# ---------------------------------------------------------------------------
# Test 8: predict() output keys preserved
# ---------------------------------------------------------------------------

def test_predict_output_keys_preserved(tmp_path, monkeypatch):
    """predict() still returns home_team, away_team, home_win_prob, draw_prob, away_win_prob, source."""
    missing_path = tmp_path / "absent.pkl"
    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", missing_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()
    game = {"home_team": "Arsenal", "away_team": "Chelsea", "home_odds": -110, "draw_odds": 300, "away_odds": 250}
    result = model.predict(game)

    required_keys = {"home_team", "away_team", "home_win_prob", "draw_prob", "away_win_prob", "source"}
    assert required_keys.issubset(result.keys()), f"Missing keys: {required_keys - set(result.keys())}"


# ---------------------------------------------------------------------------
# Test 9: backward compat — no artifact, still returns valid predict()
# ---------------------------------------------------------------------------

def test_fallback_backward_compat(tmp_path, monkeypatch):
    """No artifact → predict() returns source='market_implied' dict as before."""
    missing_path = tmp_path / "absent.pkl"
    monkeypatch.setattr(soccer_model_module, "_EPL_ARTIFACT", missing_path)
    monkeypatch.setattr(soccer_model_module.SoccerModel, "_load_xgb_models", lambda self: None)

    from alpha.engines.sports.soccer_model import SoccerModel
    model = SoccerModel()
    game = {"home_team": "Arsenal", "away_team": "Chelsea", "home_odds": -110, "draw_odds": 300, "away_odds": 250}
    result = model.predict(game)

    assert result["source"] == "market_implied"
    assert result["home_team"] == "Arsenal"
    assert result["away_team"] == "Chelsea"
    assert 0.0 < result["home_win_prob"] < 1.0
    assert 0.0 < result["draw_prob"] < 1.0
    assert 0.0 < result["away_win_prob"] < 1.0
