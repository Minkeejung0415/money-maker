"""
Soccer team and player rolling stats — EPL + Champions League.

Data source: soccerdata (FBRef backend).
Cache: data/.soccer_cache/ with 24-hour TTL (same pattern as prop_model.py).

Team stats (rolling 5-game window):
    goals_for, goals_against, xG_for, xG_against

Player stats (per 90):
    goals_per90, assists_per90, shots_per90, xG_per90

Leagues:
    "ENG-Premier League"      (EPL)
    "UEFA-Champions League"   (UCL)
"""
from __future__ import annotations

import logging
import pickle
import time
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_LEAGUES = {
    "epl": "ENG-Premier League",
    "ucl": "UEFA-Champions League",
}

_CACHE_DIR = Path("data/.soccer_cache")
_CACHE_TTL_HOURS = 24
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

    Returns [] on any failure (graceful degradation).
    """
    league_name = SUPPORTED_LEAGUES.get(league_key.lower())
    if league_name is None:
        logger.warning("Unknown league key: %s", league_key)
        return []

    cache_key = f"team_rolling_{league_key}"
    cached = _load_cache(cache_key)
    if cached is not None:
        logger.debug("Team stats loaded from cache for %s", league_key)
        return cached

    try:
        import soccerdata as sd  # noqa: PLC0415

        reader = sd.FBref(leagues=league_name, seasons="2024-25")
        schedule = reader.read_schedule()

        # Build rolling 5-game team stats
        team_stats = _compute_team_rolling(schedule, window=_ROLLING_WINDOW)

        results = []
        for team, stats in team_stats.items():
            results.append({
                "team": team,
                "league": league_key,
                "goals_for": round(stats.get("goals_for", 0.0), 3),
                "goals_against": round(stats.get("goals_against", 0.0), 3),
                "xG_for": round(stats.get("xG_for", 0.0), 3),
                "xG_against": round(stats.get("xG_against", 0.0), 3),
                "games_used": stats.get("games_used", 0),
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
            "minutes_90s": float,   # 90-minute periods played
        }

    Returns [] on any failure.
    """
    league_name = SUPPORTED_LEAGUES.get(league_key.lower())
    if league_name is None:
        logger.warning("Unknown league key: %s", league_key)
        return []

    cache_key = f"player_per90_{league_key}"
    cached = _load_cache(cache_key)
    if cached is not None:
        logger.debug("Player stats loaded from cache for %s", league_key)
        return cached

    try:
        import soccerdata as sd  # noqa: PLC0415

        reader = sd.FBref(leagues=league_name, seasons="2024-25")
        shooting = reader.read_player_season_stats("shooting")
        passing = reader.read_player_season_stats("passing")

        results = _merge_player_stats(shooting, passing, league_key)

        _save_cache(cache_key, results)
        logger.info("Fetched player stats for %s: %d players", league_key, len(results))
        return results

    except Exception as exc:
        logger.warning("Soccer player stats fetch failed for %s: %s", league_key, exc)
        return []


def get_team_rolling_stats_all() -> list[dict]:
    """Return team rolling stats for all supported leagues combined."""
    all_stats = []
    for key in SUPPORTED_LEAGUES:
        all_stats.extend(get_team_rolling_stats(key))
    return all_stats


