"""Tests for alpha/engines/sports/soccer_model.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from alpha.engines.sports.soccer_model import MAX_XGB_CONF, SoccerModel


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_soccer_model_init():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    assert hasattr(model, "ev_calc")
    assert not model._xgb_models_loaded


def test_soccer_model_max_xgb_conf():
    assert MAX_XGB_CONF == 0.70


# ---------------------------------------------------------------------------
# _market_implied_predict
# ---------------------------------------------------------------------------

def test_market_implied_predict_3way_sums_to_1():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    game = {
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_odds": -120,
        "draw_odds": 250,
        "away_odds": 300,
    }
    pred = model._market_implied_predict(game)
    total = pred["home_win_prob"] + pred["draw_prob"] + pred["away_win_prob"]
    assert total == pytest.approx(1.0, abs=0.01)


def test_market_implied_predict_has_required_keys():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    game = {"home_team": "Arsenal", "away_team": "Chelsea",
            "home_odds": -120, "draw_odds": 250, "away_odds": 300}
    pred = model._market_implied_predict(game)
    assert "home_win_prob" in pred
    assert "draw_prob" in pred
    assert "away_win_prob" in pred
    assert pred["source"] == "market_implied"


def test_market_implied_predict_draw_prob_positive():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    game = {"home_team": "A", "away_team": "B",
            "home_odds": 150, "draw_odds": 200, "away_odds": 150}
    pred = model._market_implied_predict(game)
    assert pred["draw_prob"] > 0


# ---------------------------------------------------------------------------
# predict — fallback path
# ---------------------------------------------------------------------------

def test_predict_falls_back_to_market_implied_when_no_xgb():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    model._xgb_models_loaded = False
    game = {"home_team": "Arsenal", "away_team": "Chelsea",
            "home_odds": -140, "draw_odds": 260, "away_odds": 350}
    pred = model.predict(game)
    assert pred["source"] == "market_implied"


def test_predict_returns_all_three_probs():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    game = {"home_team": "Arsenal", "away_team": "Chelsea",
            "home_odds": -140, "draw_odds": 260, "away_odds": 350}
    pred = model.predict(game)
    assert "home_win_prob" in pred
    assert "draw_prob" in pred
    assert "away_win_prob" in pred


# ---------------------------------------------------------------------------
# evaluate_bet — skips draw
# ---------------------------------------------------------------------------

def test_evaluate_bet_skips_draw_bets():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    model._xgb_models_loaded = False
    game = {
        "home_team": "Arsenal", "away_team": "Chelsea",
        "home_odds": -140, "draw_odds": 260, "away_odds": 350,
    }
    result = model.evaluate_bet(game)
    assert result["bet_side"] in ("home", "away", "no_bet")


def test_evaluate_bet_returns_no_bet_when_no_edge():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel(min_edge=0.99)  # impossibly high edge requirement
    game = {
        "home_team": "Arsenal", "away_team": "Chelsea",
        "home_odds": -200, "draw_odds": 300, "away_odds": 600,
    }
    result = model.evaluate_bet(game)
    assert result["bet_side"] == "no_bet"


# ---------------------------------------------------------------------------
# evaluate_batch
# ---------------------------------------------------------------------------

def test_evaluate_batch_returns_list_of_same_length():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    games = [
        {"home_team": "A", "away_team": "B",
         "home_odds": -120, "draw_odds": 250, "away_odds": 300},
        {"home_team": "C", "away_team": "D",
         "home_odds": 110, "draw_odds": 220, "away_odds": -130},
    ]
    results = model.evaluate_batch(games)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# _credibility_filter
# ---------------------------------------------------------------------------

def test_credibility_filter_revertes_large_underdog_artifact():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    game = {
        "home_team": "Brentford", "away_team": "Man City",
        "home_odds": 600, "draw_odds": 350, "away_odds": -400,
    }
    # Model says home_prob = 0.80, clearly an artifact for a big underdog
    home_adj, away_adj = model._credibility_filter(
        "Brentford", "Man City", 0.80, 0.15, game
    )
    # Should have reverted closer to market
    assert home_adj < 0.60


# ---------------------------------------------------------------------------
# XGBoost cap enforcement
# ---------------------------------------------------------------------------

def test_predict_caps_xgb_probability():
    with patch("alpha.engines.sports.soccer_model.SoccerModel._load_xgb_models"):
        model = SoccerModel()
    model._xgb_models_loaded = True

    # Mock _predict_xgb to return high but plausible confidence (0.80 home, 0.10 draw, 0.10 away)
    # After capping at 0.70 and re-normalizing: home = 0.70/(0.70+0.10+0.10) = 0.778
    # After re-clamping: home = min(0.778, 0.70) = 0.70
    with patch.object(model, "_predict_xgb", return_value=(0.80, 0.10, 0.10)):
        with patch.object(model, "_credibility_filter", side_effect=lambda ht, at, hp, ap, g: (hp, ap)):
            game = {
                "home_team": "Arsenal", "away_team": "Chelsea",
                "home_odds": -200, "draw_odds": 300, "away_odds": 500,
            }
            pred = model.predict(game)

    assert pred["home_win_prob"] <= MAX_XGB_CONF + 0.001
