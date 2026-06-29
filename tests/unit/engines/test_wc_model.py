"""Tests for alpha/engines/sports/wc_model.py."""
from __future__ import annotations

import inspect

import pytest
from types import SimpleNamespace

from alpha.engines.sports.wc_model import KNOCKOUT_STAGES, WCMatchModel, _draw_prob

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_FAKE_ELO: dict[str, int] = {
    "Brazil": 2100,
    "Germany": 1980,
    "France": 2050,
    "Argentina": 2070,
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
    return WCMatchModel()


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

def test_knockout_stages_contains_expected_values():
    assert "LAST_32" in KNOCKOUT_STAGES
    assert "ROUND_OF_32" in KNOCKOUT_STAGES
    assert "LAST_16" in KNOCKOUT_STAGES
    assert "QUARTER_FINALS" in KNOCKOUT_STAGES
    assert "SEMI_FINALS" in KNOCKOUT_STAGES
    assert "THIRD_PLACE" in KNOCKOUT_STAGES
    assert "FINAL" in KNOCKOUT_STAGES
    assert "GROUP_STAGE" not in KNOCKOUT_STAGES


# ---------------------------------------------------------------------------
# Draw probability - dynamic decay (DRAW-01, DRAW-02)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("elo_diff,expected", [
    (0, 0.320),
    (100, 0.262),
    (300, 0.176),
    (500, 0.118),
    (750, 0.071),
])
def test_draw_prob_exponential_decay(elo_diff, expected):
    """Draw probability matches the Phase 8 calibration table."""
    result = _draw_prob(float(elo_diff))
    assert result == pytest.approx(expected, abs=0.02), (
        f"_draw_prob({elo_diff}) = {result:.4f}, expected {expected:.4f}"
    )


def test_draw_prob_floor_enforced():
    """Extreme Elo mismatches never fall below the configured draw floor."""
    from alpha.engines.sports.wc_model import _WC_MIN_DRAW

    assert _draw_prob(9999.0) >= _WC_MIN_DRAW


def test_draw_prob_monotone_decreasing():
    """Draw probability cannot increase as the absolute Elo gap grows."""
    previous = _draw_prob(0.0)
    for delta in (100, 200, 300, 500, 750, 1000):
        current = _draw_prob(float(delta))
        assert current <= previous + 1e-9
        previous = current


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


def test_init_does_not_load_stale_tournament_stats(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
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


def test_predict_90_minute_keeps_draw_for_knockout(model):
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "stage": "LAST_32"}
    result = model.predict_90_minute(game)
    total = result["win_prob"] + result["draw_prob"] + result["loss_prob"]
    assert result["draw_prob"] > 0.0
    assert result["knockout"] is True
    assert result["stage"] == "LAST_32"
    assert result["market_type"] == "90_minute"
    assert total == pytest.approx(1.0, abs=0.001)


# ---------------------------------------------------------------------------
# Elo edge flag (MODEL-04)
# ---------------------------------------------------------------------------

def test_elo_edge_flag_set_when_divergence_exceeds_5pp(monkeypatch):
    # Brazil=2100, Germany=1500 => large Elo diff => win_prob well above market implied at -110
    fake_elo = {"Brazil": 2100, "Germany": 1500, "France": 2050, "Argentina": 2070}
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: fake_elo)
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

def test_stale_historical_xg_does_not_modify_current_elo(model):
    # Current Elo already includes recent results; old tournament xG is ignored.
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc"}
    result = model.predict(game)
    raw_elo_diff = _FAKE_ELO["Brazil"] - _FAKE_ELO["Germany"]
    assert result["elo_diff"] == pytest.approx(raw_elo_diff, abs=0.01)


def test_current_elo_used_for_every_team(model):
    game = {"home_team": "France", "away_team": "Argentina", "league": "wc"}
    result = model.predict(game)
    raw_elo_diff = _FAKE_ELO["France"] - _FAKE_ELO["Argentina"]
    assert result["elo_diff"] == pytest.approx(raw_elo_diff, abs=0.01)


def test_recent_elo_overrides_static_file_rating(model):
    game = {
        "home_team": "Brazil",
        "away_team": "Germany",
        "league": "wc",
        "home_elo_override": 2200,
        "away_elo_override": 1700,
    }
    result = model.predict(game)
    assert result["home_elo"] == 2200
    assert result["away_elo"] == 1700
    assert result["elo_diff"] == 500


def test_tactical_comparison_adjusts_outcome_but_is_capped(model):
    baseline = model.predict({"home_team": "Brazil", "away_team": "Germany", "league": "wc"})
    adjusted = model.predict({
        "home_team": "Brazil", "away_team": "Germany", "league": "wc",
        "tactical_comparison": SimpleNamespace(
            home_attack_multiplier=1.10, away_attack_multiplier=0.90
        ),
        "tactical_authorized": True,
    })
    assert adjusted["win_prob"] > baseline["win_prob"]
    assert 0 < adjusted["tactical_elo_adjustment"] <= 40


def test_unvalidated_tactical_comparison_falls_back_to_baseline(model):
    baseline = model.predict({"home_team": "Brazil", "away_team": "Germany", "league": "wc"})
    unvalidated = model.predict({
        "home_team": "Brazil", "away_team": "Germany", "league": "wc",
        "tactical_comparison": SimpleNamespace(home_attack_multiplier=1.10, away_attack_multiplier=0.90),
    })
    assert unvalidated["win_prob"] == baseline["win_prob"]
    assert unvalidated["tactical_elo_adjustment"] == 0.0


# ---------------------------------------------------------------------------
# evaluate_bet
# ---------------------------------------------------------------------------

def test_evaluate_bet_returns_none_when_no_edge(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
    m = WCMatchModel(min_edge=0.99)  # impossibly high threshold
    game = {"home_team": "Brazil", "away_team": "Germany", "league": "wc", "home_odds": -130, "away_odds": 110}
    assert m.evaluate_bet(game) is None


def test_evaluate_bet_returns_game_when_edge_exists(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
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
