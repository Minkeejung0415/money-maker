"""
PlayerPropsClient — fetches live NBA player prop lines from The Odds API v4.

Uses the same API key (ODDS_API_KEY) as OddsAPIClient (moneyline odds).
Supported markets: player_points, player_rebounds, player_assists, player_threes

Deduplication: when multiple bookmakers offer the same player/market for the
same game, the record with the highest (most favorable) over_odds is kept.

Degrades gracefully: returns [] on any failure.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_PROPS_URL_TEMPLATE = (
    "https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds/"
)
_EVENTS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/events/"

SUPPORTED_MARKETS = {
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
}


class PlayerPropsClient:
    def __init__(self, api_key: str | None = None):
        self.api_key: str = api_key or os.environ.get("ODDS_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch_game_props(self, event_id: str, home_team: str, away_team: str) -> list[dict]:
        """
        Fetch player prop lines for a single game.

        Returns a list of canonical prop dicts (one per player/market combination,
        deduplicated to best over_odds).
        """
        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — player props fetch skipped")
            return []

        markets_param = ",".join(SUPPORTED_MARKETS)
        try:
            resp = requests.get(
                _PROPS_URL_TEMPLATE.format(event_id=event_id),
                params={
                    "apiKey": self.api_key,
                    "regions": "us",
                    "markets": markets_param,
                    "oddsFormat": "american",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return self._parse_props(data, event_id, home_team, away_team)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("Props API HTTP error %s for event %s", status, event_id)
        except requests.exceptions.RequestException as exc:
            logger.warning("Props API network error: %s", exc)
        except Exception as exc:
            logger.warning("Props API unexpected error: %s", exc)
        return []

    def fetch_all_game_props(self, games: list[dict]) -> list[dict]:
        """
        Fetch props for all games. Each game dict must have event_id, home_team, away_team.
        Returns flat list of all canonical prop dicts.
        """
        all_props: list[dict] = []
        for game in games:
            event_id = game.get("event_id", "")
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")
            if not event_id:
                continue
            props = self.fetch_game_props(event_id, home_team, away_team)
            all_props.extend(props)
        return all_props

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_props(
        self,
        data: dict,
        event_id: str,
        home_team: str,
        away_team: str,
    ) -> list[dict]:
        """
        Parse Odds-API v4 event props response into canonical dicts.
        Deduplicates by keeping the record with the best (highest) over_odds
        for each (player, market) pair.
        """
        # best[(player, market)] = canonical dict
        best: dict[tuple[str, str], dict] = {}

        for bookmaker in data.get("bookmakers", []):
            bookmaker_key = bookmaker.get("key", "unknown")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")
                if market_key not in SUPPORTED_MARKETS:
                    continue

                outcomes = market.get("outcomes", [])
                # API format: name="Over"/"Under", description=player name
                player_outcomes: dict[str, list[dict]] = {}
                for outcome in outcomes:
                    player = outcome.get("description", "")
                    if player:
                        player_outcomes.setdefault(player, []).append(outcome)

                for player, player_outs in player_outcomes.items():
                    over_out = next(
                        (o for o in player_outs if o.get("name", "").lower() == "over"),
                        None,
                    )
                    under_out = next(
                        (o for o in player_outs if o.get("name", "").lower() == "under"),
                        None,
                    )
                    if over_out is None or under_out is None:
                        continue

                    line = float(over_out.get("point", 0))
                    over_odds = int(over_out.get("price", -110))
                    under_odds = int(under_out.get("price", -110))

                    key = (player, market_key)
                    existing = best.get(key)
                    if existing is None or over_odds > existing["over_odds"]:
                        best[key] = {
                            "event_id": event_id,
                            "home_team": home_team,
                            "away_team": away_team,
                            "player": player,
                            "market": market_key,
                            "line": line,
                            "over_odds": over_odds,
                            "under_odds": under_odds,
                            "bookmaker": bookmaker_key,
                        }

        return list(best.values())
