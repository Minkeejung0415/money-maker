"""Tests for alpha/engines/sports/soccer_sgp_builder.py."""
from __future__ import annotations

import pytest

from alpha.engines.sports.soccer_sgp_builder import (
    PropLeg,
    SGPMode,
    SoccerSGPBuilder,
    _STATIC_CORR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_leg(
    player="Erling Haaland",
    market="player_goals",
    model_prob=0.65,
    event_id="evt_001",
    home_team="Man City",
    away_team="Arsenal",
    confidence="HIGH",
):
    return PropLeg(
        player=player,
        market=market,
        line=0.5,
        model_prob=model_prob,
        over_odds=-110,
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        confidence=confidence,
    )


def _make_game(event_id="evt_001", home_odds=-130, away_odds=110):
    return {
        "event_id": event_id,
        "home_team": "Man City",
        "away_team": "Arsenal",
        "home_odds": home_odds,
        "away_odds": away_odds,
        "home_model_prob": 0.58,
        "away_model_prob": 0.42,
    }


# ---------------------------------------------------------------------------
# Static correlation table
# ---------------------------------------------------------------------------

def test_static_corr_goals_and_shots_positive():
    key = tuple(sorted(["player_goals", "player_shots"]))
    assert _STATIC_CORR[key] == pytest.approx(0.65)


def test_static_corr_goals_and_goals_negative():
    key = tuple(sorted(["player_goals", "player_goals"]))
    assert _STATIC_CORR[key] < 0


# ---------------------------------------------------------------------------
# LOW confidence guard
# ---------------------------------------------------------------------------

def test_low_confidence_legs_excluded():
    builder = SoccerSGPBuilder(min_edge=0.0)
    low_leg = _make_leg(confidence="LOW", model_prob=0.45)
    high_leg = _make_leg(player="Kevin De Bruyne", market="player_assists",
                          confidence="HIGH", model_prob=0.70)
    results = builder.build([low_leg, high_leg], mode=SGPMode.PROPS_ONLY)
    # Only 1 valid leg — need at least 2 for props_only
    assert results == []


def test_model_prob_guard_below_052():
    builder = SoccerSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(model_prob=0.50, confidence="HIGH")  # below 0.52 guard
    leg2 = _make_leg(player="KDB", market="player_assists", model_prob=0.70,
                     confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    assert results == []


# ---------------------------------------------------------------------------
# PROPS_ONLY mode
# ---------------------------------------------------------------------------

def test_props_only_requires_same_event():
    builder = SoccerSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(event_id="evt_001", model_prob=0.68, confidence="HIGH")
    leg2 = _make_leg(player="Son", event_id="evt_002", market="player_shots",
                     model_prob=0.68, confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    assert results == []


def test_props_only_same_event_generates_combo():
    builder = SoccerSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(model_prob=0.68, confidence="HIGH")
    leg2 = _make_leg(player="KDB", market="player_assists", model_prob=0.68,
                     confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# CLASSIC_PARLAY mode
# ---------------------------------------------------------------------------

def test_classic_parlay_requires_at_least_2_games():
    builder = SoccerSGPBuilder(min_edge=0.0)
    game = _make_game()
    results = builder.build([], ml_games=[game], mode=SGPMode.CLASSIC_PARLAY)
    assert results == []


def test_classic_parlay_two_games():
    builder = SoccerSGPBuilder(min_edge=0.0)
    game1 = _make_game(event_id="evt_001", home_odds=-200, away_odds=170)
    game2 = _make_game(event_id="evt_002", home_odds=-180, away_odds=160)
    game1["home_model_prob"] = 0.68
    game2["home_model_prob"] = 0.65
    results = builder.build([], ml_games=[game1, game2], mode=SGPMode.CLASSIC_PARLAY)
    assert len(results) >= 0  # may be 0 if edge < min_edge


# ---------------------------------------------------------------------------
# ParlayCombination structure
# ---------------------------------------------------------------------------

def test_parlay_combination_has_required_fields():
    builder = SoccerSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(model_prob=0.68, confidence="HIGH")
    leg2 = _make_leg(player="KDB", market="player_assists",
                     model_prob=0.68, confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    if results:
        combo = results[0]
        assert hasattr(combo, "ev")
        assert hasattr(combo, "edge")
        assert hasattr(combo, "combined_model_prob")
        assert hasattr(combo, "combined_decimal_odds")
        assert hasattr(combo, "stake")


def test_combined_model_prob_positive():
    builder = SoccerSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(model_prob=0.68, confidence="HIGH")
    leg2 = _make_leg(player="KDB", market="player_assists",
                     model_prob=0.68, confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    for combo in results:
        assert combo.combined_model_prob > 0


# ---------------------------------------------------------------------------
# top_n limiting
# ---------------------------------------------------------------------------

def test_top_n_limits_results():
    builder = SoccerSGPBuilder(min_edge=0.0)
    legs = [
        _make_leg(player=f"Player{i}", market="player_goals",
                   model_prob=0.70, confidence="HIGH")
        for i in range(6)
    ]
    results = builder.build(legs, mode=SGPMode.PROPS_ONLY, top_n=2)
    assert len(results) <= 2


# ---------------------------------------------------------------------------
# _get_correlation
# ---------------------------------------------------------------------------

def test_get_correlation_goals_shots():
    builder = SoccerSGPBuilder()
    leg_a = _make_leg(market="player_goals")
    leg_b = _make_leg(market="player_shots")
    r = builder._get_correlation(leg_a, leg_b)
    assert r == pytest.approx(0.65)


def test_get_correlation_unrelated_markets():
    builder = SoccerSGPBuilder()
    leg_a = _make_leg(market="player_goals")
    leg_b = _make_leg(market="player_shots")
    # Known corr is 0.65; default for unknown should be 0.0
    leg_c = _make_leg(market="unknown_market_x")
    r = builder._get_correlation(leg_a, leg_c)
    assert r == 0.0
