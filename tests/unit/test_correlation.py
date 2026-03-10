"""Unit tests for CorrelationEngine."""
from __future__ import annotations

import math

import pytest

from alpha.engines.sports.correlation import CorrelationEngine, CorrelationType


@pytest.fixture
def engine():
    return CorrelationEngine(season="2024-25")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_perfect_positive_correlation(engine):
    """Identical binary vectors → r ≈ 1.0."""
    vec = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0,
           1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    game_vectors = {
        "PlayerA": {"PTS": vec},
        "PlayerB": {"PTS": vec},
    }
    r = engine._compute_r(game_vectors, "PlayerA", "player_points", "PlayerB", "player_points")
    assert r == pytest.approx(1.0, abs=1e-6)


def test_perfect_negative_correlation(engine):
    """Perfectly opposite binary vectors → r ≈ -1.0."""
    vec_a = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0,
             1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    vec_b = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0,
             0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    game_vectors = {
        "PlayerA": {"PTS": vec_a},
        "PlayerB": {"PTS": vec_b},
    }
    r = engine._compute_r(game_vectors, "PlayerA", "player_points", "PlayerB", "player_points")
    assert r == pytest.approx(-1.0, abs=1e-6)


def test_adjust_joint_positive_r_increases_above_product(engine):
    """Positive correlation should increase joint prob above naive product."""
    p_a, p_b, r = 0.6, 0.55, 0.4
    joint = engine.adjust_joint_prob(p_a, p_b, r)
    naive = p_a * p_b
    assert joint > naive


def test_adjust_joint_negative_r_decreases_below_product(engine):
    """Negative correlation should decrease joint prob below naive product."""
    p_a, p_b, r = 0.6, 0.55, -0.4
    joint = engine.adjust_joint_prob(p_a, p_b, r)
    naive = p_a * p_b
    assert joint < naive


def test_classify_thresholds(engine):
    assert engine.classify(0.4)  == CorrelationType.POSITIVE
    assert engine.classify(0.1)  == CorrelationType.NEUTRAL
    assert engine.classify(-0.3) == CorrelationType.NEGATIVE
    assert engine.classify(0.25) == CorrelationType.NEUTRAL   # boundary: not > 0.25
    assert engine.classify(-0.25) == CorrelationType.NEUTRAL  # boundary: not < -0.25
    assert engine.classify(0.26) == CorrelationType.POSITIVE
    assert engine.classify(-0.26) == CorrelationType.NEGATIVE


def test_unknown_pair_returns_zero(engine):
    """Pairs not in the matrix default to 0.0 (no correlation assumed)."""
    r = engine.get_correlation("Ghost Player", "player_points", "Other Player", "player_rebounds")
    assert r == 0.0


def test_multi_leg_single_leg_returns_prob(engine):
    """Single leg → combined prob equals that leg's prob unchanged."""
    legs = [(0.63, "LeBron James", "player_points")]
    result = engine.adjust_multi_leg_prob(legs)
    assert result == pytest.approx(0.63, abs=1e-9)


def test_multi_leg_two_legs_neutral_approx_product(engine):
    """Two neutral legs (r=0) → result ≈ p_a * p_b."""
    # With empty matrix, get_correlation returns 0.0 for any pair
    legs = [(0.60, "PlayerA", "player_points"), (0.55, "PlayerB", "player_rebounds")]
    result = engine.adjust_multi_leg_prob(legs)
    naive = 0.60 * 0.55
    # correction = 0 * sqrt(...) = 0 → result should equal naive product
    assert result == pytest.approx(naive, abs=1e-6)
