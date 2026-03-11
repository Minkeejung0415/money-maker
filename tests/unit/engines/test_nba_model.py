from unittest.mock import MagicMock, patch
import pytest
from alpha.engines.sports.nba_model import NBAModel, MAX_XGB_CONF


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


# ---------------------------------------------------------------------------
# Fix 7: Team name normalization tests
# ---------------------------------------------------------------------------

def test_normalize_team_la_lakers():
    assert NBAModel._normalize_team("LA Lakers") == "Los Angeles Lakers"


def test_normalize_team_gs_warriors():
    assert NBAModel._normalize_team("GS Warriors") == "Golden State Warriors"


def test_normalize_team_ny_knicks():
    assert NBAModel._normalize_team("NY Knicks") == "New York Knicks"


def test_normalize_team_exact_match():
    """A canonical name should be returned unchanged."""
    assert NBAModel._normalize_team("Boston Celtics") == "Boston Celtics"


def test_normalize_team_unknown_no_crash():
    """An unrecognized name must be returned as-is without raising."""
    result = NBAModel._normalize_team("unknown team xyz")
    assert result == "unknown team xyz"


def test_normalize_team_case_insensitive_map():
    """Lowercase variant of a mapped name should still resolve."""
    assert NBAModel._normalize_team("la lakers") == "Los Angeles Lakers"


