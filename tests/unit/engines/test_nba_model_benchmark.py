"""Stage 5 tests: market benchmark separation, model selection, schema safety."""
from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from alpha.engines.sports.nba_model import NBAModel

_GAME = {
    "home_team": "Los Angeles Lakers",
    "away_team": "Boston Celtics",
    "home_odds": -150,
    "away_odds": 130,
}


def _benchmark_model() -> NBAModel:
    model = NBAModel()
    model._xgb_models_loaded = False
    model._paint_deterrence = None
    model._foul_trouble = None
    model._opp_stats = None
    model._stats_cache = None
    return model


# ---------------------------------------------------------------------------
# Probability separation
# ---------------------------------------------------------------------------

def test_benchmark_prediction_separates_probabilities():
    model = _benchmark_model()
    result = model.predict(_GAME)

    assert result["source"] == "market_benchmark"
    assert result["independent_model_prob"] is None  # benchmark != model
    assert 0.0 < result["market_consensus_prob"] < 1.0
    assert result["final_calibrated_prob"] == result["home_win_prob"]


def test_xgboost_prediction_keeps_independent_prob_visible():
    model = _benchmark_model()
    model._xgb_models_loaded = True
    model._team_stats_cache = {}

    with patch.object(model, "_predict_xgb", return_value=(0.65, 0.35)):
        result = model.predict(_GAME)

    assert result["source"] == "xgboost"
    assert result["independent_model_prob"] == pytest.approx(0.65, abs=1e-6)
    assert result["market_consensus_prob"] is not None
    assert result["final_calibrated_prob"] == result["home_win_prob"]


def test_consensus_prob_from_odds_client_is_preferred():
    model = _benchmark_model()
    game = {**_GAME, "consensus_home_prob": 0.6123}
    result = model.predict(game)
    assert result["market_consensus_prob"] == pytest.approx(0.6123, abs=1e-4)


# ---------------------------------------------------------------------------
# No bets from the benchmark by default
# ---------------------------------------------------------------------------

def test_market_benchmark_never_emits_bet_by_default():
    model = _benchmark_model()
    assert model.allow_market_fallback_bets is False
    opp = model.evaluate_bet(_GAME)
    assert opp["bet_side"] == "no_bet"
    assert opp["reason"] == "market_benchmark_only"


def test_market_fallback_bets_can_be_enabled_for_research():
    model = NBAModel(allow_market_fallback_bets=True)
    model._xgb_models_loaded = False
    model._paint_deterrence = None
    model._foul_trouble = None
    model._opp_stats = None
    model._stats_cache = None

    opp = model.evaluate_bet(_GAME)
    # May still be no_bet on EV grounds, but not short-circuited.
    assert opp.get("reason") != "market_benchmark_only"


def test_xgboost_source_still_evaluates_bets():
    model = _benchmark_model()
    model._xgb_models_loaded = True
    model._team_stats_cache = {}

    with patch.object(model, "_predict_xgb", return_value=(0.72, 0.28)):
        opp = model.evaluate_bet(_GAME)
    assert opp["bet_side"] in ("home", "away", "no_bet")
    assert opp.get("reason") != "market_benchmark_only"


# ---------------------------------------------------------------------------
# Heuristic feature flags
# ---------------------------------------------------------------------------

def test_h2h_disabled_by_default():
    model = NBAModel()
    assert model.enable_h2h is False

    model._xgb_models_loaded = False
    model._paint_deterrence = None
    model._foul_trouble = None
    model._opp_stats = None
    cache = MagicMock()
    cache.fetch_team_recent_form = MagicMock(return_value=None)
    cache.fetch_head_to_head = MagicMock(return_value={"total_games": 6, "home_win_pct_h2h": 1.0})
    model._stats_cache = cache
    model._team_stats_cache = {}

    model.predict(_GAME)
    cache.fetch_head_to_head.assert_not_called()

    model.enable_h2h = True
    model.predict(_GAME)
    cache.fetch_head_to_head.assert_called()


def test_default_flag_values():
    model = NBAModel()
    assert model.enable_paint_deterrence is True
    assert model.enable_foul_exposure is True
    assert model.enable_recent_form is True
    assert model.enable_h2h is False
    assert model.enable_tanking_guard is True


def test_tanking_guard_flag_gates_discount():
    stats = {
        "Los Angeles Lakers": {"w_pct": 0.60, "wins": 45, "gp": 75},
        # w_pct kept above 0.25 so only the tanking check (W<20, GP>50)
        # can fire — isolating the flag under test.
        "Brooklyn Nets": {"w_pct": 0.26, "wins": 15, "gp": 75},
    }
    game = {"home_team": "Los Angeles Lakers", "away_team": "Brooklyn Nets",
            "home_odds": -110, "away_odds": 600}

    on = NBAModel(enable_tanking_guard=True)
    on._team_stats_cache = stats
    off = NBAModel(enable_tanking_guard=False)
    off._team_stats_cache = stats

    # Model prob close to market so caps/artifact checks don't fire.
    mkt_away = on._market_implied_predict(game)["away_win_prob"]
    raw_away = mkt_away + 0.10
    _, away_on = on._credibility_filter(
        "Los Angeles Lakers", "Brooklyn Nets", 1 - raw_away, raw_away, game)
    _, away_off = off._credibility_filter(
        "Los Angeles Lakers", "Brooklyn Nets", 1 - raw_away, raw_away, game)
    assert away_on < away_off  # guard pulls prob toward market only when enabled


