"""Tests for the free MLB StatsAPI schedule + probable pitchers adapter."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from alpha.data.ingestion.mlb_schedule import MLBScheduleClient

DATE = "2026-06-11"


def _statsapi_game(
    game_pk=777001,
    home_pp=("Gerrit Cole", 543037),
    away_pp=("Kevin Gausman", 592332),
    double_header="N",
    game_number=1,
):
    def pp(entry):
        if entry is None:
            return {}
        name, pid = entry
        return {"probablePitcher": {"id": pid, "fullName": name}}

    return {
        "gamePk": game_pk,
        "gameDate": "2026-06-11T23:05:00Z",
        "officialDate": DATE,
        "doubleHeader": double_header,
        "gameNumber": game_number,
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "venue": {"name": "Yankee Stadium"},
        "teams": {
            "home": {"team": {"name": "New York Yankees"}, **pp(home_pp)},
            "away": {"team": {"name": "Toronto Blue Jays"}, **pp(away_pp)},
        },
    }


def _response(games):
    resp = MagicMock()
    resp.json.return_value = {"dates": [{"date": DATE, "games": games}]}
    resp.raise_for_status.return_value = None
    return resp


def _client(tmp_path, games, ttl=900):
    session = MagicMock()
    session.get.return_value = _response(games)
    return MLBScheduleClient(
        cache_dir=tmp_path, probables_ttl_seconds=ttl, session=session
    ), session


def test_confirmed_pitchers_parsed():
    client, _ = _client(None, [])
    parsed = client._parse_game(_statsapi_game(), DATE)
    assert parsed["event_id"] == "mlb-statsapi-777001"
    assert parsed["statsapi_game_id"] == 777001
    assert parsed["probable_pitcher_home"] == "Gerrit Cole"
    assert parsed["probable_pitcher_away_id"] == 592332
    assert parsed["probable_pitchers_confirmed"] is True
    assert parsed["venue"] == "Yankee Stadium"
    assert parsed["doubleheader_flag"] is False


def test_one_missing_pitcher_not_confirmed(tmp_path):
    client, _ = _client(tmp_path, [_statsapi_game(home_pp=None)])
    games = client.fetch_schedule(DATE)
    assert len(games) == 1
    assert games[0]["probable_pitcher_home"] is None
    assert games[0]["probable_pitcher_home_id"] is None
    assert games[0]["probable_pitcher_away"] == "Kevin Gausman"
    assert games[0]["probable_pitchers_confirmed"] is False


def test_both_missing_pitchers_not_confirmed(tmp_path):
    client, _ = _client(tmp_path, [_statsapi_game(home_pp=None, away_pp=None)])
    games = client.fetch_schedule(DATE)
    assert games[0]["probable_pitchers_confirmed"] is False
    assert games[0]["probable_pitcher_home"] is None
    assert games[0]["probable_pitcher_away"] is None


def test_pitcher_change_detected_and_logged(tmp_path, caplog):
    client, session = _client(tmp_path, [_statsapi_game()], ttl=0)  # ttl=0 => always refetch
    client.fetch_schedule(DATE)
    assert client.last_pitcher_changes == []

    session.get.return_value = _response(
        [_statsapi_game(home_pp=("Bullpen Day", 600000))]
    )
    with caplog.at_level("WARNING"):
        client.fetch_schedule(DATE)
    assert len(client.last_pitcher_changes) == 1
    change = client.last_pitcher_changes[0]
    assert change["side"] == "home"
    assert change["old_name"] == "Gerrit Cole"
    assert change["new_name"] == "Bullpen Day"
    assert "Probable pitcher change" in caplog.text


def test_doubleheader_parsing(tmp_path):
    client, _ = _client(
        tmp_path,
        [
            _statsapi_game(game_pk=777001, double_header="S", game_number=1),
            _statsapi_game(game_pk=777002, double_header="S", game_number=2),
        ],
    )
    games = client.fetch_schedule(DATE)
    assert [g["doubleheader_flag"] for g in games] == [True, True]
    assert [g["game_number"] for g in games] == [1, 2]
    assert games[0]["event_id"] != games[1]["event_id"]


def test_cache_hit_within_ttl_skips_refetch(tmp_path):
    client, session = _client(tmp_path, [_statsapi_game()], ttl=900)
    client.fetch_schedule(DATE)
    client.fetch_schedule(DATE)
    assert session.get.call_count == 1  # second call served from fresh cache


def test_free_refresh_never_calls_paid_api(tmp_path):
    client, session = _client(tmp_path, [_statsapi_game()], ttl=0)
    for _ in range(3):
        client.fetch_schedule(DATE)
    assert session.get.call_count == 3  # free refreshes allowed
    for call in session.get.call_args_list:
        url = call.args[0] if call.args else call.kwargs.get("url", "")
        assert "statsapi.mlb.com" in url
        assert "the-odds-api.com" not in url
        params = call.kwargs.get("params", {})
        assert "apiKey" not in params  # no paid credentials anywhere


def test_network_failure_falls_back_to_stale_cache(tmp_path):
    client, session = _client(tmp_path, [_statsapi_game()], ttl=0)
    games = client.fetch_schedule(DATE)
    assert len(games) == 1
    session.get.side_effect = ConnectionError("down")
    stale = client.fetch_schedule(DATE)
    assert stale == games


def test_cache_separate_from_paid_odds(tmp_path):
    client, _ = _client(tmp_path, [_statsapi_game()])
    client.fetch_schedule(DATE)
    cache_file = tmp_path / f"schedule_{DATE}.json"
    assert cache_file.exists()
    payload = json.loads(cache_file.read_text())
    assert payload["meta"]["source"] == "mlb_statsapi_free"
    assert "paid_fetch_count" not in payload.get("meta", {})


def test_empty_slate_returns_empty(tmp_path):
    client, _ = _client(tmp_path, [])
    assert client.fetch_schedule(DATE) == []
