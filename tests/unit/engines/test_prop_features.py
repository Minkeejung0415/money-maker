"""Stage 4 tests: shared pregame feature builder + train/inference parity."""
from __future__ import annotations

import math
import pickle
from datetime import date, timedelta

import pytest

from alpha.engines.sports.prop_features import (
    ALL_FEATURES,
    FEATURE_SCHEMA_VERSION,
    REQUIRED_FEATURES,
    build_pregame_features,
    features_to_vector,
    normalize_history_row,
)

GAME_DATE = date(2025, 1, 20)


def _history(n: int = 10, pts: float = 25.0, minutes: float = 32.0,
             gap_days: int = 2, start: date = GAME_DATE) -> list[dict]:
    """n prior games, newest-first, spaced gap_days apart before `start`."""
    return [
        {"stat": pts, "minutes": minutes,
         "game_date": start - timedelta(days=gap_days * (i + 1))}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Train/inference parity
# ---------------------------------------------------------------------------

def test_train_and_live_rows_normalize_identically():
    """nba_api-style rows and historical-CSV rows must build identical features."""
    live_rows = [
        {"PTS": 25.0 + i, "MIN_float": 30.0 + i,
         "GAME_DATE": f"2025-01-{18 - i:02d}T00:00:00"}
        for i in range(8)
    ]
    csv_rows = [
        {"pts": 25.0 + i, "min_float": 30.0 + i, "game_date": f"2025-01-{18 - i:02d}"}
        for i in range(8)
    ]
    live_hist = [normalize_history_row(r, "PTS") for r in live_rows]
    csv_hist = [normalize_history_row(r, "pts") for r in csv_rows]
    assert live_hist == csv_hist

    live = build_pregame_features(live_hist, "player_points", GAME_DATE, is_home=True)
    train = build_pregame_features(csv_hist, "player_points", GAME_DATE, is_home=True)
    assert live is not None and train is not None
    assert live.features == train.features
    assert live.feature_schema_version == FEATURE_SCHEMA_VERSION


def test_history_order_does_not_matter():
    """Builder sorts by game_date itself — input ordering can't change output."""
    hist = _history(10)
    shuffled = list(reversed(hist))
    a = build_pregame_features(hist, "player_points", GAME_DATE, is_home=False)
    b = build_pregame_features(shuffled, "player_points", GAME_DATE, is_home=False)
    assert a.features == b.features


# ---------------------------------------------------------------------------
# is_home / rest_days
# ---------------------------------------------------------------------------

def test_is_home_is_explicit():
    hist = _history()
    home = build_pregame_features(hist, "player_points", GAME_DATE, is_home=True)
    away = build_pregame_features(hist, "player_points", GAME_DATE, is_home=False)
    assert home.features["is_home"] == 1.0
    assert away.features["is_home"] == 0.0


def test_rest_days_back_to_back():
    """Last game yesterday → rest_days=0, back_to_back=1."""
    hist = _history(gap_days=1)
    out = build_pregame_features(hist, "player_points", GAME_DATE, is_home=True)
    assert out.features["rest_days"] == 0.0
    assert out.features["back_to_back"] == 1.0


def test_rest_days_three_plus_days():
    """Last game 4 days ago → rest_days=3, no back-to-back."""
    hist = _history(gap_days=4)
    out = build_pregame_features(hist, "player_points", GAME_DATE, is_home=True)
    assert out.features["rest_days"] == 3.0
    assert out.features["back_to_back"] == 0.0


def test_games_last_4_days_counts_schedule_density():
    hist = _history(n=10, gap_days=1)  # games on each of the last 10 days
    out = build_pregame_features(hist, "player_points", GAME_DATE, is_home=True)
    assert out.features["games_last_4_days"] == 4.0


# ---------------------------------------------------------------------------
# No leakage / no target-minutes selection
# ---------------------------------------------------------------------------

def test_future_rows_are_dropped():
    """Rows on/after the target game date must never contribute."""
    hist = _history(10)
    future = [{"stat": 99.0, "minutes": 40.0, "game_date": GAME_DATE}]
    clean = build_pregame_features(hist, "player_points", GAME_DATE, is_home=True)
    leaky = build_pregame_features(hist + future, "player_points", GAME_DATE, is_home=True)
    assert clean.features == leaky.features


def test_low_minute_history_games_excluded_from_rates_only():
    """History games under 20 min don't feed rolling rates but DO count for rest."""
    hist = _history(10, minutes=30.0, gap_days=3)
    # Add a 5-minute stint yesterday: rest becomes 0, rates unchanged-ish.
    stint = {"stat": 2.0, "minutes": 5.0, "game_date": GAME_DATE - timedelta(days=1)}
    out = build_pregame_features(hist + [stint], "player_points", GAME_DATE, is_home=True)
    base = build_pregame_features(hist, "player_points", GAME_DATE, is_home=True)
    assert out.features["rest_days"] == 0.0
    assert out.features["roll5_stat_per_min"] == base.features["roll5_stat_per_min"]


def test_insufficient_history_fails_closed():
    assert build_pregame_features(_history(3), "player_points", GAME_DATE, True) is None
    assert build_pregame_features(_history(10), "player_blocks", GAME_DATE, True) is None


# ---------------------------------------------------------------------------
# Missingness handling
# ---------------------------------------------------------------------------

def test_missing_opponent_context_is_nan_and_tracked():
    out = build_pregame_features(_history(), "player_points", GAME_DATE, is_home=True)
    assert math.isnan(out.features["opp_def_rtg"])
    assert math.isnan(out.features["opp_pace"])
    assert set(out.missing) == {"opp_def_rtg", "opp_pace"}

    with_ctx = build_pregame_features(
        _history(), "player_points", GAME_DATE, is_home=True,
        opp_def_rtg=110.0, opp_pace=101.5,
    )
    assert with_ctx.features["opp_def_rtg"] == 110.0
    assert with_ctx.missing == []


def test_features_to_vector_fails_closed_on_missing_required():
    out = build_pregame_features(_history(), "player_points", GAME_DATE, is_home=True)
    feats = dict(out.features)
    del feats["projected_minutes"]
    with pytest.raises(KeyError):
        features_to_vector(feats, ALL_FEATURES)


def test_required_features_all_present():
    out = build_pregame_features(_history(), "player_points", GAME_DATE, is_home=True)
    for name in REQUIRED_FEATURES:
        assert name in out.features
        assert not math.isnan(out.features[name])


def test_player_threes_market_supported():
    rows = [{"FG3M": 3.0, "MIN_float": 30.0, "GAME_DATE": f"2025-01-{15 - i:02d}"}
            for i in range(8)]
    hist = [normalize_history_row(r, "FG3M") for r in rows]
    out = build_pregame_features(hist, "player_threes", GAME_DATE, is_home=True)
    assert out is not None
    assert out.features["roll5_stat_per_min"] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Model schema safety
# ---------------------------------------------------------------------------

def test_legacy_pickle_rejected(tmp_path):
    from alpha.engines.sports.xgb_prop_model import PropSchemaError, XGBoostPropModel
    legacy = tmp_path / "old.pkl"
    legacy.write_bytes(pickle.dumps({"target": "pts", "model": None}))
    with pytest.raises(PropSchemaError):
        XGBoostPropModel.load(legacy)


def test_schema_version_mismatch_rejected(tmp_path):
    from alpha.engines.sports.xgb_prop_model import PropSchemaError, XGBoostPropModel
    stale = tmp_path / "stale.pkl"
    stale.write_bytes(pickle.dumps({
        "target": "pts", "model": None,
        "feature_names": ALL_FEATURES, "feature_schema_version": "0.9.0",
    }))
    with pytest.raises(PropSchemaError):
        XGBoostPropModel.load(stale)
