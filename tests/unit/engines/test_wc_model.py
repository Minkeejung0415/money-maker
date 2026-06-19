"""Tests for alpha/engines/sports/wc_model.py."""
from __future__ import annotations

import inspect

import pytest

from alpha.engines.sports.wc_model import WCMatchModel, _WC_DRAW_RATE, KNOCKOUT_STAGES

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_FAKE_ELO: dict[str, int] = {
    "Brazil": 2100,
    "Germany": 1980,
    "France": 2050,
    "Argentina": 2070,
}

_FAKE_STATS: dict[str, dict] = {
    "Brazil": {"avg_goals": 2.1, "avg_xG": 1.9, "avg_shots": 14.2, "defense_score": 0.8},
    "Germany": {"avg_goals": 1.8, "avg_xG": 1.5, "avg_shots": 13.1, "defense_score": 1.1},
    # France and Argentina intentionally absent — enables test_xg_modifier_skipped_when_team_not_in_stats
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
    monkeypatch.setattr("alpha.engines.sports.wc_model.get_wc_team_stats", lambda: _FAKE_STATS)
    return WCMatchModel()


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

def test_wc_draw_rate_value():
    assert _WC_DRAW_RATE == pytest.approx(0.25)


def test_knockout_stages_contains_expected_values():
    assert "LAST_16" in KNOCKOUT_STAGES
    assert "QUARTER_FINALS" in KNOCKOUT_STAGES
    assert "SEMI_FINALS" in KNOCKOUT_STAGES
    assert "THIRD_PLACE" in KNOCKOUT_STAGES
    assert "FINAL" in KNOCKOUT_STAGES
    assert "GROUP_STAGE" not in KNOCKOUT_STAGES


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_init_raises_when_elo_missing(monkeypatch):
    monkeypatch.setattr(
        "alpha.engines.sports.wc_model.load_wc_elo_ratings",
        lambda: (_ for _ in ()).throw(FileNotFoundError("wc_priors.json missing")),
    )
    with pytest.raises(FileNotFoundError):
        WCMatchModel()


def test_init_succeeds_when_stats_missing(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
    monkeypatch.setattr(
        "alpha.engines.sports.wc_model.get_wc_team_stats",
        lambda: (_ for _ in ()).throw(FileNotFoundError("wc_stats.pkl missing")),
    )
    m = WCMatchModel()
    assert m._wc_stats == {}


# ---------------------------------------------------------------------------
# predict() — required output keys
# ---------------------------------------------------------------------------

def test_predict_returns_required_keys(model):
    game = {
        "home_team": "Brazil",
        "away_team": "Germany",
        "home_odds": -130,
        "away_odds": 110,
        "league": "wc",
    }
    result = model.predict(game)
    for key in ("win_prob", "draw_prob", "loss_prob", "elo_edge", "knockout", "model_name", "elo_diff"):
        assert key in result, f"Missing key: {key}"


def test_predict_raises_for_non_wc_league(model):
    game = {"home_team": "Chelsea", "away_team": "Arsenal", "league": "epl"}
    with pytest.raises(ValueError, match="league='wc'"):
        model.predict(game)


# ---------------------------------------------------------------------------
# Group stage probabilities
# ---------------------------------------------------------------------------

def test_predict_probs_sum_to_one_group_stage(model):
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "stage": "GROUP_STAGE"}
    result = model.predict(game)
    total = result["win_prob"] + result["draw_prob"] + result["loss_prob"]
    assert total == pytest.approx(1.0, abs=0.001)


def test_group_stage_has_nonzero_draw(model):
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "stage": "GROUP_STAGE"}
    result = model.predict(game)
    assert result["draw_prob"] > 0.0
    assert result["knockout"] is False


# ---------------------------------------------------------------------------
# Knockout stage gate (MODEL-02)
# ---------------------------------------------------------------------------

def test_knockout_suppresses_draw(model):
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "stage": "QUARTER_FINALS"}
    result = model.predict(game)
    assert result["draw_prob"] == 0.0
    assert result["knockout"] is True


