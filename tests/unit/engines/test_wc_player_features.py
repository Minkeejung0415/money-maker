"""Tests for alpha.engines.sports.wc_player_features — PlayerFeatureStore."""
from __future__ import annotations

import pytest

from alpha.engines.sports.wc_player_features import (
    POSITION_FEATURES,
    PlayerFeatureStore,
    RawPlayerStats,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cb(aerial=0.60, intercepts=3.0, errors=0.05, matches=20) -> RawPlayerStats:
    return RawPlayerStats(
        position="CB", matches=matches,
        aerial_duel_win_rate=aerial,
        interceptions_p90=intercepts,
        errors_to_shot_p90=errors,
    )


def _dm(recoveries=6.0, intercepts=3.5, press=0.65, fouls=0.4, matches=20) -> RawPlayerStats:
    return RawPlayerStats(
        position="DM", matches=matches,
        ball_recoveries_p90=recoveries,
        interceptions_p90=intercepts,
        press_resistance=press,
        foul_card_rate=fouls,
    )


def _cm(pva=0.15, prog_pass=6.0, prog_carry=2.5, chances=1.0, matches=20) -> RawPlayerStats:
    return RawPlayerStats(
        position="CM", matches=matches,
        possession_value_added=pva,
        progressive_passes_p90=prog_pass,
        progressive_carries_p90=prog_carry,
        chances_created_p90=chances,
    )


def _winger(np_xg=0.18, xa=0.12, kp=1.8, box=2.5, cuts=0.6, matches=20) -> RawPlayerStats:
    return RawPlayerStats(
        position="W", matches=matches,
        np_xg_p90=np_xg,
        xa_p90=xa,
        key_passes_p90=kp,
        box_entries_p90=box,
        cutbacks_p90=cuts,
    )


def _striker(np_xg=0.35, shots=2.8, delta=0.0, matches=20) -> RawPlayerStats:
    return RawPlayerStats(
        position="ST", matches=matches,
        np_xg_p90=np_xg,
        shot_volume_p90=shots,
        finishing_delta=delta,
    )


# ---------------------------------------------------------------------------
# PLAYER-01 through PLAYER-05: Position-specific feature sets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("position,expected_keys", [
    ("CB", ["aerial_duel_win_rate", "interceptions_p90", "errors_to_shot_p90"]),
    ("DM", ["ball_recoveries_p90", "interceptions_p90", "press_resistance", "foul_card_rate"]),
    ("CM", ["possession_value_added", "progressive_passes_p90", "progressive_carries_p90", "chances_created_p90"]),
    ("W",  ["np_xg_p90", "xa_p90", "key_passes_p90", "box_entries_p90", "cutbacks_p90"]),
    ("ST", ["np_xg_p90", "shot_volume_p90", "finishing_delta"]),
])
def test_position_returns_expected_keys(position, expected_keys):
    """Each position must return exactly the documented feature keys."""
    stats = RawPlayerStats(position=position, matches=10)
    store = PlayerFeatureStore()
    result = store.compute(stats)
    for key in expected_keys:
        assert key in result, f"Missing key '{key}' for position '{position}'"


def test_cb_feature_values():
    """CB features carry through from club_stats without distortion."""
    store = PlayerFeatureStore()
    stats = _cb(aerial=0.65, intercepts=3.2, errors=0.03)
    result = store.compute(stats)
    assert result["aerial_duel_win_rate"] == pytest.approx(0.65)
    assert result["interceptions_p90"] == pytest.approx(3.2)
    assert result["errors_to_shot_p90"] == pytest.approx(0.03)


def test_dm_feature_values():
    """DM feature values pass through from club_stats."""
    store = PlayerFeatureStore()
    stats = _dm(recoveries=7.0, press=0.70)
    result = store.compute(stats)
    assert result["ball_recoveries_p90"] == pytest.approx(7.0)
    assert result["press_resistance"] == pytest.approx(0.70)


