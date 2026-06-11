"""
MLBOddsClient — budget-aware MLB moneyline (h2h) odds from The Odds API v4.

Sport key: ``baseball_mlb``.

Budget policy (matches docs/mlb_odds_budget_policy.md):
  - GET /events is FREE — always use it to discover the slate first.
  - Paid h2h odds: at most ``max_paid_fetches_per_day`` (default 1) per
    calendar day, served from a date-based cache otherwise.
  - ``force_refresh=True`` and per-event ``selected_event_ids`` refreshes
    are MANUAL operator actions only.  There is intentionally NO automatic
    polling loop anywhere in this module.
  - Quota headers (x-requests-remaining / x-requests-used /
    x-requests-last) are recorded into cache metadata.

Correctness (mirrors the NBA adapter fixes):
  - Every bookmaker's h2h pair is retained.
  - best_home_odds / best_away_odds are the best price per side with the
    book recorded — the first bookmaker is never assumed best.
  - Consensus = median of PER-BOOK no-vig home probabilities.  Best prices
    from different books are never combined into a synthetic no-vig pair.

Fail-closed:
  - An event with zero valid bookmaker pairs carries ``home_odds=None``,
    ``consensus_*=None`` and ``num_books=0`` — no -110 placeholder is ever
    fabricated for MLB.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

from alpha.data.ingestion.odds_api import build_consensus_moneyline, remove_vig_pair

logger = logging.getLogger(__name__)

SPORT_KEY = "baseball_mlb"
_ODDS_URL = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/"
_EVENTS_URL = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/events/"
_EVENT_ODDS_URL = (
    f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/events/{{event_id}}/odds/"
)

# Budget-first defaults: US books, h2h only.  Extra regions/markets
# multiply the per-call credit cost.
DEFAULT_REGIONS = ["us"]
DEFAULT_MARKETS = ["h2h"]

_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache" / "mlb" / "odds"
_CACHE_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MLBOddsClient:
    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: Path | None = _CACHE_DIR,
        regions: list[str] | None = None,
        markets: list[str] | None = None,
        max_paid_fetches_per_day: int = 1,
    ):
        self.api_key: str = api_key or os.environ.get("ODDS_API_KEY", "")
        self._cache_dir = cache_dir
        self.regions = list(regions) if regions is not None else list(DEFAULT_REGIONS)
        self.markets = list(markets) if markets is not None else list(DEFAULT_MARKETS)
        self.max_paid_fetches_per_day = max_paid_fetches_per_day
        self.last_quota: dict[str, float | None] = {
            "credits_last": None,
            "credits_used": None,
            "credits_remaining": None,
        }

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # FREE endpoint: events slate (zero credits)
    # ------------------------------------------------------------------

    def fetch_events(self) -> list[dict]:
        """Discover the upcoming MLB slate.  FREE — consumes no credits."""
        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — MLB events fetch skipped")
            return []
        try:
            resp = requests.get(_EVENTS_URL, params={"apiKey": self.api_key}, timeout=10)
            resp.raise_for_status()
            events = []
            for ev in resp.json():
                if not ev.get("home_team") or not ev.get("away_team"):
                    continue
                events.append({
                    "event_id": ev.get("id", ""),
                    "home_team": ev["home_team"],
                    "away_team": ev["away_team"],
                    "commence_time_utc": ev.get("commence_time", ""),
                })
            return events
        except Exception as exc:
            logger.warning("MLB Odds API events fetch failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # PAID: full-slate moneyline odds, daily-budgeted
    # ------------------------------------------------------------------

    def fetch_moneyline(
        self,
        force_refresh: bool = False,
        selected_event_ids: list[str] | None = None,
    ) -> list[dict]:
        """
        Fetch MLB h2h odds.  Served from today's cache when present; the
        paid endpoint is hit at most ``max_paid_fetches_per_day`` times per
        day unless ``force_refresh=True`` (manual only).

        ``selected_event_ids`` performs a MANUAL per-event refresh and
        merges results into the cache without consuming the full-slate
        daily budget slot.

        Returns [] on any failure (fail closed — never invents odds).
        """
        if selected_event_ids is not None:
            return self._fetch_selected_events(selected_event_ids)

        cache = self._load_cache()
        if not force_refresh and cache is not None:
            logger.info("MLB odds cache hit — zero credits used")
            return cache.get("games", [])

        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — MLB odds fetch skipped")
            return []

        prior_count = cache["meta"].get("paid_fetch_count", 0) if cache else 0
        if not force_refresh and prior_count >= self.max_paid_fetches_per_day:
            logger.warning(
                "MLB daily paid-fetch budget exhausted (%d) — returning cached/empty",
                self.max_paid_fetches_per_day,
            )
            return cache.get("games", []) if cache else []

        try:
            resp = requests.get(
                _ODDS_URL,
                params={
                    "apiKey": self.api_key,
                    "regions": ",".join(self.regions),
                    "markets": ",".join(self.markets),
                    "oddsFormat": "american",
                },
                timeout=10,
            )
            resp.raise_for_status()
            self._record_quota_headers(resp)
            games = self._parse_events(resp.json())
            self._write_cache(
                games,
                refresh_mode="force_full" if force_refresh else "daily",
                paid_count=prior_count + 1,
            )
            return games
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("MLB Odds API HTTP %s — fail closed, no odds", status)
        except Exception as exc:
            logger.warning("MLB Odds API error: %s — fail closed, no odds", exc)
        return []

    # ------------------------------------------------------------------
    # PAID: manual selected-event refresh (merges into cache)
    # ------------------------------------------------------------------

    def _fetch_selected_events(self, event_ids: list[str]) -> list[dict]:
        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — selected MLB refresh skipped")
            return []
        refreshed: list[dict] = []
        for event_id in event_ids:
            try:
                resp = requests.get(
                    _EVENT_ODDS_URL.format(event_id=event_id),
                    params={
                        "apiKey": self.api_key,
                        "regions": ",".join(self.regions),
                        "markets": ",".join(self.markets),
                        "oddsFormat": "american",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                self._record_quota_headers(resp)
                parsed = self._parse_event(resp.json())
                if parsed is not None:
                    refreshed.append(parsed)
            except Exception as exc:
                logger.warning("Selected MLB event %s refresh failed: %s", event_id, exc)

        if refreshed:
            self._merge_into_cache(refreshed)
        return refreshed

    def _merge_into_cache(self, refreshed: list[dict]) -> None:
        cache = self._load_cache()
        games = cache.get("games", []) if cache else []
        by_id = {g.get("event_id"): g for g in games}
        for game in refreshed:
            by_id[game["event_id"]] = game
        paid_count = cache["meta"].get("paid_fetch_count", 0) if cache else 0
        self._write_cache(
            list(by_id.values()), refresh_mode="selected_events", paid_count=paid_count
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_events(self, data: list[dict[str, Any]]) -> list[dict]:
        games: list[dict] = []
        for event in data:
            try:
                parsed = self._parse_event(event)
                if parsed is not None:
                    games.append(parsed)
            except Exception as exc:
                logger.debug("Failed to parse MLB event %s: %s", event.get("id"), exc)
        return games

    def _parse_event(self, event: dict) -> dict | None:
        home_team = event.get("home_team", "")
        away_team = event.get("away_team", "")
        if not home_team or not away_team:
            return None

        bookmaker_odds = self._extract_bookmaker_odds(event, home_team, away_team)
        consensus = build_consensus_moneyline(bookmaker_odds)

        if bookmaker_odds:
            best_home = max(bookmaker_odds, key=lambda b: b["home_odds"])
            best_away = max(bookmaker_odds, key=lambda b: b["away_odds"])
            best_home_odds: int | None = best_home["home_odds"]
            best_home_book: str | None = best_home["bookmaker"]
            best_away_odds: int | None = best_away["away_odds"]
            best_away_book: str | None = best_away["bookmaker"]
        else:
            # Fail closed: no books means NO odds — never fabricate -110.
            best_home_odds = best_away_odds = None
            best_home_book = best_away_book = None

        return {
            "event_id": event.get("id", ""),
            "league": SPORT_KEY,
            "home_team": home_team,
            "away_team": away_team,
            "commence_time_utc": event.get("commence_time", ""),
            "fetched_at_utc": _utc_now_iso(),
            "bookmaker_odds": bookmaker_odds,
            "best_home_odds": best_home_odds,
            "best_home_book": best_home_book,
            "best_away_odds": best_away_odds,
            "best_away_book": best_away_book,
            "consensus_home_no_vig_prob": (
                consensus["consensus_home_prob"] if consensus else None
            ),
            "consensus_away_no_vig_prob": (
                consensus["consensus_away_prob"] if consensus else None
            ),
            "num_books": consensus["num_books"] if consensus else 0,
        }

    @staticmethod
    def _extract_bookmaker_odds(event: dict, home_team: str, away_team: str) -> list[dict]:
        """Collect EVERY bookmaker's h2h pair, with per-book no-vig probs."""
        pairs: list[dict] = []
        for bookmaker in event.get("bookmakers", []):
            book_key = bookmaker.get("key", "unknown")
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = {o.get("name"): o.get("price") for o in market.get("outcomes", [])}
                if home_team not in outcomes or away_team not in outcomes:
                    continue
                try:
                    home_odds = int(outcomes[home_team])
                    away_odds = int(outcomes[away_team])
                except (TypeError, ValueError):
                    continue
                if home_odds == 0 or away_odds == 0:
                    continue
                fair_home, fair_away = remove_vig_pair(home_odds, away_odds)
                pairs.append({
                    "bookmaker": book_key,
                    "home_odds": home_odds,
                    "away_odds": away_odds,
                    "no_vig_home_prob": round(fair_home, 6),
                    "no_vig_away_prob": round(fair_away, 6),
                })
                break  # one h2h market per book
        return pairs

    # ------------------------------------------------------------------
    # Cache + quota
    # ------------------------------------------------------------------

    def _cache_file(self) -> Path:
        return self._cache_dir / f"h2h_{date.today()}.json"

    def _load_cache(self) -> dict | None:
        if self._cache_dir is None:
            return None
        path = self._cache_file()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt MLB odds cache %s — ignoring", path.name)
            return None
        return data if isinstance(data, dict) and "games" in data else None

    def _write_cache(self, games: list[dict], refresh_mode: str, paid_count: int) -> None:
        if self._cache_dir is None:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "meta": {
                "fetched_at_utc": _utc_now_iso(),
                "refresh_mode": refresh_mode,
                "paid_fetch_count": paid_count,
                "credits_last": self.last_quota.get("credits_last"),
                "credits_used": self.last_quota.get("credits_used"),
                "credits_remaining": self.last_quota.get("credits_remaining"),
                "regions": self.regions,
                "markets": self.markets,
                "sport_key": SPORT_KEY,
            },
            "games": games,
        }
        self._cache_file().write_text(json.dumps(payload), encoding="utf-8")

    def _record_quota_headers(self, resp: requests.Response) -> None:
        def _f(name: str) -> float | None:
            v = resp.headers.get(name) if hasattr(resp, "headers") else None
            try:
                return float(v) if v is not None else None
            except (ValueError, TypeError):
                return None

        quota = {
            "credits_last": _f("x-requests-last"),
            "credits_used": _f("x-requests-used"),
            "credits_remaining": _f("x-requests-remaining"),
        }
        if any(v is not None for v in quota.values()):
            self.last_quota = quota
            logger.info(
                "MLB Odds API quota: last=%s used=%s remaining=%s",
                quota["credits_last"], quota["credits_used"], quota["credits_remaining"],
            )
