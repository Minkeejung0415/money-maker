"""Tests for the MLB team offense baseline ingestion (MVP, fail-closed)."""
from __future__ import annotations

import pytest

from alpha.data.ingestion.mlb_team_offense import (
    get_team_offense,
    to_team_offense_features,
)

GAME_DATE = "2026-06-11"
TEAM = "New York Yankees"


class FakeSource:
    def __init__(self, season_rec=None, results=None):
        self._season_rec = season_rec
        self._results = results
        self.season_calls = 0

    def season_batting_record(self, team, season):
        self.season_calls += 1
        return self._season_rec

    def team_game_results(self, team, season):
        return self._results


def _season_rec(**overrides):
    rec = {
        "games": 64,
        "runs_per_game": 5.1,
        "woba": 0.335,
        "obp": 0.330,
        "slg": 0.445,
        "k_rate": 0.205,
        "bb_rate": 0.095,
    }
    rec.update(overrides)
    return rec


def _results(dates_runs):
    return [{"date": d, "runs": r} for d, r in dates_runs]


def test_complete_team_record(tmp_path):
    results = _results([(f"2026-05-{day:02d}", 4) for day in range(1, 16)])
    rec = get_team_offense(
        TEAM, GAME_DATE, source=FakeSource(_season_rec(), results),
        features_cache_dir=tmp_path,
    )
    assert rec["team"] == TEAM
    assert rec["runs_per_game_season"] == 5.1
    assert rec["woba_season"] == 0.335
    assert rec["k_rate_batting"] == 0.205
    assert rec["runs_per_game_last10"] == pytest.approx(4.0)
    assert rec["missing_features"] == []


def test_missing_record_fails_closed(tmp_path):
    rec = get_team_offense(
        "Expansion Team", GAME_DATE, source=FakeSource(None, None),
        features_cache_dir=tmp_path,
    )
    for field in ("runs_per_game_season", "runs_per_game_last10", "woba_season",
                  "obp_season", "slg_season", "k_rate_batting", "bb_rate_batting"):
        assert rec[field] is None
        assert field in rec["missing_features"]


def test_rolling_last10_uses_exactly_last_ten(tmp_path):
    # 12 completed games: first two score 10, last ten score 3.
    dates_runs = [("2026-05-01", 10), ("2026-05-02", 10)] + [
        (f"2026-05-{day:02d}", 3) for day in range(3, 13)
    ]
    rec = get_team_offense(
        TEAM, GAME_DATE, source=FakeSource(_season_rec(), _results(dates_runs)),
        features_cache_dir=tmp_path,
    )
    assert rec["runs_per_game_last10"] == pytest.approx(3.0)


def test_no_future_or_same_day_games_included(tmp_path):
    dates_runs = [
        ("2026-06-01", 2),
        ("2026-06-11", 99),  # same day — must be excluded
        ("2026-06-15", 99),  # future — must be excluded
    ]
    rec = get_team_offense(
        TEAM, GAME_DATE, source=FakeSource(_season_rec(), _results(dates_runs)),
        features_cache_dir=tmp_path,
    )
    assert rec["runs_per_game_last10"] == pytest.approx(2.0)


def test_no_invented_values_partial_record(tmp_path):
    rec = get_team_offense(
        TEAM, GAME_DATE,
        source=FakeSource(_season_rec(woba=None, k_rate=None), None),
        features_cache_dir=tmp_path,
    )
    assert rec["woba_season"] is None
    assert rec["k_rate_batting"] is None
    assert rec["runs_per_game_last10"] is None
    for f in ("woba_season", "k_rate_batting", "runs_per_game_last10"):
        assert f in rec["missing_features"]
    # Present fields are passed through untouched.
    assert rec["obp_season"] == 0.330


def test_daily_cache_prevents_refetch(tmp_path):
    src = FakeSource(_season_rec(), None)
    get_team_offense(TEAM, GAME_DATE, source=src, features_cache_dir=tmp_path)
    rec2 = get_team_offense(TEAM, GAME_DATE, source=src, features_cache_dir=tmp_path)
    assert src.season_calls == 1
    assert rec2["runs_per_game_season"] == 5.1


def test_conversion_to_model_features(tmp_path):
    rec = get_team_offense(
        TEAM, GAME_DATE, source=FakeSource(_season_rec(), None),
        features_cache_dir=tmp_path,
    )
    feats = to_team_offense_features(rec)
    assert feats.team == TEAM
    assert feats.runs_per_game_season == 5.1
    assert feats.runs_per_game_last10 is None
    assert "runs_per_game_last10" in feats.missing_features
