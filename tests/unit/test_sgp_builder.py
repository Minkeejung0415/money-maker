"""Unit tests for SGPBuilder."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from alpha.engines.sports.sgp_builder import (
    ParlayCombination,
    PropLeg,
    SGPBuilder,
    SGPMode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_leg(
    player: str = "LeBron James",
    market: str = "player_points",
    line: float = 27.5,
    model_prob: float = 0.63,
    over_odds: int = -115,
    event_id: str = "evt1",
    home_team: str = "Los Angeles Lakers",
    away_team: str = "Boston Celtics",
    confidence: str = "HIGH",
    player_team: str = "",
) -> PropLeg:
    return PropLeg(
        player=player,
        market=market,
        line=line,
        model_prob=model_prob,
        over_odds=over_odds,
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        confidence=confidence,
        player_team=player_team,
    )


def _make_ml_game(
    home_team: str = "Los Angeles Lakers",
    away_team: str = "Boston Celtics",
    home_odds: int = -150,
    away_odds: int = +130,
    event_id: str = "evt1",
) -> dict:
    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "event_id": event_id,
        "commence_time": "2026-03-10T20:00:00Z",
        "league": "nba",
    }


def _null_corr():
    """A mock correlation engine that always returns 0 (neutral)."""
    corr = MagicMock()
    corr.adjust_multi_leg_prob.side_effect = lambda legs: (
        legs[0][0] if len(legs) == 1 else
        float(__import__("math").prod(p for p, _, _ in legs))
    )
    corr.get_correlation.return_value = 0.0
    corr.classify.return_value = __import__(
        "alpha.engines.sports.correlation", fromlist=["CorrelationType"]
    ).CorrelationType.NEUTRAL
    return corr


@pytest.fixture
def builder():
    return SGPBuilder(
        correlation_engine=_null_corr(),
        bankroll=10_000,
        min_edge=0.0,   # set to 0 so all positive-ev combos pass through
        max_legs=4,
        min_legs=2,     # tests use 2-leg combos by design
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_props_only_requires_2_legs_minimum(builder):
    """Single leg → returns [] (need at least 2 for a parlay)."""
    legs = [_make_leg()]
    result = builder.build(legs, mode=SGPMode.PROPS_ONLY)
    assert result == []


def test_low_confidence_legs_excluded(builder):
    """All LOW confidence legs → SGPBuilder filters them → returns []."""
    legs = [
        _make_leg(confidence="LOW", player="PlayerA"),
        _make_leg(confidence="LOW", player="PlayerB"),
    ]
    result = builder.build(legs, mode=SGPMode.PROPS_ONLY)
    assert result == []


def test_props_only_2_legs_ev_calculation():
    """Verify EV formula: ev = p*(odds-1) - (1-p)."""
    two_leg_builder = SGPBuilder(
        correlation_engine=_null_corr(), bankroll=10_000, min_edge=0.0, max_legs=4, min_legs=2
    )
    leg_a = _make_leg(player="PlayerA", model_prob=0.65, over_odds=-110, confidence="HIGH")
    leg_b = _make_leg(player="PlayerB", market="player_rebounds", model_prob=0.60,
                      over_odds=-110, confidence="HIGH")

    result = two_leg_builder.build([leg_a, leg_b], mode=SGPMode.PROPS_ONLY)
    assert len(result) >= 1

    combo = result[0]
    # Verify combined_decimal_odds is product of individual decimal odds
    dec_a = 1 + 100 / 110  # -110 → 1.909...
    dec_b = 1 + 100 / 110
    expected_odds = dec_a * dec_b
    assert combo.combined_decimal_odds == pytest.approx(expected_odds, rel=1e-3)

    # Verify EV formula
    expected_ev = combo.combined_model_prob * (combo.combined_decimal_odds - 1) - (
        1 - combo.combined_model_prob
    )
    assert combo.ev == pytest.approx(expected_ev, abs=0.001)


def test_ev_positive_when_model_beats_market(builder):
    """model_joint=0.50, market_joint≈0.275 → EV > 0."""
    # -110 each → market_implied = 1/1.909 ≈ 0.524 each → joint ≈ 0.275
    # model prob per leg set so joint ≈ 0.50
    leg_a = _make_leg(player="PlayerA", model_prob=0.75, over_odds=-110, confidence="HIGH")
    leg_b = _make_leg(player="PlayerB", market="player_rebounds", model_prob=0.67,
                      over_odds=-110, confidence="HIGH")

    result = builder.build([leg_a, leg_b], mode=SGPMode.PROPS_ONLY)
    assert len(result) >= 1
    assert result[0].ev > 0


def test_results_sorted_ev_descending(builder):
    """Multiple combos should be sorted by EV from highest to lowest."""
    legs = [
        _make_leg(player="P1", model_prob=0.70, over_odds=-110, confidence="HIGH"),
        _make_leg(player="P2", market="player_rebounds", model_prob=0.68, over_odds=-110, confidence="HIGH"),
        _make_leg(player="P3", market="player_assists", model_prob=0.65, over_odds=-110, confidence="MEDIUM"),
    ]
    result = builder.build(legs, mode=SGPMode.PROPS_ONLY, top_n=10)
    if len(result) >= 2:
        for i in range(len(result) - 1):
            assert result[i].ev >= result[i + 1].ev


def test_classic_parlay_uses_product_not_corr(builder):
    """Classic parlay: 2 independent games → combined_prob = p1 * p2 (no corr engine)."""
    game1 = _make_ml_game(home_team="Lakers", away_team="Celtics",
                          home_odds=-150, away_odds=+130, event_id="g1")
    game1["home_model_prob"] = 0.70  # ensure positive EV
    game2 = _make_ml_game(home_team="Warriors", away_team="Nuggets",
                          home_odds=-120, away_odds=+100, event_id="g2")
    game2["home_model_prob"] = 0.65

    result = builder.build([], ml_games=[game1, game2], mode=SGPMode.CLASSIC_PARLAY, top_n=10)
    assert len(result) >= 1

    combo = result[0]
    legs = combo.legs
    assert len(legs) == 2

    # combined_model_prob should be simple product (no corr adjustment for classic parlay)
    expected_joint = legs[0]["model_prob"] * legs[1]["model_prob"]
    assert combo.combined_model_prob == pytest.approx(expected_joint, rel=1e-3)


def test_moneyline_same_team_prop_flags_warning():
    """ML Lakers + LeBron (Lakers) points → correlation_note contains ⚠."""
    builder = SGPBuilder(
        correlation_engine=_null_corr(),
        bankroll=10_000,
        min_edge=0.0,
        max_legs=4,
        min_legs=2,
    )
    lebron_leg = _make_leg(
        player="LeBron James",
        market="player_points",
        model_prob=0.65,
        over_odds=-110,
        event_id="evt1",
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        confidence="HIGH",
        player_team="Los Angeles Lakers",
    )
    lakers_game = _make_ml_game(
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        home_odds=-150,
        away_odds=+130,
        event_id="evt1",
    )
    lakers_game["home_model_prob"] = 0.70  # ensure positive EV for ML leg

    result = builder.build(
        [lebron_leg], ml_games=[lakers_game], mode=SGPMode.MONEYLINE_SGP, top_n=10
    )
    assert len(result) >= 1
    assert "⚠" in result[0].correlation_note


def test_kelly_stake_attached_to_results(builder):
    """All returned combos must have stake > 0 when there is positive EV."""
    leg_a = _make_leg(player="P1", model_prob=0.75, over_odds=-110, confidence="HIGH")
    leg_b = _make_leg(player="P2", market="player_rebounds", model_prob=0.70,
                      over_odds=-110, confidence="HIGH")

    result = builder.build([leg_a, leg_b], mode=SGPMode.PROPS_ONLY, top_n=5)
    for combo in result:
        assert combo.stake > 0


# ---------------------------------------------------------------------------
# Bug 1: same-player pair in correlation note
# ---------------------------------------------------------------------------


def test_corr_note_same_player_skipped():
    """Same-player pair (pts + ast) should show 'same player — r=0.65', never 'vs'."""
    corr = _null_corr()
    builder = SGPBuilder(correlation_engine=corr, bankroll=10_000, min_edge=0.0, max_legs=4, min_legs=2)
    trae_pts = _make_leg(player="Trae Young", market="player_points", model_prob=0.65,
                         over_odds=-110, event_id="e1", confidence="HIGH")
    trae_ast = _make_leg(player="Trae Young", market="player_assists", model_prob=0.62,
                         over_odds=-110, event_id="e1", confidence="HIGH")

    result = builder.build([trae_pts, trae_ast], mode=SGPMode.PROPS_ONLY, top_n=5)
    assert len(result) >= 1
    note = result[0].correlation_note
    assert "same player" in note
    assert "r=0.65" in note
    assert "Trae Young vs Trae Young" not in note


# ---------------------------------------------------------------------------
# Bug 3: negative EV ML leg returns None
# ---------------------------------------------------------------------------


def test_ml_leg_negative_ev_returns_none():
    """When both sides of a game have negative EV, _best_ml_leg returns None."""
    builder = SGPBuilder(bankroll=10_000, min_edge=0.0, max_legs=4)
    # Home: -400 → dec 1.25, implied 80%. Model 78% → EV = 0.78*0.25-0.22 = -0.025
    # Away: +300 → dec 4.0, implied 25%. Model 22% → EV = 0.22*3.0-0.78 = -0.12
    game = {
        "home_team": "Detroit Pistons",
        "away_team": "Boston Celtics",
        "home_odds": -400,
        "away_odds": +300,
        "event_id": "neg_ev_game",
        "home_model_prob": 0.78,
        "away_model_prob": 0.22,
    }
    result = builder._best_ml_leg(game)
    assert result is None
