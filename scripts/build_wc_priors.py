"""
Build WC 2026 priors: Elo ratings + StatsBomb team stats.
ONE-TIME OFFLINE SCRIPT — runtime ~2-5 minutes.

Outputs:
  data/wc_priors.json         — {team_name: elo_rating} for 48 WC nations
  data/.wc_cache/wc_stats.pkl — {team_name: {avg_goals, avg_xG, avg_shots, defense_score}}

Usage:
    ./venv/Scripts/python.exe scripts/build_wc_priors.py
"""
from __future__ import annotations

import json
import logging
import pickle
import time
from datetime import datetime
from pathlib import Path

import requests
import pandas as pd
from statsbombpy import sb

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WC_SEASONS = [
    {"competition_id": 43, "season_id": 3},    # 2018 WC
    {"competition_id": 43, "season_id": 106},   # 2022 WC
]

WC_CACHE_DIR = Path("data/.wc_cache")
WC_STATS_CACHE = WC_CACHE_DIR / "wc_stats.pkl"
WC_PRIORS_PATH = Path("data/wc_priors.json")

ELO_BASE = "https://www.eloratings.net"
ELO_FALLBACK = 1500
ELO_SLEEP = 0.1

# eloratings.net uses different slugs for some teams than football-data.org names
_ELO_SLUG_OVERRIDES: dict[str, str] = {
    "Korea Republic": "South_Korea",
    "Trinidad and Tobago": "Trinidad_&_Tobago",
}

# 48 WC 2026 qualified nations (as team names on eloratings.net slug format)
WC_2026_TEAMS = [
    "Argentina", "Australia", "Belgium", "Brazil", "Cameroon", "Canada",
    "Chile", "Colombia", "Costa Rica", "Croatia", "Ecuador", "Egypt",
    "England", "France", "Germany", "Ghana", "Honduras", "Iran",
    "Italy", "Japan", "Jamaica", "Kenya", "Korea Republic", "Mali",
    "Mexico", "Morocco", "Netherlands", "New Zealand", "Nigeria",
    "Panama", "Paraguay", "Peru", "Poland", "Portugal", "Saudi Arabia",
    "Senegal", "Serbia", "Slovenia", "South Africa", "Spain",
    "Switzerland", "Trinidad and Tobago", "Tunisia", "Turkey", "Ukraine",
    "United States", "Uruguay", "Venezuela",
]


# ---------------------------------------------------------------------------
# Elo ingestion from eloratings.net
# ---------------------------------------------------------------------------

def _fetch_team_elo(team_name: str) -> int:
    """Fetch most recent Elo rating for one team from eloratings.net TSV.

    Returns ELO_FALLBACK on any failure.
    """
    slug = _ELO_SLUG_OVERRIDES.get(team_name) or team_name.replace(" ", "_").replace("'", "")
    url = f"{ELO_BASE}/{slug}.tsv"
    try:
        resp = requests.get(url, headers={"User-Agent": "alpha-terminal/1.1"}, timeout=10)
        resp.raise_for_status()
        rows = [r.split("\t") for r in resp.text.strip().splitlines() if r.strip()]
        if not rows:
            logger.warning("Empty TSV for %s — using fallback", team_name)
            return ELO_FALLBACK
        last_row = rows[-1]
        if len(last_row) <= 10:
            logger.warning("TSV column count too low for %s (got %d) — using fallback", team_name, len(last_row))
            return ELO_FALLBACK
        elo = int(float(last_row[10]))
        if not (1000 <= elo <= 2200):
            logger.warning("Elo %d out of range for %s — using fallback", elo, team_name)
            return ELO_FALLBACK
        return elo
    except Exception as exc:
        logger.warning("Elo fetch failed for %s: %s — using fallback", team_name, exc)
        return ELO_FALLBACK
    finally:
        time.sleep(ELO_SLEEP)


def _fetch_elo_ratings(teams: list[str]) -> dict[str, int]:
    """Fetch Elo ratings for all teams, printing progress."""
    ratings: dict[str, int] = {}
    n = len(teams)
    for i, team in enumerate(teams):
        print(f"\r  [{i + 1}/{n}] {team:<40}", end="", flush=True)
        ratings[team] = _fetch_team_elo(team)
    print()  # newline after progress line
    return ratings


# ---------------------------------------------------------------------------
# StatsBomb aggregation
# ---------------------------------------------------------------------------