def get_player_per90_stats_all() -> list[dict]:
    """Return player per-90 stats for all supported leagues combined."""
    all_stats = []
    for key in SUPPORTED_LEAGUES:
        all_stats.extend(get_player_per90_stats(key))
    return all_stats


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_team_rolling(schedule, window: int = 5) -> dict[str, dict]:
    """
    Compute rolling mean over last *window* games from a schedule DataFrame.

    Expects columns: home_team, away_team, home_goals, away_goals,
    home_xg, away_xg (or similar FBRef naming).
    """
    try:
        import pandas as pd  # noqa: PLC0415

        df = schedule.reset_index() if hasattr(schedule, "reset_index") else schedule

        # Normalize column names (FBRef uses MultiIndex or flat names)
        if hasattr(df.columns, "levels"):
            df.columns = ["_".join(c).strip("_") for c in df.columns]

        # Build per-game records for each team
        team_games: dict[str, list[dict]] = {}

        for _, row in df.iterrows():
            home = _extract_str(row, ["home_team", "Home", "home"])
            away = _extract_str(row, ["away_team", "Away", "away"])
            if not home or not away:
                continue

            home_g = _extract_float(row, ["home_goals", "Score_home", "score_home", "GF", "home_GF"])
            away_g = _extract_float(row, ["away_goals", "Score_away", "score_away", "GA", "away_GF"])
            home_xg = _extract_float(row, ["home_xg", "xG_home", "xg_home", "xG"])
            away_xg = _extract_float(row, ["away_xg", "xG_away", "xg_away"])

            if home_g is None or away_g is None:
                continue

            team_games.setdefault(home, []).append({
                "goals_for": home_g,
                "goals_against": away_g,
                "xG_for": home_xg or 0.0,
                "xG_against": away_xg or 0.0,
            })
            team_games.setdefault(away, []).append({
                "goals_for": away_g,
                "goals_against": home_g,
                "xG_for": away_xg or 0.0,
                "xG_against": home_xg or 0.0,
            })

        # Rolling average over last *window* games
        result = {}
        for team, games in team_games.items():
            recent = games[-window:]
            n = len(recent)
            if n == 0:
                continue
            result[team] = {
                "goals_for": sum(g["goals_for"] for g in recent) / n,
                "goals_against": sum(g["goals_against"] for g in recent) / n,
                "xG_for": sum(g["xG_for"] for g in recent) / n,
                "xG_against": sum(g["xG_against"] for g in recent) / n,
                "games_used": n,
            }
        return result
    except Exception as exc:
        logger.debug("_compute_team_rolling failed: %s", exc)
        return {}


def _merge_player_stats(shooting, passing, league_key: str) -> list[dict]:
    """
    Merge shooting + passing DataFrames to build per-90 player stats.
    """
    try:
        import pandas as pd  # noqa: PLC0415

        # Flatten MultiIndex if present
        def _flat(df):
            if hasattr(df.columns, "levels"):
                df = df.copy()
                df.columns = ["_".join(str(c) for c in col).strip("_")
                               for col in df.columns]
            return df.reset_index()

        s = _flat(shooting)
        p = _flat(passing)

        results = []
        for _, row in s.iterrows():
            player = _extract_str(row, ["player", "Player", "name"])
            team = _extract_str(row, ["team", "Team", "squad", "Squad"])
            if not player:
                continue

            mins_90s = _extract_float(row, ["90s", "min_90s", "MP", "minutes_90s"]) or 1.0
            goals = _extract_float(row, ["goals", "Gls", "G"]) or 0.0
            shots = _extract_float(row, ["shots", "Sh", "shots_total"]) or 0.0
            xg = _extract_float(row, ["xg", "xG", "expected_goals"]) or 0.0

            # Assists from passing table (best-effort merge)
            assists = 0.0
            if not p.empty:
                mask = p.get("player", p.get("Player", pd.Series())).str.lower() == player.lower()
                if mask.any():
                    ast_row = p[mask].iloc[0]
                    assists = _extract_float(ast_row, ["ast", "Ast", "assists"]) or 0.0

            results.append({
                "player": player,
                "team": team or "",
                "league": league_key,
                "goals_per90": round(goals / mins_90s, 4) if mins_90s > 0 else 0.0,
                "assists_per90": round(assists / mins_90s, 4) if mins_90s > 0 else 0.0,
                "shots_per90": round(shots / mins_90s, 4) if mins_90s > 0 else 0.0,
                "xG_per90": round(xg / mins_90s, 4) if mins_90s > 0 else 0.0,
                "minutes_90s": float(mins_90s),
            })
        return results
    except Exception as exc:
        logger.debug("_merge_player_stats failed: %s", exc)
        return []


def _extract_str(row, keys: list[str]) -> str:
    """Try multiple column names; return first non-empty string."""
    for k in keys:
        v = row.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _extract_float(row, keys: list[str]) -> float | None:
    """Try multiple column names; return first valid float."""
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None
