from __future__ import annotations

from scripts.update_mlb_player_database import (
    _drop_online_rows_for_date,
    _general_lineup_rows,
    _general_lineup_rows_from_players,
    _top_lineup,
)


def test_top_lineup_uses_highest_plate_appearances():
    players = [
        {"player": "Bench Bat", "pa": 15},
        {"player": "Everyday Bat", "pa": 120},
        {"player": "Platoon Bat", "pa": 55},
    ]

    result = _top_lineup(players, 2)

    assert [row["player"] for row in result] == ["Everyday Bat", "Platoon Bat"]


def test_general_lineup_rows_builds_home_and_away_slots():
    hitting_splits = [
        {
            "player": {"id": 1, "fullName": "Home One"},
            "team": {"name": "Home Team"},
            "stat": {"plateAppearances": 100},
        },
        {
            "player": {"id": 2, "fullName": "Home Two"},
            "team": {"name": "Home Team"},
            "stat": {"plateAppearances": 90},
        },
        {
            "player": {"id": 3, "fullName": "Away One"},
            "team": {"name": "Away Team"},
            "stat": {"plateAppearances": 110},
        },
    ]
    games = [{
        "gamePk": 123,
        "teams": {
            "home": {"team": {"name": "Home Team"}},
            "away": {"team": {"name": "Away Team"}},
        },
    }]

    rows = _general_lineup_rows(hitting_splits, games, "2026-06-29", 2)

    assert [row["player"] for row in rows] == ["Home One", "Home Two", "Away One"]
    assert rows[0]["side"] == "home"
    assert rows[-1]["side"] == "away"
    assert rows[0]["confirmed"] == "false"


def test_general_lineup_rows_from_advanced_players_uses_team_names():
    players = [
        {"player_id": "1", "player": "Home One", "team": "Home Team", "pa": 100},
        {"player_id": "2", "player": "Home Two", "team": "Home Team", "pa": 90},
        {"player_id": "3", "player": "Away One", "team": "Away Team", "pa": 110},
    ]
    games = [{
        "gamePk": 123,
        "teams": {
            "home": {"team": {"name": "Home Team"}},
            "away": {"team": {"name": "Away Team"}},
        },
    }]

    rows = _general_lineup_rows_from_players(players, games, "2026-06-29", 2)

    assert [row["player"] for row in rows] == ["Home One", "Home Two", "Away One"]
    assert rows[0]["game_id"] == "123"
    assert rows[0]["confirmed"] == "false"


def test_drop_online_rows_for_date_keeps_manual_rows():
    snapshot = {
        "components": {
            "batters": [
                {"player_name": "Old Online", "game_date": "2026-06-29", "source": "mlb_statsapi_general_lineup"},
                {"player_name": "New Online", "game_date": "2026-06-29", "source": "mlb_online_advanced"},
                {"player_name": "Manual", "game_date": "2026-06-29", "source": "local_csv"},
                {"player_name": "Other Date", "game_date": "2026-06-28", "source": "mlb_online_advanced"},
            ],
        },
    }

    result = _drop_online_rows_for_date(snapshot, "2026-06-29")

    assert [row["player_name"] for row in result["components"]["batters"]] == ["Manual", "Other Date"]
