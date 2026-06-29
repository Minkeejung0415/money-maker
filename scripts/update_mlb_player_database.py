"""Update the local MLB player-stat database from CSV-style inputs or MLB Stats API."""
from __future__ import annotations

import argparse
import io
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from alpha.data.ingestion.mlb_player_database import (  # noqa: E402
    load_database_snapshot,
    normalize_absence_rows,
    normalize_batter_rows,
    normalize_bullpen_rows,
    normalize_lineup_rows,
    normalize_pitcher_rows,
    read_rows_csv,
    update_database_snapshot,
    write_json,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update local MLB player database from CSV inputs.")
    parser.add_argument("--date", required=True, help="Import date in YYYY-MM-DD format")
    parser.add_argument("--database", default="data/mlb/player_database/mlb_player_database.json")
    parser.add_argument("--batters-csv")
    parser.add_argument("--pitchers-csv")
    parser.add_argument("--bullpen-csv")
    parser.add_argument("--lineups-csv")
    parser.add_argument("--absences-csv")
    parser.add_argument("--source", default="local_csv")
    parser.add_argument(
        "--online-statsapi",
        action="store_true",
        help="Fetch season player stats and general lineups from MLB Stats API",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="MLB season for online stats (default: year from --date)",
    )
    parser.add_argument(
        "--lineup-size",
        type=int,
        default=9,
        help="Number of top PA batters to use as each team's general lineup",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    database_path = Path(args.database)
    if not database_path.is_absolute():
        database_path = ROOT / database_path

    snapshot = load_database_snapshot(database_path)
    online = _fetch_online_statsapi(args.date, args.season, args.lineup_size) if args.online_statsapi else {
        "batters": [],
        "pitchers": [],
        "bullpen": [],
        "lineups": [],
        "absences": [],
    }
    source = "mlb_statsapi_general_lineup" if args.online_statsapi else args.source

    updated = update_database_snapshot(
        snapshot,
        batters=normalize_batter_rows(
            [*online["batters"], *_read_optional(args.batters_csv)],
            source=source,
            as_of=args.date,
        ),
        pitchers=normalize_pitcher_rows(
            [*online["pitchers"], *_read_optional(args.pitchers_csv)],
            source=source,
            as_of=args.date,
        ),
        bullpen=normalize_bullpen_rows(
            [*online["bullpen"], *_read_optional(args.bullpen_csv)],
            source=source,
            as_of=args.date,
        ),
        lineups=normalize_lineup_rows(
            [*online["lineups"], *_read_optional(args.lineups_csv)],
            source=source,
            as_of=args.date,
        ),
        absences=normalize_absence_rows(
            [*online["absences"], *_read_optional(args.absences_csv)],
            source=source,
            as_of=args.date,
        ),
        source=source,
        import_date=args.date,
    )
    write_json(database_path, updated)
    counts = {name: len(rows) for name, rows in updated["components"].items()}
    print(f"Updated MLB player database: {database_path}")
    print("Rows: " + ", ".join(f"{name}={count}" for name, count in counts.items()))


def _read_optional(path: str | None) -> list[dict]:
    if not path:
        return []
    input_path = Path(path)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    return read_rows_csv(input_path)


def _fetch_online_statsapi(target_date: str, season: int | None, lineup_size: int) -> dict[str, list[dict]]:
    import requests  # noqa: PLC0415

    selected_season = season or date.fromisoformat(target_date).year
    as_of = (date.fromisoformat(target_date) - timedelta(days=1)).isoformat()
    hitting_splits = _statsapi_splits(requests, selected_season, "hitting")
    pitching_splits = _statsapi_splits(requests, selected_season, "pitching")
    games = _statsapi_schedule_games(requests, target_date)

    batters = [_batter_row(split, as_of) for split in hitting_splits]
    pitchers = [_pitcher_row(split, as_of) for split in pitching_splits]
    bullpen = _bullpen_rows(pitching_splits, as_of)
    lineups = _general_lineup_rows(hitting_splits, games, target_date, lineup_size)
    return {
        "batters": [row for row in batters if row],
        "pitchers": [row for row in pitchers if row],
        "bullpen": bullpen,
        "lineups": lineups,
        "absences": [],
    }


def _statsapi_splits(requests_module, season: int, group: str) -> list[dict]:
    response = requests_module.get(
        "https://statsapi.mlb.com/api/v1/stats",
        params={
            "stats": "season",
            "group": group,
            "playerPool": "ALL",
            "season": str(season),
            "sportIds": "1",
            "limit": "5000",
            "hydrate": "team",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return list((payload.get("stats") or [{}])[0].get("splits") or [])


def _statsapi_schedule_games(requests_module, target_date: str) -> list[dict]:
    response = requests_module.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": "1", "date": target_date, "hydrate": "probablePitcher"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    games: list[dict] = []
    for day in payload.get("dates") or []:
        games.extend(day.get("games") or [])
    return games


def _team_name(split: dict) -> str:
    return str((split.get("team") or {}).get("name") or "").strip()


def _player_name(split: dict) -> str:
    return str((split.get("player") or {}).get("fullName") or "").strip()


def _player_id(split: dict) -> str:
    value = (split.get("player") or {}).get("id")
    return "" if value in (None, "") else str(value)


def _num(stat: dict, key: str, default: float = 0.0) -> float:
    value = stat.get(key, default)
    if value in (None, "", ".---", "-.--"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _batter_row(split: dict, as_of: str) -> dict:
    stat = split.get("stat") or {}
    name = _player_name(split)
    team = _team_name(split)
    if not name or not team:
        return {}
    return {
        "player_id": _player_id(split),
        "player": name,
        "team": team,
        "date": as_of,
        "h": _num(stat, "hits"),
        "ab": _num(stat, "atBats"),
        "bb": _num(stat, "baseOnBalls"),
        "hbp": _num(stat, "hitByPitch"),
        "sf": _num(stat, "sacFlies"),
        "tb": _num(stat, "totalBases"),
        "hr": _num(stat, "homeRuns"),
        "rbi": _num(stat, "rbi"),
        "pa": _num(stat, "plateAppearances"),
    }


def _pitcher_row(split: dict, as_of: str) -> dict:
    stat = split.get("stat") or {}
    name = _player_name(split)
    team = _team_name(split)
    if not name or not team:
        return {}
    return {
        "player_id": _player_id(split),
        "player": name,
        "team": team,
        "date": as_of,
        "er": _num(stat, "earnedRuns"),
        "ip": str(stat.get("inningsPitched") or "0.0"),
        "r": _num(stat, "runs"),
        "h": _num(stat, "hits"),
        "bb": _num(stat, "baseOnBalls"),
        "so": _num(stat, "strikeOuts"),
        "hr": _num(stat, "homeRuns"),
        "pit": _num(stat, "numberOfPitches"),
        "bf": _num(stat, "battersFaced"),
    }


def _bullpen_rows(pitching_splits: list[dict], as_of: str) -> list[dict]:
    totals: dict[str, defaultdict[str, float]] = {}
    for split in pitching_splits:
        team = _team_name(split)
        stat = split.get("stat") or {}
        if not team:
            continue
        starts = _num(stat, "gamesStarted")
        if starts > 0:
            continue
        bucket = totals.setdefault(team, defaultdict(float))
        bucket["er"] += _num(stat, "earnedRuns")
        bucket["ip"] += _num(stat, "outs") / 3.0
        bucket["bb"] += _num(stat, "baseOnBalls")
        bucket["so"] += _num(stat, "strikeOuts")
        bucket["hr"] += _num(stat, "homeRuns")
        bucket["pit"] += _num(stat, "numberOfPitches")
    return [
        {
            "team": team,
            "date": as_of,
            "er": values["er"],
            "ip": f"{values['ip']:.1f}",
            "bb": values["bb"],
            "so": values["so"],
            "hr": values["hr"],
            "pit": values["pit"],
        }
        for team, values in totals.items()
    ]


def _general_lineup_rows(
    hitting_splits: list[dict],
    games: list[dict],
    target_date: str,
    lineup_size: int,
) -> list[dict]:
    by_team: dict[str, list[dict]] = defaultdict(list)
    for split in hitting_splits:
        team = _team_name(split)
        stat = split.get("stat") or {}
        if not team:
            continue
        by_team[team].append({
            "player_id": _player_id(split),
            "player": _player_name(split),
            "team": team,
            "pa": _num(stat, "plateAppearances"),
        })

    rows: list[dict] = []
    for game in games:
        game_id = str(game.get("gamePk") or "")
        teams = game.get("teams") or {}
        for side in ("home", "away"):
            team = ((teams.get(side) or {}).get("team") or {}).get("name") or ""
            for slot, player in enumerate(_top_lineup(by_team.get(team, []), lineup_size), start=1):
                rows.append({
                    "game_id": game_id,
                    "player_id": player.get("player_id", ""),
                    "player": player.get("player", ""),
                    "team": team,
                    "side": side,
                    "date": target_date,
                    "order": slot,
                    "confirmed": "false",
                })
    return rows


def _top_lineup(players: list[dict], lineup_size: int) -> list[dict]:
    return sorted(
        [player for player in players if player.get("player")],
        key=lambda row: float(row.get("pa") or 0.0),
        reverse=True,
    )[:lineup_size]


if __name__ == "__main__":
    main()
