"""Tests for alpha/data/ingestion/soccer_stats.py (Understat backend)."""
from __future__ import annotations

import pickle
from datetime import date
from unittest.mock import patch

import pytest

from alpha.data.ingestion.soccer_stats import (
    SUPPORTED_LEAGUES,
    _UNDERSTAT_LEAGUE_MAP,
    _safe_float,
    get_player_per90_stats,
    get_player_per90_stats_all,
    get_team_rolling_stats,
    get_team_rolling_stats_all,
)


# ---------------------------------------------------------------------------
# SUPPORTED_LEAGUES / _UNDERSTAT_LEAGUE_MAP
# ---------------------------------------------------------------------------

def test_supported_leagues_contains_epl():
    assert "epl" in SUPPORTED_LEAGUES


def test_supported_leagues_contains_ucl():
    assert "ucl" in SUPPORTED_LEAGUES


def test_understat_map_has_epl():
    assert "epl" in _UNDERSTAT_LEAGUE_MAP
    assert _UNDERSTAT_LEAGUE_MAP["epl"] == "EPL"


def test_understat_map_does_not_have_ucl():
    # UCL is not available on Understat — returns empty stats
    assert "ucl" not in _UNDERSTAT_LEAGUE_MAP


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

def test_safe_float_valid_string():
    assert _safe_float("1.5") == pytest.approx(1.5)


def test_safe_float_valid_int():
    assert _safe_float(3) == pytest.approx(3.0)


def test_safe_float_invalid_string():
    assert _safe_float("n/a") is None


def test_safe_float_none():
    assert _safe_float(None) is None


# ---------------------------------------------------------------------------
# get_team_rolling_stats — unsupported leagues
# ---------------------------------------------------------------------------

def test_get_team_rolling_stats_unknown_league_returns_empty():
    result = get_team_rolling_stats("xyz_unknown")
    assert result == []


def test_get_team_rolling_stats_ucl_returns_empty_without_api_call():
    """UCL is not on Understat — must return [] without touching _run_async."""
    with patch("alpha.data.ingestion.soccer_stats._run_async") as mock_run:
        result = get_team_rolling_stats("ucl")
    mock_run.assert_not_called()
    assert result == []


# ---------------------------------------------------------------------------
# get_team_rolling_stats — cache
# ---------------------------------------------------------------------------

def test_get_team_rolling_stats_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    cache_file = tmp_path / f"team_rolling_epl_{date.today()}.pkl"
    fake_data = [
        {
            "team": "Arsenal", "league": "epl", "goals_for": 2.1,
            "goals_against": 1.0, "xG_for": 1.9, "xG_against": 1.1, "games_used": 5,
        }
    ]
    with open(cache_file, "wb") as f:
        pickle.dump(fake_data, f)

    with patch("alpha.data.ingestion.soccer_stats._run_async") as mock_run:
        result = get_team_rolling_stats("epl")

    mock_run.assert_not_called()
    assert result[0]["team"] == "Arsenal"


# ---------------------------------------------------------------------------
# get_team_rolling_stats — live parsing via mocked _run_async
# ---------------------------------------------------------------------------

