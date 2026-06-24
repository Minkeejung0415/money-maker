from __future__ import annotations

from alpha.data.ingestion.mlb_player_data import (
    build_player_id_map,
    espn_team_id_duplicates,
    fetch_day_of_player_context,
    normalize_games,
    normalize_player_slots,
    report_unmatched_players,
)
from alpha.engines.sports.mlb_training import FEATURE_NAMES


def test_normalize_games_preserves_missing_starters_and_doubleheader():
    rows = normalize_games([
        {
            "game_id": "2",
            "game_date": "2026-04-01",
            "home_name": "New York Yankees",
            "away_name": "Boston Red Sox",
            "status": "Scheduled",
            "doubleheader": True,
            "game_number": "2",
        },
        {
            "game_id": "1",
            "game_date": "2026-04-01",
            "home_name": "Toronto Blue Jays",
            "away_name": "Tampa Bay Rays",
            "status": "Final",
            "home_score": 5,
            "away_score": 3,
            "home_probable_pitcher": "Kevin Gausman",
            "away_probable_pitcher": "Zach Eflin",
            "venue_name": "Rogers Centre",
        },
    ])

    assert [row["game_id"] for row in rows] == ["1", "2"]
    assert rows[0]["home_win"] == 1
    assert rows[0]["home_starter_name"] == "Kevin Gausman"
    assert rows[1]["doubleheader"] is True
    assert rows[1]["game_number"] == 2
    assert "missing_home_starter" in rows[1]["missing_reason"]
    assert "missing_away_starter" in rows[1]["missing_reason"]


def test_normalize_games_dedupes_by_game_id_and_prefers_confirmed():
    rows = normalize_games([
        {
            "gamePk": 100,
            "gameDate": "2026-04-01T18:00:00Z",
            "home_name": "A",
            "away_name": "B",
            "status": "Scheduled",
        },
        {
            "gamePk": 100,
            "gameDate": "2026-04-01T18:00:00Z",
            "home_name": "A",
            "away_name": "B",
            "status": "Final",
            "home_score": 1,
            "away_score": 2,
        },
    ])

    assert len(rows) == 1
    assert rows[0]["confirmed"] is True
    assert rows[0]["home_win"] == 0


def test_normalize_player_slots_requires_game_identity_and_keeps_uncertainty():
    slots = normalize_player_slots([
        {
            "team": "New York Yankees",
            "side": "home",
            "player_id": 592450,
            "player_name": "Aaron Judge",
            "batting_order": "2",
            "position": "RF",
            "confirmed": True,
        },
        {
            "team": "New York Yankees",
            "side": "home",
            "batting_order": 9,
            "confirmed": False,
        },
        {"player_name": "No Game"},
    ], game_id="game-1")

    assert len(slots) == 3
    assert slots[0]["player_name"] == "Aaron Judge"
    assert slots[0]["batting_order"] == 2
    assert slots[1]["confirmed"] is False
    assert slots[1]["missing_reason"] == "missing_player_identity"
    assert slots[2]["game_id"] == "game-1"
    assert normalize_player_slots([{"player_name": "No Game"}]) == []


def test_build_player_id_map_and_unmatched_report():
    id_map = build_player_id_map([
        {
            "player_name": "Aaron Judge",
            "key_mlbam": "592450",
            "key_retro": "judga001",
            "key_bbref": "judgeaa01",
            "key_fangraphs": "15640",
        }
    ])
    slots = normalize_player_slots([
        {"game_id": "1", "team": "NYY", "side": "home", "player_id": "592450", "player_name": "Aaron Judge"},
        {"game_id": "1", "team": "BOS", "side": "away", "player_id": "999", "player_name": "Unknown Player"},
    ])

    assert id_map["key_mlbam:592450"]["player_name"] == "Aaron Judge"
    assert id_map["name:aaron judge"]["retrosheet_id"] == "judga001"
    unmatched = report_unmatched_players(slots, id_map)
    assert len(unmatched) == 1
    assert unmatched[0]["player_name"] == "Unknown Player"
    assert unmatched[0]["missing_reason"] == "unmatched_player_id"


def test_fetch_day_of_player_context_uses_injected_providers_without_network():
    def schedule_provider(date_str):
        assert date_str == "2026-04-01"
        return [{
            "game_id": "1",
            "game_date": date_str,
            "home_name": "New York Yankees",
            "away_name": "Boston Red Sox",
            "status": "Scheduled",
            "home_probable_pitcher": "Gerrit Cole",
        }]

    def lineup_provider(date_str, games):
        assert games[0]["game_id"] == "1"
        return [
            {"game_id": "1", "team": "New York Yankees", "side": "home", "player_id": "592450", "player_name": "Aaron Judge"},
            {"game_id": "1", "team": "Boston Red Sox", "side": "away", "player_id": "999", "player_name": "Unknown Player"},
        ]

    context = fetch_day_of_player_context(
        "2026-04-01",
        schedule_provider=schedule_provider,
        lineup_provider=lineup_provider,
        injury_provider=lambda date_str: {"New York Yankees": {"out": []}},
        id_rows=[{"player_name": "Aaron Judge", "key_mlbam": "592450"}],
    )

    assert context["date"] == "2026-04-01"
    assert len(context["games"]) == 1
    assert len(context["game_player_slots"]) == 2
    assert context["injuries"]["New York Yankees"]["out"] == []
    assert [row["player_name"] for row in context["unmatched_players"]] == ["Unknown Player"]
    assert context["errors"] == []


def test_fetch_day_of_player_context_returns_partial_context_on_provider_failure():
    def broken_provider(date_str):
        raise RuntimeError("source down")

    context = fetch_day_of_player_context(
        "2026-04-01",
        schedule_provider=broken_provider,
        lineup_provider=lambda date_str, games: [],
        injury_provider=lambda date_str: {},
    )

    assert context["games"] == []
    assert context["errors"][0]["source"] == "schedule"


def test_espn_duplicate_id_audit_exposes_fallback_risk():
    duplicates = espn_team_id_duplicates({
        "Milwaukee Brewers": 21,
        "New York Mets": 21,
        "New York Yankees": 10,
    })

    assert duplicates == {21: ["Milwaukee Brewers", "New York Mets"]}


def test_v1_3_mlb_feature_schema_is_unchanged():
    assert FEATURE_NAMES == (
        "elo_diff",
        "home_win_pct",
        "away_win_pct",
        "home_run_diff",
        "away_run_diff",
        "home_rest_days",
        "away_rest_days",
        "home_indicator",
    )
