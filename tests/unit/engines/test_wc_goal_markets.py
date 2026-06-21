"""Tests for the World Cup scoreline and goal-market model."""
from __future__ import annotations

import pytest

from alpha.engines.sports.wc_goal_markets import WCScorelineModel


TEAM_STATS = {
    "Brazil": {"avg_xG": 1.9, "defense_score": 0.8},
    "Germany": {"avg_xG": 1.5, "defense_score": 1.1},
}


def _game(**overrides):
    game = {
        "home_team": "Brazil",
        "away_team": "Germany",
        "stage": "GROUP_STAGE",
        "win_prob": 0.55,
        "draw_prob": 0.25,
        "loss_prob": 0.20,
    }
    game.update(overrides)
    return game


def test_goal_rates_use_team_attack_and_opponent_defense():
    distribution = WCScorelineModel(TEAM_STATS).build(_game())
    assert distribution.home_lambda == pytest.approx(1.5)
    assert distribution.away_lambda == pytest.approx(1.15)


def test_missing_stats_use_neutral_bounded_fallback():
    distribution = WCScorelineModel({}).build(_game())
    assert 0.25 <= distribution.home_lambda <= 3.5
    assert 0.25 <= distribution.away_lambda <= 3.5
    assert distribution.home_lambda == distribution.away_lambda


def test_scoreline_distribution_matches_elo_1x2_marginals():
    distribution = WCScorelineModel(TEAM_STATS).build(_game())
    assert distribution.probability("home_win") == pytest.approx(0.55, abs=1e-9)
    assert distribution.probability("draw") == pytest.approx(0.25, abs=1e-9)
    assert distribution.probability("away_win") == pytest.approx(0.20, abs=1e-9)


def test_binary_goal_markets_are_coherent():
    distribution = WCScorelineModel(TEAM_STATS).build(_game())
    assert distribution.probability("over_2_5") + distribution.probability("under_2_5") == pytest.approx(1.0)
    assert distribution.probability("btts_yes") + distribution.probability("btts_no") == pytest.approx(1.0)
    assert sum(distribution.cells.values()) == pytest.approx(1.0)


def test_joint_probability_uses_scorelines_not_naive_multiplication():
    distribution = WCScorelineModel(TEAM_STATS).build(_game())
    joint = distribution.joint_probability(["home_win", "over_2_5"])
    naive = distribution.probability("home_win") * distribution.probability("over_2_5")
    assert joint > 0
    assert joint != pytest.approx(naive, abs=1e-3)


@pytest.mark.parametrize(
    "legs",
    [
        ["home_win", "away_win"],
        ["over_2_5", "under_2_5"],
        ["btts_yes", "btts_no"],
        ["not_a_market", "over_2_5"],
    ],
)
def test_joint_probability_rejects_invalid_or_contradictory_legs(legs):
    distribution = WCScorelineModel(TEAM_STATS).build(_game())
    with pytest.raises(ValueError):
        distribution.joint_probability(legs)


def test_knockout_goal_markets_do_not_use_advance_probabilities_as_1x2():
    distribution = WCScorelineModel(TEAM_STATS).build(
        _game(stage="QUARTER_FINALS", win_prob=0.70, draw_prob=0.0, loss_prob=0.30)
    )
    assert distribution.outcome_available is False
    assert distribution.probability("over_2_5") > 0
    with pytest.raises(ValueError, match="not available"):
        distribution.probability("home_win")

