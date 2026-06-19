"""Club Elo ratings loader for EPL/UCL club teams.

Source: clubelo.com CSV API.
"""
from __future__ import annotations

import io
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_CLUB_ELO_API = "http://api.clubelo.com"
_CACHE_DIR = Path("data/.soccer_cache")
_MAX_STALE_DAYS = 2
_ELO_FALLBACK = 1500.0

_CLUB_ALIASES = {
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Wolves": "Wolverhampton Wanderers",
    "Spurs": "Tottenham Hotspur",
    "Brighton": "Brighton & Hove Albion",
    "Newcastle": "Newcastle United",
    "West Ham": "West Ham United",
    "Nottm Forest": "Nottingham Forest",
    "Leicester": "Leicester City",
}


def _cache_file(date_str: str) -> Path:
    return _CACHE_DIR / f"club_elo_{date_str}.csv"


def _find_stale_cache() -> tuple[Path, int] | None:
    if not _CACHE_DIR.exists():
        return None

    candidates: list[tuple[Path, int]] = []
    today = date.today()
    for path in _CACHE_DIR.glob("club_elo_*.csv"):
        try:
            cached_date = date.fromisoformat(path.stem.removeprefix("club_elo_"))
        except ValueError:
            continue
        age = (today - cached_date).days
        if 0 <= age <= _MAX_STALE_DAYS:
            candidates.append((path, age))

    return min(candidates, key=lambda item: item[1]) if candidates else None


def _parse_csv_to_dict(csv_text: str) -> dict[str, float]:
    try:
        frame = pd.read_csv(io.StringIO(csv_text))
    except Exception as exc:
        logger.warning("Could not parse Club Elo CSV: %s", exc)
        return {}

    if not {"Club", "Elo"}.issubset(frame.columns):
        logger.warning("Club Elo CSV is missing Club or Elo columns")
        return {}

    ratings: dict[str, float] = {}
    for _, row in frame.iterrows():
        try:
            ratings[str(row["Club"])] = float(row["Elo"])
        except (TypeError, ValueError):
            continue
    return ratings


def load_club_elo_ratings(date_str: str | None = None) -> dict[str, float]:
    requested_date = date_str or date.today().isoformat()
    cache_file = _cache_file(requested_date)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache_file.exists():
        return _parse_csv_to_dict(cache_file.read_text(encoding="utf-8"))

    try:
        response = requests.get(f"{_CLUB_ELO_API}/{requested_date}", timeout=10)
        response.raise_for_status()
        cache_file.write_text(response.text, encoding="utf-8")
        return _parse_csv_to_dict(response.text)
    except Exception as exc:
        logger.warning("clubelo.com fetch failed: %s", exc)
        stale = _find_stale_cache()
        if stale is not None:
            path, age = stale
            logger.warning("Using stale Club Elo cache (%d days old): %s", age, path)
            return _parse_csv_to_dict(path.read_text(encoding="utf-8"))
        raise RuntimeError(
            f"Club Elo unavailable and no cache found: {exc}"
        ) from exc


def get_club_elo_rating(club: str, ratings: dict[str, float]) -> float:
    canonical = _CLUB_ALIASES.get(club, club)
    if canonical not in ratings:
        logger.warning(
            "No Club Elo rating for '%s'; using fallback %.0f",
            club,
            _ELO_FALLBACK,
        )
        return _ELO_FALLBACK
    return ratings[canonical]
