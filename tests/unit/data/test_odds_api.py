"""
Tests for alpha.data.ingestion.odds_api.OddsAPIClient
"""
from unittest.mock import MagicMock, patch

import pytest

from alpha.data.ingestion.odds_api import OddsAPIClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    event_id="evt1",
    home_team="Boston Celtics",
    away_team="Miami Heat",
    home_price=-150,
    away_price=130,
):
    """Build a minimal Odds-API v4 event object."""
    return {
        "id": event_id,
        "sport_key": "basketball_nba",
        "commence_time": "2026-03-10T00:00:00Z",
        "home_team": home_team,
        "away_team": away_team,
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": home_team, "price": home_price},
                            {"name": away_team, "price": away_price},
                        ],
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# is_configured()
# ---------------------------------------------------------------------------

def test_is_configured_false_when_key_empty():
    client = OddsAPIClient(api_key="")
    assert client.is_configured() is False


def test_is_configured_true_when_key_set():
    client = OddsAPIClient(api_key="test_key_123")
    assert client.is_configured() is True


def test_is_configured_reads_env(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "env_key")
    # Do NOT pass api_key so it falls back to env
    client = OddsAPIClient()
    assert client.is_configured() is True


# ---------------------------------------------------------------------------
# fetch_nba_games() — no key
# ---------------------------------------------------------------------------

def test_fetch_returns_empty_when_no_key():
    """No API key → no network call, returns []."""
    client = OddsAPIClient(api_key="", cache_dir=None)
    with patch("alpha.data.ingestion.odds_api.requests.get") as mock_get:
        result = client.fetch_nba_games()
    mock_get.assert_not_called()
    assert result == []


# ---------------------------------------------------------------------------
# fetch_nba_games() — parse logic
# ---------------------------------------------------------------------------

def test_fetch_parses_single_event():
    client = OddsAPIClient(api_key="key", cache_dir=None)
    event = _make_event(
        home_team="Boston Celtics",
        away_team="Miami Heat",
        home_price=-150,
        away_price=130,
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = [event]
    mock_resp.raise_for_status.return_value = None

    with patch("alpha.data.ingestion.odds_api.requests.get", return_value=mock_resp):
        games = client.fetch_nba_games()

    assert len(games) == 1
    g = games[0]
    assert g["home_team"] == "Boston Celtics"
    assert g["away_team"] == "Miami Heat"
    assert g["home_odds"] == -150
    assert g["away_odds"] == 130
    assert g["league"] == "nba"
    assert g["event_id"] == "evt1"
    assert g["commence_time"] == "2026-03-10T00:00:00Z"


def test_fetch_parses_multiple_events():
    client = OddsAPIClient(api_key="key", cache_dir=None)
    events = [
        _make_event("e1", "Los Angeles Lakers", "Golden State Warriors", -120, 100),
        _make_event("e2", "Denver Nuggets", "Dallas Mavericks", -200, 170),
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = events
    mock_resp.raise_for_status.return_value = None

    with patch("alpha.data.ingestion.odds_api.requests.get", return_value=mock_resp):
        games = client.fetch_nba_games()

    assert len(games) == 2
    assert games[0]["event_id"] == "e1"
    assert games[1]["home_team"] == "Denver Nuggets"


# ---------------------------------------------------------------------------
# fetch_nba_games() — error handling
# ---------------------------------------------------------------------------

def test_fetch_returns_empty_on_http_error():
    import requests as req_lib
    client = OddsAPIClient(api_key="key", cache_dir=None)
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    http_err = req_lib.exceptions.HTTPError(response=mock_resp)

    with patch("alpha.data.ingestion.odds_api.requests.get", side_effect=http_err):
        result = client.fetch_nba_games()

    assert result == []


def test_fetch_returns_empty_on_network_error():
    import requests as req_lib
    client = OddsAPIClient(api_key="key", cache_dir=None)

    with patch(
        "alpha.data.ingestion.odds_api.requests.get",
        side_effect=req_lib.exceptions.ConnectionError("timeout"),
    ):
        result = client.fetch_nba_games()

    assert result == []


def test_fetch_returns_empty_on_unexpected_exception():
    client = OddsAPIClient(api_key="key", cache_dir=None)

    with patch(
        "alpha.data.ingestion.odds_api.requests.get",
        side_effect=ValueError("bad JSON"),
    ):
        result = client.fetch_nba_games()

    assert result == []


# ---------------------------------------------------------------------------
# _extract_best_odds fallback
# ---------------------------------------------------------------------------

def test_fallback_odds_when_no_bookmakers():
    client = OddsAPIClient(api_key="key", cache_dir=None)
    event_no_books = {
        "id": "x",
        "home_team": "Team A",
        "away_team": "Team B",
        "commence_time": "",
        "bookmakers": [],
    }
    game = client._parse_event(event_no_books)
    assert game is not None
    assert game["home_odds"] == -110
    assert game["away_odds"] == -110
