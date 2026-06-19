"""
Form, H2H, and days-rest ingestion for EPL/UCL teams. Source: football-data.org v4 API.

Public API:
    fetch_team_form(team_id, n=5)  -> dict with form_points, wdl, goals, etc.
    fetch_h2h(home_id, away_id, n=5) -> dict with meetings, win rates, etc.
    fetch_days_rest(team_id, match_date) -> int days since last game (clamped [0, 7])

Cache: data/.soccer_cache/ (daily TTL, date-keyed filenames).
Isolated from WC pipeline - no cross-pipeline imports.
"""
from __future__ import annotations

import logging
import pickle
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CACHE_DIR = Path("data/.soccer_cache")
_FORM_WINDOW = 5
_REST_DEFAULT = 3   # days rest returned when no prior game found
_REST_MAX = 7
_REST_MIN = 0


# ---------------------------------------------------------------------------
# Cache helpers (copied verbatim from soccer_stats.py - kept self-contained
# per D-07 so this module has zero dependencies on the Understat pipeline)
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}_{date.today()}.pkl"


def _load_cache(key: str) -> Any | None:
    path = _cache_path(key)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    return None


def _save_cache(key: str, data: Any) -> None:
    try:
        with open(_cache_path(key), "wb") as f:
            pickle.dump(data, f)
    except Exception as exc:
        logger.debug("Cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_form(team_id: int, matches: list[dict], n: int = 5) -> dict:
    """
    Compute form from a list of raw API match dicts.

    Filters to completed matches (fullTime scores present, winner not None),
    takes the last n, and returns a form summary dict.

    W=3 pts (HOME_WIN when team is home, AWAY_WIN when team is away), D=1, L=0.
    wdl list is ordered oldest-to-newest.
    """
    # Filter to completed matches only
    completed = [
        m for m in matches
        if m.get("score", {}).get("fullTime", {}).get("home") is not None
        and m.get("score", {}).get("winner") is not None
    ]

    # Match lists are chronological; keep the most recent n entries.
    recent = completed[-n:] if len(completed) > n else completed

    form_points = 0
    goals_for = 0
    goals_against = 0
    wdl: list[str] = []

    for match in recent:
        is_home = match.get("homeTeam", {}).get("id") == team_id
        score = match.get("score", {})
        full_time = score.get("fullTime", {})
        winner = score.get("winner")

        home_goals = int(full_time.get("home") or 0)
        away_goals = int(full_time.get("away") or 0)

        if is_home:
            gf, ga = home_goals, away_goals
        else:
            gf, ga = away_goals, home_goals

        goals_for += gf
        goals_against += ga

        if (is_home and winner == "HOME_WIN") or (not is_home and winner == "AWAY_WIN"):
            wdl.append("W")
            form_points += 3
        elif winner == "DRAW":
            wdl.append("D")
            form_points += 1
        else:
            wdl.append("L")

    return {
        "team_id": team_id,
        "games": len(recent),
        "form_points": form_points,
        "form_goal_diff": goals_for - goals_against,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "wdl": wdl,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_team_form(team_id: int, n: int = 5) -> dict:
    """
    Return last-n-game form for a team using football-data.org.

    Args:
        team_id: football-data.org numeric team ID (e.g. 57 = Arsenal).
        n: form window (default 5).

    Returns dict with keys: team_id, games, form_points, form_goal_diff,
        goals_for, goals_against, wdl.

    Results are cached with a daily TTL. Returns empty form on any failure.
    """
    # Security: validate team_id is integer to prevent path traversal in cache key
    team_id = int(team_id)

    cache_key = f"form_{team_id}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    # Import inside function body to avoid circular import risk
    from alpha.data.ingestion.football_data_client import FootballDataClient  # noqa: PLC0415

    try:
        client = FootballDataClient()
        raw = client.fetch_team_matches(team_id, status="FINISHED", limit=max(n * 2, 10))
        result = _compute_form(team_id, raw, n)
    except Exception as exc:
        logger.warning("fetch_team_form(%d) failed: %s", team_id, exc)
        result = _compute_form(team_id, [], n)

    _save_cache(cache_key, result)
    return result


def fetch_h2h(home_id: int, away_id: int, n: int = 5) -> dict:
    """
    Return head-to-head record between two teams using football-data.org.

    Fetches home_id's last 50 matches and filters to those involving both teams.
    Counts wins from the home_id perspective.

    Args:
        home_id: football-data.org ID of the home team for today's match.
        away_id: football-data.org ID of the away team for today's match.
        n: maximum meetings to consider (default 5).

    Returns dict with keys: home_id, away_id, meetings, h2h_home_wins,
        h2h_draws, h2h_away_wins, h2h_home_win_rate.

    Results are cached with a daily TTL.
    """
    # Security: validate IDs are integers
    home_id = int(home_id)
    away_id = int(away_id)

    cache_key = f"h2h_{home_id}_{away_id}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    from alpha.data.ingestion.football_data_client import FootballDataClient  # noqa: PLC0415

    try:
        client = FootballDataClient()
        raw = client.fetch_team_matches(home_id, status="FINISHED", limit=50)
    except Exception as exc:
        logger.warning("fetch_h2h(%d, %d) failed: %s", home_id, away_id, exc)
        raw = []

    # Filter to matches involving both teams (either direction)
    meetings_raw = [
        m for m in raw
        if (
            (m.get("homeTeam", {}).get("id") == home_id and m.get("awayTeam", {}).get("id") == away_id)
            or (m.get("homeTeam", {}).get("id") == away_id and m.get("awayTeam", {}).get("id") == home_id)
        )
    ]
    meetings_raw = meetings_raw[-n:] if len(meetings_raw) > n else meetings_raw

    h2h_home_wins = 0
    h2h_draws = 0
    h2h_away_wins = 0

    for match in meetings_raw:
        match_home_id = match.get("homeTeam", {}).get("id")
        winner = match.get("score", {}).get("winner")

        if winner == "HOME_WIN":
            if match_home_id == home_id:
                h2h_home_wins += 1
            else:
                h2h_away_wins += 1
        elif winner == "AWAY_WIN":
            if match_home_id == away_id:
                h2h_home_wins += 1
            else:
                h2h_away_wins += 1
        elif winner == "DRAW":
            h2h_draws += 1

    meetings = len(meetings_raw)
    h2h_home_win_rate = h2h_home_wins / meetings if meetings > 0 else 0.0

    result = {
        "home_id": home_id,
        "away_id": away_id,
        "meetings": meetings,
        "h2h_home_wins": h2h_home_wins,
        "h2h_draws": h2h_draws,
        "h2h_away_wins": h2h_away_wins,
        "h2h_home_win_rate": h2h_home_win_rate,
    }
    _save_cache(cache_key, result)
    return result


def fetch_days_rest(team_id: int, match_date: str) -> int:
    """
    Return integer days rest since the team's last completed game.

    No caching (called per-game at scan time; cheap per-call).

    Args:
        team_id: football-data.org numeric team ID.
        match_date: ISO 8601 date string for today's match (e.g. "2025-12-08").

    Returns int clamped to [_REST_MIN, _REST_MAX] (default _REST_DEFAULT=3 if
    no prior game found).
    """
    # Security: validate team_id is integer
    team_id = int(team_id)

    from alpha.data.ingestion.football_data_client import FootballDataClient  # noqa: PLC0415

    try:
        client = FootballDataClient()
        matches = client.fetch_team_matches(team_id, status="FINISHED", limit=2)
    except Exception as exc:
        logger.warning("fetch_days_rest(%d) failed: %s", team_id, exc)
        return _REST_DEFAULT

    if not matches:
        return _REST_DEFAULT

    # API returns newest-first; matches[0] is the most recent completed game
    last_date_str = matches[0].get("utcDate", "")[:10]
    if not last_date_str:
        return _REST_DEFAULT

    try:
        delta = (
            date.fromisoformat(match_date[:10]) - date.fromisoformat(last_date_str)
        ).days
        return max(_REST_MIN, min(_REST_MAX, delta - 1))
    except (ValueError, TypeError) as exc:
        logger.warning("fetch_days_rest date parse error: %s", exc)
        return _REST_DEFAULT
