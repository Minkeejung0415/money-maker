"""
OddsAPIClient — fetches live NBA moneyline odds from The-Odds-API (v4).

Free tier: 500 requests/month.  Register at https://the-odds-api.com
Set ODDS_API_KEY in your .env file.

Always degrades gracefully: returns [] on any failure (missing key, network
error, rate limit, unexpected response format).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ODDS_API_URL = (
    "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
)


class OddsAPIClient:
    def __init__(self, api_key: str | None = None):
        self.api_key: str = api_key or os.environ.get("ODDS_API_KEY", "")

    def is_configured(self) -> bool:
        """Return True if an API key is set and non-empty."""
        return bool(self.api_key)

    def fetch_games(self, sport_key: str) -> list[dict]:
        """
        NBA-ONLY: fetch games for a basketball_nba sport key.

        This API key is reserved for NBA usage only.  Calls for any other
        sport (soccer, MLB, etc.) will be rejected and return [].
        Use football_data_client.FootballDataClient for soccer games and
        alpha.data.ingestion.mlb_stats.fetch_today_games() for MLB games.
        """
        if "nba" not in sport_key.lower() and "basketball_nba" not in sport_key.lower():
            logger.warning(
                "OddsAPIClient.fetch_games() is NBA-only. "
                "Rejected sport_key=%r — use sport-specific free clients instead.",
                sport_key,
            )
            return []
        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — %s odds fetch skipped", sport_key)
            return []
        try:
            resp = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
                params={
                    "apiKey": self.api_key,
                    "regions": "us,eu,uk",
                    "markets": "h2h",
                    "oddsFormat": "american",
                },
                timeout=10,
            )
            resp.raise_for_status()
            games = self._parse_games(resp.json())
            for g in games:
                g["league"] = sport_key
            return games
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("Odds API HTTP %s for %s", status, sport_key)
        except Exception as exc:
            logger.warning("Odds API error for %s: %s", sport_key, exc)
        return []

    def fetch_nba_games(self) -> list[dict]:
        """
        Fetch today's NBA moneyline odds from The-Odds-API.

        Returns a list of game dicts:
            {
                "home_team": str,
                "away_team": str,
                "home_odds": int,   # American odds (e.g. -150, +130)
                "away_odds": int,
                "league": "nba",
                "event_id": str,
                "commence_time": str,
            }

        Returns [] on any failure (no key, network error, rate limit).
        """
        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — NBA odds fetch skipped")
            return []

        try:
            resp = requests.get(
                _ODDS_API_URL,
                params={
                    "apiKey": self.api_key,
                    "regions": "us,eu,uk",
                    "markets": "h2h",
                    "oddsFormat": "american",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()
            return self._parse_games(data)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("Odds API HTTP error %s — skipping sports vertical", status)
        except requests.exceptions.RequestException as exc:
            logger.warning("Odds API network error: %s — skipping sports vertical", exc)
        except Exception as exc:
            logger.warning("Odds API unexpected error: %s — skipping sports vertical", exc)
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_games(self, data: list[dict]) -> list[dict]:
        """Parse Odds-API v4 response into canonical game dicts."""
        games: list[dict] = []
        for event in data:
            try:
                game = self._parse_event(event)
                if game is not None:
                    games.append(game)
            except Exception as exc:
                logger.debug("Failed to parse event: %s — %s", event.get("id"), exc)
        return games

    def _parse_event(self, event: dict) -> dict | None:
        """
        Extract home/away teams and best available h2h American odds from
        a single Odds-API v4 event object.
        """
        home_team: str = event.get("home_team", "")
        away_team: str = event.get("away_team", "")
        event_id: str = event.get("id", "")
        commence_time: str = event.get("commence_time", "")

        if not home_team or not away_team:
            return None

        home_odds, away_odds = self._extract_best_odds(event, home_team, away_team)

        return {
            "home_team": home_team,
            "away_team": away_team,
            "home_odds": home_odds,
            "away_odds": away_odds,
            "league": "nba",
            "event_id": event_id,
            "commence_time": commence_time,
        }

    def _extract_best_odds(
        self,
        event: dict,
        home_team: str,
        away_team: str,
    ) -> tuple[int, int]:
        """
        Walk the bookmakers list and return the first usable
        American moneyline odds pair (home, away).

        Falls back to (-110, -110) if no odds are found.
        """
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                if home_team in outcomes and away_team in outcomes:
                    return int(outcomes[home_team]), int(outcomes[away_team])
        return -110, -110
