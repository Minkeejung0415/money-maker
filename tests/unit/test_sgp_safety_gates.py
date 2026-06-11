"""
Regression tests for NBA props scanner real-money safety gates.

Covers the observed incident: legacy XGBoost models were rejected, the
scanner silently fell back to the rule-based model, and still emitted 99%
prop probabilities, 4-leg SGP recommendations, 1000%+ EV estimates and
$500 Kelly stakes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from alpha.engines.sports.sgp_builder import (
    EV_UNAVAILABLE_MSG,
    RESEARCH_ONLY_MSG,
    PropLeg,
    SGPBuilder,
    SGPMode,
)


# ---------------------------------------------------------------------------
# PropModel helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def model():
    from alpha.engines.sports.prop_model import PropModel
    with patch("alpha.engines.sports.xgb_prop_model.XGBoostPropModel.load",
               side_effect=Exception("no models on disk")):
        m = PropModel(season="2024-25")
    m._xgb_models = {}
    return m


def _patch_logs(rows):
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_game_logs",
        return_value=rows,
    )


def _patch_team_stats():
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_team_per_game_stats",
        return_value={},
    )


def _patch_def_ratings():
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_def_ratings",
        return_value={},
    )


def _rows(pts: float, minutes: float, n: int) -> list[dict]:
    return [
        {"PTS": pts, "REB": 5.0, "AST": 3.0, "FG3M": 1.0,
         "MIN": str(int(minutes)), "MIN_float": minutes}
        for _ in range(n)
    ]


# ---------------------------------------------------------------------------
# Gate 1: explicit prediction source
# ---------------------------------------------------------------------------

def test_fallback_result_labeled_rule_fallback(model):
    with _patch_logs(_rows(25.0, 32.0, 15)), _patch_team_stats(), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 20.5, "Boston Celtics")
    assert result["source"] == "rule_fallback"


# ---------------------------------------------------------------------------
# Gate 3/4: bench players + fallback probability caps
# ---------------------------------------------------------------------------

def test_bench_player_alt_line_cannot_get_99_percent(model):
    """
    A demoted bench player (12 recent games of 5-8 minutes after 8 old
    30-minute games) on a low alt line must NEVER show ~0.99 — the minutes
    model and the 0.75 fallback cap both push it down.
    """
    recent_bench = _rows(2.0, 6.0, 6) + _rows(3.0, 8.0, 6)   # newest first
    old_starter = _rows(8.0, 30.0, 8)
    logs = recent_bench + old_starter

    with _patch_logs(logs), _patch_team_stats(), _patch_def_ratings():
        result = model.predict_prop("Bench Guy", "player_points", 1.5, "Boston Celtics")

    assert result is not None
    assert result["source"] == "rule_fallback"
    assert result["model_prob"] <= 0.75
    # Minutes risk surfaced explicitly, not hidden by the MIN>=20 filter.
    assert result["projected_minutes"] < 15.0
    assert result["low_minutes_risk"] > 0.5


def test_fallback_max_probability_is_075(model):
    """Even a 35-ppg player against a 10.5 line caps at 0.75 on fallback."""
    with _patch_logs(_rows(35.0, 34.0, 20)), _patch_team_stats(), _patch_def_ratings():
        result = model.predict_prop("Superstar", "player_points", 10.5, "Boston Celtics")
    assert result["source"] == "rule_fallback"
    assert result["model_prob"] <= 0.75
    # Derived UNDER probability is bounded symmetrically.
    assert 1.0 - result["model_prob"] <= 0.75


def test_unvalidated_xgb_capped_at_085(model):
    """XGBoost without held-out validation evidence caps at 0.85."""
    class _UnvalidatedXGB:
        validation_metrics = {}
        def predict(self, features):
            return 40.0  # absurdly above the line

    rows = [
        {"PTS": 35.0, "REB": 5.0, "AST": 3.0, "FG3M": 1.0,
         "MIN": "34", "MIN_float": 34.0,
         "GAME_DATE": f"2025-01-{28 - 2 * i:02d}"}
        for i in range(12)
    ]
    model._xgb_models = {"player_points": _UnvalidatedXGB()}
    with _patch_logs(rows), _patch_team_stats(), _patch_def_ratings():
        result = model.predict_prop(
            "Superstar", "player_points", 10.5, "Boston Celtics", is_home=True)
    assert result["source"] == "xgb"
    assert result["model_prob"] <= 0.85


def test_validated_xgb_may_exceed_085_never_099(model):
    class _ValidatedXGB:
        validation_metrics = {"val_mae": 3.1, "val_samples": 5000}
        def predict(self, features):
            return 40.0

    rows = [
        {"PTS": 35.0, "REB": 5.0, "AST": 3.0, "FG3M": 1.0,
         "MIN": "34", "MIN_float": 34.0,
         "GAME_DATE": f"2025-01-{28 - 2 * i:02d}"}
        for i in range(12)
    ]
    model._xgb_models = {"player_points": _ValidatedXGB()}
    with _patch_logs(rows), _patch_team_stats(), _patch_def_ratings():
        result = model.predict_prop(
            "Superstar", "player_points", 10.5, "Boston Celtics", is_home=True)
    assert result["model_prob"] > 0.85   # validated evidence may go higher
    assert result["model_prob"] <= 0.99


# ---------------------------------------------------------------------------
# SGP builder gates
# ---------------------------------------------------------------------------

def _leg(player="P1", market="player_points", line=20.5, prob=0.70,
         direction="over", source="rule_fallback", confidence="HIGH") -> PropLeg:
    return PropLeg(
        player=player, market=market, line=line, model_prob=prob,
        over_odds=-110, event_id="evt1", home_team="LAL", away_team="BOS",
        confidence=confidence, direction=direction, source=source,
    )


def _builder(**kw) -> SGPBuilder:
    return SGPBuilder(bankroll=10_000, min_edge=0.0, **kw)


def test_fallback_sgp_has_no_kelly_stake():
    builder = _builder()
    legs = [
        _leg(player="P1", prob=0.74, source="rule_fallback"),
        _leg(player="P2", market="player_rebounds", prob=0.72, source="xgb"),
    ]
    combos = builder.build(legs, mode=SGPMode.PROPS_ONLY)
    assert len(combos) >= 1
    combo = combos[0]
    assert combo.research_only is True   # one fallback leg poisons the combo
    assert combo.stake == 0.0
    # Even an explicit quote never attaches a stake to research-only combos.
    builder.apply_sgp_quote(combo, quote_decimal_odds=3.4)
    assert combo.stake == 0.0
    assert RESEARCH_ONLY_MSG  # message constant exists for displays


def test_sgp_ev_unavailable_without_actual_quote():
    builder = _builder()
    legs = [
        _leg(player="P1", prob=0.74, source="xgb"),
        _leg(player="P2", market="player_rebounds", prob=0.72, source="xgb"),
    ]
    combos = builder.build(legs, mode=SGPMode.PROPS_ONLY)
    assert len(combos) >= 1
    assert combos[0].ev is None
    assert combos[0].sgp_quote_odds is None
    assert "sportsbook SGP quote" in EV_UNAVAILABLE_MSG

    builder.apply_sgp_quote(combos[0], quote_decimal_odds=3.1)
    assert combos[0].ev is not None


def test_nested_alt_lines_rejected_in_same_sgp():
    """Player OVER 1.5 pts + Player OVER 2.5 pts can never share an SGP."""
    builder = _builder()
    legs = [
        _leg(player="P1", line=1.5, prob=0.74, source="xgb"),
        _leg(player="P1", line=2.5, prob=0.65, source="xgb"),
        _leg(player="P2", market="player_rebounds", prob=0.70, source="xgb"),
    ]
    combos = builder.build(legs, mode=SGPMode.PROPS_ONLY, top_n=50)
    for combo in combos:
        keys = [(l.player, l.market) for l in combo.legs]
        assert len(keys) == len(set(keys)), "redundant player-market pair in SGP"


def test_opposite_sides_of_same_line_rejected():
    builder = _builder()
    legs = [
        _leg(player="P1", line=20.5, prob=0.70, direction="over", source="xgb"),
        _leg(player="P1", line=20.5, prob=0.68, direction="under", source="xgb"),
        _leg(player="P2", market="player_rebounds", prob=0.70, source="xgb"),
    ]
    combos = builder.build(legs, mode=SGPMode.PROPS_ONLY, top_n=50)
    for combo in combos:
        keys = [(l.player, l.market) for l in combo.legs]
        assert len(keys) == len(set(keys))


def test_four_leg_recommendation_rejected():
    """max_legs=4 is clamped: 2 by default, 3 in research mode — never 4."""
    default_builder = _builder(max_legs=4)
    research_builder = _builder(max_legs=4, research_mode=True)
    assert default_builder._max_legs == 2
    assert research_builder._max_legs == 3

    legs = [
        _leg(player="P1", market="player_points", prob=0.74, source="xgb"),
        _leg(player="P2", market="player_rebounds", prob=0.73, source="xgb"),
        _leg(player="P3", market="player_assists", prob=0.72, source="xgb"),
        _leg(player="P4", market="player_threes", prob=0.71, source="xgb"),
    ]
    for builder in (default_builder, research_builder):
        combos = builder.build(legs, mode=SGPMode.PROPS_ONLY, top_n=100)
        assert combos, "expected some combos"
        assert max(len(c.legs) for c in combos) <= builder._max_legs


def test_three_legs_require_research_mode():
    legs = [
        _leg(player="P1", market="player_points", prob=0.74, source="xgb"),
        _leg(player="P2", market="player_rebounds", prob=0.73, source="xgb"),
        _leg(player="P3", market="player_assists", prob=0.72, source="xgb"),
    ]
    # Default mode: even asking for 3-leg-only combos yields nothing over 2.
    default_combos = _builder(max_legs=3, min_legs=3).build(
        legs, mode=SGPMode.PROPS_ONLY, top_n=100)
    assert all(len(c.legs) <= 2 for c in default_combos)

    research_combos = _builder(max_legs=3, min_legs=3, research_mode=True).build(
        legs, mode=SGPMode.PROPS_ONLY, top_n=100)
    assert any(len(c.legs) == 3 for c in research_combos)


def test_leg_default_source_is_safe():
    """A PropLeg built without an explicit source defaults to rule_fallback."""
    leg = PropLeg(
        player="P", market="player_points", line=10.5, model_prob=0.7,
        over_odds=-110, event_id="e", home_team="H", away_team="A",
        confidence="HIGH",
    )
    assert leg.source == "rule_fallback"
