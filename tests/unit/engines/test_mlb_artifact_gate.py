import joblib
import numpy as np
from alpha.engines.sports.mlb_model import MLBModel
from alpha.engines.sports.mlb_player_modeling import PLAYER_FEATURE_SETS
from alpha.engines.sports.mlb_training import FEATURE_NAMES


class ConstantProbModel:
    def __init__(self, prob=0.58):
        self.prob = prob

    def predict_proba(self, x):
        positive = np.full(len(x), self.prob)
        return np.column_stack((1.0 - positive, positive))


class IdentityCalibrator:
    def predict(self, raw_probs):
        return list(raw_probs)


class PredictProbaCalibrator:
    def predict_proba(self, x):
        positive = np.full(len(x), 0.56)
        return np.column_stack((1.0 - positive, positive))


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


def _valid_baseline_artifact(**overrides):
    artifact = {
        "kind": "mlb_win_probability_bundle",
        "validated": True,
        "feature_names": list(FEATURE_NAMES),
        "model": ConstantProbModel(0.56),
        "calibrator": PredictProbaCalibrator(),
        "team_state": {},
        "metrics": {"brier_score": 0.24, "log_loss": 0.68, "accuracy": 0.52},
        "version": "mlb-v1.3",
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


def test_starter_only_artifact_gets_capped_runtime_starter_run_adjustment(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(
        _valid_player_artifact(
            schema_version="mlb-player-v2.3",
            model_version="mlb-player-v2.3",
            candidate={"feature_set": "starter_run_offset", "model": "starter_only_logit_offset"},
            feature_names=list(PLAYER_FEATURE_SETS["starter_only"]),
            model=ConstantProbModel(0.50),
            offset_config={
                "model_id": "mlb_starter_offset_v23",
                "base_model": "starter_only_logistic",
                "feature": "starter_run_value_diff",
                "beta": 0.08,
                "cap": 0.75,
            },
        ),
        path,
    )
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -110,
        "away_odds": -110,
        "player_features": _player_features(
            elo_diff=10.0,
            starter_run_value_diff=0.50,
            absence_value_diff=0.0,
        ),
    })

    assert pred["home_win_prob"] > 0.50
    assert pred["feature_context"]["runtime_context_adjustment"] > 0.0


def test_starter_only_artifact_without_offset_config_does_not_adjust(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(
        _valid_player_artifact(
            feature_names=list(PLAYER_FEATURE_SETS["starter_only"]),
            model=ConstantProbModel(0.50),
        ),
        path,
    )
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -110,
        "away_odds": -110,
        "player_features": _player_features(
            elo_diff=10.0,
            starter_run_value_diff=0.50,
        ),
    })

    assert pred["home_win_prob"] == 0.50
    assert "runtime_context_adjustment" not in pred["feature_context"]


def test_full_player_artifact_does_not_double_count_lineup_adjustment(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(_valid_player_artifact(model=ConstantProbModel(0.50)), path)
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -110,
        "away_odds": -110,
        "player_features": _player_features(
            elo_diff=10.0,
            lineup_strength_diff=0.30,
            top_order_strength_diff=0.20,
            bullpen_quality_diff=0.10,
        ),
    })

    assert pred["home_win_prob"] == 0.50
    assert "runtime_context_adjustment" not in pred["feature_context"]


def test_v23_artifact_is_accepted_and_labeled(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(
        _valid_player_artifact(
            schema_version="mlb-player-v2.3",
            model_version="mlb-player-v2.3",
            candidate={"feature_set": "starter_lineup_bullpen", "model": "logistic"},
            feature_names=list(PLAYER_FEATURE_SETS["starter_lineup_bullpen"]),
        ),
        path,
    )
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -120,
        "away_odds": 105,
        "player_features": _player_features(elo_diff=10.0),
    })

    assert pred["model_label"] == "v2.3 player-aware lineup/bullpen"
    assert model.runtime_report()["source"] == "v2.3 player-aware lineup/bullpen"


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


def test_player_aware_stale_database_features_suppress_pick(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(_valid_player_artifact(), path)
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -120,
        "away_odds": 105,
        "player_features": _player_features(player_data_stale_flag=1.0),
    })

    assert pred["source"] == "player_aware"
    assert pred["confidence"] == "LOW"
    assert pred["pick_eligible"] is False
    assert "player_data_stale" in pred["uncertainty_flags"]


def test_player_aware_low_lineup_confidence_suppresses_pick(tmp_path, monkeypatch):
    path = tmp_path / "mlb_player_moneyline.pkl"
    joblib.dump(_valid_player_artifact(), path)
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -120,
        "away_odds": 105,
        "player_features": _player_features(lineup_source_confidence=0.4),
    })

    assert pred["source"] == "player_aware"
    assert pred["confidence"] == "LOW"
    assert pred["pick_eligible"] is False
    assert "low_lineup_source_confidence" in pred["uncertainty_flags"]


def test_player_aware_missing_features_falls_back_to_v1_3_bundle(tmp_path, monkeypatch):
    player_path = tmp_path / "mlb_player_moneyline.pkl"
    baseline_path = tmp_path / "mlb_win_probability.pkl"
    joblib.dump(_valid_player_artifact(), player_path)
    joblib.dump(_valid_baseline_artifact(), baseline_path)
    monkeypatch.setattr(MLBModel, "_find_model_paths", lambda self: [player_path, baseline_path])

    model = MLBModel()
    pred = model.predict({
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": -120,
        "away_odds": 105,
    })

    assert pred["source"] == "trained_calibrated"
    assert pred["model_label"] == "v1.3 baseline fallback"
    assert pred["fallback_reason"].startswith("missing_player_features:")


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
