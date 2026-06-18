"""
Elo ratings reader for WC 2026 national teams.

Reads from data/wc_priors.json written by scripts/build_wc_priors.py.
No network calls — pure file I/O only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_WC_PRIORS_PATH = Path("data/wc_priors.json")
_ELO_FALLBACK: int = 1500


def load_wc_elo_ratings() -> dict[str, int]:
    """
    Load Elo ratings from data/wc_priors.json.

    Returns {team_name: elo_rating} for all teams in the file.
    Raises FileNotFoundError if wc_priors.json is missing — run
    scripts/build_wc_priors.py to generate it.
    """
    if not _WC_PRIORS_PATH.exists():
        raise FileNotFoundError(
            f"WC Elo priors not found at {_WC_PRIORS_PATH}. "
            "Run: ./venv/Scripts/python.exe scripts/build_wc_priors.py"
        )
    with open(_WC_PRIORS_PATH, "r", encoding="utf-8") as f:
        ratings: dict[str, int] = json.load(f)
    logger.debug("Loaded Elo ratings for %d teams from %s", len(ratings), _WC_PRIORS_PATH)
    return ratings


def get_elo_rating(team: str, ratings: dict[str, int]) -> int:
    """
    Return Elo rating for team, falling back to _ELO_FALLBACK (1500) if not present.

    Logs a warning when the fallback is used so callers can detect missing mappings.
    """
    if team not in ratings:
        logger.warning(
            "No Elo rating for '%s' — using fallback %d", team, _ELO_FALLBACK
        )
        return _ELO_FALLBACK
    return ratings[team]
