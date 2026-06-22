"""
FootballDataClient — fetches today's fixtures from football-data.org (free tier).

API key: FOOTBALL_API_KEY env var (maps to Settings.football_api_key).
Free tier: 10 requests/minute, covers PL (EPL) and CL (UCL).

Odds are NOT available on the free tier — games are returned with -110/-110 defaults
(model falls back to market-implied probabilities).

Set FOOTBALL_API_KEY in your .env file.
Register at https://www.football-data.org
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.football-data.org/v4"

_COMP_MAP: dict[str, str] = {
    "epl": "PL",   # English Premier League
    "ucl": "CL",   # UEFA Champions League
    "wc":  "WC",   # FIFA World Cup
}


def _get_with_retry(url: str, *, headers: dict, params: dict, timeout: int = 10):
    """
    GET with one 429 retry after 60s backoff.

    On status_code==429 at attempt 0, sleeps 60s and retries once.
    On any other non-2xx status, calls raise_for_status() immediately.
    Returns requests.Response on success.
    Raises requests.exceptions.HTTPError on persistent errors.
    """
    for attempt in range(2):
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        if resp.status_code == 429 and attempt == 0:
            logger.warning("football-data.org 429 — waiting 60s before retry")
            time.sleep(60)
            continue
        resp.raise_for_status()
        return resp
    # Second attempt still returned 429 — raise to let caller handle
    resp.raise_for_status()
    return resp  # unreachable; satisfies type checkers


class FootballDataClient:
    def __init__(self, api_key: str | None = None):
        self.api_key: str = os.environ.get("FOOTBALL_API_KEY", "") if api_key is None else api_key

    def is_configured(self) -> bool:
        """Return True if an API key is set and non-empty."""
        return bool(self.api_key)

    def fetch_today_games(self, league_key: str) -> list[dict]:
        """
        Fetch today's scheduled fixtures for the given league.

        Returns a list of game dicts:
            {
                "home_team": str,
                "away_team": str,
                "home_odds": int,    # -110 default (no odds on free tier)
                "away_odds": int,    # -110 default
                "league": str,
                "event_id": str,
                "commence_time": str,
                "home_team_id": int,  # homeTeam.id from API (0 if missing)
                "away_team_id": int,  # awayTeam.id from API (0 if missing)
            }

        Returns [] on any failure.
        """
        comp = _COMP_MAP.get(league_key.lower())
        if not comp:
            logger.warning("Unknown league key: %s", league_key)
            return []

        if not self.is_configured():
            logger.warning("FOOTBALL_API_KEY not set — %s game fetch skipped", league_key)
            return []

        today = date.today().isoformat()

        try:
            resp = requests.get(
                f"{_BASE_URL}/competitions/{comp}/matches",
                headers={"X-Auth-Token": self.api_key},
                params={"dateFrom": today, "dateTo": today},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            games = []
            for match in data.get("matches", []):
                home = match.get("homeTeam", {}).get("name", "")
                away = match.get("awayTeam", {}).get("name", "")
                match_id = str(match.get("id", ""))
                commence = match.get("utcDate", "")
                if not home or not away:
                    continue
                home_id = match.get("homeTeam", {}).get("id") or 0
                away_id = match.get("awayTeam", {}).get("id") or 0
                games.append({
                    "home_team": home,
                    "away_team": away,
                    "home_odds": -110,   # no odds on free tier
                    "away_odds": -110,
                    "league": league_key,
                    "event_id": match_id,
                    "commence_time": commence,
                    "home_team_id": int(home_id),
                    "away_team_id": int(away_id),
                })

            logger.info(
                "Fetched %d %s games from football-data.org", len(games), league_key
            )
            return games

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("football-data.org HTTP %s for %s", status, league_key)
        except Exception as exc:
            logger.warning("football-data.org error for %s: %s", league_key, exc)
        return []

    def fetch_wc_games(self, date_from: str, date_to: str) -> list[dict]:
        """
        Fetch WC 2026 fixtures for a date range.

        Returns game dicts with all standard fields plus two new fields:
            "stage": str   — e.g. "GROUP_STAGE", "LAST_16", "QUARTER_FINALS",
                             "SEMI_FINALS", "THIRD_PLACE", "FINAL"
            "group": str   — e.g. "Group A" (empty string in knockout rounds)

        Returns [] on any failure (including missing API key).
        """
        if not self.is_configured():
            logger.warning("FOOTBALL_API_KEY not set — WC game fetch skipped")
            return []

        try:
            resp = _get_with_retry(
                f"{_BASE_URL}/competitions/WC/matches",
                headers={"X-Auth-Token": self.api_key},
                params={"dateFrom": date_from, "dateTo": date_to},
                timeout=10,
            )
            data = resp.json()
            _PLAYABLE = {"TIMED", "SCHEDULED", "IN_PLAY", "PAUSED"}
            games = []
            for match in data.get("matches", []):
                home = match.get("homeTeam", {}).get("name", "")
                away = match.get("awayTeam", {}).get("name", "")
                if not home or not away:
                    continue
                status = match.get("status", "")
                if status and status not in _PLAYABLE:
                    logger.debug("Skipping %s vs %s — status=%s", home, away, status)
                    continue
                games.append({
                    "home_team": home,
                    "away_team": away,
                    "home_odds": -110,
                    "away_odds": -110,
                    "league": "wc",
                    "event_id": str(match.get("id", "")),
                    "commence_time": match.get("utcDate", ""),
                    "stage": match.get("stage", ""),
                    "group": match.get("group", ""),
                })
            logger.info("Fetched %d WC games from football-data.org", len(games))
            return games

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("football-data.org HTTP %s for WC", status)
        except Exception as exc:
            logger.warning("football-data.org WC error: %s", exc)
        return []

    def fetch_team_matches(
        self,
        team_id: int,
        *,
        status: str = "FINISHED",
        limit: int = 10,
    ) -> list[dict]:
        """
        Fetch recent matches for a specific team.

        Args:
            team_id: football-data.org numeric team ID (e.g. 57 = Arsenal).
            status: match status filter (default "FINISHED").
            limit: maximum number of matches to return (default 10).

        Returns a list of raw match dicts from the API.
        Returns [] when not configured or on any failure.
        """
        if not self.is_configured():
            logger.warning("FOOTBALL_API_KEY not set — team %d match fetch skipped", team_id)
            return []

        try:
            resp = _get_with_retry(
                f"{_BASE_URL}/teams/{team_id}/matches",
                headers={"X-Auth-Token": self.api_key},
                params={"status": status, "limit": limit},
                timeout=10,
            )
            data = resp.json()
            return data.get("matches", [])
        except Exception as exc:
            logger.warning("football-data.org team %d match fetch failed: %s", team_id, exc)
            return []
