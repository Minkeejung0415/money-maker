"""Tests for FootballDataClient.fetch_wc_games() and 429 retry."""
from unittest.mock import MagicMock, call, patch

import pytest
import requests as req_lib

from alpha.data.ingestion.football_data_client import FootballDataClient, _COMP_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_match_response(
    home: str,
    away: str,
    match_id: int = 1,
    stage: str = "GROUP_STAGE",
    group: str = "Group A",
) -> dict:
    """Build a minimal football-data.org /competitions/WC/matches response body."""
    return {
        "matches": [
            {
                "id": match_id,
                "utcDate": "2026-06-12T18:00:00Z",
                "stage": stage,
                "group": group,
                "homeTeam": {"name": home},
                "awayTeam": {"name": away},
            }
        ]
    }


# ---------------------------------------------------------------------------
# _COMP_MAP regression tests
# ---------------------------------------------------------------------------

def test_comp_map_has_wc():
    assert "wc" in _COMP_MAP
    assert _COMP_MAP["wc"] == "WC"


def test_comp_map_epl_ucl_unchanged():
    assert _COMP_MAP["epl"] == "PL"
    assert _COMP_MAP["ucl"] == "CL"


# ---------------------------------------------------------------------------
# fetch_wc_games() — happy path
# ---------------------------------------------------------------------------

def test_fetch_wc_games_returns_stage_and_group():
    """Group-stage game returns stage and group fields."""
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_match_response("Brazil", "Germany")
    mock_resp.raise_for_status.return_value = None

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        return_value=mock_resp,
    ):
        games = client.fetch_wc_games("2026-06-12", "2026-06-12")

    assert len(games) == 1
    g = games[0]
    assert g["home_team"] == "Brazil"
    assert g["away_team"] == "Germany"
    assert g["stage"] == "GROUP_STAGE"
    assert g["group"] == "Group A"
    assert g["league"] == "wc"


def test_fetch_wc_games_knockout_no_group():
    """Knockout game has stage set and empty group string."""
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_match_response(
        "France", "Argentina", stage="LAST_16", group=""
    )
    mock_resp.raise_for_status.return_value = None

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        return_value=mock_resp,
    ):
        games = client.fetch_wc_games("2026-07-04", "2026-07-04")

    assert len(games) == 1
    assert games[0]["stage"] == "LAST_16"
    assert games[0]["group"] == ""


def test_fetch_wc_games_event_id_is_string():
    """event_id must be a string, even when match id is an int in the API response."""
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_match_response("Spain", "Morocco", match_id=42)
    mock_resp.raise_for_status.return_value = None

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        return_value=mock_resp,
    ):
        games = client.fetch_wc_games("2026-06-18", "2026-06-18")

    assert len(games) == 1
    assert isinstance(games[0]["event_id"], str)
    assert games[0]["event_id"] == "42"


def test_fetch_wc_games_default_odds():
    """Returned game dicts have -110 default odds (no odds on free tier)."""
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_match_response("England", "USA")
    mock_resp.raise_for_status.return_value = None

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        return_value=mock_resp,
    ):
        games = client.fetch_wc_games("2026-06-22", "2026-06-22")

    assert games[0]["home_odds"] == -110
    assert games[0]["away_odds"] == -110


# ---------------------------------------------------------------------------
# fetch_wc_games() — skip logic
# ---------------------------------------------------------------------------

def test_fetch_wc_games_skips_missing_teams():
    """Matches with missing homeTeam.name or awayTeam.name are skipped silently."""
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # First match has empty homeTeam name — should be skipped
    mock_resp.json.return_value = {
        "matches": [
            {
                "id": 1,
                "utcDate": "2026-06-12T18:00:00Z",
                "stage": "GROUP_STAGE",
                "group": "Group A",
                "homeTeam": {"name": ""},
                "awayTeam": {"name": "Germany"},
            },
            {
                "id": 2,
                "utcDate": "2026-06-12T21:00:00Z",
                "stage": "GROUP_STAGE",
                "group": "Group B",
                "homeTeam": {"name": "Brazil"},
                "awayTeam": {"name": "Mexico"},
            },
        ]
    }
    mock_resp.raise_for_status.return_value = None

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        return_value=mock_resp,
    ):
        games = client.fetch_wc_games("2026-06-12", "2026-06-12")

    assert len(games) == 1
    assert games[0]["home_team"] == "Brazil"


# ---------------------------------------------------------------------------
# fetch_wc_games() — 429 retry
# ---------------------------------------------------------------------------

def test_fetch_wc_games_429_retry(monkeypatch):
    """First call returns 429; second call returns 200 with one match."""
    client = FootballDataClient(api_key="testkey")

    resp_429 = MagicMock()
    resp_429.status_code = 429
    # raise_for_status is NOT called on 429 at attempt 0 — the retry logic checks status_code
    resp_429.raise_for_status.return_value = None

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = _make_match_response("France", "Argentina")
    resp_200.raise_for_status.return_value = None

    sleep_calls = []
    monkeypatch.setattr(
        "alpha.data.ingestion.football_data_client.time.sleep",
        lambda s: sleep_calls.append(s),
    )

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        side_effect=[resp_429, resp_200],
    ):
        games = client.fetch_wc_games("2026-06-14", "2026-06-14")

    assert len(games) == 1
    assert sleep_calls == [60]  # exactly one 60s wait


# ---------------------------------------------------------------------------
# fetch_wc_games() — error paths
# ---------------------------------------------------------------------------

def test_fetch_wc_games_returns_empty_on_http_error():
    """Non-429 HTTP error returns [] and does not raise."""
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    http_err = req_lib.exceptions.HTTPError(response=mock_resp)

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        side_effect=http_err,
    ):
        result = client.fetch_wc_games("2026-06-12", "2026-06-12")

    assert result == []


def test_fetch_wc_games_returns_empty_on_general_exception():
    """A network error (ConnectionError etc.) returns [] and does not raise."""
    client = FootballDataClient(api_key="testkey")

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        side_effect=req_lib.exceptions.ConnectionError("timeout"),
    ):
        result = client.fetch_wc_games("2026-06-12", "2026-06-12")

    assert result == []


def test_fetch_wc_games_returns_empty_when_not_configured():
    """Empty api_key returns [] immediately without making any network call."""
    client = FootballDataClient(api_key="")

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get"
    ) as mock_get:
        result = client.fetch_wc_games("2026-06-12", "2026-06-12")

    mock_get.assert_not_called()
    assert result == []


# ---------------------------------------------------------------------------
# fetch_today_games() — regression test (must NOT gain stage/group keys)
# ---------------------------------------------------------------------------

def test_fetch_today_games_epl_regression():
    """fetch_today_games() for EPL must return the 7-key dict shape — no stage or group."""
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "matches": [
            {
                "id": 99,
                "utcDate": "2026-06-18T15:00:00Z",
                "homeTeam": {"name": "Arsenal"},
                "awayTeam": {"name": "Chelsea"},
            }
        ]
    }

    with patch(
        "alpha.data.ingestion.football_data_client.requests.get",
        return_value=mock_resp,
    ):
        games = client.fetch_today_games("epl")

    assert len(games) == 1
    expected_keys = {"home_team", "away_team", "home_odds", "away_odds", "league", "event_id", "commence_time"}
    assert set(games[0].keys()) == expected_keys
    assert "stage" not in games[0]
    assert "group" not in games[0]
