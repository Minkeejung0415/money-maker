"""Tests for alpha/engines/sports/mlb_model.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from alpha.engines.sports.mlb_model import MAX_XGB_CONF, MLBModel


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_mlb_model_init():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    assert hasattr(model, "ev_calc")
    assert not model._xgb_models_loaded


def test_mlb_model_max_xgb_conf():
    assert MAX_XGB_CONF == 0.72


# ---------------------------------------------------------------------------
# _market_implied_predict
# ---------------------------------------------------------------------------

def test_market_implied_predict_sums_to_1():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -130, "away_odds": 110}
    pred = model._market_implied_predict(game)
    assert pred["home_win_prob"] + pred["away_win_prob"] == pytest.approx(1.0, abs=0.001)


def test_market_implied_predict_source_is_market_implied():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -130, "away_odds": 110}
    pred = model._market_implied_predict(game)
    assert pred["source"] == "market_implied"


def test_market_implied_predict_favorite_higher_prob():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -200, "away_odds": 170}
    pred = model._market_implied_predict(game)
    assert pred["home_win_prob"] > pred["away_win_prob"]


# ---------------------------------------------------------------------------
# predict — fallback path
# ---------------------------------------------------------------------------

def test_predict_uses_market_implied_when_no_xgb():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    model._xgb_models_loaded = False
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -150, "away_odds": 130}
    pred = model.predict(game)
    assert pred["source"] == "market_implied"


def test_predict_has_required_keys():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -150, "away_odds": 130}
    pred = model.predict(game)
    for key in ("home_team", "away_team", "home_win_prob", "away_win_prob", "source"):
        assert key in pred


# ---------------------------------------------------------------------------
# evaluate_bet
# ---------------------------------------------------------------------------

def test_evaluate_bet_returns_no_bet_when_no_edge():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel(min_edge=0.99)
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -200, "away_odds": 170}
    result = model.evaluate_bet(game)
    assert result["bet_side"] == "no_bet"


def test_evaluate_bet_returns_home_or_away():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel(min_edge=0.0)
    # Force a clear home advantage
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -500, "away_odds": 400}
    result = model.evaluate_bet(game)
    assert result["bet_side"] in ("home", "away", "no_bet")


def test_evaluate_bet_has_required_keys():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -150, "away_odds": 130}
    result = model.evaluate_bet(game)
    for key in ("bet_side", "team", "model_prob", "decimal_odds", "ev"):
        assert key in result


# ---------------------------------------------------------------------------
# evaluate_batch
# ---------------------------------------------------------------------------

def test_evaluate_batch_returns_correct_length():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    games = [
        {"home_team": "NYY", "away_team": "BOS",
         "home_odds": -150, "away_odds": 130},
        {"home_team": "LAD", "away_team": "SFG",
         "home_odds": -120, "away_odds": 100},
    ]
    results = model.evaluate_batch(games)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# _credibility_filter
# ---------------------------------------------------------------------------

def test_credibility_filter_normalizes_to_1():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -150, "away_odds": 130}
    home_adj, away_adj = model._credibility_filter("NYY", "BOS", 0.55, 0.45, game)
    assert home_adj + away_adj == pytest.approx(1.0, abs=0.01)


def test_credibility_filter_reverts_big_underdog_artifact():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    game = {"home_team": "MIA", "away_team": "LAD",
            "home_odds": 400, "away_odds": -500}
    # XGB claims huge home win probability
    home_adj, away_adj = model._credibility_filter("MIA", "LAD", 0.85, 0.15, game)
    assert home_adj < 0.60


# ---------------------------------------------------------------------------
# _pitcher_adjusted_era
# ---------------------------------------------------------------------------

def test_pitcher_adjusted_era_returns_bullpen_era_when_no_pitcher():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    model._pitcher_loaded = True
    model._pitcher_cache = {}  # No pitcher found
    era = model._pitcher_adjusted_era("NYY", 4.0)
    from alpha.engines.sports.mlb_model import _BULLPEN_ERA
    assert era == _BULLPEN_ERA


def test_pitcher_adjusted_era_uses_pitcher_stats_when_available():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    model._pitcher_loaded = True
    model._pitcher_cache = {"NYY": "Gerrit Cole"}
    with patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats",
               return_value=[{"player": "Gerrit Cole", "team": "NYY", "era": 2.80,
                               "whip": 1.05, "k_per9": 12.0, "ip": 200.0}]):
        era = model._pitcher_adjusted_era("NYY", 4.0)
    assert era == pytest.approx(2.80)
