import joblib
import numpy as np
from alpha.engines.sports.mlb_model import MLBModel
from alpha.engines.sports.mlb_player_modeling import PLAYER_FEATURE_SETS


class ConstantProbModel:
    def __init__(self, prob=0.58):
        self.prob = prob

    def predict_proba(self, x):
        positive = np.full(len(x), self.prob)
        return np.column_stack((1.0 - positive, positive))


class IdentityCalibrator:
    def predict(self, raw_probs):
        return list(raw_probs)


def _player_features(**overrides):
    values = {name: 0.0 for name in PLAYER_FEATURE_SETS["full_player_aware"]}
    values.update({
        "home_indicator": 1.0,
        "home_win_pct": 0.55,
        "away_win_pct": 0.45,
        "lineup_missing_count_total": 0.0,
        "player_feature_missing_flag": 0.0,
    })
    values.update(overrides)
    return values


def _valid_player_artifact(**overrides):
    artifact = {
        "kind": "mlb_player_moneyline_artifact",
        "schema_version": "mlb-player-v1.8",
        "model_version": "mlb-player-v1.8",
        "validated": True,
        "promotion_gates": {
            "baseline_available": True,
            "candidate_improves_baseline_brier": True,
            "has_walkforward_folds": True,
            "has_feature_schema": True,
        },
        "feature_names": list(PLAYER_FEATURE_SETS["full_player_aware"]),
        "model": ConstantProbModel(0.58),
        "calibrator": IdentityCalibrator(),
        "metrics": {
            "coverage": 0.72,
            "selective_win_rate": 0.57,
            "accuracy": 0.54,
            "brier_score": 0.22,
            "log_loss": 0.64,
        },
    }
    artifact.update(overrides)
    return artifact


def test_unvalidated_bundle_is_rejected(tmp_path, monkeypatch):
    path=tmp_path/"mlb_win_probability.pkl"; joblib.dump({"kind":"mlb_win_probability_bundle","validated":False},path)
    monkeypatch.setattr(MLBModel,"_find_model_paths",lambda self:[path])
    model=MLBModel(); assert not model._xgb_models_loaded


def test_schema_mismatch_is_rejected(tmp_path, monkeypatch):
    path=tmp_path/"mlb_win_probability.pkl"; joblib.dump({"kind":"mlb_win_probability_bundle","validated":True,"feature_names":["bad"]},path)
    monkeypatch.setattr(MLBModel,"_find_model_paths",lambda self:[path])
    model=MLBModel(); assert not model._xgb_models_loaded


def test_valid_player_aware_artifact_scores_precomputed_features(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(_valid_player_artifact(), path)
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -120,
        "away_odds": 105,
        "player_features": _player_features(elo_diff=10.0),
    })

    assert pred["source"] == "player_aware"
    assert pred["model_label"] == "v1.8 player-aware"
    assert pred["confidence"] == "HIGH"
    assert pred["pick_eligible"] is True
    assert model.runtime_report()["selective_report"]["brier_score"] == 0.22


def test_player_aware_uncertainty_suppresses_pick(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(_valid_player_artifact(), path)
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -120,
        "away_odds": 105,
        "player_features": _player_features(lineup_missing_count_total=2.0),
    })

    assert pred["source"] == "player_aware"
    assert pred["confidence"] == "LOW"
    assert pred["pick_eligible"] is False
    assert "lineup_missing" in pred["uncertainty_flags"]


def test_invalid_player_aware_artifact_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(_valid_player_artifact(validated=False), path)
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()

    assert not model._xgb_models_loaded
    assert "player_validation_failed" in model.runtime_report()["rejections"][0]


def test_legacy_non_bundle_artifact_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "legacy.pkl"
    joblib.dump(ConstantProbModel(), path)
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()

    assert not model._xgb_models_loaded
    assert "legacy_artifact_unsupported" in model.runtime_report()["rejections"][0]
