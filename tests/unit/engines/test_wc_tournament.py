"""Tests for alpha.engines.sports.wc_tournament — TournamentState."""
from __future__ import annotations

import pytest

from alpha.engines.sports.wc_tournament import (
    PressureState,
    Stage,
    TeamStanding,
    TournamentState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _final_group(*, wins_a=3, wins_b=2, wins_c=1, wins_d=0) -> list[TeamStanding]:
    """All-done 4-team group with distinct point totals and 0 remaining."""
    return [
        TeamStanding("A", wins=wins_a, draws=0, losses=3 - wins_a, matches_remaining=0),
        TeamStanding("B", wins=wins_b, draws=0, losses=3 - wins_b, matches_remaining=0),
        TeamStanding("C", wins=wins_c, draws=0, losses=3 - wins_c, matches_remaining=0),
        TeamStanding("D", wins=wins_d, draws=0, losses=3 - wins_d, matches_remaining=0),
    ]


# ---------------------------------------------------------------------------
# TOURNEY-01: Qualification pressure state
# ---------------------------------------------------------------------------

def test_already_through_first_place():
    """Team A (9 pts, 0 remaining) is mathematically through."""
    ts = TournamentState()
    standings = _final_group()
    assert ts.classify_pressure(standings, "A") == PressureState.ALREADY_THROUGH


def test_already_through_second_place():
    """Team B (6 pts, 0 remaining) is also through when C max ≤ 3."""
    ts = TournamentState()
    standings = _final_group()
    assert ts.classify_pressure(standings, "B") == PressureState.ALREADY_THROUGH


def test_already_out():
    """Team with 2 rivals already exceeding its maximum possible points."""
    ts = TournamentState()
    standings = [
        TeamStanding("A", wins=2, draws=1, matches_remaining=0),  # 7 pts
        TeamStanding("B", wins=2, draws=0, losses=1, matches_remaining=0),  # 6 pts
        TeamStanding("C", wins=0, draws=1, losses=2, matches_remaining=1),  # 1 pt, max 4
        TeamStanding("D", wins=0, draws=0, losses=3, matches_remaining=1),  # 0 pts
    ]
    # C: max = 1 + 3 = 4; A(7) > 4 and B(6) > 4 → 2 locked above → already-out
    assert ts.classify_pressure(standings, "C") == PressureState.ALREADY_OUT


def test_draw_enough():
    """Team B (4 pts, 1 remaining) needs only a draw to secure top-2."""
    ts = TournamentState()
    standings = [
        TeamStanding("A", wins=2, draws=0, losses=0, goals_for=4, goals_against=1, matches_remaining=0),  # 6 pts
        TeamStanding("B", wins=1, draws=1, losses=0, goals_for=3, goals_against=2, matches_remaining=1),  # 4 pts
        TeamStanding("C", wins=0, draws=1, losses=1, goals_for=1, goals_against=3, matches_remaining=1),  # 1 pt
        TeamStanding("D", wins=0, draws=0, losses=2, goals_for=0, goals_against=5, matches_remaining=1),  # 0 pts
    ]
    # B draws → 5 pts. C max = 1+3=4 < 5. D max = 3 < 5. → draw-enough.
    assert ts.classify_pressure(standings, "B") == PressureState.DRAW_ENOUGH


def test_must_win():
    """Team C (3 pts, 1 remaining) must win to reach top-2."""
    ts = TournamentState()
    standings = [
        TeamStanding("A", wins=2, draws=1, losses=0, matches_remaining=0),  # 7 pts
        TeamStanding("B", wins=1, draws=1, losses=1, matches_remaining=1),  # 4 pts
        TeamStanding("C", wins=1, draws=0, losses=2, matches_remaining=1),  # 3 pts
        TeamStanding("D", wins=0, draws=0, losses=3, matches_remaining=1),  # 0 pts
    ]
    # C draws → 4 pts. B has 4 pts + can win → 7 pts. C can't guarantee top-2 with draw.
    assert ts.classify_pressure(standings, "C") == PressureState.MUST_WIN


def test_likely_through():
    """Team in top-2 but 3rd-place can still theoretically catch up."""
    ts = TournamentState()
    standings = [
        TeamStanding("A", wins=2, draws=1, losses=0, goals_for=7, goals_against=1, matches_remaining=0),  # 7 pts
        TeamStanding("B", wins=1, draws=1, losses=0, goals_for=4, goals_against=2, matches_remaining=1),  # 4 pts
        TeamStanding("C", wins=1, draws=1, losses=0, goals_for=3, goals_against=2, matches_remaining=1),  # 4 pts
        TeamStanding("D", wins=0, draws=0, losses=3, matches_remaining=1),  # 0 pts
    ]
    # B is 2nd (better GD than C). C has 4 pts + max 7 pts > B's draw result 5. → likely-through.
    assert ts.classify_pressure(standings, "B") == PressureState.LIKELY_THROUGH


def test_team_not_in_standings_raises():
    """Unknown team raises ValueError."""
    ts = TournamentState()
    with pytest.raises(ValueError, match="not found"):
        ts.classify_pressure(_final_group(), "Unknown")


# ---------------------------------------------------------------------------
# TOURNEY-02: Rotation risk
# ---------------------------------------------------------------------------

def test_rotation_risk_true_for_already_through():
    """Teams mathematically through should have rotation_risk = True."""
    ts = TournamentState()
    standings = _final_group()
    assert ts.rotation_risk(standings, "A") is True
    assert ts.rotation_risk(standings, "B") is True


def test_rotation_risk_false_for_must_win():
    """Teams that must win should not have rotation risk."""
    ts = TournamentState()
    standings = [
        TeamStanding("A", wins=2, draws=1, losses=0, matches_remaining=0),
        TeamStanding("B", wins=1, draws=1, losses=1, matches_remaining=1),
        TeamStanding("C", wins=1, draws=0, losses=2, matches_remaining=1),
        TeamStanding("D", wins=0, draws=0, losses=3, matches_remaining=1),
    ]
    assert ts.rotation_risk(standings, "C") is False


def test_rotation_risk_false_for_already_out():
    """Teams that are already-out are desperate, not rotating."""
    ts = TournamentState()
    standings = [
        TeamStanding("A", wins=2, draws=1, matches_remaining=0),
        TeamStanding("B", wins=2, draws=0, losses=1, matches_remaining=0),
        TeamStanding("C", wins=0, draws=1, losses=2, matches_remaining=1),
        TeamStanding("D", wins=0, draws=0, losses=3, matches_remaining=1),
    ]
    assert ts.rotation_risk(standings, "C") is False


# ---------------------------------------------------------------------------
# TOURNEY-03: Yellow-card suspension risk + resets
# ---------------------------------------------------------------------------

def test_suspension_risk_one_yellow():
    """Player on 1 yellow card is flagged as suspension risk."""
    assert TournamentState.suspension_risk(1) is True


def test_suspension_risk_zero_yellows():
    """Player on 0 yellows is not flagged."""
    assert TournamentState.suspension_risk(0) is False


def test_suspension_risk_two_yellows():
    """Player already on 2 yellows (likely suspended) is flagged."""
    assert TournamentState.suspension_risk(2) is True


def test_suspension_risk_custom_threshold():
    """Custom threshold of 2 — 1 yellow is not risky."""
    assert TournamentState.suspension_risk(1, threshold=2) is False
    assert TournamentState.suspension_risk(2, threshold=2) is True


def test_card_reset_entering_last_16():
    """All group-stage yellows wiped when entering LAST_16."""
    cards = {"PlayerA": 1, "PlayerB": 2, "PlayerC": 0}
    result = TournamentState.reset_cards(cards, Stage.LAST_16.value)
    assert result == {"PlayerA": 0, "PlayerB": 0, "PlayerC": 0}


def test_card_reset_entering_semi_finals():
    """QF-accumulated yellows wiped when entering SEMI_FINALS."""
    cards = {"PlayerX": 1, "PlayerY": 1}
    result = TournamentState.reset_cards(cards, Stage.SEMI_FINALS.value)
    assert result == {"PlayerX": 0, "PlayerY": 0}


def test_no_card_reset_quarter_finals():
    """No card wipe when entering QUARTER_FINALS."""
    cards = {"PlayerA": 1}
    result = TournamentState.reset_cards(cards, Stage.QUARTER_FINALS.value)
    assert result == {"PlayerA": 1}


def test_no_card_reset_group_stage():
    """No wipe within group stage."""
    cards = {"P": 1}
    result = TournamentState.reset_cards(cards, Stage.GROUP_STAGE.value)
    assert result == {"P": 1}


def test_card_reset_does_not_mutate_original():
    """reset_cards returns a new dict and does not mutate the input."""
    original = {"Player1": 1}
    result = TournamentState.reset_cards(original, Stage.LAST_16.value)
    assert original == {"Player1": 1}  # unchanged
    assert result == {"Player1": 0}


# ---------------------------------------------------------------------------
# TOURNEY-04: Best-third-place ranking
# ---------------------------------------------------------------------------

def _make_thirds() -> list[TeamStanding]:
    """
    12 third-place teams for 2026 format test.
    Top 8 by (pts, gd, gf) should qualify.
    """
    return [
        TeamStanding("G01-3rd", wins=1, draws=2, losses=0, goals_for=5, goals_against=3),   # 5 pts
        TeamStanding("G02-3rd", wins=1, draws=1, losses=1, goals_for=4, goals_against=3),   # 4 pts, +1
        TeamStanding("G03-3rd", wins=1, draws=1, losses=1, goals_for=3, goals_against=3),   # 4 pts, 0
        TeamStanding("G04-3rd", wins=1, draws=1, losses=1, goals_for=3, goals_against=4),   # 4 pts, -1
        TeamStanding("G05-3rd", wins=1, draws=0, losses=2, goals_for=4, goals_against=4),   # 3 pts, 0
        TeamStanding("G06-3rd", wins=1, draws=0, losses=2, goals_for=3, goals_against=4),   # 3 pts, -1
        TeamStanding("G07-3rd", wins=1, draws=0, losses=2, goals_for=2, goals_against=4),   # 3 pts, -2
        TeamStanding("G08-3rd", wins=1, draws=0, losses=2, goals_for=2, goals_against=5),   # 3 pts, -3
        # Below threshold (won't qualify)
        TeamStanding("G09-3rd", wins=0, draws=2, losses=1, goals_for=2, goals_against=3),   # 2 pts
        TeamStanding("G10-3rd", wins=0, draws=1, losses=2, goals_for=1, goals_against=3),   # 1 pt
        TeamStanding("G11-3rd", wins=0, draws=1, losses=2, goals_for=1, goals_against=4),   # 1 pt
        TeamStanding("G12-3rd", wins=0, draws=0, losses=3, goals_for=0, goals_against=5),   # 0 pts
    ]


def test_best_third_returns_eight():
    """WC 2026: exactly 8 best third-place teams should be returned."""
    ts = TournamentState()
    qualifiers = ts.best_third_qualifiers(_make_thirds())
    assert len(qualifiers) == 8


def test_best_third_top_team_first():
    """Team with 5 pts is the best third-place team."""
    ts = TournamentState()
    qualifiers = ts.best_third_qualifiers(_make_thirds())
    assert qualifiers[0] == "G01-3rd"


def test_best_third_excludes_worst_four():
    """Bottom 4 teams (2 pts, 1 pt, 1 pt, 0 pts) should not qualify."""
    ts = TournamentState()
    qualifiers = ts.best_third_qualifiers(_make_thirds())
    non_qualifiers = {"G09-3rd", "G10-3rd", "G11-3rd", "G12-3rd"}
    assert not non_qualifiers.intersection(qualifiers)


def test_best_third_respects_goal_diff_tiebreak():
    """Teams tied on points are ranked by goal difference."""
    ts = TournamentState()
    qualifiers = ts.best_third_qualifiers(_make_thirds())
    # G02-3rd (4 pts, +1 gd) should rank above G03-3rd (4 pts, 0 gd)
    assert qualifiers.index("G02-3rd") < qualifiers.index("G03-3rd")


# ---------------------------------------------------------------------------
# TOURNEY-05: Tiebreak features
# ---------------------------------------------------------------------------

def test_tiebreak_features_fair_play():
    """Fair-play score is negative (cards = penalty)."""
    standing = TeamStanding("Spain", yellow_cards=3, red_cards=1)
    feats = TournamentState.get_tiebreak_features(standing, fifa_rank=8)
    # fair_play = -(3 + 3*1) = -6
    assert feats["fair_play_score"] == -6


def test_tiebreak_features_fifa_rank():
    """FIFA rank is returned as-is."""
    standing = TeamStanding("Germany")
    feats = TournamentState.get_tiebreak_features(standing, fifa_rank=12)
    assert feats["fifa_rank"] == 12


def test_tiebreak_features_default_rank():
    """Missing FIFA rank defaults to 999."""
    standing = TeamStanding("SomeTeam")
    feats = TournamentState.get_tiebreak_features(standing)
    assert feats["fifa_rank"] == 999


def test_tiebreak_features_clean_sheet():
    """Team with no cards has fair_play_score = 0."""
    standing = TeamStanding("France", yellow_cards=0, red_cards=0)
    feats = TournamentState.get_tiebreak_features(standing)
    assert feats["fair_play_score"] == 0
