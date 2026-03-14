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
_ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

# ESPN internal team IDs (stable, used for their injury endpoint)
_ESPN_TEAM_IDS: dict[str, int] = {
    "Atlanta Hawks": 1,        "Boston Celtics": 2,        "Brooklyn Nets": 17,
    "Charlotte Hornets": 30,   "Chicago Bulls": 4,         "Cleveland Cavaliers": 5,
    "Dallas Mavericks": 6,     "Denver Nuggets": 7,        "Detroit Pistons": 8,
    "Golden State Warriors": 9,"Houston Rockets": 10,      "Indiana Pacers": 11,
    "Los Angeles Clippers": 12,"Los Angeles Lakers": 13,   "Memphis Grizzlies": 29,
    "Miami Heat": 14,          "Milwaukee Bucks": 15,      "Minnesota Timberwolves": 16,
    "New Orleans Pelicans": 3, "New York Knicks": 18,      "Oklahoma City Thunder": 25,
    "Orlando Magic": 19,       "Philadelphia 76ers": 20,   "Phoenix Suns": 21,
    "Portland Trail Blazers": 22,"Sacramento Kings": 23,   "San Antonio Spurs": 24,
    "Toronto Raptors": 28,     "Utah Jazz": 26,            "Washington Wizards": 27,
}

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


def get_espn_out_players(team_name: str) -> list[str]:
    """
    Return list of player names confirmed OUT for *team_name* via ESPN's
    pre-game injury report.  Available hours before tip, unlike NBA CDN
    boxscore which only populates close to tip-off.

    Only returns players with status exactly "Out" (not Questionable/DTD).
    Returns [] on any failure (never raises).
    """
    espn_id = _ESPN_TEAM_IDS.get(team_name)
    if espn_id is None:
        return []
    data = _get(f"{_ESPN_API}/teams/{espn_id}/injuries")
    if not data:
        return []
    out_players: list[str] = []
    for injury in data.get("injuries", []):
        status = injury.get("status", "")
        if status.lower() == "out":
            athlete = injury.get("athlete", {})
            name = athlete.get("displayName", "")
            if name:
                out_players.append(name)
    return out_players


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

        # Supplement with ESPN pre-game injury report for teams where the
        # NBA CDN boxscore hasn't populated the inactive list yet (too early).
        for team_name in (game["home"], game["away"]):
            if team_name not in inactive_map:
                espn_out = get_espn_out_players(team_name)
                if espn_out:
                    logger.debug("ESPN injury fallback for %s: %s", team_name, espn_out)
                    inactive_map[team_name] = espn_out

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


def get_player_injury_statuses(team_names: list[str]) -> dict[str, str]:
    """
    Return {player_name: status} where status is one of:
      "OUT"          - confirmed out (will not play)
      "QUESTIONABLE" - day-to-day, may not play
      "PROBABLE"     - likely to play

    Uses ESPN injury endpoint. Only includes players with an active injury entry.
    Returns {} on any failure.
    """
    result: dict[str, str] = {}
    _QUESTIONABLE_STATUSES = {"questionable", "doubtful", "day-to-day", "dtd"}

    for team_name in team_names:
        espn_id = _ESPN_TEAM_IDS.get(team_name)
        if espn_id is None:
            continue
        data = _get(f"{_ESPN_API}/teams/{espn_id}/injuries")
        if not data:
            continue
        for injury in data.get("injuries", []):
            status_raw = injury.get("status", "")
            status_lower = status_raw.lower()
            athlete = injury.get("athlete", {})
            name = athlete.get("displayName", "")
            if not name:
                continue
            if status_lower == "out":
                result[name] = "OUT"
            elif status_lower in _QUESTIONABLE_STATUSES:
                result[name] = "QUESTIONABLE"
            elif status_lower == "probable":
                result[name] = "PROBABLE"
            # skip anything else
    return result


def get_teammate_boost_map(
    out_players: list[dict],  # list of {"name": str, "pts": float, "reb": float, "ast": float, "min": float, "team": str}
    team_roster: dict[str, list[str]],  # {team_name: [active_player_names]}
) -> dict[str, dict[str, float]]:
    """
    For each OUT player, distribute their pts/reb/ast proportionally to active teammates.
    Returns {player_name: {"pts_boost": float, "reb_boost": float, "ast_boost": float}}
    where each boost is a multiplier (e.g. 1.08 = 8% more production expected).

    Simple heuristic: split the OUT player's stats equally among their top-5 active teammates.
    Each teammate gets out_player_stat / num_active_teammates as additive boost,
    expressed as a multiplier on their own projection.
    """
    boost_map: dict[str, dict[str, float]] = {}

    for out_player in out_players:
        team = out_player.get("team", "")
        if not team:
            continue
        active_teammates = team_roster.get(team, [])
        # exclude the out player themselves
        active_teammates = [p for p in active_teammates if p != out_player.get("name", "")]
        top5 = active_teammates[:5]
        if not top5:
            continue

        out_pts = float(out_player.get("pts", 0.0))
        out_reb = float(out_player.get("reb", 0.0))
        out_ast = float(out_player.get("ast", 0.0))
        n = len(top5)

        for teammate in top5:
            existing = boost_map.get(teammate, {"pts_boost": 1.0, "reb_boost": 1.0, "ast_boost": 1.0})
            # Each teammate gets a share; express as multiplier additive to 1.0
            # We store cumulative multipliers by multiplying
            pts_add = out_pts / n if n > 0 else 0.0
            reb_add = out_reb / n if n > 0 else 0.0
            ast_add = out_ast / n if n > 0 else 0.0
            # Convert additive stats to a multiplier: use a flat 8% per out star heuristic
            # (exact per-stat redistribution would need per-player averages, which we don't have here)
            existing["pts_boost"] = min(existing["pts_boost"] * (1.0 + (pts_add / 20.0 if pts_add > 0 else 0.0)), 1.30)
            existing["reb_boost"] = min(existing["reb_boost"] * (1.0 + (reb_add / 10.0 if reb_add > 0 else 0.0)), 1.30)
            existing["ast_boost"] = min(existing["ast_boost"] * (1.0 + (ast_add / 10.0 if ast_add > 0 else 0.0)), 1.30)
            boost_map[teammate] = existing

    return boost_map


def _fuzzy_match_player(name: str, stats_map: dict) -> dict | None:
    """Try last-name match as fallback for name format differences."""
    last = name.split()[-1].lower()
    for key, val in stats_map.items():
        if key.split()[-1].lower() == last:
            return val
    return None
