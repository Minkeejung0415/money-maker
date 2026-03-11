"""
MLB injury ingestion via ESPN API.

Endpoint:
    https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{id}/injuries

ESPN MLB team IDs: fetched dynamically from ESPN scoreboard or from static map.

Return shape mirrors nba_injuries.get_team_injury_impact():
    {
        "New York Yankees": {
            "out": [{"name": "Aaron Judge", "avg": 0.310, "hr_per_game": 0.040}],
            "avg_lost": 0.310,
            "hr_lost": 0.040,
        },
        ...
    }
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"

# Static ESPN MLB team ID map (stable as of 2025)
# Used as fallback when dynamic fetch fails
_ESPN_TEAM_IDS: dict[str, int] = {
    "Arizona Diamondbacks": 29,
    "Atlanta Braves": 15,
    "Baltimore Orioles": 1,
    "Boston Red Sox": 2,
    "Chicago Cubs": 16,
    "Chicago White Sox": 4,
    "Cincinnati Reds": 17,
    "Cleveland Guardians": 5,
    "Colorado Rockies": 27,
    "Detroit Tigers": 6,
    "Houston Astros": 18,
    "Kansas City Royals": 7,
    "Los Angeles Angels": 3,
    "Los Angeles Dodgers": 19,
    "Miami Marlins": 28,
    "Milwaukee Brewers": 21,
    "Minnesota Twins": 9,
    "New York Mets": 21,
    "New York Yankees": 10,
    "Oakland Athletics": 11,
    "Philadelphia Phillies": 22,
    "Pittsburgh Pirates": 23,
    "San Diego Padres": 25,
    "San Francisco Giants": 26,
    "Seattle Mariners": 12,
    "St. Louis Cardinals": 24,
    "Tampa Bay Rays": 30,
    "Texas Rangers": 13,
    "Toronto Blue Jays": 14,
    "Washington Nationals": 20,
}


def _get(url: str, timeout: int = 10) -> dict | None:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.debug("ESPN MLB request failed %s: %s", url, exc)
        return None


def get_espn_team_ids_dynamic() -> dict[str, int]:
    """
    Fetch team name → ESPN team ID mapping from the MLB scoreboard endpoint.
    Falls back to static map on failure.
    """
    data = _get(f"{_ESPN_BASE}/scoreboard")
    if not data:
        return dict(_ESPN_TEAM_IDS)

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
        logger.debug("ESPN MLB team ID parse failed: %s", exc)

    return teams or dict(_ESPN_TEAM_IDS)


def get_espn_out_players(team_name: str) -> list[str]:
    """
    Return list of player names confirmed OUT for *team_name* via ESPN
    MLB injury endpoint.

    Only returns players with status exactly "Out".
    Returns [] on any failure.
    """
    espn_id = _ESPN_TEAM_IDS.get(team_name)
    if espn_id is None:
        return []

    data = _get(f"{_ESPN_BASE}/teams/{espn_id}/injuries")
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


def get_team_injury_impact() -> dict[str, dict]:
    """
    Main entry point. Returns per-team MLB injury impact:

        {
            "New York Yankees": {
                "out": [{"name": "Aaron Judge", "avg": 0.310, "hr_per_game": 0.040}],
                "avg_lost": 0.310,
                "hr_lost": 0.040,
            },
            ...
        }

    Returns {} on any error.
    """
    player_stats = _load_player_stats()

    impact: dict[str, dict] = {}
    for team_name in _ESPN_TEAM_IDS:
        out_names = get_espn_out_players(team_name)
        if not out_names:
            continue

        out_details = []
        for name in out_names:
            stats = player_stats.get(name) or _fuzzy_match_player(name, player_stats)
            if stats:
                out_details.append({"name": name, **stats})
            else:
                out_details.append({"name": name, "avg": 0.0, "hr_per_game": 0.0})

        impact[team_name] = {
            "out": out_details,
            "avg_lost": round(sum(p.get("avg", 0.0) for p in out_details), 3),
            "hr_lost": round(sum(p.get("hr_per_game", 0.0) for p in out_details), 4),
        }

    return impact


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_player_stats() -> dict[str, dict]:
    """Load per-batter avg/hr from mlb_stats cache."""
    try:
        from alpha.data.ingestion.mlb_stats import get_batter_stats  # noqa: PLC0415
        rows = get_batter_stats()
        return {
            r["player"]: {"avg": r.get("avg", 0.0), "hr_per_game": r.get("hr_per_game", 0.0)}
            for r in rows
        }
    except Exception as exc:
        logger.debug("Could not load MLB player stats for injuries: %s", exc)
        return {}


def _fuzzy_match_player(name: str, stats_map: dict) -> dict | None:
    last = name.split()[-1].lower()
    for key, val in stats_map.items():
        if key.split()[-1].lower() == last:
            return val
    return None
