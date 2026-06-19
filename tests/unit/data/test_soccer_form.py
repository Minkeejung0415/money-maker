"""
Unit tests for alpha.data.ingestion.soccer_form.

All tests mock FootballDataClient.fetch_team_matches() - no live API calls.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import alpha.data.ingestion.soccer_form as soccer_form
from alpha.data.ingestion.soccer_form import (
    fetch_days_rest,
    fetch_h2h,
    fetch_team_form,
)


@pytest.fixture(autouse=True)
def _isolated_cache(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent one test's daily cache entry from leaking into another."""
    if request.node.name != "test_cache_namespace_isolated":
        monkeypatch.setattr(soccer_form, "_CACHE_DIR", tmp_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_match(
    home_id: int,
    away_id: int,
    winner: str | None,
    home_goals: int = 1,
    away_goals: int = 0,
    utc_date: str = "2025-12-01T15:00:00Z",
) -> dict:
    """Build a minimal football-data.org match dict for testing."""
    return {
        "homeTeam": {"id": home_id, "name": f"Team{home_id}"},
        "awayTeam": {"id": away_id, "name": f"Team{away_id}"},
        "utcDate": utc_date,
        "score": {
            "winner": winner,
            "fullTime": {"home": home_goals, "away": away_goals},
        },
    }


# ---------------------------------------------------------------------------
# Form tests (SDATA-01)
# ---------------------------------------------------------------------------

def test_form_all_wins():
    """5 matches all HOME_WIN with team as home team: form_points=15, wdl=5 Ws."""
    team_id = 57
    matches = [
        _make_match(team_id, 99, "HOME_WIN", 2, 0, f"2025-11-0{i}T15:00:00Z")
        for i in range(1, 6)
    ]
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = matches
        result = fetch_team_form(team_id, n=5)

    assert result["form_points"] == 15
    assert result["wdl"] == ["W", "W", "W", "W", "W"]
    assert result["games"] == 5


def test_form_mixed():
    """2W, 1D, 2L: form_points = 6+1+0+0 = 7."""
    team_id = 57
    matches = [
        _make_match(team_id, 99, "HOME_WIN", 2, 0, "2025-11-01T15:00:00Z"),
        _make_match(team_id, 99, "HOME_WIN", 1, 0, "2025-11-05T15:00:00Z"),
        _make_match(team_id, 99, "DRAW", 1, 1, "2025-11-10T15:00:00Z"),
        _make_match(99, team_id, "HOME_WIN", 2, 0, "2025-11-15T15:00:00Z"),  # team as away, loses
        _make_match(99, team_id, "HOME_WIN", 3, 1, "2025-11-20T15:00:00Z"),  # team as away, loses
    ]
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = matches
        result = fetch_team_form(team_id, n=5)

    assert result["form_points"] == 7


def test_form_empty():
    """No matches: games=0, form_points=0, wdl=[]."""
    team_id = 57
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = []
        result = fetch_team_form(team_id, n=5)

    assert result["games"] == 0
    assert result["form_points"] == 0
    assert result["wdl"] == []


def test_form_skips_null_winner():
    """Matches where score.winner=null are excluded from computation."""
    team_id = 57
    matches = [
        _make_match(team_id, 99, None, 0, 0, "2025-11-01T15:00:00Z"),  # null winner - skip
        _make_match(team_id, 99, "HOME_WIN", 2, 0, "2025-11-05T15:00:00Z"),
    ]
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = matches
        result = fetch_team_form(team_id, n=5)

    # Only 1 completed match (the null-winner one is excluded)
    assert result["games"] == 1
    assert result["form_points"] == 3
    assert result["wdl"] == ["W"]


# ---------------------------------------------------------------------------
# H2H tests (SDATA-02)
# ---------------------------------------------------------------------------

def test_h2h_basic():
    """3 meetings (2 home wins, 1 draw): meetings=3, h2h_home_win_rate ~0.667."""
    home_id, away_id = 57, 61
    matches = [
        _make_match(home_id, away_id, "HOME_WIN", 2, 0, "2024-01-01T15:00:00Z"),
        _make_match(home_id, away_id, "HOME_WIN", 1, 0, "2024-04-01T15:00:00Z"),
        _make_match(away_id, home_id, "DRAW", 1, 1, "2024-08-01T15:00:00Z"),
    ]
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = matches
        result = fetch_h2h(home_id, away_id, n=5)

    assert result["meetings"] == 3
    assert result["h2h_home_wins"] == 2
    assert result["h2h_draws"] == 1
    assert result["h2h_away_wins"] == 0
    assert abs(result["h2h_home_win_rate"] - 2 / 3) < 0.001


def test_h2h_partial():
    """Only 2 meetings found: meetings=2, no error, no padding."""
    home_id, away_id = 57, 61
    matches = [
        _make_match(home_id, away_id, "HOME_WIN", 2, 0, "2024-01-01T15:00:00Z"),
        _make_match(away_id, home_id, "AWAY_WIN", 0, 1, "2024-04-01T15:00:00Z"),
    ]
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = matches
        result = fetch_h2h(home_id, away_id, n=5)

    assert result["meetings"] == 2


def test_h2h_no_meetings():
    """Empty filtered list (no meetings between the two teams): meetings=0."""
    home_id, away_id = 57, 61
    # Matches involve neither team pairing
    matches = [
        _make_match(99, 100, "HOME_WIN", 1, 0, "2024-01-01T15:00:00Z"),
    ]
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = matches
        result = fetch_h2h(home_id, away_id, n=5)

    assert result["meetings"] == 0
    assert result["h2h_home_win_rate"] == 0.0


# ---------------------------------------------------------------------------
# Days rest tests (SDATA-03)
# ---------------------------------------------------------------------------

def test_days_rest_normal():
    """7 days apart (last=Dec 1, match=Dec 8): returns max(0, min(7, 8-1-1))=6."""
    team_id = 57
    matches = [
        _make_match(team_id, 99, "HOME_WIN", 2, 0, "2025-12-01T15:00:00Z"),
    ]
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = matches
        result = fetch_days_rest(team_id, "2025-12-08")

    assert result == 6


def test_days_rest_no_prior():
    """Empty matches list: returns default of 3."""
    team_id = 57
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = []
        result = fetch_days_rest(team_id, "2025-12-08")

    assert result == 3


def test_days_rest_b2b():
    """1 day apart (last=Dec 7, match=Dec 8): returns max(0, 1-1)=0."""
    team_id = 57
    matches = [
        _make_match(team_id, 99, "HOME_WIN", 2, 0, "2025-12-07T15:00:00Z"),
    ]
    with patch(
        "alpha.data.ingestion.football_data_client.FootballDataClient"
    ) as MockClient:
        MockClient.return_value.fetch_team_matches.return_value = matches
        result = fetch_days_rest(team_id, "2025-12-08")

    assert result == 0


# ---------------------------------------------------------------------------
# Cache isolation (D-07)
# ---------------------------------------------------------------------------

def test_cache_namespace_isolated():
    """soccer_form._CACHE_DIR must be data/.soccer_cache, not data/.wc_cache."""
    assert soccer_form._CACHE_DIR == Path("data/.soccer_cache")


def test_no_wc_imports():
    """soccer_form must not import from wc_elo or wc_stats."""
    import inspect
    source = inspect.getsource(soccer_form)
    assert "wc_elo" not in source
    assert "wc_stats" not in source
