"""Tests for alpha/data/ingestion/soccer_stats.py (mocked soccerdata calls)."""
from __future__ import annotations

import pickle
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alpha.data.ingestion.soccer_stats import (
    SUPPORTED_LEAGUES,
    _compute_team_rolling,
    _extract_float,
    _extract_str,
    _merge_player_stats,
    get_player_per90_stats,
    get_player_per90_stats_all,
    get_team_rolling_stats,
    get_team_rolling_stats_all,
)


# ---------------------------------------------------------------------------
# SUPPORTED_LEAGUES
# ---------------------------------------------------------------------------

def test_supported_leagues_contains_epl():
    assert "epl" in SUPPORTED_LEAGUES
    assert "Premier League" in SUPPORTED_LEAGUES["epl"]


def test_supported_leagues_contains_ucl():
    assert "ucl" in SUPPORTED_LEAGUES
    assert "Champions League" in SUPPORTED_LEAGUES["ucl"]


# ---------------------------------------------------------------------------
# _extract_str / _extract_float
# ---------------------------------------------------------------------------

def test_extract_str_finds_first_match():
    row = {"player": "Erling Haaland", "name": "Other"}
    assert _extract_str(row, ["player", "name"]) == "Erling Haaland"


def test_extract_str_skips_empty():
    row = {"player": "", "name": "Saka"}
    assert _extract_str(row, ["player", "name"]) == "Saka"


def test_extract_str_returns_empty_on_miss():
    row = {"x": "y"}
    assert _extract_str(row, ["player", "name"]) == ""


def test_extract_float_valid():
    row = {"goals": "1.5", "shots": 3}
    assert _extract_float(row, ["goals"]) == pytest.approx(1.5)


def test_extract_float_falls_back_on_bad_value():
    row = {"goals": "n/a", "shots": "2.0"}
    assert _extract_float(row, ["goals", "shots"]) == pytest.approx(2.0)


def test_extract_float_returns_none_on_miss():
    row = {"other": 99}
    assert _extract_float(row, ["goals"]) is None


# ---------------------------------------------------------------------------
# _compute_team_rolling
# ---------------------------------------------------------------------------

def test_compute_team_rolling_basic():
    import pandas as pd

    rows = [
        {"home_team": "Arsenal", "away_team": "Chelsea",
         "home_goals": 2.0, "away_goals": 1.0,
         "home_xg": 1.8, "away_xg": 1.0},
        {"home_team": "Arsenal", "away_team": "Liverpool",
         "home_goals": 1.0, "away_goals": 3.0,
         "home_xg": 0.9, "away_xg": 2.5},
    ]
    df = pd.DataFrame(rows)
    result = _compute_team_rolling(df, window=5)
    assert "Arsenal" in result
    assert result["Arsenal"]["goals_for"] == pytest.approx(1.5)


def test_compute_team_rolling_respects_window():
    import pandas as pd

    rows = [{"home_team": f"TeamA", "away_team": f"TeamB",
             "home_goals": float(i), "away_goals": 0.0,
             "home_xg": float(i), "away_xg": 0.0}
            for i in range(10)]
    df = pd.DataFrame(rows)
    result = _compute_team_rolling(df, window=3)
    # Last 3 rows: 7, 8, 9
    assert result["TeamA"]["goals_for"] == pytest.approx(8.0)


def test_compute_team_rolling_returns_empty_on_bad_data():
    import pandas as pd

    df = pd.DataFrame([{"foo": "bar"}])
    result = _compute_team_rolling(df, window=5)
    assert result == {}


# ---------------------------------------------------------------------------
# get_team_rolling_stats — mocked soccerdata
# ---------------------------------------------------------------------------

def test_get_team_rolling_stats_returns_empty_on_unknown_league():
    result = get_team_rolling_stats("xyz_unknown")
    assert result == []


def test_get_team_rolling_stats_uses_cache(tmp_path, monkeypatch):
    """If a cache file exists, soccerdata should not be called."""
    import pandas as pd

    monkeypatch.setattr(
        "alpha.data.ingestion.soccer_stats._CACHE_DIR",
        tmp_path,
    )
    cache_file = tmp_path / f"team_rolling_epl_{__import__('datetime').date.today()}.pkl"
    fake_data = [{"team": "Arsenal", "league": "epl", "goals_for": 2.1,
                  "goals_against": 1.0, "xG_for": 1.9, "xG_against": 1.1,
                  "games_used": 5}]
    with open(cache_file, "wb") as f:
        pickle.dump(fake_data, f)

    with patch("alpha.data.ingestion.soccer_stats.SUPPORTED_LEAGUES",
               {"epl": "ENG-Premier League"}):
        with patch("soccerdata.FBref") as mock_sd:
            result = get_team_rolling_stats("epl")
    mock_sd.assert_not_called()
    assert result[0]["team"] == "Arsenal"


def test_get_team_rolling_stats_returns_empty_on_soccerdata_error(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    with patch("soccerdata.FBref", side_effect=Exception("network error")):
        result = get_team_rolling_stats("epl")
    assert result == []


# ---------------------------------------------------------------------------
# get_player_per90_stats
# ---------------------------------------------------------------------------

def test_get_player_per90_stats_returns_empty_on_unknown_league():
    result = get_player_per90_stats("xyz_unknown")
    assert result == []


def test_get_player_per90_stats_returns_empty_on_soccerdata_error(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    with patch("soccerdata.FBref", side_effect=RuntimeError("connection refused")):
        result = get_player_per90_stats("ucl")
    assert result == []


# ---------------------------------------------------------------------------
# get_*_all helpers
# ---------------------------------------------------------------------------

def test_get_team_rolling_stats_all_combines_leagues(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    epl_data = [{"team": "Arsenal", "league": "epl", "goals_for": 2.0,
                 "goals_against": 1.0, "xG_for": 1.8, "xG_against": 1.0, "games_used": 5}]
    ucl_data = [{"team": "Real Madrid", "league": "ucl", "goals_for": 2.5,
                 "goals_against": 0.8, "xG_for": 2.2, "xG_against": 0.9, "games_used": 5}]
    with patch("alpha.data.ingestion.soccer_stats.get_team_rolling_stats",
               side_effect=lambda k: epl_data if k == "epl" else ucl_data):
        result = get_team_rolling_stats_all()
    teams = [r["team"] for r in result]
    assert "Arsenal" in teams
    assert "Real Madrid" in teams
