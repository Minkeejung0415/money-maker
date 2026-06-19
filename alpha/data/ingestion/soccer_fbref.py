"""FBref set piece stats for EPL teams via soccerdata.

Additive to Understat xG data; this module does not replace soccer_stats.py.

Column discovery fallback (soccerdata unavailable in the active environment):
- corners: ("Corner Kicks", "CK")
- aerial win rate: ("Aerial Duels", "Won%")
- pressing proxy: ("Pressures", "Press")
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import pickle
import re
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("data/.soccer_cache")
_CURRENT_SEASON = 2024


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value.replace(" ", "_")).strip("_")


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}_{date.today()}.pkl"


def _load_cache(key: str) -> Any | None:
    path = _cache_path(key)
    if path.exists():
        try:
            with path.open("rb") as handle:
                return pickle.load(handle)
        except Exception:
            pass
    return None


def _save_cache(key: str, data: Any) -> None:
    try:
        with _cache_path(key).open("wb") as handle:
            pickle.dump(data, handle)
    except Exception as exc:
        logger.debug("Cache write failed: %s", exc)


def _column(frame: Any, candidates: tuple[Any, ...]) -> Any | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate

    normalized = {
        " ".join(str(part) for part in column if str(part) != "nan").lower()
        if isinstance(column, tuple)
        else str(column).lower(): column
        for column in frame.columns
    }
    for candidate in candidates:
        target = (
            " ".join(str(part) for part in candidate).lower()
            if isinstance(candidate, tuple)
            else str(candidate).lower()
        )
        if target in normalized:
            return normalized[target]
    return None


def _number(value: Any) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _team_name(index_value: Any) -> str:
    if isinstance(index_value, tuple):
        return str(index_value[-1])
    return str(index_value)


def _extract_set_pieces(
    df_passing_types: Any,
    df_misc: Any,
    df_defense: Any,
) -> dict[str, dict[str, float]]:
    corners_col = _column(
        df_passing_types,
        (("Corner Kicks", "CK"), "CK", "corners", "corner_kicks"),
    )
    matches_col = _column(
        df_passing_types,
        (("Playing Time", "MP"), "MP", "matches_played"),
    )
    aerial_col = _column(
        df_misc,
        (("Aerial Duels", "Won%"), "Won%", "aerials_won_pct"),
    )
    pressing_col = _column(
        df_defense,
        (("Pressures", "Press"), "Press", "pressures", "pressing_proxy"),
    )

    results: dict[str, dict[str, float]] = {}
    for index_value in df_passing_types.index:
        corners = _number(
            df_passing_types.loc[index_value, corners_col]
            if corners_col is not None
            else 0.0
        )
        matches = _number(
            df_passing_types.loc[index_value, matches_col]
            if matches_col is not None
            else 0.0
        )
        aerial = _number(
            df_misc.loc[index_value, aerial_col]
            if aerial_col is not None and index_value in df_misc.index
            else 0.0
        )
        pressing = _number(
            df_defense.loc[index_value, pressing_col]
            if pressing_col is not None and index_value in df_defense.index
            else 0.0
        )
        results[_team_name(index_value)] = {
            "corners_per_game": corners / matches if matches > 0 else 0.0,
            "aerial_won_pct": aerial,
            "pressing_proxy": pressing,
        }
    return results


def get_fbref_set_pieces(
    league: str = "ENG-Premier League",
    season: int | None = None,
) -> dict[str, dict[str, float]]:
    selected_season = season or _CURRENT_SEASON
    cache_key = f"fbref_set_pieces_{_safe_key(league)}_{selected_season}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        os.environ.setdefault("SOCCERDATA_DIR", str(_CACHE_DIR / "soccerdata"))
        soccerdata = importlib.import_module("soccerdata")
        fbref = soccerdata.FBref(leagues=league, seasons=selected_season)
        passing = fbref.read_team_season_stats(stat_type="passing_types")
        misc = fbref.read_team_season_stats(stat_type="misc")
        defense = fbref.read_team_season_stats(stat_type="defense")
        result = _extract_set_pieces(passing, misc, defense)
        _save_cache(cache_key, result)
        logger.info("FBref set piece stats loaded: %d teams", len(result))
        return result
    except Exception as exc:
        logger.warning("FBref set pieces fetch failed: %s", exc)
        return {}
