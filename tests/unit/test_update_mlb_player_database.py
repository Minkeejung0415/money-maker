from __future__ import annotations

from scripts.update_mlb_player_database import _general_lineup_rows, _top_lineup


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
