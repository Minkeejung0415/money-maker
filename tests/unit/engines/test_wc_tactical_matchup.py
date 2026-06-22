"""Tests for tactical style comparison."""
from __future__ import annotations

from dataclasses import replace

from alpha.data.ingestion.wc_tactics import WCTacticalProfile
from alpha.engines.sports.wc_tactical_matchup import compare_tactics


def _profile(team="Spain", **overrides):
    values = dict(
        team=team, matches=5, latest_match="2026-06-15", formation="4-3-3",
        possession=0.58, pass_completion=0.86, long_ball_rate=0.08,
        cross_rate=0.04, shots_for=15.0, shots_allowed=9.0,
        shot_on_target_rate=0.36, corners_for=6.0, corners_allowed=3.5,
        pressing_proxy=4.0, clearances=12.0,
    )
    values.update(overrides)
    return WCTacticalProfile(**values)


def test_comparison_is_bounded_and_explainable():
    home = _profile()
    away = _profile("Saudi Arabia", possession=0.38, pass_completion=0.70, shots_for=7, shots_allowed=18, clearances=28)
    result = compare_tactics(home, away)
    assert 0.90 <= result.home_attack_multiplier <= 1.10
    assert 0.90 <= result.away_attack_multiplier <= 1.10
    assert result.home_explanations
    assert "chance creation" in result.home_components


def test_reversing_teams_swaps_the_comparison_exactly():
    home = _profile()
    away = _profile("Germany", possession=0.48, shots_for=12, clearances=18)
    forward = compare_tactics(home, away)
    reverse = compare_tactics(away, home)
    assert forward.home_attack_multiplier == reverse.away_attack_multiplier
    assert forward.away_attack_multiplier == reverse.home_attack_multiplier
    assert forward.home_components == reverse.away_components


def test_extreme_profiles_remain_capped():
    dominant = _profile(possession=1.0, pass_completion=1.0, shots_for=50, corners_for=20, pressing_proxy=10)
    weak = _profile("Weak", possession=0.0, pass_completion=0.2, shots_for=1, shots_allowed=50, clearances=50)
    result = compare_tactics(dominant, weak)
    assert result.home_attack_multiplier <= 1.10
    assert result.away_attack_multiplier >= 0.90


def test_formation_is_context_not_a_numeric_input():
    home = _profile()
    away = _profile("Germany")
    baseline = compare_tactics(home, away)
    changed = compare_tactics(replace(home, formation="5-4-1"), away)
    assert baseline.home_attack_multiplier == changed.home_attack_multiplier
    assert changed.home_formation == "5-4-1"

