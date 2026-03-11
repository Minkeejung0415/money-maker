"""
Soccer team and player rolling stats — EPL + Champions League.

Data source: Understat (https://understat.com).
  - EPL (English Premier League): full support
  - UCL (Champions League): not available on Understat — returns [] (model falls
    back to market-implied)

Cache: data/.soccer_cache/ with 24-hour TTL (same pattern as prop_model.py).

Team stats (rolling 5-game window):
    goals_for, goals_against, xG_for, xG_against

Player stats (per 90 minutes from season totals):
    goals_per90, assists_per90, shots_per90, xG_per90

Season: _CURRENT_SEASON = 2024 (2024-25) — update annually.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import pickle
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Understat supports domestic leagues only (not UCL/Champions League)
_UNDERSTAT_LEAGUE_MAP: dict[str, str] = {
    "epl": "EPL",
}

# Kept for backward compatibility with helpers that iterate all leagues
SUPPORTED_LEAGUES: dict[str, str] = {
    "epl": "EPL (Understat)",
    "ucl": "UCL (not on Understat — market-implied fallback)",
}

_CURRENT_SEASON: int = 2024  # 2024-25 season — update annually
_CACHE_DIR = Path("data/.soccer_cache")
_ROLLING_WINDOW = 5


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
# Async helpers (Understat uses aiohttp internally)
# ---------------------------------------------------------------------------

async def _async_fetch_league_results(league_name: str) -> list[dict]:
    """Async: fetch completed match results from Understat."""
    import aiohttp  # noqa: PLC0415
    import understat  # noqa: PLC0415

    async with aiohttp.ClientSession() as session:
        u = understat.Understat(session)
        return await u.get_league_results(league_name, _CURRENT_SEASON)


async def _async_fetch_league_players(league_name: str) -> list[dict]:
    """Async: fetch season player stats from Understat."""
    import aiohttp  # noqa: PLC0415
    import understat  # noqa: PLC0415

    async with aiohttp.ClientSession() as session:
        u = understat.Understat(session)
        return await u.get_league_players(league_name, _CURRENT_SEASON)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine safely — handles already-running event loops."""
    try:
        asyncio.get_running_loop()
        # Inside a running loop (e.g. Jupyter) — run in a separate thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_team_rolling_stats(league_key: str = "epl") -> list[dict]:
    """
    Return team rolling stats for the given league.

    Each record:
        {
            "team": str,
            "league": str,
            "goals_for": float,       # avg last 5 games
            "goals_against": float,
            "xG_for": float,
            "xG_against": float,
            "games_used": int,
        }

    UCL returns [] — Understat does not cover Champions League.
    Returns [] on any failure (graceful degradation).
    """
    understat_league = _UNDERSTAT_LEAGUE_MAP.get(league_key.lower())
    if understat_league is None:
        logger.info(
            "Understat does not support '%s' — returning empty (market-implied fallback)",
            league_key,
        )
        return []

    cache_key = f"team_rolling_{league_key}"
    cached = _load_cache(cache_key)
    if cached is not None:
        logger.debug("Team stats loaded from cache for %s", league_key)
        return cached

    try:
        raw_results: list[dict] = _run_async(_async_fetch_league_results(understat_league))

        team_games: dict[str, list[dict]] = {}
        for match in raw_results:
            if not match.get("isResult"):
                continue  # skip future / unplayed matches

            home_title = match.get("h", {}).get("title", "")
            away_title = match.get("a", {}).get("title", "")
            if not home_title or not away_title:
                continue

            goals = match.get("goals", {})
            xg = match.get("xG", {})

            home_g = _safe_float(goals.get("h"))
            away_g = _safe_float(goals.get("a"))
            home_xg = _safe_float(xg.get("h")) or 0.0
            away_xg = _safe_float(xg.get("a")) or 0.0

            if home_g is None or away_g is None:
                continue

            team_games.setdefault(home_title, []).append({
                "goals_for": home_g, "goals_against": away_g,
                "xG_for": home_xg, "xG_against": away_xg,
            })
            team_games.setdefault(away_title, []).append({
                "goals_for": away_g, "goals_against": home_g,
                "xG_for": away_xg, "xG_against": home_xg,
            })

        results = []
        for team, games in team_games.items():
            recent = games[-_ROLLING_WINDOW:]
            n = len(recent)
            if n == 0:
                continue
            results.append({
                "team": team,
                "league": league_key,
                "goals_for": round(sum(g["goals_for"] for g in recent) / n, 3),
                "goals_against": round(sum(g["goals_against"] for g in recent) / n, 3),
                "xG_for": round(sum(g["xG_for"] for g in recent) / n, 3),
                "xG_against": round(sum(g["xG_against"] for g in recent) / n, 3),
                "games_used": n,
            })

        _save_cache(cache_key, results)
        logger.info("Fetched team stats for %s: %d teams", league_key, len(results))
        return results

    except Exception as exc:
        logger.warning("Soccer team stats fetch failed for %s: %s", league_key, exc)
        return []