# ---------------------------------------------------------------------------
# Model selection: validated metric first, mtime as tie-breaker
# ---------------------------------------------------------------------------

def test_model_selection_prefers_validated_accuracy(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.nba_model._MODEL_DIR", tmp_path)

    older_better = tmp_path / "XGBoost_68.9%_ML.json"
    newer_worse = tmp_path / "XGBoost_62.1%_ML.json"
    older_better.write_text("{}")
    newer_worse.write_text("{}")
    past = time.time() - 86400
    os.utime(older_better, (past, past))  # better model is OLDER

    model = NBAModel.__new__(NBAModel)
    assert model._select_model_path("ML") == older_better


def test_model_selection_mtime_breaks_ties(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.nba_model._MODEL_DIR", tmp_path)

    old = tmp_path / "XGBoost_65.0%_ML_a.json"
    new = tmp_path / "XGBoost_65.0%_ML_b.json"
    old.write_text("{}")
    new.write_text("{}")
    past = time.time() - 86400
    os.utime(old, (past, past))

    model = NBAModel.__new__(NBAModel)
    assert model._select_model_path("ML") == new


def test_model_selection_meta_json_overrides_filename(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.nba_model._MODEL_DIR", tmp_path)

    filename_says_better = tmp_path / "XGBoost_68.9%_ML.json"
    meta_says_better = tmp_path / "XGBoost_60.0%_ML.json"
    filename_says_better.write_text("{}")
    meta_says_better.write_text("{}")
    # Sidecar metadata carries the real validated accuracy.
    (tmp_path / "XGBoost_60.0%_ML.meta.json").write_text(
        json.dumps({"accuracy": 71.5}))

    model = NBAModel.__new__(NBAModel)
    assert model._select_model_path("ML") == meta_says_better


def test_save_model_metadata_roundtrip(tmp_path):
    model_path = tmp_path / "XGBoost_65.0%_ML.json"
    model_path.write_text("{}")
    meta_path = NBAModel.save_model_metadata(
        model_path,
        model_version="ml-1.0.0",
        trained_at="2026-06-01T00:00:00Z",
        feature_schema_version="1.0",
        validation_period={"start": "2025-10-01", "end": "2026-04-01"},
        brier_score=0.21,
        log_loss=0.62,
        accuracy=66.4,
        sample_count=1230,
    )
    meta = json.loads(meta_path.read_text())
    assert meta["brier_score"] == 0.21
    assert meta["sample_count"] == 1230
    assert NBAModel._validated_accuracy(model_path) == 66.4


# ---------------------------------------------------------------------------
# TEAM_NAME-based feature lookup (no positional iloc)
# ---------------------------------------------------------------------------

def test_build_game_features_uses_team_name_not_position():
    import pandas as pd

    # Deliberately shuffled order: positional index would pair wrong teams.
    team_df = pd.DataFrame([
        {"TEAM_NAME": "Boston Celtics", "PTS": 118.0, "W_PCT": 0.65},
        {"TEAM_NAME": "Los Angeles Lakers", "PTS": 112.0, "W_PCT": 0.55},
        {"TEAM_NAME": "Miami Heat", "PTS": 108.0, "W_PCT": 0.45},
    ])
    model = NBAModel.__new__(NBAModel)
    series = model._build_game_features(team_df, "Los Angeles Lakers", "Boston Celtics")

    assert series is not None
    assert series["PTS"] == 112.0       # home = Lakers
    assert series["PTS.1"] == 118.0     # away = Celtics


def test_build_game_features_fails_closed_on_unknown_team():
    import pandas as pd
    team_df = pd.DataFrame([{"TEAM_NAME": "Miami Heat", "PTS": 108.0}])
    model = NBAModel.__new__(NBAModel)
    assert model._build_game_features(team_df, "Atlantis Krakens", "Miami Heat") is None


def test_build_game_features_fails_closed_without_team_name_column():
    import pandas as pd
    team_df = pd.DataFrame([{"PTS": 108.0}])
    model = NBAModel.__new__(NBAModel)
    assert model._build_game_features(team_df, "Miami Heat", "Boston Celtics") is None


# ---------------------------------------------------------------------------
# Feature schema fail-closed
# ---------------------------------------------------------------------------

def test_missing_model_features_fail_closed_to_benchmark():
    import pandas as pd

    model = _benchmark_model()
    model._xgb_models_loaded = True
    model._injury_loaded = True
    model._injury_impact = {}

    booster = MagicMock()
    booster.feature_names = ["PTS", "W_PCT", "FEATURE_THAT_DOES_NOT_EXIST"]
    model._xgb_ml = booster
    model._xgb_ml_calibrator = None

    team_df = pd.DataFrame([
        {"TEAM_NAME": "Los Angeles Lakers", "PTS": 112.0, "W_PCT": 0.55},
        {"TEAM_NAME": "Boston Celtics", "PTS": 118.0, "W_PCT": 0.65},
    ])
    with patch.object(model, "_get_latest_team_df", return_value=team_df), \
         patch.object(model, "_get_days_rest", return_value=(2, 2)):
        result = model.predict(_GAME)

    assert result["source"] == "market_benchmark"
    booster.predict.assert_not_called()
