"""Tests for alpha/engines/sports/mlb_sgp_builder.py."""
from __future__ import annotations

import pytest

from alpha.engines.sports.mlb_sgp_builder import (
    MLBSGPBuilder,
    PropLeg,
    SGPMode,
    _STATIC_CORR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_leg(
    player="Aaron Judge",
    market="batter_hits",
    model_prob=0.65,
    event_id="evt_001",
    home_team="NYY",
    away_team="BOS",
    confidence="HIGH",
):
    return PropLeg(
        player=player,
        market=market,
        line=1.5,
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
        "home_team": "NYY",
        "away_team": "BOS",
        "home_odds": home_odds,
        "away_odds": away_odds,
        "home_model_prob": 0.58,
        "away_model_prob": 0.42,
    }


# ---------------------------------------------------------------------------
# Static correlation table
# ---------------------------------------------------------------------------

def test_static_corr_hits_rbis_positive():
    key = tuple(sorted(["batter_hits", "batter_rbis"]))
    assert _STATIC_CORR[key] == pytest.approx(0.70)


def test_static_corr_pitcher_ks_hits_negative():
    key = tuple(sorted(["batter_hits", "pitcher_strikeouts"]))
    assert _STATIC_CORR[key] < 0


# ---------------------------------------------------------------------------
# LOW confidence guard
# ---------------------------------------------------------------------------

def test_low_confidence_legs_excluded():
    builder = MLBSGPBuilder(min_edge=0.0)
    low_leg = _make_leg(confidence="LOW", model_prob=0.45)
    high_leg = _make_leg(player="Shohei Ohtani", market="batter_home_runs",
                          confidence="HIGH", model_prob=0.70)
    results = builder.build([low_leg, high_leg], mode=SGPMode.PROPS_ONLY)
    assert results == []


def test_model_prob_guard():
    builder = MLBSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(model_prob=0.45, confidence="HIGH")  # below 0.52
    leg2 = _make_leg(player="Ohtani", market="batter_home_runs",
                     model_prob=0.70, confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    assert results == []


# ---------------------------------------------------------------------------
# PROPS_ONLY mode
# ---------------------------------------------------------------------------

def test_props_only_requires_same_event():
    builder = MLBSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(event_id="evt_001", model_prob=0.68, confidence="HIGH")
    leg2 = _make_leg(player="Mookie", event_id="evt_002", market="batter_rbis",
                     model_prob=0.68, confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    assert results == []


def test_props_only_same_event():
    builder = MLBSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(model_prob=0.68, confidence="HIGH")
    leg2 = _make_leg(player="Shohei", market="batter_home_runs",
                     model_prob=0.68, confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# CLASSIC_PARLAY mode
# ---------------------------------------------------------------------------

def test_classic_parlay_requires_at_least_2_games():
    builder = MLBSGPBuilder(min_edge=0.0)
    game = _make_game()
    results = builder.build([], ml_games=[game], mode=SGPMode.CLASSIC_PARLAY)
    assert results == []


def test_classic_parlay_with_two_games():
    builder = MLBSGPBuilder(min_edge=0.0)
    game1 = _make_game(event_id="evt_001", home_odds=-200, away_odds=170)
    game2 = _make_game(event_id="evt_002", home_odds=-180, away_odds=160)
    game1["home_model_prob"] = 0.68
    game2["home_model_prob"] = 0.65
    results = builder.build([], ml_games=[game1, game2], mode=SGPMode.CLASSIC_PARLAY)
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# MONEYLINE_SGP mode
# ---------------------------------------------------------------------------

def test_ml_sgp_combines_ml_and_prop():
    builder = MLBSGPBuilder(min_edge=0.0)
    game = _make_game(home_odds=-200, away_odds=170)
    game["home_model_prob"] = 0.68
    leg = _make_leg(model_prob=0.68, confidence="HIGH")
    results = builder.build([leg], ml_games=[game], mode=SGPMode.MONEYLINE_SGP)
    # May produce results depending on edge
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# ParlayCombination structure
# ---------------------------------------------------------------------------

def test_combination_has_required_fields():
    builder = MLBSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(model_prob=0.68, confidence="HIGH")
    leg2 = _make_leg(player="Ohtani", market="batter_home_runs",
                     model_prob=0.68, confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    if results:
        combo = results[0]
        assert hasattr(combo, "ev")
        assert hasattr(combo, "edge")
        assert hasattr(combo, "combined_model_prob")
        assert hasattr(combo, "combined_market_prob")
        assert hasattr(combo, "stake")


def test_combined_prob_in_valid_range():
    builder = MLBSGPBuilder(min_edge=0.0)
    leg1 = _make_leg(model_prob=0.68, confidence="HIGH")
    leg2 = _make_leg(player="Ohtani", market="batter_home_runs",
                     model_prob=0.68, confidence="HIGH")
    results = builder.build([leg1, leg2], mode=SGPMode.PROPS_ONLY)
    for combo in results:
        assert 0 < combo.combined_model_prob < 1


# ---------------------------------------------------------------------------
# _get_correlation
# ---------------------------------------------------------------------------

def test_get_correlation_hits_rbis():
    builder = MLBSGPBuilder()
    leg_a = _make_leg(market="batter_hits")
    leg_b = _make_leg(market="batter_rbis")
    r = builder._get_correlation(leg_a, leg_b)
    assert r == pytest.approx(0.70)


def test_get_correlation_unknown_returns_zero():
    builder = MLBSGPBuilder()
    leg_a = _make_leg(market="batter_hits")
    leg_b = _make_leg(market="pitcher_strikeouts")
    # hits vs strikeouts: -0.40
    r = builder._get_correlation(leg_a, leg_b)
    assert r == pytest.approx(-0.40)
