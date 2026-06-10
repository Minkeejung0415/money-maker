"""Tests: MLB feature schema, ABS-era handling, hierarchical shrinkage."""
from __future__ import annotations

import pandas as pd
import pytest

from alpha.engines.sports.mlb_features import (
    FEATURE_GROUPS,
    REQUIRED_FOR_BET,
    TeamSideFeatures,
    abs_era,
    add_abs_era_flag,
    assert_zone_features_era_safe,
    normalize_zone_features_by_era,
    pitcher_xwoba_allowed,
    shrink,
    shrink_handedness_split,
    times_through_order_decay,
)


# ---------------------------------------------------------------------------
# ABS era (2026 Statcast zone schema change)
# ---------------------------------------------------------------------------

def test_abs_era_flag():
    assert abs_era(2024) == 0
    assert abs_era(2025) == 0
    assert abs_era(2026) == 1
    assert abs_era(2027) == 1


def test_add_abs_era_flag_dataframe():
    df = pd.DataFrame({"season": [2024, 2026, 2025, 2027]})
    out = add_abs_era_flag(df)
    assert out["abs_era"].tolist() == [0, 1, 0, 1]


def test_zone_normalization_within_era():
    """Each era is z-scored independently — cross-era shift is removed."""
    df = pd.DataFrame({
        "season": [2025] * 4 + [2026] * 4,
        # ABS-era values are systematically offset by +0.5 (schema change).
        "plate_z": [2.0, 2.2, 2.4, 2.6, 2.5, 2.7, 2.9, 3.1],
        "plate_x": [0.0, 0.1, -0.1, 0.2, 0.5, 0.6, 0.4, 0.7],
        "sz_top": [3.4, 3.5, 3.3, 3.6, 3.9, 4.0, 3.8, 4.1],
        "sz_bot": [1.5, 1.6, 1.4, 1.7, 2.0, 2.1, 1.9, 2.2],
    })
    out = normalize_zone_features_by_era(df)
    pre = out[out["abs_era"] == 0]
    post = out[out["abs_era"] == 1]
    for col in ("plate_z_norm", "plate_x_norm", "sz_top_norm", "sz_bot_norm"):
        # Both eras normalized to ~zero mean: the offset no longer leaks.
        assert abs(pre[col].mean()) < 1e-9
        assert abs(post[col].mean()) < 1e-9
    # Raw columns untouched.
    assert out["plate_z"].tolist() == df["plate_z"].tolist()


def test_mixed_era_raw_zone_features_fail_closed():
    df = pd.DataFrame({"season": [2025, 2026], "plate_z": [2.0, 2.5]})
    with pytest.raises(ValueError, match="ABS"):
        assert_zone_features_era_safe(df)
    # After normalization the same frame passes.
    assert_zone_features_era_safe(normalize_zone_features_by_era(df))


def test_single_era_raw_zone_features_allowed():
    df = pd.DataFrame({"season": [2024, 2025], "plate_z": [2.0, 2.1]})
    assert_zone_features_era_safe(df)  # no raise


# ---------------------------------------------------------------------------
# Hierarchical shrinkage
# ---------------------------------------------------------------------------

def test_shrink_small_sample_pulls_to_prior():
    # 10 PA of .500 wOBA shrinks nearly all the way to the .315 prior.
    shrunk = shrink(observed=0.500, n=10, prior=0.315, k=220)
    assert 0.315 < shrunk < 0.34


def test_shrink_large_sample_trusts_data():
    shrunk = shrink(observed=0.380, n=600, prior=0.315, k=220)
    assert abs(shrunk - 0.380) < abs(shrunk - 0.315)
    assert shrunk == pytest.approx((600 * 0.380 + 220 * 0.315) / 820)


def test_shrink_zero_sample_returns_prior():
    assert shrink(0.999, 0, 0.315, 220) == 0.315


def test_handedness_split_two_level_shrinkage():
    """A tiny platoon split shrinks toward the (shrunk) overall wOBA."""
    out = shrink_handedness_split(
        split_woba=0.450, split_pa=20,
        overall_woba=0.340, overall_pa=500,
    )
    overall_shrunk = shrink(0.340, 500, 0.315, 220)
    assert overall_shrunk < out < 0.40  # nudged up, nowhere near .450
    # With a big split sample, the split dominates.
    big = shrink_handedness_split(0.450, 2000, 0.340, 500)
    assert big > 0.42


# ---------------------------------------------------------------------------
# Statcast aggregation helpers
# ---------------------------------------------------------------------------

def test_pitcher_xwoba_allowed_fails_closed_below_min_bbe():
    df = pd.DataFrame({"estimated_woba_using_speedangle": [0.3] * 10})
    assert pitcher_xwoba_allowed(df, min_bbe=30) is None
    df_big = pd.DataFrame({"estimated_woba_using_speedangle": [0.3] * 40})
    assert pitcher_xwoba_allowed(df_big, min_bbe=30) == pytest.approx(0.3)


def test_times_through_order_decay():
    df = pd.DataFrame({
        "n_thruorder_pitcher": [1] * 10 + [2] * 10 + [3] * 10,
        "estimated_woba_using_speedangle": [0.30] * 10 + [0.32] * 10 + [0.36] * 10,
    })
    decay = times_through_order_decay(df)
    assert decay == pytest.approx(0.03, abs=1e-9)  # (0.36-0.30)/2
    assert times_through_order_decay(pd.DataFrame({"x": [1]})) is None


# ---------------------------------------------------------------------------
# Schema / missingness
# ---------------------------------------------------------------------------

def test_feature_groups_are_ordered_for_ablation():
    assert list(FEATURE_GROUPS) == [
        "starter", "lineup", "bullpen", "park_weather", "market",
        "statcast_quality",
    ]


def test_required_for_bet_missing_tracking():
    side = TeamSideFeatures(team="NYY")  # everything unset
    missing = side.missing(REQUIRED_FOR_BET)
    assert "pitcher_confirmed" in missing
    assert "starter_xera" in missing

    side.pitcher_confirmed = True
    side.starter_xera = 3.4
    side.lineup_woba_vs_rhp = 0.33
    side.lineup_woba_vs_lhp = 0.31
    assert side.missing(REQUIRED_FOR_BET) == []


def test_ablation_configs_are_cumulative_in_order():
    from alpha.engines.sports.mlb_features import mlb_feature_group_ablations
    configs = mlb_feature_group_ablations()
    names = list(configs)
    assert names[0] == "+starter"
    assert configs["+starter"] == ["starter"]
    assert configs["+lineup"] == ["starter", "lineup"]
    assert configs["+statcast_quality"] == [
        "starter", "lineup", "bullpen", "park_weather", "market",
        "statcast_quality",
    ]
