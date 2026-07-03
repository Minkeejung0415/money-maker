"""Tests for alpha/data/ingestion/mlb_stats.py (mocked pybaseball calls)."""
from __future__ import annotations

import pickle
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from alpha.data.ingestion.mlb_stats import (
    get_advanced_batter_stats,
    get_advanced_bullpen_stats,
    get_advanced_pitcher_stats,
    get_batter_stats,
    get_pitcher_stats,
    get_probable_pitchers,
    get_team_batting_stats,
    get_team_pitching_stats,
    get_team_stats_map,
)


# ---------------------------------------------------------------------------
# get_team_batting_stats
# ---------------------------------------------------------------------------

def test_team_batting_stats_returns_empty_on_pybaseball_error(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    with patch("pybaseball.team_batting", side_effect=Exception("network error")):
        result = get_team_batting_stats(2025)
    assert result == []


def test_team_batting_stats_parses_dataframe(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    fake_df = pd.DataFrame([{
        "Team": "NYY", "G": 162, "R": 800,
        "BA": 0.260, "OBP": 0.330, "SLG": 0.450, "OPS": 0.780,
    }])
    with patch("pybaseball.team_batting", return_value=fake_df):
        result = get_team_batting_stats(2025)
    assert len(result) == 1
    assert result[0]["team"] == "NYY"
    assert result[0]["runs_per_game"] == pytest.approx(800 / 162, abs=0.01)


def test_team_batting_stats_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    cached = [{"team": "NYY", "runs_per_game": 4.9, "batting_avg": 0.260,
               "obp": 0.330, "slg": 0.450, "ops": 0.780}]
    cache_file = tmp_path / f"team_batting_2025_{date.today()}.pkl"
    with open(cache_file, "wb") as f:
        pickle.dump(cached, f)
    with patch("pybaseball.team_batting") as mock_pb:
        result = get_team_batting_stats(2025)
    mock_pb.assert_not_called()
    assert result[0]["team"] == "NYY"


def test_team_batting_stats_returns_empty_for_empty_df(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    with patch("pybaseball.team_batting", return_value=pd.DataFrame()):
        result = get_team_batting_stats(2025)
    assert result == []


# ---------------------------------------------------------------------------
# get_team_pitching_stats
# ---------------------------------------------------------------------------

def test_team_pitching_stats_parses_dataframe(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    fake_df = pd.DataFrame([{
        "Team": "NYY", "G": 162, "ERA": 3.50, "WHIP": 1.15,
        "R": 550, "SO": 1400, "IP": 1450.0,
    }])
    with patch("pybaseball.team_pitching", return_value=fake_df):
        result = get_team_pitching_stats(2025)
    assert len(result) == 1
    assert result[0]["era"] == pytest.approx(3.50)
    assert result[0]["k_per9"] > 0


def test_team_pitching_stats_returns_empty_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    with patch("pybaseball.team_pitching", side_effect=RuntimeError("fail")):
        result = get_team_pitching_stats(2025)
    assert result == []


# ---------------------------------------------------------------------------
# get_batter_stats
# ---------------------------------------------------------------------------

def test_batter_stats_parses_dataframe(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    fake_df = pd.DataFrame([{
        "Name": "Aaron Judge", "Team": "NYY", "G": 150,
        "AVG": 0.310, "OBP": 0.400, "SLG": 0.600, "HR": 50, "PA": 600,
    }])
    with patch("pybaseball.batting_stats", return_value=fake_df):
        result = get_batter_stats(2025)
    assert len(result) == 1
    assert result[0]["player"] == "Aaron Judge"
    assert result[0]["hr_per_game"] == pytest.approx(50 / 150, abs=0.001)


def test_batter_stats_returns_empty_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    with patch("pybaseball.batting_stats", side_effect=Exception("rate limit")):
        result = get_batter_stats(2025)
    assert result == []


# ---------------------------------------------------------------------------
# get_pitcher_stats
# ---------------------------------------------------------------------------

def test_pitcher_stats_parses_dataframe(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    fake_df = pd.DataFrame([{
        "Name": "Gerrit Cole", "Team": "NYY", "ERA": 2.80, "WHIP": 1.05,
        "SO": 200, "IP": 200.0,
    }])
    with patch("pybaseball.pitching_stats", return_value=fake_df):
        result = get_pitcher_stats(2025)
    assert len(result) == 1
    assert result[0]["player"] == "Gerrit Cole"
    assert result[0]["era"] == pytest.approx(2.80)
    assert result[0]["k_per9"] == pytest.approx(200 / 200 * 9)


def test_advanced_batter_stats_combines_savant_xwoba_and_war(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    savant = pd.DataFrame([{
        "last_name, first_name": "Judge, Aaron",
        "player_id": 592450,
        "pa": 100,
        "est_woba": 0.430,
    }])
    bwar = pd.DataFrame([{
        "name_common": "Aaron Judge",
        "mlb_ID": 592450,
        "year_ID": 2026,
        "team_ID": "NYY",
        "PA": 100,
        "WAR": 5.4,
    }])
    with patch("pybaseball.statcast_batter_expected_stats", return_value=savant), \
         patch("pybaseball.bwar_bat", return_value=bwar):
        result = get_advanced_batter_stats(2026, min_pa=20)
    assert result[0]["player"] == "Aaron Judge"
    assert result[0]["team"] == "New York Yankees"
    assert result[0]["xwoba"] == pytest.approx(0.430)
    assert result[0]["war"] == pytest.approx(5.4)
    assert result[0]["wrc_plus"] == 0.0


def test_advanced_pitcher_stats_combines_xera_war_and_derived_components(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    savant = pd.DataFrame([{
        "last_name, first_name": "Cole, Gerrit",
        "player_id": 543037,
        "pa": 120,
        "xera": 3.10,
    }])
    bwar = pd.DataFrame([{
        "name_common": "Gerrit Cole",
        "mlb_ID": 543037,
        "year_ID": 2026,
        "team_ID": "NYY",
        "GS": 4,
        "WAR": 1.2,
    }])
    stats_response = MagicMock()
    stats_response.raise_for_status.return_value = None
    stats_response.json.return_value = {
        "stats": [{
            "splits": [{
                "player": {"id": 543037, "fullName": "Gerrit Cole"},
                "team": {"name": "New York Yankees"},
                "stat": {
                    "inningsPitched": "20.0",
                    "baseOnBalls": 5,
                    "hitByPitch": 1,
                    "strikeOuts": 30,
                    "homeRuns": 2,
                    "battersFaced": 80,
                    "gamesStarted": 4,
                    "games": 4,
                },
            }],
        }],
    }
    with patch("pybaseball.statcast_pitcher_expected_stats", return_value=savant), \
         patch("pybaseball.bwar_pitch", return_value=bwar), \
         patch("requests.get", return_value=stats_response):
        result = get_advanced_pitcher_stats(2026, min_bf=20)
    assert result[0]["player"] == "Gerrit Cole"
    assert result[0]["team"] == "New York Yankees"
    assert result[0]["xera"] == pytest.approx(3.10)
    assert result[0]["war"] == pytest.approx(1.2)
    assert result[0]["k_bb_pct"] == pytest.approx((30 - 5) / 80)
    assert result[0]["projected_innings"] == pytest.approx(5.0)


def test_advanced_bullpen_stats_groups_relievers(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    stats_response = MagicMock()
    stats_response.raise_for_status.return_value = None
    stats_response.json.return_value = {
        "stats": [{
            "splits": [
                {
                    "player": {"id": 1, "fullName": "Reliever One"},
                    "team": {"name": "New York Yankees"},
                    "stat": {
                        "inningsPitched": "10.0",
                        "baseOnBalls": 2,
                        "hitByPitch": 0,
                        "strikeOuts": 15,
                        "homeRuns": 1,
                        "battersFaced": 40,
                        "gamesStarted": 0,
                        "games": 10,
                    },
                },
                {
                    "player": {"id": 2, "fullName": "Starter One"},
                    "team": {"name": "New York Yankees"},
                    "stat": {
                        "inningsPitched": "20.0",
                        "baseOnBalls": 4,
                        "hitByPitch": 0,
                        "strikeOuts": 20,
                        "homeRuns": 2,
                        "battersFaced": 80,
                        "gamesStarted": 4,
                        "games": 4,
                    },
                },
            ],
        }],
    }
    with patch("requests.get", return_value=stats_response):
        result = get_advanced_bullpen_stats(2026)
    assert len(result) == 1
    assert result[0]["team"] == "New York Yankees"
    assert result[0]["k_bb_pct"] == pytest.approx((15 - 2) / 40)


# ---------------------------------------------------------------------------
# get_probable_pitchers
# ---------------------------------------------------------------------------

def test_probable_pitchers_returns_empty_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    # Patch the import inside the function — statsapi may not be installed
    import sys
    import types
    fake_statsapi = types.ModuleType("statsapi")
    fake_statsapi.schedule = MagicMock(side_effect=Exception("API down"))
    with patch.dict(sys.modules, {"statsapi": fake_statsapi}):
        result = get_probable_pitchers("2025-04-01")
    assert isinstance(result, dict)


def test_probable_pitchers_parses_schedule(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    fake_schedule = [{
        "home_name": "New York Yankees",
        "away_name": "Boston Red Sox",
        "home_probable_pitcher": "Gerrit Cole",
        "away_probable_pitcher": "Chris Sale",
    }]
    import sys
    import types
    fake_statsapi = types.ModuleType("statsapi")
    fake_statsapi.schedule = MagicMock(return_value=fake_schedule)
    with patch.dict(sys.modules, {"statsapi": fake_statsapi}):
        result = get_probable_pitchers("2025-04-01")
    assert result.get("New York Yankees") == "Gerrit Cole"
    assert result.get("Boston Red Sox") == "Chris Sale"


# ---------------------------------------------------------------------------
# get_team_stats_map
# ---------------------------------------------------------------------------

def test_team_stats_map_combines_batting_and_pitching(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats._CACHE_DIR", tmp_path)
    batting = [{"team": "NYY", "runs_per_game": 5.0, "batting_avg": 0.260,
                "obp": 0.330, "slg": 0.450, "ops": 0.780}]
    pitching = [{"team": "NYY", "era": 3.50, "whip": 1.15,
                 "runs_allowed_per_game": 3.5, "k_per9": 9.0}]
    with patch("alpha.data.ingestion.mlb_stats.get_team_batting_stats", return_value=batting), \
         patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=pitching):
        result = get_team_stats_map(2025)
    assert "NYY" in result
    assert result["NYY"]["runs_per_game"] == pytest.approx(5.0)
    assert result["NYY"]["era"] == pytest.approx(3.50)
