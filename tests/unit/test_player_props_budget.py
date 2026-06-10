"""Stage 1 tests: line-aware prop records, aggregation, and budget-first cache."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from alpha.data.ingestion.player_props import (
    DEFAULT_MARKETS,
    PlayerPropsClient,
    aggregate_prop_lines,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# FanDuel: Over 25.5 -110 | DraftKings: Over 26.5 +105 — different products.
RESP_ALT_LINES = {
    "commence_time": "2026-06-10T23:00:00Z",
    "bookmakers": [
        {
            "key": "fanduel",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over", "description": "LeBron James", "price": -110, "point": 25.5},
                        {"name": "Under", "description": "LeBron James", "price": -110, "point": 25.5},
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
                        {"name": "Over", "description": "LeBron James", "price": 105, "point": 26.5},
                        {"name": "Under", "description": "LeBron James", "price": -125, "point": 26.5},
                    ],
                }
            ],
        },
    ],
}

# Same line at three books; best over and best under at DIFFERENT books.
RESP_SAME_LINE_THREE_BOOKS = {
    "bookmakers": [
        {
            "key": "fanduel",
            "markets": [{
                "key": "player_points",
                "outcomes": [
                    {"name": "Over", "description": "LeBron James", "price": -115, "point": 27.5},
                    {"name": "Under", "description": "LeBron James", "price": -105, "point": 27.5},
                ],
            }],
        },
        {
            "key": "draftkings",
            "markets": [{
                "key": "player_points",
                "outcomes": [
                    {"name": "Over", "description": "LeBron James", "price": -105, "point": 27.5},
                    {"name": "Under", "description": "LeBron James", "price": -115, "point": 27.5},
                ],
            }],
        },
        {
            "key": "betmgm",
            "markets": [{
                "key": "player_points",
                "outcomes": [
                    {"name": "Over", "description": "LeBron James", "price": -110, "point": 27.5},
                    {"name": "Under", "description": "LeBron James", "price": -100, "point": 27.5},
                ],
            }],
        },
    ],
}


def _mock_get(fake_json: dict, headers: dict | None = None):
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_json
    mock_resp.raise_for_status.return_value = None
    mock_resp.headers = headers or {}
    return MagicMock(return_value=mock_resp)


GAMES = [
    {"event_id": "evt1", "home_team": "Los Angeles Lakers",
     "away_team": "Boston Celtics", "commence_time": "2026-06-10T23:00:00Z"},
]


# ---------------------------------------------------------------------------
# Line preservation + aggregation
# ---------------------------------------------------------------------------

def test_different_lines_are_preserved():
    """Over 25.5 and Over 26.5 are different products — both must survive."""
    client = PlayerPropsClient(api_key="k", cache_dir=None)
    with patch("alpha.data.ingestion.player_props.requests.get", _mock_get(RESP_ALT_LINES)):
        props = client.fetch_game_props("evt1", "Lakers", "Celtics")

    lines = sorted(p["line"] for p in props)
    assert lines == [25.5, 26.5]
    by_line = {p["line"]: p for p in props}
    assert by_line[25.5]["bookmaker"] == "fanduel"
    assert by_line[25.5]["over_odds"] == -110
    assert by_line[26.5]["bookmaker"] == "draftkings"
    assert by_line[26.5]["over_odds"] == 105


def test_same_line_multiple_books_aggregated():
    """Same line across books → one record with best/median aggregates."""
    client = PlayerPropsClient(api_key="k", cache_dir=None)
    with patch("alpha.data.ingestion.player_props.requests.get",
               _mock_get(RESP_SAME_LINE_THREE_BOOKS)):
        props = client.fetch_game_props("evt1", "Lakers", "Celtics")

    assert len(props) == 1
    p = props[0]
    assert p["num_books"] == 3
    assert p["best_over_odds"] == -105
    assert p["best_over_book"] == "draftkings"
    # Median of (-115, -105, -110) in implied-prob space is -110.
    assert p["median_over_odds"] == -110


def test_best_over_and_under_from_different_books():
    client = PlayerPropsClient(api_key="k", cache_dir=None)
    with patch("alpha.data.ingestion.player_props.requests.get",
               _mock_get(RESP_SAME_LINE_THREE_BOOKS)):
        props = client.fetch_game_props("evt1", "Lakers", "Celtics")

    p = props[0]
    assert p["best_over_book"] == "draftkings"
    assert p["best_under_book"] == "betmgm"
    assert p["best_under_odds"] == -100
    # Back-compat pair stays internally consistent (both from best-over book).
    assert p["over_odds"] == -105
    assert p["under_odds"] == -115


def test_raw_records_keyed_by_event_player_market_line_book():
    client = PlayerPropsClient(api_key="k", cache_dir=None)
    with patch("alpha.data.ingestion.player_props.requests.get", _mock_get(RESP_ALT_LINES)):
        raw = client.fetch_game_props_raw("evt1", "Lakers", "Celtics")

    assert len(raw) == 2
    for rec in raw:
        for field in ("event_id", "player", "market", "line", "bookmaker",
                      "over_odds", "under_odds", "fetched_at_utc", "commence_time"):
            assert field in rec
    assert raw[0]["commence_time"] == "2026-06-10T23:00:00Z"


def test_aggregate_prop_lines_groups_across_events():
    raw = [
        {"event_id": "e1", "player": "A", "market": "player_points", "line": 20.5,
         "over_odds": -110, "under_odds": -110, "bookmaker": "fd",
         "home_team": "H", "away_team": "A2", "fetched_at_utc": "t", "commence_time": "c"},
        {"event_id": "e2", "player": "A", "market": "player_points", "line": 20.5,
         "over_odds": -120, "under_odds": -100, "bookmaker": "fd",
         "home_team": "H2", "away_team": "A3", "fetched_at_utc": "t", "commence_time": "c"},
    ]
    out = aggregate_prop_lines(raw)
    assert len(out) == 2  # same player/market/line but different events


# ---------------------------------------------------------------------------
# Budget cache behavior
# ---------------------------------------------------------------------------

def test_daily_cache_prevents_duplicate_paid_calls(tmp_path):
    client = PlayerPropsClient(api_key="k", cache_dir=tmp_path)
    mock = _mock_get(RESP_ALT_LINES)
    with patch("alpha.data.ingestion.player_props.requests.get", mock):
        first = client.fetch_all_game_props(GAMES)
        second = client.fetch_all_game_props(GAMES)

    assert mock.call_count == 1  # second call served from cache
    assert first == second
    assert len(first) == 2


def test_force_refresh_refetches(tmp_path):
    client = PlayerPropsClient(api_key="k", cache_dir=tmp_path)
    mock = _mock_get(RESP_ALT_LINES)
    with patch("alpha.data.ingestion.player_props.requests.get", mock):
        client.fetch_all_game_props(GAMES)
        client.fetch_all_game_props(GAMES, force_refresh=True)

    assert mock.call_count == 2
    cache_files = list(tmp_path.glob("props_*.json"))
    meta = json.loads(cache_files[0].read_text())["meta"]
    assert meta["refresh_mode"] == "force_full"
    assert meta["paid_fetch_count"] == 2


def test_selected_event_refresh_only_requests_selected(tmp_path):
    games = GAMES + [
        {"event_id": "evt2", "home_team": "Denver Nuggets",
         "away_team": "Miami Heat", "commence_time": "2026-06-11T01:00:00Z"},
    ]
    client = PlayerPropsClient(api_key="k", cache_dir=tmp_path)
    mock = _mock_get(RESP_ALT_LINES)
    with patch("alpha.data.ingestion.player_props.requests.get", mock):
        client.fetch_all_game_props(games)          # 2 paid calls (one per event)
        assert mock.call_count == 2
        client.fetch_all_game_props(
            games, force_refresh=True, selected_event_ids=["evt2"]
        )

    # Selected refresh adds exactly ONE more request, only for evt2.
    assert mock.call_count == 3
    requested_url = mock.call_args[0][0]
    assert "evt2" in requested_url

    cache_files = list(tmp_path.glob("props_*.json"))
    payload = json.loads(cache_files[0].read_text())
    assert payload["meta"]["refresh_mode"] == "force_selected"
    # evt1 records were kept, evt2 records replaced.
    events_in_raw = {r["event_id"] for r in payload["raw"]}
    assert events_in_raw == {"evt1", "evt2"}


def test_quota_headers_recorded(tmp_path):
    headers = {
        "x-requests-remaining": "412",
        "x-requests-used": "88",
        "x-requests-last": "5",
    }
    client = PlayerPropsClient(api_key="k", cache_dir=tmp_path)
    with patch("alpha.data.ingestion.player_props.requests.get",
               _mock_get(RESP_ALT_LINES, headers=headers)):
        client.fetch_all_game_props(GAMES)

    assert client.last_quota == {
        "credits_last": 5.0, "credits_used": 88.0, "credits_remaining": 412.0,
    }
    cache_files = list(tmp_path.glob("props_*.json"))
    meta = json.loads(cache_files[0].read_text())["meta"]
    assert meta["credits_remaining"] == 412.0
    assert meta["credits_used"] == 88.0
    assert meta["credits_last"] == 5.0
    assert meta["fetched_at_utc"]


# ---------------------------------------------------------------------------
# Market configuration
# ---------------------------------------------------------------------------

def test_player_threes_disabled_by_default():
    client = PlayerPropsClient(api_key="k", cache_dir=None)
    assert client.markets == DEFAULT_MARKETS
    assert "player_threes" not in client.markets

    resp_threes = {
        "bookmakers": [{
            "key": "fanduel",
            "markets": [{
                "key": "player_threes",
                "outcomes": [
                    {"name": "Over", "description": "Stephen Curry", "price": -110, "point": 4.5},
                    {"name": "Under", "description": "Stephen Curry", "price": -110, "point": 4.5},
                ],
            }],
        }],
    }
    with patch("alpha.data.ingestion.player_props.requests.get", _mock_get(resp_threes)):
        props = client.fetch_game_props("evt1", "Warriors", "Lakers")
    assert props == []


def test_player_threes_can_be_enabled_via_config():
    client = PlayerPropsClient(
        api_key="k", cache_dir=None,
        markets=DEFAULT_MARKETS + ["player_threes"],
    )
    assert "player_threes" in client.markets

    mock = _mock_get({"bookmakers": []})
    with patch("alpha.data.ingestion.player_props.requests.get", mock):
        client.fetch_game_props("evt1", "Warriors", "Lakers")
    assert "player_threes" in mock.call_args[1]["params"]["markets"]


def test_unsupported_market_is_rejected():
    client = PlayerPropsClient(api_key="k", cache_dir=None,
                               markets=["player_points", "player_tunnels"])
    assert client.markets == ["player_points"]


def test_legacy_list_cache_still_readable(tmp_path):
    """Pre-v2 cache files were a bare list — they must still be served."""
    from datetime import date
    legacy = [{"player": "X", "market": "player_points", "line": 10.5}]
    (tmp_path / f"props_{date.today()}.json").write_text(json.dumps(legacy))
    client = PlayerPropsClient(api_key="k", cache_dir=tmp_path)
    with patch("alpha.data.ingestion.player_props.requests.get") as mock:
        props = client.fetch_all_game_props(GAMES)
    mock.assert_not_called()
    assert props == legacy
