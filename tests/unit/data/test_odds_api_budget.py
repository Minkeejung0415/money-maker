"""Stage 2/3 tests: per-book moneyline retention, consensus no-vig, budget cache."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from alpha.data.ingestion.odds_api import (
    DEFAULT_REGIONS,
    OddsAPIClient,
    american_to_implied,
    build_consensus_moneyline,
    remove_vig_pair,
)


def _book(key: str, home_price: int, away_price: int, home="Boston Celtics",
          away="Miami Heat") -> dict:
    return {
        "key": key,
        "markets": [{
            "key": "h2h",
            "outcomes": [
                {"name": home, "price": home_price},
                {"name": away, "price": away_price},
            ],
        }],
    }


def _event(books: list[dict], event_id="evt1", home="Boston Celtics",
           away="Miami Heat") -> dict:
    return {
        "id": event_id,
        "sport_key": "basketball_nba",
        "commence_time": "2026-06-10T23:00:00Z",
        "home_team": home,
        "away_team": away,
        "bookmakers": books,
    }


def _mock_get(payload, headers: dict | None = None):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    resp.headers = headers or {}
    return MagicMock(return_value=resp)


# ---------------------------------------------------------------------------
# Odds math helpers
# ---------------------------------------------------------------------------

def test_american_to_implied():
    assert american_to_implied(-110) == pytest.approx(110 / 210)
    assert american_to_implied(150) == pytest.approx(100 / 250)
    assert american_to_implied(100) == pytest.approx(0.5)


def test_remove_vig_pair():
    fair_home, fair_away = remove_vig_pair(-110, -110)
    assert fair_home == pytest.approx(0.5)
    assert fair_home + fair_away == pytest.approx(1.0)

    fair_home, fair_away = remove_vig_pair(-200, 170)
    assert fair_home > 0.6
    assert fair_home + fair_away == pytest.approx(1.0)


def test_consensus_uses_all_valid_books_median():
    books = [
        {"bookmaker": "a", "home_odds": -150, "away_odds": 130},
        {"bookmaker": "b", "home_odds": -160, "away_odds": 140},
        {"bookmaker": "c", "home_odds": -140, "away_odds": 120},
    ]
    out = build_consensus_moneyline(books)
    assert out is not None
    assert out["num_books"] == 3
    # Median book is "a" (-150/130): no-vig fair home prob.
    expected, _ = remove_vig_pair(-150, 130)
    assert out["consensus_home_prob"] == pytest.approx(expected, abs=1e-6)
    assert out["consensus_home_prob"] + out["consensus_away_prob"] == pytest.approx(1.0)


def test_consensus_fails_closed_when_no_books():
    assert build_consensus_moneyline([]) is None
    assert build_consensus_moneyline([{"bookmaker": "x"}]) is None


def test_consensus_not_built_from_cross_book_best_prices():
    """
    Consensus must remove vig per book, NOT pair best home with best away.
    Best-price pairing (-140 home from c, +140 away from b) would yield a
    fake low-vig home prob of ~0.583 vs per-book median ~0.589.
    """
    books = [
        {"bookmaker": "a", "home_odds": -150, "away_odds": 130},
        {"bookmaker": "b", "home_odds": -160, "away_odds": 140},
        {"bookmaker": "c", "home_odds": -140, "away_odds": 120},
    ]
    out = build_consensus_moneyline(books)
    fake_pair, _ = remove_vig_pair(-140, 140)
    assert out["consensus_home_prob"] != pytest.approx(fake_pair, abs=1e-4)


# ---------------------------------------------------------------------------
# Parsing: best price is not "first book"
# ---------------------------------------------------------------------------

def test_first_bookmaker_is_not_automatically_best():
    """Second book has the better home price; third has the better away price."""
    event = _event([
        _book("fanduel", -150, 125),
        _book("draftkings", -145, 120),   # best home
        _book("betmgm", -155, 135),       # best away
    ])
    client = OddsAPIClient(api_key="k", cache_dir=None)
    game = client._parse_event(event)

    assert game["home_odds"] == -145
    assert game["best_home_book"] == "draftkings"
    assert game["away_odds"] == 135
    assert game["best_away_book"] == "betmgm"


def test_all_bookmaker_pairs_retained():
    event = _event([_book("fanduel", -150, 125), _book("draftkings", -145, 120)])
    client = OddsAPIClient(api_key="k", cache_dir=None)
    game = client._parse_event(event)

    assert len(game["bookmaker_odds"]) == 2
    assert {b["bookmaker"] for b in game["bookmaker_odds"]} == {"fanduel", "draftkings"}
    assert game["num_books"] == 2
    assert game["consensus_home_prob"] is not None
    assert game["snapshot_timestamp"]
    assert game["commence_time"] == "2026-06-10T23:00:00Z"


def test_no_books_fails_closed_on_consensus():
    event = _event([])
    client = OddsAPIClient(api_key="k", cache_dir=None)
    game = client._parse_event(event)
    assert game["consensus_home_prob"] is None
    assert game["num_books"] == 0


# ---------------------------------------------------------------------------
# Regions configuration
# ---------------------------------------------------------------------------

def test_us_only_region_is_default_and_configurable():
    client = OddsAPIClient(api_key="k", cache_dir=None)
    assert client.regions == DEFAULT_REGIONS == ["us"]

    mock = _mock_get([])
    with patch("alpha.data.ingestion.odds_api.requests.get", mock):
        client.fetch_nba_games()
    assert mock.call_args[1]["params"]["regions"] == "us"

    client_eu = OddsAPIClient(api_key="k", cache_dir=None, regions=["us", "eu"])
    mock2 = _mock_get([])
    with patch("alpha.data.ingestion.odds_api.requests.get", mock2):
        client_eu.fetch_nba_games()
    assert mock2.call_args[1]["params"]["regions"] == "us,eu"


# ---------------------------------------------------------------------------
# Budget cache
# ---------------------------------------------------------------------------

def test_daily_cache_prevents_duplicate_paid_calls(tmp_path):
    client = OddsAPIClient(api_key="k", cache_dir=tmp_path)
    mock = _mock_get([_event([_book("fanduel", -150, 130)])])
    with patch("alpha.data.ingestion.odds_api.requests.get", mock):
        first = client.fetch_nba_games()
        second = client.fetch_nba_games()

    assert mock.call_count == 1
    assert first == second
    assert len(first) == 1


def test_force_refresh_refetches(tmp_path):
    client = OddsAPIClient(api_key="k", cache_dir=tmp_path)
    mock = _mock_get([_event([_book("fanduel", -150, 130)])])
    with patch("alpha.data.ingestion.odds_api.requests.get", mock):
        client.fetch_nba_games()
        client.fetch_nba_games(force_refresh=True)

    assert mock.call_count == 2
    payload = json.loads(next(tmp_path.glob("games_*.json")).read_text())
    assert payload["meta"]["refresh_mode"] == "force_full"
    assert payload["meta"]["paid_fetch_count"] == 2
    assert payload["meta"]["fetched_at_utc"]


def test_quota_headers_stored(tmp_path):
    headers = {
        "x-requests-remaining": "377",
        "x-requests-used": "123",
        "x-requests-last": "10",
    }
    client = OddsAPIClient(api_key="k", cache_dir=tmp_path)
    with patch("alpha.data.ingestion.odds_api.requests.get",
               _mock_get([_event([_book("fanduel", -150, 130)])], headers=headers)):
        client.fetch_nba_games()

    assert client.last_quota["credits_remaining"] == 377.0
    meta = json.loads(next(tmp_path.glob("games_*.json")).read_text())["meta"]
    assert meta["credits_remaining"] == 377.0
    assert meta["credits_used"] == 123.0
    assert meta["credits_last"] == 10.0


def test_legacy_list_cache_still_readable(tmp_path):
    from datetime import date
    legacy = [{"home_team": "X", "away_team": "Y", "home_odds": -110, "away_odds": -110}]
    (tmp_path / f"games_{date.today()}.json").write_text(json.dumps(legacy))
    client = OddsAPIClient(api_key="k", cache_dir=tmp_path)
    with patch("alpha.data.ingestion.odds_api.requests.get") as mock:
        games = client.fetch_nba_games()
    mock.assert_not_called()
    assert games == legacy


# ---------------------------------------------------------------------------
# Stage 3: free events endpoint
# ---------------------------------------------------------------------------

def test_fetch_events_returns_slate():
    payload = [
        {"id": "e1", "home_team": "Boston Celtics", "away_team": "Miami Heat",
         "commence_time": "2026-06-10T23:00:00Z"},
        {"id": "e2", "home_team": "Denver Nuggets", "away_team": "Utah Jazz",
         "commence_time": "2026-06-11T01:00:00Z"},
        {"id": "bad"},  # malformed — skipped
    ]
    client = OddsAPIClient(api_key="k", cache_dir=None)
    mock = _mock_get(payload)
    with patch("alpha.data.ingestion.odds_api.requests.get", mock):
        events = client.fetch_events()

    assert [e["event_id"] for e in events] == ["e1", "e2"]
    assert events[0]["commence_time"] == "2026-06-10T23:00:00Z"
    # Events endpoint must not request markets/regions (it's the free call).
    params = mock.call_args[1]["params"]
    assert "markets" not in params
    assert "regions" not in params


def test_fetch_events_no_key_returns_empty():
    client = OddsAPIClient(api_key="", cache_dir=None)
    with patch("alpha.data.ingestion.odds_api.requests.get") as mock:
        assert client.fetch_events() == []
    mock.assert_not_called()
