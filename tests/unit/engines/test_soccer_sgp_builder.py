"""
Unit tests for SoccerSGPBuilder draw leg support (Plan 14-01).

Tests cover:
  - Draw leg inclusion gate (D-11): model_name not None/market_implied AND EV > 5%
  - Draw leg exclusion when market_implied or model_name None
  - Draw leg EV threshold gate
  - is_draw=True annotation on qualifying draw legs
  - Classic parlay regression (win legs still work)
  - Same-game guard: no combo with both win + draw leg from same event_id
  - Multi-game draw leg combination
"""
from __future__ import annotations

import pytest

from alpha.engines.sports.soccer_sgp_builder import SGPMode, SoccerSGPBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game(
    event_id: str,
    model_name: str | None,
    draw_prob: float | None,
    draw_odds: int,
    home_odds: int = -130,
    away_odds: int = 110,
    home_model_prob: float = 0.55,
    away_model_prob: float = 0.35,
) -> dict:
    """Return a minimal game dict matching the shape _build_draw_legs reads."""
    return {
        "home_team": f"Home-{event_id}",
        "away_team": f"Away-{event_id}",
        "event_id": event_id,
        "model_name": model_name,
        "draw_prob": draw_prob,
        "draw_odds": draw_odds,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "home_model_prob": home_model_prob,
        "away_model_prob": away_model_prob,
    }


def _builder(min_edge: float = -10.0) -> SoccerSGPBuilder:
    """Return a builder with a very low min_edge so EV gate is permissive for testing."""
    return SoccerSGPBuilder(min_edge=min_edge, max_legs=4)


# ---------------------------------------------------------------------------
# EV reference values (computed from plan spec):
#   High-EV draw: draw_prob=0.45, draw_odds=+250 → decimal=3.5
#     EV = 0.45 * (3.5 - 1) - (1 - 0.45) = 0.45 * 2.5 - 0.55 = 1.125 - 0.55 = 0.575
#   Low-EV draw: draw_prob=0.25, draw_odds=-130 → decimal ~1.769
#     EV = 0.25 * 0.769 - 0.75 ≈ -0.558
# ---------------------------------------------------------------------------

_HIGH_EV_DRAW_PROB = 0.45
_HIGH_EV_DRAW_ODDS = 250   # american +250 → 3.5x decimal → EV 0.575

_LOW_EV_DRAW_PROB = 0.25
_LOW_EV_DRAW_ODDS = -130   # american -130 → ~1.769x decimal → EV ~-0.558


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildDrawLegs:
    """Direct tests for _build_draw_legs method."""

    def test_draw_leg_included_when_model_ev_positive(self):
        """Draw leg from a qualified model with EV > 5% appears in results."""
        builder = _builder()
        game = _make_game(
            event_id="A",
            model_name="epl_xgboost_v1",
            draw_prob=_HIGH_EV_DRAW_PROB,
            draw_odds=_HIGH_EV_DRAW_ODDS,
        )
        draw_legs = builder._build_draw_legs([game])
        assert len(draw_legs) == 1
        leg = draw_legs[0]
        assert leg["type"] == "draw"
        assert leg["event_id"] == "A"

    def test_draw_leg_excluded_when_market_implied(self):
        """Draw leg excluded when model_name is 'market_implied' (D-11 gate)."""
        builder = _builder()
        game = _make_game(
            event_id="B",
            model_name="market_implied",
            draw_prob=_HIGH_EV_DRAW_PROB,
            draw_odds=_HIGH_EV_DRAW_ODDS,
        )
        draw_legs = builder._build_draw_legs([game])
        assert draw_legs == []

    def test_draw_leg_excluded_when_model_name_none(self):
        """Draw leg excluded when model_name is None (D-11 gate)."""
        builder = _builder()
        game = _make_game(
            event_id="C",
            model_name=None,
            draw_prob=_HIGH_EV_DRAW_PROB,
            draw_odds=_HIGH_EV_DRAW_ODDS,
        )
        draw_legs = builder._build_draw_legs([game])
        assert draw_legs == []

    def test_draw_leg_excluded_when_ev_below_threshold(self):
        """Draw leg excluded when EV <= 0.05, even with valid model_name."""
        builder = _builder()
        game = _make_game(
            event_id="D",
            model_name="epl_xgboost_v1",
            draw_prob=_LOW_EV_DRAW_PROB,
            draw_odds=_LOW_EV_DRAW_ODDS,
        )
        draw_legs = builder._build_draw_legs([game])
        assert draw_legs == []

    def test_draw_leg_annotation_is_draw_true(self):
        """Qualifying draw leg dict carries is_draw=True for downstream annotation."""
        builder = _builder()
        game = _make_game(
            event_id="E",
            model_name="ucl_elo_logistic",
            draw_prob=_HIGH_EV_DRAW_PROB,
            draw_odds=_HIGH_EV_DRAW_ODDS,
        )
        draw_legs = builder._build_draw_legs([game])
        assert len(draw_legs) == 1
        assert draw_legs[0].get("is_draw") is True

    def test_draw_leg_fields_complete(self):
        """Qualifying draw leg has all required fields with correct values."""
        builder = _builder()
        game = _make_game(
            event_id="F",
            model_name="epl_xgboost_v1",
            draw_prob=_HIGH_EV_DRAW_PROB,
            draw_odds=_HIGH_EV_DRAW_ODDS,
        )
        draw_legs = builder._build_draw_legs([game])
        assert len(draw_legs) == 1
        leg = draw_legs[0]
        assert leg["type"] == "draw"
        assert leg["team"] == "Draw"
        assert leg["model_prob"] == _HIGH_EV_DRAW_PROB
        assert leg["home_team"] == "Home-F"
        assert leg["away_team"] == "Away-F"
        assert leg["event_id"] == "F"
        # decimal_odds should be approx 3.5 for +250 american
        assert abs(leg["decimal_odds"] - 3.5) < 0.01