def get_player_per90_stats(league_key: str = "epl") -> list[dict]:
    """
    Return player per-90 stats for the given league.

    Each record:
        {
            "player": str,
            "team": str,
            "league": str,
            "goals_per90": float,
            "assists_per90": float,
            "shots_per90": float,
            "xG_per90": float,
            "minutes_90s": float,
        }

    UCL returns [] — Understat does not cover Champions League.
    Returns [] on any failure.
    """
    understat_league = _UNDERSTAT_LEAGUE_MAP.get(league_key.lower())
    if understat_league is None:
        logger.info(
            "Understat does not support '%s' — returning empty (market-implied fallback)",
            league_key,
        )
        return []

    cache_key = f"player_per90_{league_key}"
    cached = _load_cache(cache_key)
    if cached is not None:
        logger.debug("Player stats loaded from cache for %s", league_key)
        return cached

    try:
        raw_players: list[dict] = _run_async(_async_fetch_league_players(understat_league))

        results = []
        for row in raw_players:
            player = str(row.get("player_name", "")).strip()
            team = str(row.get("team_title", "")).strip()
            if not player:
                continue

            mins = _safe_float(row.get("time")) or 0.0
            mins_90s = mins / 90.0
            if mins_90s < 1.0:  # less than one 90-minute block — skip
                continue

            goals = _safe_float(row.get("goals")) or 0.0
            assists = _safe_float(row.get("assists")) or 0.0
            shots = _safe_float(row.get("shots")) or 0.0
            xg = _safe_float(row.get("xG")) or 0.0

            results.append({
                "player": player,
                "team": team,
                "league": league_key,
                "goals_per90": round(goals / mins_90s, 4),
                "assists_per90": round(assists / mins_90s, 4),
                "shots_per90": round(shots / mins_90s, 4),
                "xG_per90": round(xg / mins_90s, 4),
                "minutes_90s": round(mins_90s, 2),
            })

        _save_cache(cache_key, results)
        logger.info("Fetched player stats for %s: %d players", league_key, len(results))
        return results

    except Exception as exc:
        logger.warning("Soccer player stats fetch failed for %s: %s", league_key, exc)
        return []


def get_team_rolling_stats_all() -> list[dict]:
    """Return team rolling stats for all supported leagues combined."""
    all_stats: list[dict] = []
    for key in SUPPORTED_LEAGUES:
        all_stats.extend(get_team_rolling_stats(key))
    return all_stats


def get_player_per90_stats_all() -> list[dict]:
    """Return player per-90 stats for all supported leagues combined."""
    all_stats: list[dict] = []
    for key in SUPPORTED_LEAGUES:
        all_stats.extend(get_player_per90_stats(key))
    return all_stats


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> float | None:
    """Safely convert a value to float; returns None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
