"""Tests for the budget-aware MLB moneyline odds adapter."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from alpha.data.ingestion.mlb_odds_api import MLBOddsClient

EVENT = {
    "id": "abc123",
    "home_team": "New York Yankees",
    "away_team": "Toronto Blue Jays",
    "commence_time": "2026-06-11T23:05:00Z",
    "bookmakers": [
        {
            "key": "fanduel",
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "New York Yankees", "price": -150},
                    {"name": "Toronto Blue Jays", "price": 130},
                ],
            }],
        },
        {
            "key": "draftkings",
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "New York Yankees", "price": -140},  # best home price
                    {"name": "Toronto Blue Jays", "price": 120},
                ],
            }],
        },
        {
            "key": "betmgm",
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "New York Yankees", "price": -155},
                    {"name": "Toronto Blue Jays", "price": 135},  # best away price
                ],
            }],
        },
    ],
}


def _response(payload, headers=None):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.headers = headers or {}
    resp.raise_for_status.return_value = None
    return resp


def _client(tmp_path, **kwargs):
    return MLBOddsClient(api_key="test-key", cache_dir=tmp_path, **kwargs)


def test_daily_cache_prevents_duplicate_paid_calls(tmp_path):
    client = _client(tmp_path)
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.return_value = _response([EVENT])
        first = client.fetch_moneyline()
        second = client.fetch_moneyline()
        assert mock_get.call_count == 1  # second call served from cache
    assert len(first) == 1
    assert [g["event_id"] for g in second] == ["abc123"]


def test_budget_exhausted_returns_cache_without_paid_call(tmp_path):
    client = _client(tmp_path, max_paid_fetches_per_day=1)
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.return_value = _response([EVENT])
        client.fetch_moneyline()
    # Simulate cache hit miss by corrupting nothing: cache exists with count=1.
    cache_file = client._cache_file()
    payload = json.loads(cache_file.read_text())
    assert payload["meta"]["paid_fetch_count"] == 1
    payload["games"] = []  # cache present but empty games
    cache_file.write_text(json.dumps(payload))
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        result = client.fetch_moneyline()
        # Cache hit path: no paid request at all.
        assert mock_get.call_count == 0
    assert result == []


def test_force_refresh_bypasses_cache(tmp_path):
    client = _client(tmp_path)
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.return_value = _response([EVENT])
        client.fetch_moneyline()
        client.fetch_moneyline(force_refresh=True)
        assert mock_get.call_count == 2
    meta = json.loads(client._cache_file().read_text())["meta"]
    assert meta["refresh_mode"] == "force_full"
    assert meta["paid_fetch_count"] == 2


def test_selected_event_refresh_merges_into_cache(tmp_path):
    client = _client(tmp_path)
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.return_value = _response([EVENT])
        client.fetch_moneyline()

    updated = dict(EVENT)
    updated["bookmakers"] = [EVENT["bookmakers"][0]]  # line moved, one book
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.return_value = _response(updated)
        refreshed = client.fetch_moneyline(selected_event_ids=["abc123"])
        assert mock_get.call_count == 1
        url = mock_get.call_args.args[0]
        assert "events/abc123/odds" in url
    assert len(refreshed) == 1
    cached = json.loads(client._cache_file().read_text())
    assert cached["meta"]["refresh_mode"] == "selected_events"
    assert cached["games"][0]["num_books"] == 1


def test_first_bookmaker_is_not_automatically_best(tmp_path):
    client = _client(tmp_path)
    parsed = client._parse_event(EVENT)
    assert parsed["best_home_odds"] == -140
    assert parsed["best_home_book"] == "draftkings"
    assert parsed["best_away_odds"] == 135
    assert parsed["best_away_book"] == "betmgm"
    assert len(parsed["bookmaker_odds"]) == 3  # all books retained


def test_no_vig_consensus_uses_per_book_pairs(tmp_path):
    client = _client(tmp_path)
    parsed = client._parse_event(EVENT)
    # Median of per-book no-vig home probs; never best-price-cross-book.
    per_book = sorted(b["no_vig_home_prob"] for b in parsed["bookmaker_odds"])
    assert parsed["consensus_home_no_vig_prob"] == pytest.approx(per_book[1], abs=1e-6)
    assert (
        parsed["consensus_home_no_vig_prob"] + parsed["consensus_away_no_vig_prob"]
        == pytest.approx(1.0, abs=1e-6)
    )
    for book in parsed["bookmaker_odds"]:
        assert (
            book["no_vig_home_prob"] + book["no_vig_away_prob"]
            == pytest.approx(1.0, abs=1e-6)
        )


def test_quota_headers_recorded(tmp_path):
    client = _client(tmp_path)
    headers = {
        "x-requests-remaining": "478",
        "x-requests-used": "22",
        "x-requests-last": "1",
    }
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.return_value = _response([EVENT], headers=headers)
        client.fetch_moneyline()
    assert client.last_quota == {
        "credits_remaining": 478.0,
        "credits_used": 22.0,
        "credits_last": 1.0,
    }
    meta = json.loads(client._cache_file().read_text())["meta"]
    assert meta["credits_remaining"] == 478.0


def test_empty_books_fail_closed_no_fabricated_odds(tmp_path):
    client = _client(tmp_path)
    bare = {k: v for k, v in EVENT.items() if k != "bookmakers"}
    parsed = client._parse_event(bare)
    assert parsed["best_home_odds"] is None
    assert parsed["best_away_odds"] is None
    assert parsed["consensus_home_no_vig_prob"] is None
    assert parsed["num_books"] == 0
    assert parsed["bookmaker_odds"] == []


def test_missing_api_key_fails_closed(tmp_path):
    client = MLBOddsClient(api_key="", cache_dir=tmp_path)
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        assert client.fetch_moneyline() == []
        assert client.fetch_events() == []
        assert client.fetch_moneyline(selected_event_ids=["x"]) == []
        assert mock_get.call_count == 0


def test_http_error_fails_closed(tmp_path):
    import requests as _requests

    client = _client(tmp_path)
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.side_effect = _requests.exceptions.ConnectionError("down")
        assert client.fetch_moneyline() == []


def test_events_endpoint_is_free_slate_discovery(tmp_path):
    client = _client(tmp_path)
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.return_value = _response([{
            "id": "abc123",
            "home_team": "New York Yankees",
            "away_team": "Toronto Blue Jays",
            "commence_time": "2026-06-11T23:05:00Z",
        }])
        events = client.fetch_events()
        url = mock_get.call_args.args[0]
        assert url.endswith("/events/")
        params = mock_get.call_args.kwargs["params"]
        assert "markets" not in params  # events call carries no paid market params
    assert events[0]["event_id"] == "abc123"


def test_sport_key_is_baseball_mlb(tmp_path):
    client = _client(tmp_path)
    with patch("alpha.data.ingestion.mlb_odds_api.requests.get") as mock_get:
        mock_get.return_value = _response([EVENT])
        client.fetch_moneyline()
        url = mock_get.call_args.args[0]
    assert "baseball_mlb" in url
    assert mock_get.call_args.kwargs["params"]["markets"] == "h2h"
    assert mock_get.call_args.kwargs["params"]["regions"] == "us"
