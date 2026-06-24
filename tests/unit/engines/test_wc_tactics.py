"""Tests for alpha.engines.sports.wc_tactics — TacticalEngine."""
from __future__ import annotations

import pytest

from alpha.engines.sports.wc_tactics import (
    MatchSummary,
    StyleMatchup,
    TacticalEngine,
    TacticalProfile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pressing_match(team: str) -> MatchSummary:
    """High-press, counter-attacking team match."""
    return MatchSummary(
        team=team,
        ppda=6.0,         # low PPDA = high press
        possession=38.0,  # counter style
        transitions=10,
        rest_defense_conceded=0,
        rest_defense_transitions_faced=8,
        sp_xg_for=0.30,
        sp_xg_against=0.10,
        corner_xg_for=0.15,
        corner_xg_against=0.05,
        aerial_duels_won_rate=0.65,
        open_play_xg_for=1.5,
        open_play_xg_against=0.8,
    )


def _possession_match(team: str) -> MatchSummary:
    """Possession-heavy, low-transition team match."""
    return MatchSummary(
        team=team,
        ppda=14.0,        # high PPDA = less pressing
        possession=68.0,
        transitions=3,
        rest_defense_conceded=1,
        rest_defense_transitions_faced=4,
        sp_xg_for=0.20,
        sp_xg_against=0.25,
        corner_xg_for=0.10,
        corner_xg_against=0.12,
        aerial_duels_won_rate=0.45,
        open_play_xg_for=1.8,
        open_play_xg_against=0.5,
    )


# ---------------------------------------------------------------------------
# TACTICAL-01: PPDA and possession profile
# ---------------------------------------------------------------------------

def test_profile_has_all_required_fields():
    """TacticalProfile must expose all documented fields."""
    engine = TacticalEngine()
    engine.update(_pressing_match("Spain"))
    profile = engine.get_profile("Spain")

    assert hasattr(profile, "ppda")
    assert hasattr(profile, "possession_index")
    assert hasattr(profile, "counterattack_freq")
    assert hasattr(profile, "rest_defense_stability")
    assert hasattr(profile, "sp_xg_for_ewma")
    assert hasattr(profile, "sp_xg_against_ewma")
    assert hasattr(profile, "corner_xg_for_ewma")
    assert hasattr(profile, "corner_xg_against_ewma")
    assert hasattr(profile, "aerial_duel_edge")


def test_ppda_updated_from_match():
    """PPDA should reflect match input after update."""
    engine = TacticalEngine()
    engine.update(_pressing_match("Brazil"))
    profile = engine.get_profile("Brazil")
    # Should be pulled from default toward 6.0 (pressing match)
    assert profile.ppda < 10.0


def test_possession_index_range():
    """possession_index must be in [0, 1]."""
    engine = TacticalEngine()
    engine.update(_possession_match("Germany"))
    engine.update(_pressing_match("Germany"))
    profile = engine.get_profile("Germany")
    assert 0.0 <= profile.possession_index <= 1.0


def test_high_press_team_has_lower_ppda():
    """Pressing team PPDA should be lower than possession team."""
    engine = TacticalEngine()
    # Feed pressing team 5 matches
    for _ in range(5):
        engine.update(_pressing_match("Press-FC"))
    for _ in range(5):
        engine.update(_possession_match("Poss-FC"))

    assert engine.get_profile("Press-FC").ppda < engine.get_profile("Poss-FC").ppda


def test_possession_team_has_higher_possession_index():
    """Possession team should have higher possession_index than counter team."""
    engine = TacticalEngine()
    for _ in range(5):
        engine.update(_pressing_match("Counter-FC"))
    for _ in range(5):
        engine.update(_possession_match("Poss-FC"))

    assert (
        engine.get_profile("Poss-FC").possession_index
        > engine.get_profile("Counter-FC").possession_index
    )


# ---------------------------------------------------------------------------
# TACTICAL-02: Counterattack frequency and rest-defense
# ---------------------------------------------------------------------------

def test_counterattack_freq_reflects_transitions():
    """Counter-attacking team should have higher counterattack_freq."""
    engine = TacticalEngine()
    for _ in range(5):
        engine.update(_pressing_match("Counter"))   # transitions=10
    for _ in range(5):
        engine.update(_possession_match("Possession"))  # transitions=3

    assert (
        engine.get_profile("Counter").counterattack_freq
        > engine.get_profile("Possession").counterattack_freq
    )


def test_rest_defense_stability_perfect_when_none_conceded():
    """Team conceding 0 on rest-defense → stability approaches 1.0."""
    engine = TacticalEngine()
    for _ in range(10):
        engine.update(MatchSummary(
            team="Solid",
            rest_defense_conceded=0,
            rest_defense_transitions_faced=5,
        ))
    assert engine.get_profile("Solid").rest_defense_stability > 0.9


def test_rest_defense_stability_low_when_leaky():
    """Team conceding often on transitions should have lower stability."""
    engine = TacticalEngine()
    for _ in range(5):
        engine.update(MatchSummary(
            team="Leaky",
            rest_defense_conceded=2,
            rest_defense_transitions_faced=4,
        ))
    assert engine.get_profile("Leaky").rest_defense_stability < 0.70


# ---------------------------------------------------------------------------
# TACTICAL-03: Style matchup interactions
# ---------------------------------------------------------------------------

def test_matchup_returns_styleatchup():
    """compute_matchup must return a StyleMatchup instance."""
    engine = TacticalEngine()
    engine.update(_pressing_match("Argentina"))
    engine.update(_possession_match("France"))
    result = engine.compute_matchup("Argentina", "France")
    assert isinstance(result, StyleMatchup)


def test_press_vs_build_high_for_press_vs_poss():
    """High-press team vs possession team → higher press_vs_build."""
    engine = TacticalEngine()
    for _ in range(5):
        engine.update(_pressing_match("PressTeam"))
    for _ in range(5):
        engine.update(_possession_match("PossTeam"))
    for _ in range(5):
        engine.update(_pressing_match("CounterTeam"))  # both press teams

    # PressTeam vs PossTeam: high press × high possession_index → higher
    matchup_press_vs_poss = engine.compute_matchup("PressTeam", "PossTeam")
    # PressTeam vs CounterTeam: high press × low possession_index → lower
    matchup_press_vs_counter = engine.compute_matchup("PressTeam", "CounterTeam")

    assert matchup_press_vs_poss.press_vs_build > matchup_press_vs_counter.press_vs_build


def test_possession_vs_transition_positive_for_poss_vs_counter():
    """Possession team hosting counter team → positive possession_vs_transition."""
    engine = TacticalEngine()
    for _ in range(5):
        engine.update(_possession_match("Spain"))
    for _ in range(5):
        engine.update(_pressing_match("Morocco"))

    matchup = engine.compute_matchup("Spain", "Morocco")
    # Spain (high poss) vs Morocco (low poss) → positive value
    assert matchup.possession_vs_transition > 0


def test_interaction_features_symmetric_by_construction():
    """width_vs_centrality uses home team's transitions × away vulnerability."""
    engine = TacticalEngine()
    for _ in range(5):
        engine.update(_pressing_match("A"))  # high transitions
    for _ in range(5):
        engine.update(MatchSummary(
            team="B",
            rest_defense_conceded=3,
            rest_defense_transitions_faced=4,  # leaky rest defense
        ))

    matchup = engine.compute_matchup("A", "B")
    # A's transitions × B's rest-defense vulnerability should be positive
    assert matchup.width_vs_centrality > 0


# ---------------------------------------------------------------------------
# TACTICAL-04: Set-piece states independent of open-play xG
# ---------------------------------------------------------------------------

def test_setpiece_unaffected_by_removing_openplay():
    """Removing open-play xG states must not affect set-piece EWMA."""
    engine = TacticalEngine()
    for _ in range(3):
        engine.update(MatchSummary(
            team="Portugal",
            sp_xg_for=0.40,
            sp_xg_against=0.15,
            corner_xg_for=0.20,
            open_play_xg_for=2.0,
            open_play_xg_against=0.6,
        ))

    sp_before = engine.get_profile("Portugal").sp_xg_for_ewma
    corner_before = engine.get_profile("Portugal").corner_xg_for_ewma

    # Remove open-play xG states
    engine.reset_open_play_xg("Portugal")

    sp_after = engine.get_profile("Portugal").sp_xg_for_ewma
    corner_after = engine.get_profile("Portugal").corner_xg_for_ewma

    assert sp_after == pytest.approx(sp_before)
    assert corner_after == pytest.approx(corner_before)


def test_openplay_xg_separate_from_setpiece():
    """open_xg_for_ewma and sp_xg_for_ewma update independently."""
    engine = TacticalEngine()
    engine.update(MatchSummary(
        team="Test",
        sp_xg_for=0.5,
        open_play_xg_for=0.0,  # zero open-play xG
    ))
    profile = engine.get_profile("Test")
    # Set-piece should be nonzero, open-play pulled toward 0
    assert profile.sp_xg_for_ewma > 0
    # open_xg_for_ewma starts at 1.0 default, pulled toward 0 but not equal to sp
    assert profile.open_xg_for_ewma != profile.sp_xg_for_ewma


def test_setpiece_ewma_increases_with_high_sp_matches():
    """Team with consistent high sp_xg should have elevated sp_xg_for_ewma."""
    engine = TacticalEngine()
    for _ in range(8):
        engine.update(MatchSummary(team="SetPieceKing", sp_xg_for=0.8))
    assert engine.get_profile("SetPieceKing").sp_xg_for_ewma > 0.5


# ---------------------------------------------------------------------------
# TACTICAL-05: Corner xG and aerial duel edge
# ---------------------------------------------------------------------------

def test_aerial_duel_edge_positive_for_strong_aerial_team():
    """Team winning 70% aerial duels → positive aerial_duel_edge."""
    engine = TacticalEngine()
    for _ in range(5):
        engine.update(MatchSummary(team="AerialTeam", aerial_duels_won_rate=0.70))
    assert engine.get_profile("AerialTeam").aerial_duel_edge > 0.0


def test_aerial_duel_edge_negative_for_weak_aerial_team():
    """Team winning 30% aerial duels → negative aerial_duel_edge."""
    engine = TacticalEngine()
    for _ in range(5):
        engine.update(MatchSummary(team="SmallTeam", aerial_duels_won_rate=0.30))
    assert engine.get_profile("SmallTeam").aerial_duel_edge < 0.0


def test_corner_xg_tracked_separately():
    """corner_xg_for_ewma and sp_xg_for_ewma can differ."""
    engine = TacticalEngine()
    engine.update(MatchSummary(
        team="Corners",
        sp_xg_for=0.5,        # total set-piece
        corner_xg_for=0.2,    # corners are subset
    ))
    profile = engine.get_profile("Corners")
    assert profile.corner_xg_for_ewma != profile.sp_xg_for_ewma


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_unknown_team_returns_defaults():
    """get_profile for unknown team returns sensible defaults, not error."""
    engine = TacticalEngine()
    profile = engine.get_profile("UnknownFC")
    assert isinstance(profile, TacticalProfile)
    assert profile.ppda > 0
    assert 0.0 <= profile.possession_index <= 1.0


def test_teams_with_data_lists_updated_teams():
    """teams_with_data returns only teams that have received updates."""
    engine = TacticalEngine()
    engine.update(_pressing_match("TeamA"))
    engine.update(_possession_match("TeamB"))
    teams = engine.teams_with_data()
    assert "TeamA" in teams
    assert "TeamB" in teams
    assert "TeamC" not in teams