def test_winger_feature_values():
    """Winger feature values pass through from club_stats."""
    store = PlayerFeatureStore()
    stats = _winger(np_xg=0.20, xa=0.15, box=3.0)
    result = store.compute(stats)
    assert result["np_xg_p90"] == pytest.approx(0.20)
    assert result["xa_p90"] == pytest.approx(0.15)
    assert result["box_entries_p90"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# PLAYER-06: Hierarchical shrinkage — 0 NT caps
# ---------------------------------------------------------------------------

def test_zero_nt_caps_equals_club_stats():
    """PLAYER-06: 0 NT caps → feature vector identical to club stats."""
    store = PlayerFeatureStore()
    club = _cb(aerial=0.65, intercepts=3.0, errors=0.04, matches=25)
    result_zero_nt = store.compute(club, nat_stats=None, nat_matches=0)
    result_with_nat = store.compute(club, nat_stats=_cb(), nat_matches=0)

    assert result_zero_nt["aerial_duel_win_rate"] == pytest.approx(club.aerial_duel_win_rate)
    assert result_with_nat["aerial_duel_win_rate"] == pytest.approx(club.aerial_duel_win_rate)


def test_zero_nt_caps_no_nat_influence():
    """With nat_matches=0, even different nat_stats must not affect result."""
    store = PlayerFeatureStore()
    club = _dm(recoveries=6.0, intercepts=3.5)
    # NT stats wildly different
    nat = RawPlayerStats(position="DM", matches=30,
                         ball_recoveries_p90=10.0, interceptions_p90=10.0)
    result = store.compute(club, nat_stats=nat, nat_matches=0)
    assert result["ball_recoveries_p90"] == pytest.approx(6.0)
    assert result["interceptions_p90"] == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# PLAYER-06: Hierarchical shrinkage — 50 NT caps
# ---------------------------------------------------------------------------

def test_50_nt_caps_closer_to_nat_stats():
    """PLAYER-06: 50 NT caps → result closer to NT observed stats than to club prior."""
    store = PlayerFeatureStore()
    club = _winger(np_xg=0.10, xa=0.08)   # weaker on NT stage
    nat = RawPlayerStats(
        position="W", matches=50,
        np_xg_p90=0.40, xa_p90=0.35,       # much stronger NT performer
        key_passes_p90=2.5, box_entries_p90=4.0, cutbacks_p90=1.0,
    )
    result = store.compute(club, nat_stats=nat, nat_matches=50)

    blended_xg = result["np_xg_p90"]
    # Should be closer to NT (0.40) than to club (0.10)
    assert abs(blended_xg - 0.40) < abs(blended_xg - 0.10), (
        f"Expected blend {blended_xg:.3f} closer to NT 0.40 than club 0.10"
    )


def test_increasing_nt_caps_shifts_toward_nat():
    """Blend should shift toward NT stats as NT caps increase."""
    store = PlayerFeatureStore()
    club = _cb(aerial=0.50, intercepts=2.0, errors=0.10)
    nat = RawPlayerStats(position="CB", matches=50,
                         aerial_duel_win_rate=0.80,
                         interceptions_p90=5.0,
                         errors_to_shot_p90=0.01)

    r_10 = store.compute(club, nat_stats=nat, nat_matches=10)["aerial_duel_win_rate"]
    r_50 = store.compute(club, nat_stats=nat, nat_matches=50)["aerial_duel_win_rate"]

    # More NT caps → blend closer to NT aerial (0.80)
    assert r_50 > r_10


# ---------------------------------------------------------------------------
# PLAYER-05: Finishing delta shrinkage (striker)
# ---------------------------------------------------------------------------

def test_finishing_delta_shrunk_at_5_games():
    """
    PLAYER-05/06: +0.3 finishing delta over 5 club games shrunk toward 0.
    Shrunk value should be closer to 0.05 than to raw 0.3.
    """
    store = PlayerFeatureStore(finishing_shrinkage_prior=10)
    club = _striker(delta=0.3, matches=5)
    result = store.compute(club)  # 0 NT caps
    shrunk = result["finishing_delta"]

    # shrunk = 0.3 * 5/(5+10) = 0.1; check closer to 0.05 than to 0.3
    assert abs(shrunk - 0.05) < abs(shrunk - 0.3), (
        f"Shrunk delta {shrunk:.3f} should be closer to 0.05 than to raw 0.3"
    )


def test_finishing_delta_zero_at_zero_matches():
    """Finishing delta with 0 matches → shrunk to 0."""
    store = PlayerFeatureStore()
    club = RawPlayerStats(position="ST", matches=0, finishing_delta=0.5)
    result = store.compute(club)
    assert result["finishing_delta"] == pytest.approx(0.0)


def test_finishing_delta_approaches_raw_at_high_match_count():
    """With many matches, finishing delta approaches its raw value."""
    store = PlayerFeatureStore(finishing_shrinkage_prior=10)
    club = _striker(delta=0.2, matches=100)
    result = store.compute(club)
    # 100/(100+10) ≈ 0.909 → shrunk = 0.182, close to 0.2
    assert result["finishing_delta"] > 0.15


def test_finishing_delta_negative_preserved_direction():
    """Negative finishing delta (under-performance) stays negative after shrinkage."""
    store = PlayerFeatureStore()
    club = _striker(delta=-0.2, matches=20)
    result = store.compute(club)
    assert result["finishing_delta"] < 0.0


# ---------------------------------------------------------------------------
# PLAYER-07: Configurable weights
# ---------------------------------------------------------------------------

def test_custom_max_nat_weight():
    """max_nat_weight=0.50 should reduce NT influence vs default 0.70."""
    club = _cm(pva=0.10, prog_pass=4.0)
    nat = RawPlayerStats(position="CM", matches=50,
                         possession_value_added=0.50,
                         progressive_passes_p90=10.0,
                         chances_created_p90=2.0,
                         progressive_carries_p90=4.0)

    store_high = PlayerFeatureStore(max_nat_weight=0.70)
    store_low = PlayerFeatureStore(max_nat_weight=0.30)

    high_blend = store_high.compute(club, nat_stats=nat, nat_matches=50)["progressive_passes_p90"]
    low_blend = store_low.compute(club, nat_stats=nat, nat_matches=50)["progressive_passes_p90"]

    # Higher max_nat_weight → blend closer to NT (10.0) than lower weight
    assert high_blend > low_blend


def test_supported_positions():
    """All 5 WC player positions are supported."""
    store = PlayerFeatureStore()
    assert set(store.supported_positions()) == {"CB", "DM", "CM", "W", "ST"}


def test_position_features_registry():
    """POSITION_FEATURES registry has all 5 positions."""
    assert set(POSITION_FEATURES.keys()) == {"CB", "DM", "CM", "W", "ST"}
