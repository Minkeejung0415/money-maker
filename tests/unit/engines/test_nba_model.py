from unittest.mock import MagicMock, patch
import pytest
from alpha.engines.sports.nba_model import NBAModel


_GAME = {
    "home_team": "Lakers",
    "away_team": "Celtics",
    "home_odds": -150,   # American odds
    "away_odds": +130,
    "over_under": 220.5,
}


# ---------------------------------------------------------------------------
# Existing baseline tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# New tests for XGBoost wiring (Improvement #1)
# ---------------------------------------------------------------------------

def test_predict_returns_source_field():
    """predict() must always include a 'source' field."""
    model = NBAModel()
    result = model.predict(_GAME)
    assert "source" in result
    assert result["source"] in ("xgboost", "market_implied")


def test_predict_probs_sum_to_one_regardless_of_source():
    """home_win_prob + away_win_prob must equal ~1.0 for any source."""
    model = NBAModel()
    result = model.predict(_GAME)
    total = result["home_win_prob"] + result["away_win_prob"]
    assert abs(total - 1.0) < 1e-6


def test_predict_market_implied_when_sqlite_unavailable():
    """
    When _get_latest_team_df returns None (no SQLite data), predict()
    must fall back to market_implied.
    """
    model = NBAModel()
    model._xgb_models_loaded = True  # pretend model is loaded

    with patch.object(model, "_get_latest_team_df", return_value=None):
        result = model.predict(_GAME)

    assert result["source"] == "market_implied"
    assert abs(result["home_win_prob"] + result["away_win_prob"] - 1.0) < 1e-6


def test_predict_market_implied_when_xgb_not_loaded():
    """When XGBoost models aren't loaded, predict() uses market_implied."""
    model = NBAModel()
    model._xgb_models_loaded = False  # force fallback

    result = model.predict(_GAME)
    assert result["source"] == "market_implied"
    assert 0.0 <= result["home_win_prob"] <= 1.0
    assert 0.0 <= result["away_win_prob"] <= 1.0


def test_predict_fallback_when_xgb_raises():
    """If _predict_xgb raises an exception, predict() must still return valid result."""
    model = NBAModel()
    model._xgb_models_loaded = True

    with patch.object(model, "_predict_xgb", side_effect=RuntimeError("boom")):
        result = model.predict(_GAME)

    assert result["source"] == "market_implied"
    assert abs(result["home_win_prob"] + result["away_win_prob"] - 1.0) < 1e-6


def test_refresh_stats_returns_bool():
    """refresh_stats() must return True or False (never raise)."""
    model = NBAModel()
    # We mock Get_Data.main to avoid real network calls
    with patch("importlib.util.spec_from_file_location", side_effect=ImportError("no file")):
        result = model.refresh_stats()
    assert isinstance(result, bool)
    assert result is False  # should fail gracefully


def test_refresh_stats_returns_false_on_network_error():
    """If Get_Data.main() raises, refresh_stats() returns False without raising."""
    model = NBAModel()

    # Simulate a network failure inside Get_Data.main
    fake_mod = MagicMock()
    fake_mod.main.side_effect = ConnectionError("NBA API down")

    with patch("importlib.util.spec_from_file_location") as mock_spec_fn, \
         patch("importlib.util.module_from_spec", return_value=fake_mod):
        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()
        mock_spec_fn.return_value = mock_spec

        result = model.refresh_stats()

    assert result is False


def test_predict_valid_after_refresh_stats_fails():
    """Even if refresh_stats() returns False, predict() must still produce valid output."""
    model = NBAModel()
    model._xgb_models_loaded = False  # ensure market-implied path

    with patch("importlib.util.spec_from_file_location", side_effect=ImportError):
        model.refresh_stats()  # fails silently

    result = model.predict(_GAME)
    assert "home_win_prob" in result
    assert "away_win_prob" in result
    assert abs(result["home_win_prob"] + result["away_win_prob"] - 1.0) < 1e-6
