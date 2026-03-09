import pytest
from alpha.engines.sports.nba_model import NBAModel


_GAME = {
    "home_team": "Lakers",
    "away_team": "Celtics",
    "home_odds": -150,   # American odds
    "away_odds": +130,
    "over_under": 220.5,
}


def test_model_initializes():
    model = NBAModel()
    assert model is not None


def test_predict_returns_probs():
    model = NBAModel()
    result = model.predict(_GAME)
    assert "home_win_prob" in result
    assert "away_win_prob" in result
    assert abs(result["home_win_prob"] + result["away_win_prob"] - 1.0) < 1e-6


def test_predict_probs_in_range():
    model = NBAModel()
    result = model.predict(_GAME)
    assert 0.0 <= result["home_win_prob"] <= 1.0
    assert 0.0 <= result["away_win_prob"] <= 1.0


def test_evaluate_bet_returns_opportunity():
    model = NBAModel()
    opp = model.evaluate_bet(_GAME)
    assert "bet_side" in opp
    assert opp["bet_side"] in ("home", "away", "no_bet")
    assert "ev" in opp
    assert "model_prob" in opp


def test_evaluate_batch():
    model = NBAModel()
    games = [_GAME, {**_GAME, "home_team": "Warriors", "away_team": "Heat",
                     "home_odds": +110, "away_odds": -130}]
    results = model.evaluate_batch(games)
    assert len(results) == 2
