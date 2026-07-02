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


def _dated(flags: list[float], start_day: int = 1) -> dict[str, float]:
    """Build a {game_date: flag} vector from a list of binary flags."""
    return {f"2026-01-{start_day + i:02d}": v for i, v in enumerate(flags)}


def test_perfect_positive_correlation(engine):
    """Identical binary vectors on the same game dates → r ≈ 1.0."""
    flags = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0,
             1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    game_vectors = {
        "PlayerA": {"PTS": _dated(flags)},
        "PlayerB": {"PTS": _dated(flags)},
    }
    r = engine._compute_r(game_vectors, "PlayerA", "player_points", "PlayerB", "player_points")
    assert r == pytest.approx(1.0, abs=1e-6)


def test_perfect_negative_correlation(engine):
    """Perfectly opposite binary vectors on the same dates → r ≈ -1.0."""
    flags_a = [1.0, 0.0] * 10
    flags_b = [0.0, 1.0] * 10
    game_vectors = {
        "PlayerA": {"PTS": _dated(flags_a)},
        "PlayerB": {"PTS": _dated(flags_b)},
    }
    r = engine._compute_r(game_vectors, "PlayerA", "player_points", "PlayerB", "player_points")
    assert r == pytest.approx(-1.0, abs=1e-6)


def test_disjoint_schedules_return_zero(engine):
    """Regression: players who share no game dates must get r = 0.0.
    The v1 engine paired vectors by array index, so two players on
    different teams with unrelated schedules could show strong fake
    correlation."""
    flags = [1.0, 0.0] * 10
    game_vectors = {
        "PlayerA": {"PTS": _dated(flags, start_day=1)},
        # Same flag pattern but on entirely different dates (Feb, not Jan)
        "PlayerB": {"PTS": {f"2026-02-{i + 1:02d}": v for i, v in enumerate(flags)}},
    }
    r = engine._compute_r(game_vectors, "PlayerA", "player_points", "PlayerB", "player_points")
    assert r == 0.0


def test_insufficient_shared_games_return_zero(engine):
    """Fewer than the minimum shared dates → r = 0.0 (assume independence)."""
    flags = [1.0, 0.0] * 10
    game_vectors = {
        "PlayerA": {"PTS": _dated(flags, start_day=1)},
        # Only 5 overlapping dates (days 16-20)
        "PlayerB": {"PTS": _dated(flags, start_day=16)},
    }
    r = engine._compute_r(game_vectors, "PlayerA", "player_points", "PlayerB", "player_points")
    assert r == 0.0


def test_shared_dates_align_even_with_offset_schedules(engine):
    """Correlation is computed on the intersection of dates, not on
    index-aligned prefixes: identical flags on the shared dates → r ≈ 1.0
    even when one player has extra earlier games."""
    shared = _dated([1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 1.0],
                    start_day=10)
    extra_early = {f"2026-01-{i:02d}": 0.0 for i in range(1, 10)}
    game_vectors = {
        "PlayerA": {"PTS": {**extra_early, **shared}},
        "PlayerB": {"PTS": dict(shared)},
    }
    r = engine._compute_r(game_vectors, "PlayerA", "player_points", "PlayerB", "player_points")
    assert r == pytest.approx(1.0, abs=1e-6)


def test_binarize_trailing_no_future_leakage():
    """Regression: v1 binarized every game against the mean of the 20 most
    RECENT games, so future performance changed the flags of past games.
    For a strictly increasing series, every flagged game beats the average
    of its prior games, so all flags must be 1.0 (v1 flagged early games 0)."""
    from alpha.engines.sports.correlation import CorrelationEngine

    dated = [(f"2026-01-{i:02d}", float(i)) for i in range(1, 31)]  # 1..30 rising
    flags = CorrelationEngine._binarize_trailing(dated)
    assert flags, "expected flags after the minimum-history warmup"
    assert all(v == 1.0 for v in flags.values())
    # The warmup games themselves must not be flagged at all
    assert "2026-01-01" not in flags


def test_binarize_trailing_requires_min_history():
    """Games before the minimum prior-game count emit no flag."""
    from alpha.engines.sports.correlation import CorrelationEngine

    dated = [(f"2026-01-{i:02d}", 10.0) for i in range(1, 9)]  # only 8 games
    assert CorrelationEngine._binarize_trailing(dated) == {}


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