def _fetch_statsbomb_stats() -> dict[str, dict]:
    """Aggregate 2018+2022 WC team stats from StatsBomb open data.

    Returns {team_name: {avg_goals, avg_xG, avg_shots, defense_score}}.
    Does NOT include "built_at" — caller adds that.
    """
    # Accumulators: team → offense stats
    team_offense: dict[str, dict] = {}   # team → {goals, xg, shots, n_games}
    team_defense: dict[str, float] = {}  # team → total xg conceded

    total_matches = 0

    for season in WC_SEASONS:
        cid, sid = season["competition_id"], season["season_id"]
        logger.info("Fetching StatsBomb matches: competition=%d season=%d", cid, sid)

        try:
            matches_df = sb.matches(competition_id=cid, season_id=sid)
        except Exception as exc:
            logger.warning("Could not fetch matches for season %d: %s", sid, exc)
            continue

        match_ids = matches_df["match_id"].tolist()
        n = len(match_ids)
        logger.info("  %d matches to process", n)

        for idx, match_id in enumerate(match_ids):
            print(f"\r    [{idx + 1}/{n}] match {match_id}", end="", flush=True)
            try:
                events = sb.events(match_id=match_id)
            except Exception as exc:
                logger.warning("Failed to fetch events for match %s: %s — skipping", match_id, exc)
                continue

            # Get home/away team names from matches DataFrame
            row = matches_df[matches_df["match_id"] == match_id].iloc[0]
            home_team = row["home_team"]
            away_team = row["away_team"]

            # Filter to shot events only
            shots = events[events["type"] == "Shot"].copy() if "type" in events.columns else pd.DataFrame()
            if shots.empty:
                continue

            xg_col = "shot_statsbomb_xg" if "shot_statsbomb_xg" in shots.columns else None
            outcome_col = "shot_outcome" if "shot_outcome" in shots.columns else None

            for team_name in [home_team, away_team]:
                opponent = away_team if team_name == home_team else home_team

                team_shots = shots[shots["team"] == team_name] if "team" in shots.columns else pd.DataFrame()
                opp_shots = shots[shots["team"] == opponent] if "team" in shots.columns else pd.DataFrame()

                n_shots = len(team_shots)
                xg_for = float(team_shots[xg_col].sum()) if xg_col and not team_shots.empty else 0.0
                xg_against = float(opp_shots[xg_col].sum()) if xg_col and not opp_shots.empty else 0.0
                goals = 0
                if outcome_col and not team_shots.empty:
                    goals = int((team_shots[outcome_col] == "Goal").sum())

                if team_name not in team_offense:
                    team_offense[team_name] = {"goals": 0, "xg": 0.0, "shots": 0, "n_games": 0}
                if team_name not in team_defense:
                    team_defense[team_name] = 0.0

                team_offense[team_name]["goals"] += goals
                team_offense[team_name]["xg"] += xg_for
                team_offense[team_name]["shots"] += n_shots
                team_offense[team_name]["n_games"] += 1
                team_defense[team_name] += xg_against

            total_matches += 1

        print()  # newline after season progress

    logger.info("Processed %d matches total across %d seasons", total_matches, len(WC_SEASONS))

    # Build output dict
    stats: dict[str, dict] = {}
    for team, off in team_offense.items():
        n_games = max(off["n_games"], 1)  # avoid div/0
        stats[team] = {
            "avg_goals": round(off["goals"] / n_games, 4),
            "avg_xG": round(off["xg"] / n_games, 4),
            "avg_shots": round(off["shots"] / n_games, 4),
            "defense_score": round(team_defense.get(team, 0.0) / n_games, 4),
        }

    return stats


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_wc_priors() -> None:
    """Build both output files. Safe to re-run — always overwrites."""
    WC_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # --- Elo ratings ---
    print("=== Fetching Elo ratings from eloratings.net ===")
    ratings = _fetch_elo_ratings(WC_2026_TEAMS)
    WC_PRIORS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WC_PRIORS_PATH, "w", encoding="utf-8") as f:
        json.dump(ratings, f, indent=2, ensure_ascii=False)
    logger.info("Wrote %d team Elo ratings to %s", len(ratings), WC_PRIORS_PATH)

    # --- StatsBomb stats ---
    print("\n=== Fetching StatsBomb 2018+2022 WC event data ===")
    stats = _fetch_statsbomb_stats()
    stats["built_at"] = datetime.now().isoformat(timespec="seconds")
    with open(WC_STATS_CACHE, "wb") as f:
        pickle.dump(stats, f)
    n_teams = len(stats) - 1  # exclude built_at
    logger.info("Wrote WC stats to %s (%d teams)", WC_STATS_CACHE, n_teams)

    print("\n=== Build complete ===")
    print(f"  data/wc_priors.json          -> {len(ratings)} teams")
    print(f"  data/.wc_cache/wc_stats.pkl  -> {n_teams} teams")


if __name__ == "__main__":
    build_wc_priors()
