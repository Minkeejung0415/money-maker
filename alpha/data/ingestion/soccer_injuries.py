"""
Soccer injury ingestion — EPL + Champions League.

Data source: ESPN API
  https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/teams/{id}/injuries

League slugs:
    EPL  → "eng.1"
    UCL  → "UEFA.Champions_League"

ESPN team IDs are fetched dynamically from the ESPN scoreboard endpoint.

Return shape mirrors nba_injuries.get_team_injury_impact():
    {
        "Arsenal": {
            "out": [{"name": "Bukayo Saka", "goals": 0.3, "assists": 0.2}],
            "goals_lost": 0.3,
            "assists_lost": 0.2,
        },
        ...
    }
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUE_SLUGS: dict[str, str] = {
    "epl": "eng.1",
    "ucl": "UEFA.Champions_League",
}


def _get(url: str, timeout: int = 10) -> dict | None:
    """GET JSON from *url*, returning None on any failure."""
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.debug("ESPN request failed %s: %s", url, exc)
        return None


def get_espn_team_ids(league_key: str) -> dict[str, int]:
    """
    Fetch team name → ESPN team ID mapping from the scoreboard endpoint.

    Returns {} on failure.
    """
    slug = LEAGUE_SLUGS.get(league_key.lower())
    if slug is None:
        return {}

    data = _get(f"{_ESPN_BASE}/{slug}/scoreboard")
    if not data:
        return {}

    teams: dict[str, int] = {}
    try:
        for event in data.get("events", []):
            for competition in event.get("competitions", []):
                for competitor in competition.get("competitors", []):
                    team = competitor.get("team", {})
                    name = team.get("displayName", "") or team.get("name", "")
                    team_id = team.get("id")
                    if name and team_id:
                        try:
                            teams[name] = int(team_id)
                        except (TypeError, ValueError):
                            pass
    except Exception as exc:
        logger.debug("ESPN team ID parse failed: %s", exc)

    return teams


def get_espn_out_players(team_name: str, team_id: int, league_key: str) -> list[str]:
    """
    Return list of player names confirmed OUT for *team_name* via ESPN
    injury endpoint.

    Only returns players with status exactly "Out".
    Returns [] on any failure.
    """
    slug = LEAGUE_SLUGS.get(league_key.lower())
    if slug is None:
        return []

    url = f"{_ESPN_BASE}/{slug}/teams/{team_id}/injuries"
    data = _get(url)
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


def get_team_injury_impact(league_key: str = "epl") -> dict[str, dict]:
    """
    Main entry point. Returns per-team injury impact dict:

        {
            "Arsenal": {
                "out": [{"name": "Bukayo Saka", "goals": 0.3, "assists": 0.2}],
                "goals_lost": 0.3,
                "assists_lost": 0.2,
            },
            ...
        }

    Falls back to {} on any error.
    """
    team_ids = get_espn_team_ids(league_key)
    if not team_ids:
        logger.info("No ESPN team IDs found for %s — injury adjustment skipped", league_key)
        return {}

    # Try to get per-player stats from soccerdata for goal/assist impact
    player_stats = _load_player_stats(league_key)

    impact: dict[str, dict] = {}
    for team_name, team_id in team_ids.items():
        out_names = get_espn_out_players(team_name, team_id, league_key)
        if not out_names:
            continue

        out_details = []
        for name in out_names:
            stats = player_stats.get(name) or _fuzzy_match_player(name, player_stats)
            if stats:
                out_details.append({"name": name, **stats})
            else:
                out_details.append({"name": name, "goals": 0.0, "assists": 0.0})

        impact[team_name] = {
            "out": out_details,
            "goals_lost": round(sum(p.get("goals", 0.0) for p in out_details), 3),
            "assists_lost": round(sum(p.get("assists", 0.0) for p in out_details), 3),
        }

    return impact


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_player_stats(league_key: str) -> dict[str, dict]:
    """
    Load per-player goals/assists from soccer_stats cache.
    Returns {player_name: {goals, assists}}.
    """
    try:
        from alpha.data.ingestion.soccer_stats import get_player_per90_stats  # noqa: PLC0415
        rows = get_player_per90_stats(league_key)
        result: dict[str, dict] = {}
        for row in rows:
            result[row["player"]] = {
                "goals": row.get("goals_per90", 0.0),
                "assists": row.get("assists_per90", 0.0),
            }
        return result
    except Exception as exc:
        logger.debug("Could not load player stats for injuries: %s", exc)
        return {}


def _fuzzy_match_player(name: str, stats_map: dict) -> dict | None:
    """Last-name fuzzy match as fallback for name format differences."""
    last = name.split()[-1].lower()
    for key, val in stats_map.items():
        if key.split()[-1].lower() == last:
            return val
    return None
