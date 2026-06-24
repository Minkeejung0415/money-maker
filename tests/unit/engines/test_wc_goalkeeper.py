"""Tests for alpha.engines.sports.wc_goalkeeper — GoalkeeperModule."""
from __future__ import annotations

import pytest

from alpha.engines.sports.wc_goalkeeper import (
    GKFeatures,
    GKStats,
    GoalkeeperModule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _above_avg_stats() -> GKStats:
    return GKStats(
        goals_prevented=0.5,
        save_high=2.0, save_medium=3.0, save_low=1.0,
        cross_claims=3.0, crosses_not_claimed=1.0,
        sweeper_actions=2.0,
    )


def _neutral_stats() -> GKStats:
    return GKStats(
        goals_prevented=0.0,
        save_high=1.0, save_medium=2.0, save_low=1.0,
        cross_claims=2.0, crosses_not_claimed=2.0,
        sweeper_actions=1.0,
    )


# ---------------------------------------------------------------------------
# GK-01: Goals prevented and save distribution
# ---------------------------------------------------------------------------

def test_positive_goals_prevented_increases_strength():
    """GK with +0.5 goals prevented should score higher than one with 0."""
    gk = GoalkeeperModule()
    strong = gk.compute("GK_A", _above_avg_stats())
    neutral = gk.compute("GK_B", _neutral_stats())
    assert strong.gk_strength > neutral.gk_strength


def test_negative_goals_prevented_reduces_strength():
    """GK conceding above xGOT should have lower strength."""
    gk = GoalkeeperModule()
    poor_stats = GKStats(goals_prevented=-0.5, save_high=1.0, save_medium=1.0, save_low=1.0)
    poor = gk.compute("GK_Poor", poor_stats)
    neutral = gk.compute("GK_Neutral", _neutral_stats())
    assert poor.gk_strength < neutral.gk_strength


def test_save_distribution_zero_when_no_saves():
    """No saves → save_distribution_score = 0.0."""
    gk = GoalkeeperModule()
    stats = GKStats(goals_prevented=0.0, save_high=0.0, save_medium=0.0, save_low=0.0)
    f = gk.compute("GK1", stats)
    assert f.save_distribution_score == pytest.approx(0.0)


def test_save_distribution_positive_with_saves():
    """Any saves → save_distribution_score > 0."""
    gk = GoalkeeperModule()
    f = gk.compute("GK1", _above_avg_stats())
    assert f.save_distribution_score > 0.0


# ---------------------------------------------------------------------------
# GK-02: Cross claims and sweeper actions
# ---------------------------------------------------------------------------

def test_cross_command_perfect():
    """All crosses claimed → cross_command_score == _CROSS_COMMAND_WEIGHT."""
    gk = GoalkeeperModule()
    stats = GKStats(cross_claims=5.0, crosses_not_claimed=0.0)
    f = gk.compute("GK1", stats)
    assert f.cross_command_score == pytest.approx(10.0)


def test_cross_command_zero_no_crosses():
    """No crosses → cross_command_score = 0.0."""
    gk = GoalkeeperModule()
    stats = GKStats(cross_claims=0.0, crosses_not_claimed=0.0)
    f = gk.compute("GK1", stats)
    assert f.cross_command_score == pytest.approx(0.0)


def test_sweeper_score_capped_at_max():
    """Sweeper actions >= 5 → sweeper_score capped at max (5.0)."""
    gk = GoalkeeperModule()
    stats = GKStats(sweeper_actions=10.0)
    f = gk.compute("GK1", stats)
    assert f.sweeper_score == pytest.approx(5.0)


def test_sweeper_score_zero():
    """No sweeper actions → sweeper_score = 0.0."""
    gk = GoalkeeperModule()
    stats = GKStats(sweeper_actions=0.0)
    f = gk.compute("GK1", stats)
    assert f.sweeper_score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# GK-03: Continuity modifier
# ---------------------------------------------------------------------------

def test_continuity_no_change():
    """Same GK and CBs → continuity_modifier = 0.0."""
    gk = GoalkeeperModule(last_gk="GK1", last_cbs={"CB1", "CB2"})
    f = gk.compute("GK1", _neutral_stats(), cb_names={"CB1", "CB2"})
    assert f.continuity_modifier == pytest.approx(0.0)


def test_continuity_gk_change():
    """New GK → continuity_modifier = -0.1."""
    gk = GoalkeeperModule(last_gk="OldGK", last_cbs={"CB1", "CB2"})
    f = gk.compute("NewGK", _neutral_stats(), cb_names={"CB1", "CB2"})
    assert f.continuity_modifier == pytest.approx(-0.1)


def test_continuity_cb_change():
    """One CB changed → modifier = -0.1."""
    gk = GoalkeeperModule(last_gk="GK1", last_cbs={"CB1", "CB2"})
    f = gk.compute("GK1", _neutral_stats(), cb_names={"CB1", "NewCB"})
    assert f.continuity_modifier == pytest.approx(-0.1)


def test_continuity_gk_and_cb_change():
    """GK + one CB changed → modifier = -0.2."""
    gk = GoalkeeperModule(last_gk="OldGK", last_cbs={"CB1", "CB2"})
    f = gk.compute("NewGK", _neutral_stats(), cb_names={"CB1", "NewCB"})
    assert f.continuity_modifier == pytest.approx(-0.2)


def test_continuity_no_reference():
    """No last lineup → modifier = 0.0 regardless of current GK/CBs."""
    gk = GoalkeeperModule()
    f = gk.compute("AnyGK", _neutral_stats(), cb_names={"CB1", "CB2"})
    assert f.continuity_modifier == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# GK-04: Independence from xg_defense
# ---------------------------------------------------------------------------

def test_can_remove_independently():
    """GK-04: module confirms independence from xg_defense."""
    gk = GoalkeeperModule()
    assert gk.can_remove_independently() is True


def test_features_returned_independently():
    """GoalkeeperModule.compute() returns GKFeatures, not WCTeamRatings fields."""
    gk = GoalkeeperModule()
    f = gk.compute("GK1", _above_avg_stats())
    assert isinstance(f, GKFeatures)
    assert hasattr(f, "gk_strength")
    assert not hasattr(f, "xg_defense")  # not mixed with team defense
