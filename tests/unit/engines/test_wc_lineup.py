"""Tests for alpha.engines.sports.wc_lineup — LineupProjector."""
from __future__ import annotations

import math

import pytest

from alpha.engines.sports.wc_lineup import (
    LineupFeatures,
    LineupProjector,
    PlayerInfo,
    build_mock_squad,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _squad_three_cbs() -> dict[str, PlayerInfo]:
    """Squad with 3 CBs at value=80, p_start=1.0."""
    return {
        "GK1": PlayerInfo(role="GK", p_start=1.0, value=75.0, replacement_value=60.0),
        "CB1": PlayerInfo(role="CB", p_start=1.0, value=80.0, replacement_value=65.0),
        "CB2": PlayerInfo(role="CB", p_start=1.0, value=80.0, replacement_value=65.0),
        "CB3": PlayerInfo(role="CB", p_start=1.0, value=80.0, replacement_value=65.0),
        "ST1": PlayerInfo(role="ST", p_start=1.0, value=90.0, replacement_value=70.0),
    }


def _simple_squad() -> dict[str, PlayerInfo]:
    """Minimal squad for continuity and absence tests."""
    return {
        "GK1": PlayerInfo(role="GK", p_start=0.95, value=75.0, replacement_value=55.0),
        "CB1": PlayerInfo(role="CB", p_start=0.90, value=80.0, replacement_value=60.0),
        "CB2": PlayerInfo(role="CB", p_start=0.85, value=78.0, replacement_value=58.0),
        "ST1": PlayerInfo(role="ST", p_start=0.92, value=95.0, replacement_value=70.0),
    }


# ---------------------------------------------------------------------------
# Line score tests (LINEUP-02)
# ---------------------------------------------------------------------------

def test_line_scores_sum_not_mean():
    """3 CB at value=80, p_start=1.0 → back_score=240.0 (sum, not 80.0 mean)."""
    squad = _squad_three_cbs()
    features = LineupProjector().project(squad)
    assert features.back_score == pytest.approx(240.0)


def test_ten_player_lower_than_eleven():
    """Removing one back (p_start=0) reduces back_score."""
    squad = _squad_three_cbs()
    features_11 = LineupProjector().project(squad)

    # Drop one CB
    squad["CB3"] = PlayerInfo(role="CB", p_start=0.0, value=80.0, replacement_value=65.0)
    features_10 = LineupProjector().project(squad)

    assert features_10.back_score < features_11.back_score


def test_total_score_sum_of_lines():
    """total_score == gk_score + back_score + midfield_score + front_score."""
    squad = build_mock_squad(team_strength=80.0)
    f = LineupProjector().project(squad)
    expected = f.gk_score + f.back_score + f.midfield_score + f.front_score
    assert f.total_score == pytest.approx(expected)


def test_expected_starters_approx_eleven():
    """Default mock squad → expected_starters ≈ 11.0 ± 0.5."""
    squad = build_mock_squad(team_strength=75.0)
    f = LineupProjector().project(squad)
    assert abs(f.expected_starters - 11.0) < 1.5


# ---------------------------------------------------------------------------
# Absence impact tests (LINEUP-03)
# ---------------------------------------------------------------------------

def test_absence_impact_key_player():
    """value=90, replacement=60 → absence_impact = 30.0."""
    squad = {
        "Star": PlayerInfo(role="ST", p_start=0.95, value=90.0, replacement_value=60.0),
    }
    f = LineupProjector().project(squad)
    assert f.absence_impacts["Star"] == pytest.approx(30.0)


def test_absence_impact_non_negative():
    """Replacement value > player value → impact clipped to 0."""
    squad = {
        "Bench": PlayerInfo(role="CM", p_start=0.10, value=50.0, replacement_value=70.0),
    }
    f = LineupProjector().project(squad)
    assert f.absence_impacts["Bench"] == pytest.approx(0.0)


def test_absence_impact_all_non_negative():
    """All absence impacts must be >= 0."""
    squad = build_mock_squad(team_strength=80.0)
    f = LineupProjector().project(squad)
    assert all(v >= 0.0 for v in f.absence_impacts.values())


# ---------------------------------------------------------------------------
# Uncertainty band tests (LINEUP-04)
# ---------------------------------------------------------------------------

def test_uncertainty_high_when_probs_bimodal():
    """Mix of p_start=1.0 and p_start=0.0 → std dev ~0.5 (HIGH)."""
    squad = {
        "P1": PlayerInfo(role="ST", p_start=1.0, value=80.0, replacement_value=60.0),
        "P2": PlayerInfo(role="CM", p_start=0.0, value=80.0, replacement_value=60.0),
        "P3": PlayerInfo(role="CB", p_start=1.0, value=80.0, replacement_value=60.0),
        "P4": PlayerInfo(role="LB", p_start=0.0, value=80.0, replacement_value=60.0),
    }
    f = LineupProjector().project(squad)
    assert f.uncertainty_band > 0.35
    assert f.lineup_confidence == "HIGH"


def test_uncertainty_low_when_probs_uniform():
    """All p_start ≈ 0.45 → std dev ≈ 0 (LOW)."""
    squad = {
        "P1": PlayerInfo(role="ST", p_start=0.45, value=80.0, replacement_value=60.0),
        "P2": PlayerInfo(role="CM", p_start=0.45, value=80.0, replacement_value=60.0),
        "P3": PlayerInfo(role="CB", p_start=0.45, value=80.0, replacement_value=60.0),
    }
    f = LineupProjector().project(squad)
    assert f.uncertainty_band < 0.35
    assert f.lineup_confidence == "LOW"


# ---------------------------------------------------------------------------
# Continuity modifier tests (LINEUP-05)
# ---------------------------------------------------------------------------

def test_continuity_modifier_unchanged():
    """Same GK and CBs as reference → modifier = 0.0."""
    reference = {"GK1": "GK", "CB1": "CB", "CB2": "CB"}
    squad = _simple_squad()
    f = LineupProjector(reference_lineup=reference).project(squad)
    assert f.continuity_modifier == pytest.approx(0.0)


def test_continuity_modifier_gk_change():
    """GK changed (new player) → modifier = -0.05."""
    reference = {"OldGK": "GK", "CB1": "CB", "CB2": "CB"}
    squad = _simple_squad()  # GK1 is new (not in reference)
    f = LineupProjector(reference_lineup=reference).project(squad)
    # GK1 starts (p_start=0.95 > 0.5) and is not in reference → -0.05
    assert f.continuity_modifier <= -0.05


def test_continuity_modifier_two_cb_changes():
    """Two CBs changed → modifier = -0.10."""
    reference = {"GK1": "GK", "OldCB1": "CB", "OldCB2": "CB"}
    squad = _simple_squad()  # CB1, CB2 are new
    f = LineupProjector(reference_lineup=reference).project(squad)
    # CB1 (0.90 > 0.5) + CB2 (0.85 > 0.5) both new → -0.10
    assert f.continuity_modifier <= -0.10


def test_continuity_no_reference():
    """No reference lineup → modifier = 0.0."""
    squad = _simple_squad()
    f = LineupProjector().project(squad)
    assert f.continuity_modifier == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_squad():
    """Empty squad returns zero-valued features without error."""
    f = LineupProjector().project({})
    assert f.total_score == 0.0
    assert f.expected_starters == 0.0
    assert f.lineup_confidence == "LOW"


def test_build_mock_squad_count():
    """build_mock_squad returns a non-empty dict."""
    squad = build_mock_squad()
    assert len(squad) > 0


def test_build_mock_squad_strength_scaling():
    """Higher team_strength produces higher line scores."""
    f_strong = LineupProjector().project(build_mock_squad(team_strength=90.0))
    f_weak = LineupProjector().project(build_mock_squad(team_strength=60.0))
    assert f_strong.total_score > f_weak.total_score
