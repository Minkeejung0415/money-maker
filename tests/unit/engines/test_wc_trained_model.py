from __future__ import annotations

import pickle

import pytest

from alpha.engines.sports.wc_trained_model import (
    FEATURE_NAMES,
    WCTrainedInternationalModel,
    build_runtime_features,
    normalize_team_name,
)


class FakeModel:
    classes_ = ["A", "D", "H"]

    def predict_proba(self, _x):
        return [[0.25, 0.20, 0.55]]


def test_normalize_team_name_handles_common_fixture_aliases():
    assert normalize_team_name("USA") == "United States"
    assert normalize_team_name("DR Congo") == "Congo DR"
    assert normalize_team_name("Cape Verde") == "Cape Verde Islands"


def test_build_runtime_features_has_numeric_host_flags_when_country_missing():
    features = build_runtime_features("Brazil", "Japan", ratings={"Brazil": 1600, "Japan": 1500}, country="")
    assert set(FEATURE_NAMES) <= set(features)
    assert features["home_host"] == 0.0
    assert features["away_host"] == 0.0
    assert all(isinstance(features[name], float) for name in FEATURE_NAMES)


def test_trained_model_predicts_90_minute_distribution(tmp_path):
    artifact = {
        "model_id": "wc_international_1x2_v1",
        "model": FakeModel(),
        "classes": ["A", "D", "H"],
        "ratings": {"Brazil": 1600.0, "Japan": 1500.0},
    }
    path = tmp_path / "wc.pkl"
    with path.open("wb") as handle:
        pickle.dump(artifact, handle)

    model = WCTrainedInternationalModel(path)
    result = model.predict_90_minute({
        "home_team": "Brazil",
        "away_team": "Japan",
        "league": "wc",
        "stage": "LAST_32",
    })

    assert result["win_prob"] == pytest.approx(0.55, abs=0.001)
    assert result["draw_prob"] == pytest.approx(0.20, abs=0.001)
    assert result["loss_prob"] == pytest.approx(0.25, abs=0.001)
    assert result["market_type"] == "90_minute"
    assert result["model_name"] == "wc_international_1x2_v1"


def test_trained_model_predict_suppresses_draw_for_knockout_advance(tmp_path):
    artifact = {
        "model_id": "wc_international_1x2_v1",
        "model": FakeModel(),
        "classes": ["A", "D", "H"],
        "ratings": {"Brazil": 1600.0, "Japan": 1500.0},
    }
    path = tmp_path / "wc.pkl"
    with path.open("wb") as handle:
        pickle.dump(artifact, handle)

    result = WCTrainedInternationalModel(path).predict({
        "home_team": "Brazil",
        "away_team": "Japan",
        "league": "wc",
        "stage": "LAST_32",
    })

    assert result["draw_prob"] == 0.0
    assert result["win_prob"] + result["loss_prob"] == pytest.approx(1.0, abs=0.001)
    assert result["market_type"] == "advance"