def test_knockout_probs_sum_to_one(model):
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "stage": "LAST_16"}
    result = model.predict(game)
    total = result["win_prob"] + result["draw_prob"] + result["loss_prob"]
    assert total == pytest.approx(1.0, abs=0.001)


# ---------------------------------------------------------------------------
# Elo edge flag (MODEL-04)
# ---------------------------------------------------------------------------

def test_elo_edge_flag_set_when_divergence_exceeds_5pp(monkeypatch):
    # Brazil=2100, Germany=1500 => large Elo diff => win_prob well above market implied at -110
    fake_elo = {"Brazil": 2100, "Germany": 1500, "France": 2050, "Argentina": 2070}
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: fake_elo)
    monkeypatch.setattr("alpha.engines.sports.wc_model.get_wc_team_stats", lambda: {})
    m = WCMatchModel()
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "home_odds": -110}
    result = m.predict(game)
    assert result["elo_edge"] is True


# ---------------------------------------------------------------------------
# Model name
# ---------------------------------------------------------------------------

def test_model_name_is_wc_elo_logistic(model):
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc"}
    result = model.predict(game)
    assert result["model_name"] == "wc_elo_logistic"


# ---------------------------------------------------------------------------
# xG modifier
# ---------------------------------------------------------------------------

def test_xg_modifier_applied_when_stats_available(model):
    # Both Brazil and Germany are in _FAKE_STATS — elo_diff should be adjusted
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc"}
    result = model.predict(game)
    raw_elo_diff = _FAKE_ELO["Brazil"] - _FAKE_ELO["Germany"]
    # elo_diff in output should NOT equal raw diff (xG modifier applied)
    assert result["elo_diff"] != pytest.approx(raw_elo_diff, abs=0.01)


def test_xg_modifier_skipped_when_team_not_in_stats(model):
    # France and Argentina not in _FAKE_STATS — raw Elo diff should be used
    game = {"home_team": "France", "away_team": "Argentina", "league": "wc"}
    result = model.predict(game)
    raw_elo_diff = _FAKE_ELO["France"] - _FAKE_ELO["Argentina"]
    assert result["elo_diff"] == pytest.approx(raw_elo_diff, abs=0.01)


# ---------------------------------------------------------------------------
# evaluate_bet
# ---------------------------------------------------------------------------

def test_evaluate_bet_returns_none_when_no_edge(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
    monkeypatch.setattr("alpha.engines.sports.wc_model.get_wc_team_stats", lambda: _FAKE_STATS)
    m = WCMatchModel(min_edge=0.99)  # impossibly high threshold
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "home_odds": -130, "away_odds": 110}
    assert m.evaluate_bet(game) is None


def test_evaluate_bet_returns_game_when_edge_exists(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
    monkeypatch.setattr("alpha.engines.sports.wc_model.get_wc_team_stats", lambda: _FAKE_STATS)
    m = WCMatchModel(min_edge=0.0)  # always has edge
    # Brazil at +200 (underdog price) but strong Elo team — clear EV
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "home_odds": 200, "away_odds": -240}
    result = m.evaluate_bet(game)
    assert result is not None
    assert "win_prob" in result


# ---------------------------------------------------------------------------
# evaluate_batch
# ---------------------------------------------------------------------------

def test_evaluate_batch_returns_list(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
    monkeypatch.setattr("alpha.engines.sports.wc_model.get_wc_team_stats", lambda: _FAKE_STATS)
    m = WCMatchModel(min_edge=0.0)
    games = [
        {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "home_odds": -130, "away_odds": 110},
        {"home_team": "France", "away_team": "Argentina", "league": "wc", "home_odds": -110, "away_odds": -110},
    ]
    result = m.evaluate_batch(games)
    assert isinstance(result, list)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Soccer model isolation guard
# ---------------------------------------------------------------------------

def test_wc_model_does_not_import_soccer_model():
    import alpha.engines.sports.wc_model as wc_mod
    source = inspect.getsource(wc_mod)
    assert "soccer_model" not in source