def test_predict_normalizes_team_names():
    """predict() should internally normalize team names before building features."""
    model = NBAModel()
    model._xgb_models_loaded = False
    game = {
        "home_team": "LA Lakers",
        "away_team": "GS Warriors",
        "home_odds": -150,
        "away_odds": +130,
    }
    result = model.predict(game)
    assert "home_win_prob" in result
    assert abs(result["home_win_prob"] + result["away_win_prob"] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# XGBoost confidence cap tests
# ---------------------------------------------------------------------------

def test_xgb_confidence_cap_fires_on_heavy_favorite():
    """
    When XGBoost returns >MAX_XGB_CONF for the home team, predict() must
    cap it to MAX_XGB_CONF before the credibility filter runs.
    """
    model = NBAModel()
    model._xgb_models_loaded = True
    model._team_stats_cache = {}  # empty → credibility filter is a no-op

    with patch.object(model, "_predict_xgb", return_value=(0.90, 0.10)):
        result = model.predict(_GAME)

    assert result["home_win_prob"] <= MAX_XGB_CONF + 1e-6
    assert abs(result["home_win_prob"] + result["away_win_prob"] - 1.0) < 1e-6


def test_xgb_confidence_cap_fires_on_heavy_away_favorite():
    """Same cap applies when away team is the heavy favorite."""
    model = NBAModel()
    model._xgb_models_loaded = True
    model._team_stats_cache = {}

    with patch.object(model, "_predict_xgb", return_value=(0.08, 0.92)):
        result = model.predict(_GAME)

    assert result["away_win_prob"] <= MAX_XGB_CONF + 1e-6
    assert abs(result["home_win_prob"] + result["away_win_prob"] - 1.0) < 1e-6


def test_xgb_confidence_cap_not_triggered_for_normal_prediction():
    """A normal 65/35 split should pass through unchanged."""
    model = NBAModel()
    model._xgb_models_loaded = True
    model._team_stats_cache = {}

    with patch.object(model, "_predict_xgb", return_value=(0.65, 0.35)):
        result = model.predict(_GAME)

    assert abs(result["home_win_prob"] - 0.65) < 0.02
    assert abs(result["home_win_prob"] + result["away_win_prob"] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Credibility filter tests
# ---------------------------------------------------------------------------

def _make_model_with_stats(stats: dict) -> NBAModel:
    """Return a model with a pre-loaded _team_stats_cache."""
    model = NBAModel()
    model._team_stats_cache = stats
    return model


_UNDERDOG_GAME = {
    "home_team": "Los Angeles Lakers",
    "away_team": "Brooklyn Nets",
    "home_odds": -110,
    "away_odds": +600,   # big underdog, decimal ~7.0
}


def test_credibility_filter_no_op_for_good_teams():
    """Filter should not change probs when both teams have solid records."""
    model = _make_model_with_stats({
        "Los Angeles Lakers": {"w_pct": 0.60, "wins": 45, "gp": 75},
        "Boston Celtics": {"w_pct": 0.65, "wins": 49, "gp": 75},
    })
    game = {**_GAME, "home_odds": -150, "away_odds": +130}
    # Probs that don't diverge enough from market to trigger artifact check
    hp, ap = model._credibility_filter(
        "Los Angeles Lakers", "Boston Celtics", 0.62, 0.38, game
    )
    assert abs(hp + ap - 1.0) < 1e-6
    # Should be close to input (no filter triggered)
    assert abs(hp - 0.62) < 0.02


def test_credibility_filter_win_rate_cap():
    """W_PCT < 0.25 should pull the model's away prob down toward market-implied."""
    model = _make_model_with_stats({
        "Los Angeles Lakers": {"w_pct": 0.60, "wins": 45, "gp": 75},
        "Brooklyn Nets": {"w_pct": 0.15, "wins": 10, "gp": 65},
    })
    # Model gives Brooklyn 0.35, but market (~0.21 for +600) should cap it
    raw_away = 0.35
    hp, ap = model._credibility_filter(
        "Los Angeles Lakers", "Brooklyn Nets", 0.65, raw_away, _UNDERDOG_GAME
    )
    assert abs(hp + ap - 1.0) < 1e-6
    # Filter should have reduced the away prob from raw input
    assert ap < raw_away


def test_credibility_filter_tanking_discount():
    """W < 20 and GP > 50 should blend model 50% toward market."""
    model = _make_model_with_stats({
        "Los Angeles Lakers": {"w_pct": 0.60, "wins": 45, "gp": 75},
        "Brooklyn Nets": {"w_pct": 0.20, "wins": 15, "gp": 75},
    })
    market = model._market_implied_predict(_UNDERDOG_GAME)
    raw_away = 0.30
    hp, ap = model._credibility_filter(
        "Los Angeles Lakers", "Brooklyn Nets", 0.70, raw_away, _UNDERDOG_GAME
    )
    assert abs(hp + ap - 1.0) < 1e-6
    # After tanking discount + re-normalize, away prob should be < raw input
    assert ap < raw_away + 1e-6


def test_credibility_filter_big_underdog_artifact():
    """Model that gives >15% boost to a +600 underdog should be pulled back toward market."""
    model = _make_model_with_stats({
        "Los Angeles Lakers": {"w_pct": 0.60, "wins": 45, "gp": 75},
        "Brooklyn Nets": {"w_pct": 0.50, "wins": 38, "gp": 75},
    })
    # Market implies ~0.21 for +600 away; model says 0.40 — diff 0.19 > 0.15 threshold
    raw_away = 0.40
    hp, ap = model._credibility_filter(
        "Los Angeles Lakers", "Brooklyn Nets", 0.60, raw_away, _UNDERDOG_GAME
    )
    assert abs(hp + ap - 1.0) < 1e-6
    # Artifact check should have pulled away prob significantly below the raw model input
    assert ap < raw_away - 0.05


def test_credibility_filter_probs_always_sum_to_one():
    """Output probs must always sum to 1.0 regardless of which filters fire."""
    model = _make_model_with_stats({
        "Los Angeles Lakers": {"w_pct": 0.10, "wins": 5, "gp": 60},
        "Brooklyn Nets": {"w_pct": 0.10, "wins": 5, "gp": 60},
    })
    hp, ap = model._credibility_filter(
        "Los Angeles Lakers", "Brooklyn Nets", 0.85, 0.15, _UNDERDOG_GAME
    )
    assert abs(hp + ap - 1.0) < 1e-6


def test_credibility_filter_no_sqlite_data_is_safe():
    """Filter must not raise when team stats are unavailable (empty cache)."""
    model = _make_model_with_stats({})  # no data at all
    game = {**_GAME, "home_odds": -150, "away_odds": +130}
    hp, ap = model._credibility_filter("Los Angeles Lakers", "Boston Celtics", 0.62, 0.38, game)
    assert abs(hp + ap - 1.0) < 1e-6
