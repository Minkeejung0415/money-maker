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
from datetime import date

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.football-data.org/v4"

_COMP_MAP: dict[str, str] = {
    "epl": "PL",   # English Premier League
    "ucl": "CL",   # UEFA Champions League
}


class FootballDataClient:
    def __init__(self, api_key: str | None = None):
        self.api_key: str = api_key or os.environ.get("FOOTBALL_API_KEY", "")

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
                games.append({
                    "home_team": home,
                    "away_team": away,
                    "home_odds": -110,   # no odds on free tier
                    "away_odds": -110,
                    "league": league_key,
                    "event_id": match_id,
                    "commence_time": commence,
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