class TestClassicParlayWithDrawLegs:
    """Integration tests via _build_classic_parlay / build()."""

    def test_classic_parlay_win_legs_still_work(self):
        """Regression: win-only combos still returned when no qualifying draw legs."""
        builder = _builder()
        game_a = _make_game(
            event_id="A",
            model_name="epl_xgboost_v1",
            draw_prob=_LOW_EV_DRAW_PROB,   # low EV → no draw leg
            draw_odds=_LOW_EV_DRAW_ODDS,
        )
        game_b = _make_game(
            event_id="B",
            model_name="epl_xgboost_v1",
            draw_prob=_LOW_EV_DRAW_PROB,   # low EV → no draw leg
            draw_odds=_LOW_EV_DRAW_ODDS,
        )
        combos = builder.build(
            prop_legs=[],
            ml_games=[game_a, game_b],
            mode=SGPMode.CLASSIC_PARLAY,
            top_n=10,
        )
        # Should still produce ml-type combos
        assert len(combos) >= 1
        for combo in combos:
            for leg in combo.legs:
                assert leg["type"] == "ml"

    def test_no_same_game_draw_plus_win_combo(self):
        """No returned combo pairs a draw leg and win leg from the same event_id."""
        builder = _builder()
        # game_A: has a qualifying draw leg
        game_a = _make_game(
            event_id="A",
            model_name="epl_xgboost_v1",
            draw_prob=_HIGH_EV_DRAW_PROB,
            draw_odds=_HIGH_EV_DRAW_ODDS,
        )
        # game_B: standard win-only game
        game_b = _make_game(
            event_id="B",
            model_name="epl_xgboost_v1",
            draw_prob=_LOW_EV_DRAW_PROB,
            draw_odds=_LOW_EV_DRAW_ODDS,
        )
        combos = builder.build(
            prop_legs=[],
            ml_games=[game_a, game_b],
            mode=SGPMode.CLASSIC_PARLAY,
            top_n=20,
        )
        for combo in combos:
            # Collect event_ids per leg type within this combo
            draw_eids = {leg["event_id"] for leg in combo.legs if leg.get("type") == "draw"}
            ml_eids = {leg["event_id"] for leg in combo.legs if leg.get("type") == "ml"}
            overlap = draw_eids & ml_eids
            assert overlap == set(), (
                f"Illegal combo: event_ids {overlap} appear in both draw and ml legs"
            )

    def test_draw_legs_from_multiple_games(self):
        """A combo of 2 draw legs (one per game) is valid when both games qualify."""
        builder = _builder()
        game_a = _make_game(
            event_id="A",
            model_name="epl_xgboost_v1",
            draw_prob=_HIGH_EV_DRAW_PROB,
            draw_odds=_HIGH_EV_DRAW_ODDS,
        )
        game_b = _make_game(
            event_id="B",
            model_name="ucl_elo_logistic",
            draw_prob=_HIGH_EV_DRAW_PROB,
            draw_odds=_HIGH_EV_DRAW_ODDS,
        )
        combos = builder.build(
            prop_legs=[],
            ml_games=[game_a, game_b],
            mode=SGPMode.CLASSIC_PARLAY,
            top_n=20,
        )
        # At least one combo should have 2 draw legs
        draw_only_combos = [
            c for c in combos
            if all(leg.get("type") == "draw" for leg in c.legs)
        ]
        assert len(draw_only_combos) >= 1, (
            "Expected at least one combo with 2 draw legs from different games"
        )
