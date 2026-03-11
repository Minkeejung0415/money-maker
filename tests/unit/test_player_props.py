"""Unit tests for PlayerPropsClient."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from alpha.data.ingestion.player_props import PlayerPropsClient

# ---------------------------------------------------------------------------
# Shared test fixture — a minimal two-player, two-bookmaker API response
# ---------------------------------------------------------------------------

FAKE_RESPONSE = {
    "bookmakers": [
        {
            "key": "fanduel",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over",  "description": "LeBron James", "price": -115, "point": 27.5},
                        {"name": "Under", "description": "LeBron James", "price": -105, "point": 27.5},
                        {"name": "Over",  "description": "Anthony Davis", "price": -110, "point": 24.5},
                        {"name": "Under", "description": "Anthony Davis", "price": -110, "point": 24.5},
                    ],
                }
            ],
        }
    ]
}

FAKE_RESPONSE_TWO_BOOKS = {
    "bookmakers": [
        {
            "key": "fanduel",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over",  "description": "LeBron James", "price": -115, "point": 27.5},
                        {"name": "Under", "description": "LeBron James", "price": -105, "point": 27.5},
                    ],
                }
            ],
        },
        {
            "key": "draftkings",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over",  "description": "LeBron James", "price": -105, "point": 27.5},
                        {"name": "Under", "description": "LeBron James", "price": -115, "point": 27.5},
                    ],
                }
            ],
        },
    ]
}

FAKE_RESPONSE_UNSUPPORTED_MARKET = {
    "bookmakers": [
        {
            "key": "fanduel",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over",  "description": "LeBron James", "price": -110, "point": 27.5},
                        {"name": "Under", "description": "LeBron James", "price": -110, "point": 27.5},
                    ],
                },
                {
                    "key": "player_steals",   # not supported
                    "outcomes": [
                        {"name": "Over",  "description": "LeBron James", "price": -120, "point": 1.5},
                        {"name": "Under", "description": "LeBron James", "price": +100, "point": 1.5},
                    ],
                },
            ],
        }
    ]
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _mock_get(fake_json: dict):
    """Return a mock requests.get whose .json() returns fake_json."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_json
    mock_resp.raise_for_status.return_value = None
    return MagicMock(return_value=mock_resp)


def test_parse_props_returns_canonical_dicts():
    client = PlayerPropsClient(api_key="test-key")
    with patch("alpha.data.ingestion.player_props.requests.get", _mock_get(FAKE_RESPONSE)):
        props = client.fetch_game_props("event123", "Los Angeles Lakers", "Boston Celtics")

    assert len(props) == 2
    required_fields = {"event_id", "home_team", "away_team", "player", "market", "line",
                       "over_odds", "under_odds", "bookmaker"}
    for prop in props:
        assert required_fields == required_fields & prop.keys()
        assert prop["event_id"] == "event123"
        assert prop["home_team"] == "Los Angeles Lakers"
        assert prop["away_team"] == "Boston Celtics"
        assert prop["market"] == "player_points"

    players = {p["player"] for p in props}
    assert players == {"LeBron James", "Anthony Davis"}


def test_no_api_key_returns_empty():
    client = PlayerPropsClient(api_key="")
    result = client.fetch_game_props("event123", "Lakers", "Celtics")
    assert result == []


def test_http_error_returns_empty():
    client = PlayerPropsClient(api_key="test-key")
    import requests as req
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    http_error = req.exceptions.HTTPError(response=mock_resp)
    mock_get = MagicMock(side_effect=http_error)
    with patch("alpha.data.ingestion.player_props.requests.get", mock_get):
        result = client.fetch_game_props("event123", "Lakers", "Celtics")
    assert result == []


def test_markets_filtered_to_supported():
    client = PlayerPropsClient(api_key="test-key")
    with patch("alpha.data.ingestion.player_props.requests.get",
               _mock_get(FAKE_RESPONSE_UNSUPPORTED_MARKET)):
        props = client.fetch_game_props("event123", "Lakers", "Celtics")

    # Only player_points should appear; player_steals must be excluded
    markets = {p["market"] for p in props}
    assert "player_steals" not in markets
    assert "player_points" in markets
    assert len(props) == 1


def test_deduplication_keeps_best_over_odds():
    """Two bookmakers offer the same player/market — keep the one with higher over_odds."""
    client = PlayerPropsClient(api_key="test-key")
    with patch("alpha.data.ingestion.player_props.requests.get",
               _mock_get(FAKE_RESPONSE_TWO_BOOKS)):
        props = client.fetch_game_props("event123", "Lakers", "Celtics")

    assert len(props) == 1
    assert props[0]["player"] == "LeBron James"
    # DraftKings offers -105 over vs FanDuel -115 — -105 is better (higher)
    assert props[0]["over_odds"] == -105
    assert props[0]["bookmaker"] == "draftkings"
