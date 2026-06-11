"""Tests for pregame starter feature ingestion (fail-closed, free data)."""
from __future__ import annotations

import pandas as pd
import pytest

from alpha.data.ingestion.mlb_starter_features import (
    get_starter_features,
    to_starter_features,
)
from alpha.engines.sports.mlb_features import LEAGUE_XERA

GAME_DATE = "2026-06-11"


class FakeSource:
    def __init__(self, season_rec=None, pitch_log=None):
        self._season_rec = season_rec
        self._pitch_log = pitch_log
        self.season_calls = 0
        self.statcast_calls = 0

    def season_pitching_record(self, pitcher_id, season):
        self.season_calls += 1
        return self._season_rec

    def statcast_pitch_log(self, pitcher_id, season):
        self.statcast_calls += 1
        return self._pitch_log


def _season_rec(**overrides):
    rec = {
        "throws": "R",
        "starts": 14,
        "innings": 85.0,
        "era": 3.20,
        "xera": 3.45,
        "fip": 3.30,
        "whip": 1.10,
        "k_per9": 9.8,
        "bb_per9": 2.4,
        "hr_per9": 1.0,
    }
    rec.update(overrides)
    return rec


def _pitch_log(dates_counts, xwoba=0.300, velo_by_date=None):
    """dates_counts: [(date, n_pitches)]; velo_by_date: {date: mph}."""
    rows = []
    for d, n in dates_counts:
        for _ in range(n):
            rows.append({
                "game_date": d,
                "pitch_type": "FF",
                "release_speed": (velo_by_date or {}).get(d, 95.0),
                "estimated_woba_using_speedangle": xwoba,
                "events": "field_out",
            })
    return pd.DataFrame(rows)


def test_complete_starter_record(tmp_path):
    log = _pitch_log([("2026-06-01", 90), ("2026-06-06", 95)])
    rec = get_starter_features(
        543037, "Gerrit Cole", GAME_DATE,
        source=FakeSource(_season_rec(), log), features_cache_dir=tmp_path,
    )
    assert rec["pitcher_id"] == 543037
    assert rec["era"] == 3.20
    assert rec["xera"] == 3.45
    assert rec["xwoba_allowed"] == pytest.approx(0.300)
    assert rec["days_rest"] == 5  # last start 06-06, game 06-11
    assert rec["pitch_count_last_start"] == 95
    assert rec["missing_features"] == []


def test_small_sample_shrinkage_at_model_layer(tmp_path):
    rec = get_starter_features(
        1, "Rookie", GAME_DATE,
        source=FakeSource(_season_rec(era=1.50, xera=1.50, innings=10.0, starts=2)),
        features_cache_dir=tmp_path,
    )
    sf = to_starter_features(rec)
    assert sf.xera == 1.50  # ingestion stores observed value untouched
    shrunk = sf.shrunk("xera")
    assert 1.50 < shrunk < LEAGUE_XERA  # small sample pulled toward prior


def test_missing_statcast_fields_stay_missing(tmp_path):
    # Pitch log without statcast quality columns.
    log = pd.DataFrame({"game_date": ["2026-06-06"] * 80})
    rec = get_starter_features(
        2, "No Statcast", GAME_DATE,
        source=FakeSource(_season_rec(xera=None), log), features_cache_dir=tmp_path,
    )
    assert rec["xera"] is None
    assert rec["xwoba_allowed"] is None
    assert rec["velocity_delta_last3"] is None
    assert rec["days_rest"] == 5  # derivable from game_date alone
    for f in ("xera", "xwoba_allowed", "velocity_delta_last3"):
        assert f in rec["missing_features"]


def test_missing_pitcher_id_returns_all_missing(tmp_path):
    src = FakeSource(_season_rec())
    rec = get_starter_features(
        None, None, GAME_DATE, source=src, features_cache_dir=tmp_path
    )
    assert rec["pitcher_id"] is None
    assert "pitcher_id" in rec["missing_features"]
    assert rec["era"] is None
    assert src.season_calls == 0  # never guesses a pitcher


def test_no_invented_values_when_source_empty(tmp_path):
    rec = get_starter_features(
        3, "Ghost", GAME_DATE, source=FakeSource(None, None), features_cache_dir=tmp_path
    )
    for field in ("era", "xera", "fip", "whip", "k_per9", "bb_per9", "hr_per9",
                  "xwoba_allowed", "days_rest", "velocity_delta_last3",
                  "pitch_count_last_start", "throws"):
        assert rec[field] is None
        assert field in rec["missing_features"]


def test_pregame_only_date_filtering(tmp_path):
    # Feed leaks the game-day start and a future start; both must be dropped.
    log = _pitch_log(
        [("2026-06-01", 90), ("2026-06-11", 100), ("2026-06-16", 100)],
        velo_by_date={"2026-06-01": 95.0, "2026-06-11": 80.0, "2026-06-16": 80.0},
    )
    rec = get_starter_features(
        4, "Leaky Feed", GAME_DATE, source=FakeSource(_season_rec(), log),
        features_cache_dir=tmp_path,
    )
    assert rec["days_rest"] == 10  # from 06-01, not the leaked rows
    assert rec["pitch_count_last_start"] == 90
    assert rec["velocity_delta_last3"] == pytest.approx(0.0)  # leaked 80mph excluded


def test_velocity_delta_last3(tmp_path):
    log = _pitch_log(
        [("2026-05-01", 10), ("2026-05-06", 10), ("2026-05-11", 10),
         ("2026-05-16", 10), ("2026-05-21", 10)],
        velo_by_date={
            "2026-05-01": 96.0, "2026-05-06": 96.0,  # earlier starts faster
            "2026-05-11": 94.0, "2026-05-16": 94.0, "2026-05-21": 94.0,
        },
    )
    rec = get_starter_features(
        5, "Fading Velo", GAME_DATE, source=FakeSource(_season_rec(), log),
        features_cache_dir=tmp_path,
    )
    # Season mean = 94.8; last-3 mean = 94.0 => delta -0.8
    assert rec["velocity_delta_last3"] == pytest.approx(-0.8, abs=1e-6)


def test_daily_derived_cache_prevents_source_refetch(tmp_path):
    src = FakeSource(_season_rec(), _pitch_log([("2026-06-06", 90)]))
    get_starter_features(6, "Cached", GAME_DATE, source=src, features_cache_dir=tmp_path)
    rec2 = get_starter_features(
        6, "Cached", GAME_DATE, source=src, features_cache_dir=tmp_path
    )
    assert src.season_calls == 1  # second call served from derived cache
    assert rec2["era"] == 3.20
