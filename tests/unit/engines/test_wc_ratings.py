"""Tests for alpha/engines/sports/wc_ratings.py."""
from __future__ import annotations

import pytest

from alpha.engines.sports.wc_ratings import WCTeamRatings

# ---------------------------------------------------------------------------
# Fixture: shared ratings instance (construction is deterministic)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ratings() -> WCTeamRatings:
    return WCTeamRatings()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_features_returns_required_keys(ratings: WCTeamRatings) -> None:
    """Result must contain all 11 documented keys."""
    feats = ratings.get_features("Argentina", "France")
    required = (
        "elo",
        "elo_away",
        "xg_attack",
        "xg_defense",
        "xg_attack_away",
        "xg_defense_away",
        "fifa_sum",
        "host_flag",
        "confederation_interaction",
        "composite_home_elo",
        "composite_away_elo",
    )
    for key in required:
        assert key in feats, f"Missing key: {key}"


def test_host_flag_us(ratings: WCTeamRatings) -> None:
    """US is a 2026 WC host — host_flag must be 1."""
    assert ratings.get_features("United States", "Argentina")["host_flag"] == 1


def test_host_flag_mexico(ratings: WCTeamRatings) -> None:
    """Mexico is a 2026 WC host — host_flag must be 1."""
    assert ratings.get_features("Mexico", "Brazil")["host_flag"] == 1


def test_host_flag_canada(ratings: WCTeamRatings) -> None:
    """Canada is a 2026 WC host — host_flag must be 1."""
    assert ratings.get_features("Canada", "France")["host_flag"] == 1


def test_host_flag_non_host(ratings: WCTeamRatings) -> None:
    """Argentina is NOT a 2026 host — host_flag must be 0."""
    assert ratings.get_features("Argentina", "France")["host_flag"] == 0


def test_confederation_interaction_cross(ratings: WCTeamRatings) -> None:
    """Brazil (CONMEBOL) vs France (UEFA) — confederation_interaction must be 1."""
    assert ratings.get_features("Brazil", "France")["confederation_interaction"] == 1


def test_confederation_interaction_same(ratings: WCTeamRatings) -> None:
    """Spain vs Germany (both UEFA) — confederation_interaction must be 0."""
    assert ratings.get_features("Spain", "Germany")["confederation_interaction"] == 0


def test_composite_elo_bounded(ratings: WCTeamRatings) -> None:
    """
    Composite Elo adjustments should not blow up to implausible values.
    Max total adjustment: xg(40) + fifa(20) + host(50) + conf(10) = 120.
    Allow small float buffer to 130.
    """
    feats = ratings.get_features("Argentina", "France")
    base_elo = feats["elo"]
    delta = abs(feats["composite_home_elo"] - base_elo)
    assert delta <= 130, f"Composite Elo delta {delta:.1f} exceeds expected bound 130"


def test_sequential_elo_updates(ratings: WCTeamRatings) -> None:
    """
    After replaying 2018 + 2022 WC history, France (2018 champion, 2022 finalist)
    should have a substantially elevated Elo vs 1500 fallback.
    """
    feats = ratings.get_features("France", "Germany")
    # France's starting Elo in wc_priors.json is ~2084; after winning 2018 it
    # should be at least 1800 (this is a conservative floor).
    assert feats["elo"] >= 1800, (
        f"France Elo {feats['elo']} is lower than expected after 2018+2022 replay"
    )


def test_xg_ewma_seeded_from_cache(ratings: WCTeamRatings) -> None:
    """
    Teams in wc_stats.pkl (e.g. Brazil) should have non-default xg_attack values.
    The cache avg_xG for Brazil is 2.59, so after EWMA updates it should remain > 1.0.
    """
    feats = ratings.get_features("Brazil", "Argentina")
    # Brazil has xG data in cache (avg_xG=2.59) — attack should remain elevated
    assert feats["xg_attack"] > 1.0, (
        f"Brazil xg_attack {feats['xg_attack']:.3f} unexpectedly low — cache seed may not have loaded"
    )


def test_elo_values_are_ints(ratings: WCTeamRatings) -> None:
    """elo and elo_away should be int (not float) as documented."""
    feats = ratings.get_features("Spain", "Brazil")
    assert isinstance(feats["elo"], int)
    assert isinstance(feats["elo_away"], int)


def test_away_composite_elo_equals_sequential(ratings: WCTeamRatings) -> None:
    """composite_away_elo must equal sequential elo_away (adjustments are home-perspective only)."""
    feats = ratings.get_features("Argentina", "France")
    assert feats["composite_away_elo"] == float(feats["elo_away"])
