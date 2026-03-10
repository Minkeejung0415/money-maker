"""
NBA injury + player availability ingestion.

Data sources:
  - NBA CDN scoreboard  → today's game IDs
  - NBA CDN boxscore    → ACTIVE / INACTIVE per player per game
  - nba_api             → per-player season stats (PPG, RPG, APG, MIN)

Flow:
  get_team_injury_impact() → {team_name: {out: [...], pts_lost, reb_lost, ast_lost, min_lost}}

These deltas are subtracted from team season averages before feeding XGBoost,
so the model sees a realistic lineup instead of a full-strength roster.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_NBA_CDN = "https://cdn.nba.com/static/json/liveData"
_TRICODE_TO_FULL: dict[str, str] = {
    "ATL": "Atlanta Hawks",        "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",        "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",        "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",     "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",      "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",      "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",      "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder","ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",   "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers","SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",            "WAS": "Washington Wizards",
}


def _get(url: str, timeout: int = 10) -> dict | None:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.debug("NBA CDN request failed %s: %s", url, exc)
        return None


def get_today_game_ids() -> list[dict]:
    """Return list of {game_id, home_tricode, away_tricode} for today's games."""
    data = _get(f"{_NBA_CDN}/scoreboard/todaysScoreboard_00.json")
    if not data:
        return []
    games = []
    for g in data.get("scoreboard", {}).get("games", []):
        games.append({
            "game_id": g["gameId"],
            "home": _TRICODE_TO_FULL.get(g["homeTeam"]["teamTricode"], g["homeTeam"]["teamTricode"]),
            "away": _TRICODE_TO_FULL.get(g["awayTeam"]["teamTricode"], g["awayTeam"]["teamTricode"]),
            "home_tricode": g["homeTeam"]["teamTricode"],
            "away_tricode": g["awayTeam"]["teamTricode"],
        })
    return games


def get_inactive_players(game_id: str) -> dict[str, list[str]]:
    """
    Return {team_full_name: [inactive_player_name, ...]} for a game.
    Only includes players explicitly marked INACTIVE.
    """
    data = _get(f"{_NBA_CDN}/boxscore/boxscore_{game_id}.json")
    if not data:
        return {}

    result: dict[str, list[str]] = {}
    game = data.get("game", {})
    for side in ("homeTeam", "awayTeam"):
        team = game.get(side, {})
        tricode = team.get("teamTricode", "")
        full_name = _TRICODE_TO_FULL.get(tricode, tricode)
        inactive = [
            p["name"] for p in team.get("players", [])
            if p.get("status", "").upper() == "INACTIVE"
        ]
        if inactive:
            result[full_name] = inactive
    return result


def get_player_stats_map(season: str = "2025-26") -> dict[str, dict]:
    """
    Fetch per-game stats for all players via nba_api.
    Returns {player_name: {pts, reb, ast, min, team_abbr}}.
    Cached in-process (call once per run).
    """
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats  # noqa: PLC0415
        df = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            per_mode_detailed="PerGame",
            timeout=30,
        ).get_data_frames()[0]
        result: dict[str, dict] = {}
        for _, row in df.iterrows():
            result[row["PLAYER_NAME"]] = {
                "pts": float(row["PTS"]),
                "reb": float(row["REB"]),
                "ast": float(row["AST"]),
                "min": float(row["MIN"]),
                "team": str(row["TEAM_ABBREVIATION"]),
            }
        return result
    except Exception as exc:
        logger.warning("Could not fetch player stats: %s", exc)
        return {}


def get_team_injury_impact(season: str = "2025-26") -> dict[str, dict]:
    """
    Main entry point. Returns per-team injury impact dict:
    {
        "Boston Celtics": {
            "out": [{"name": "Jayson Tatum", "pts": 27.1, "reb": 8.1, "ast": 4.9}],
            "pts_lost": 27.1,
            "reb_lost": 8.1,
            "ast_lost": 4.9,
            "min_lost": 34.2,
        },
        ...
    }
    Returns {} if no games found or all players active.
    """
    game_ids = get_today_game_ids()
    if not game_ids:
        logger.info("No games found in NBA CDN scoreboard — injury adjustment skipped")
        return {}

    player_stats = get_player_stats_map(season)
    if not player_stats:
        logger.warning("Player stats unavailable — injury adjustment skipped")
        return {}

    impact: dict[str, dict] = {}

    for game in game_ids:
        inactive_map = get_inactive_players(game["game_id"])
        for team_name, inactive_players in inactive_map.items():
            out_details = []
            for name in inactive_players:
                stats = player_stats.get(name)
                if stats is None:
                    # Try fuzzy match (handle name format differences)
                    stats = _fuzzy_match_player(name, player_stats)
                if stats:
                    out_details.append({"name": name, **stats})
                else:
                    out_details.append({"name": name, "pts": 0, "reb": 0, "ast": 0, "min": 0})

            impact[team_name] = {
                "out": out_details,
                "pts_lost": round(sum(p["pts"] for p in out_details), 2),
                "reb_lost": round(sum(p["reb"] for p in out_details), 2),
                "ast_lost": round(sum(p["ast"] for p in out_details), 2),
                "min_lost": round(sum(p["min"] for p in out_details), 2),
            }

    return impact


def _fuzzy_match_player(name: str, stats_map: dict) -> dict | None:
    """Try last-name match as fallback for name format differences."""
    last = name.split()[-1].lower()
    for key, val in stats_map.items():
        if key.split()[-1].lower() == last:
            return val
    return None