def test_get_team_rolling_stats_parses_understat_results(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    fake_results = [
        {
            "isResult": True,
            "h": {"title": "Arsenal"}, "a": {"title": "Chelsea"},
            "goals": {"h": "2", "a": "1"}, "xG": {"h": "1.8", "a": "0.9"},
        },
        {
            "isResult": True,
            "h": {"title": "Arsenal"}, "a": {"title": "Liverpool"},
            "goals": {"h": "1", "a": "3"}, "xG": {"h": "0.7", "a": "2.5"},
        },
    ]
    with patch("alpha.data.ingestion.soccer_stats._run_async", return_value=fake_results):
        result = get_team_rolling_stats("epl")

    teams = {r["team"] for r in result}
    assert "Arsenal" in teams

    arsenal = next(r for r in result if r["team"] == "Arsenal")
    assert arsenal["goals_for"] == pytest.approx(1.5)   # (2 + 1) / 2
    assert arsenal["league"] == "epl"
    assert arsenal["games_used"] == 2


def test_get_team_rolling_stats_skips_future_matches(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    fake_results = [
        {
            "isResult": False,
            "h": {"title": "Arsenal"}, "a": {"title": "Chelsea"},
            "goals": {"h": "0", "a": "0"}, "xG": {"h": "0", "a": "0"},
        },
    ]
    with patch("alpha.data.ingestion.soccer_stats._run_async", return_value=fake_results):
        result = get_team_rolling_stats("epl")

    assert result == []


def test_get_team_rolling_stats_returns_empty_on_exception(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    with patch(
        "alpha.data.ingestion.soccer_stats._run_async",
        side_effect=Exception("network error"),
    ):
        result = get_team_rolling_stats("epl")

    assert result == []


# ---------------------------------------------------------------------------
# get_player_per90_stats — unsupported leagues
# ---------------------------------------------------------------------------

def test_get_player_per90_stats_ucl_returns_empty_without_api_call():
    with patch("alpha.data.ingestion.soccer_stats._run_async") as mock_run:
        result = get_player_per90_stats("ucl")
    mock_run.assert_not_called()
    assert result == []


def test_get_player_per90_stats_unknown_returns_empty():
    assert get_player_per90_stats("xyz") == []


# ---------------------------------------------------------------------------
# get_player_per90_stats — live parsing
# ---------------------------------------------------------------------------

def test_get_player_per90_stats_parses_understat_players(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    fake_players = [
        {
            "player_name": "Mohamed Salah",
            "team_title": "Liverpool",
            "time": "1800",   # 20 × 90 min
            "goals": "18",
            "assists": "7",
            "shots": "90",
            "xG": "16.5",
        },
        {
            "player_name": "Short Player",
            "team_title": "Arsenal",
            "time": "45",    # less than 90 min — should be skipped
            "goals": "0",
            "assists": "0",
            "shots": "1",
            "xG": "0.1",
        },
    ]
    with patch("alpha.data.ingestion.soccer_stats._run_async", return_value=fake_players):
        result = get_player_per90_stats("epl")

    players = {r["player"] for r in result}
    assert "Mohamed Salah" in players
    assert "Short Player" not in players

    salah = next(r for r in result if r["player"] == "Mohamed Salah")
    mins_90s = 1800 / 90  # = 20.0
    assert salah["goals_per90"] == pytest.approx(18 / mins_90s, rel=1e-3)
    assert salah["shots_per90"] == pytest.approx(90 / mins_90s, rel=1e-3)
    assert salah["assists_per90"] == pytest.approx(7 / mins_90s, rel=1e-3)
    assert salah["league"] == "epl"
    assert salah["minutes_90s"] == pytest.approx(20.0)


def test_get_player_per90_stats_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    cache_file = tmp_path / f"player_per90_epl_{date.today()}.pkl"
    fake = [
        {
            "player": "Salah", "team": "Liverpool", "league": "epl",
            "goals_per90": 0.9, "assists_per90": 0.35,
            "shots_per90": 4.5, "xG_per90": 0.82, "minutes_90s": 20.0,
        }
    ]
    with open(cache_file, "wb") as f:
        pickle.dump(fake, f)

    with patch("alpha.data.ingestion.soccer_stats._run_async") as mock_run:
        result = get_player_per90_stats("epl")

    mock_run.assert_not_called()
    assert result[0]["player"] == "Salah"


def test_get_player_per90_stats_returns_empty_on_exception(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    with patch(
        "alpha.data.ingestion.soccer_stats._run_async",
        side_effect=RuntimeError("timeout"),
    ):
        result = get_player_per90_stats("epl")

    assert result == []


# ---------------------------------------------------------------------------
# get_*_all helpers
# ---------------------------------------------------------------------------

def test_get_team_rolling_stats_all_combines_leagues(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    epl_data = [
        {
            "team": "Arsenal", "league": "epl", "goals_for": 2.0,
            "goals_against": 1.0, "xG_for": 1.8, "xG_against": 1.0, "games_used": 5,
        }
    ]
    ucl_data: list = []  # UCL returns empty (not on Understat)

    with patch(
        "alpha.data.ingestion.soccer_stats.get_team_rolling_stats",
        side_effect=lambda k: epl_data if k == "epl" else ucl_data,
    ):
        result = get_team_rolling_stats_all()

    teams = [r["team"] for r in result]
    assert "Arsenal" in teams


def test_get_player_per90_stats_all_combines_leagues(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.soccer_stats._CACHE_DIR", tmp_path)
    epl_data = [
        {
            "player": "Salah", "team": "Liverpool", "league": "epl",
            "goals_per90": 0.9, "assists_per90": 0.35,
            "shots_per90": 4.5, "xG_per90": 0.82, "minutes_90s": 20.0,
        }
    ]

    with patch(
        "alpha.data.ingestion.soccer_stats.get_player_per90_stats",
        side_effect=lambda k: epl_data if k == "epl" else [],
    ):
        result = get_player_per90_stats_all()

    assert any(r["player"] == "Salah" for r in result)
