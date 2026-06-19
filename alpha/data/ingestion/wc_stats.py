"""
WC team stats reader — loads pre-built StatsBomb aggregated data from
data/.wc_cache/wc_stats.pkl.

Cache is written once by scripts/build_wc_priors.py; this module only reads.
No network calls — pure file I/O only.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

# Separate namespace from data/.soccer_cache/ — never share keys
_WC_CACHE_DIR = Path("data/.wc_cache")
_WC_STATS_CACHE = _WC_CACHE_DIR / "wc_stats.pkl"  # no date suffix: historical data is static

# Maps StatsBomb team names to football-data.org team names.
# Populate after first run of build_wc_priors.py by comparing sb.matches()
# team names to fixture response team names.
_TEAM_NAME_MAP: dict[str, str] = {
    # StatsBomb name -> football-data.org name
    # Populated from first build_wc_priors.py run (Phase 5 execution):
    "South Korea": "Korea Republic",
}


def get_wc_team_stats() -> dict[str, dict]:
    """
    Return StatsBomb-derived team stats keyed by football-data.org team name.

    Output shape per team:
        {
            "avg_goals":     float,   # goals scored per game
            "avg_xG":        float,   # xG for per game
            "avg_shots":     float,   # shots per game
            "defense_score": float,   # xG against per game (lower = better)
        }

    Raises FileNotFoundError if cache is missing — instructs user to run
    scripts/build_wc_priors.py to generate it.

    Pops the "built_at" metadata key before returning so callers never see it.
    Applies _TEAM_NAME_MAP normalization (StatsBomb names -> football-data.org names).
    """
    if not _WC_STATS_CACHE.exists():
        raise FileNotFoundError(
            f"WC stats cache not found at {_WC_STATS_CACHE}. "
            "Run: ./venv/Scripts/python.exe scripts/build_wc_priors.py"
        )

    with open(_WC_STATS_CACHE, "rb") as f:
        data: dict = pickle.load(f)

    built_at = data.pop("built_at", "unknown")
    logger.debug("WC stats cache loaded (built_at=%s, teams=%d)", built_at, len(data))

    # Apply team name normalisation map
    normalised: dict[str, dict] = {}
    for team, stats in data.items():
        canonical = _TEAM_NAME_MAP.get(team, team)
        normalised[canonical] = stats

    return normalised
