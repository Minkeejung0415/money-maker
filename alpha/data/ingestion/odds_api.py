"""
OddsAPIClient — fetches live NBA moneyline odds from The-Odds-API (v4).

Free tier: 500 requests/month.  Register at https://the-odds-api.com
Set ODDS_API_KEY in your .env file.

Correctness:
  - Every bookmaker odds pair is retained (``bookmaker_odds``) instead of
    keeping only the first usable book.
  - ``home_odds``/``away_odds`` are the BEST available price per side
    (book recorded in ``best_home_book``/``best_away_book``).
  - Consensus fair probability removes vig independently per book, then
    takes the median across books — best prices from different books are
    never combined into one synthetic no-vig pair.

Budget policy:
  - Default regions=["us"] (each extra region multiplies credit cost).
  - Date-based cache: one paid fetch per day by default
    (``max_paid_fetches_per_day=1``); manual ``force_refresh=True`` only.
  - Quota headers (x-requests-remaining/used/last) are recorded.
  - The GET /events endpoint is FREE and should be used to discover the
    slate before any paid odds call (``fetch_events()``).
  - There is intentionally NO automatic polling loop.

Always degrades gracefully: returns [] on any failure (missing key, network
error, rate limit, unexpected response format).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import requests

_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache" / "odds"

logger = logging.getLogger(__name__)

_ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
_EVENTS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/events/"

# Budget-first default: US books only.  Each additional region in a request
# multiplies the credit cost of the call.
DEFAULT_REGIONS = ["us"]

_CACHE_SCHEMA_VERSION = 2


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Odds math helpers (module-level, import-friendly)
# ---------------------------------------------------------------------------

def american_to_implied(odds: int | float) -> float:
    """Convert American odds to raw implied probability (vig included)."""
    odds = float(odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def remove_vig_pair(home_odds: int | float, away_odds: int | float) -> tuple[float, float]:
    """
    Remove the bookmaker margin from a SINGLE book's two-way odds pair.
    Returns (fair_home_prob, fair_away_prob) summing to 1.0.

    Must only be applied to odds from the same bookmaker — combining best
    prices from different books produces a fake low-vig pair.
    """
    h = american_to_implied(home_odds)
    a = american_to_implied(away_odds)
    total = h + a
    if total <= 0:
        return 0.5, 0.5
    return h / total, a / total


def build_consensus_moneyline(bookmaker_odds: list[dict]) -> dict | None:
    """
    Build the consensus market view from per-bookmaker odds pairs.

    For each book: remove vig independently -> fair home probability.
    Consensus = median fair home probability across books;
    away probability = 1 - home probability.

    Each entry needs ``home_odds`` and ``away_odds``.  Returns None when no
    valid books are present (fail closed — callers must not invent a prior).
    """
    fair_home_probs: list[float] = []
    for entry in bookmaker_odds:
        try:
            h, a = float(entry["home_odds"]), float(entry["away_odds"])
        except (KeyError, TypeError, ValueError):
            continue
        if h == 0 or a == 0:
            continue
        fair_home, _ = remove_vig_pair(h, a)
        fair_home_probs.append(fair_home)

    if not fair_home_probs:
        return None
    consensus_home = float(median(fair_home_probs))
    return {
        "consensus_home_prob": round(consensus_home, 6),
        "consensus_away_prob": round(1.0 - consensus_home, 6),
        "num_books": len(fair_home_probs),
    }


class OddsAPIClient:
    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: Path | None = _CACHE_DIR,
        regions: list[str] | None = None,
        max_paid_fetches_per_day: int = 1,
    ):
        self.api_key: str = api_key or os.environ.get("ODDS_API_KEY", "")
        self._cache_dir = cache_dir
        self.regions = list(regions) if regions is not None else list(DEFAULT_REGIONS)
        self.max_paid_fetches_per_day = max_paid_fetches_per_day
        self.last_quota: dict[str, float | None] = {
            "credits_last": None,
            "credits_used": None,
            "credits_remaining": None,
        }

    def is_configured(self) -> bool:
        """Return True if an API key is set and non-empty."""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # FREE endpoint: events (no quota cost)
    # ------------------------------------------------------------------

    def fetch_events(self) -> list[dict]:
        """
        Fetch the upcoming NBA event slate from the FREE events endpoint.

        Returns [{event_id, home_team, away_team, commence_time}].
        This call does NOT consume quota — use it to discover today's slate
        before deciding which events deserve a paid odds/props call.  Never
        use paid odds calls just to check whether games exist.
        """
        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — events fetch skipped")
            return []
        try:
            resp = requests.get(
                _EVENTS_URL,
                params={"apiKey": self.api_key},
                timeout=10,
            )
            resp.raise_for_status()
            events = []
            for ev in resp.json():
                if not ev.get("home_team") or not ev.get("away_team"):
                    continue
                events.append({
                    "event_id": ev.get("id", ""),
                    "home_team": ev["home_team"],
                    "away_team": ev["away_team"],
                    "commence_time": ev.get("commence_time", ""),
                })
            return events
        except Exception as exc:
            logger.warning("Odds API events fetch failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Paid odds fetches
    # ------------------------------------------------------------------

    def fetch_games(self, sport_key: str) -> list[dict]:
        """
        NBA-ONLY: fetch games for a basketball_nba sport key.  PAID call.

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
                    "regions": ",".join(self.regions),
                    "markets": "h2h",
                    "oddsFormat": "american",
                },
                timeout=10,
            )
            resp.raise_for_status()
            self._record_quota_headers(resp)
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

    def fetch_nba_games(self, force_refresh: bool = False) -> list[dict]:
        """
        Fetch today's NBA moneyline odds from The-Odds-API.  PAID call,
        served from the date-based cache by default.

        Returns a list of game dicts:
            {
                "home_team": str,
                "away_team": str,
                "home_odds": int,        # BEST American odds across books
                "away_odds": int,
                "best_home_book": str,
                "best_away_book": str,
                "bookmaker_odds": [{bookmaker, home_odds, away_odds}],
                "consensus_home_prob": float | None,  # median per-book no-vig
                "consensus_away_prob": float | None,
                "num_books": int,
                "league": "nba",
                "event_id": str,
                "commence_time": str,
                "snapshot_timestamp": str,  # fetched_at_utc
            }

        Budget policy: re-runs within the same day read from cache and
        consume zero API credits unless ``force_refresh=True``.
        Returns [] on any failure (no key, network error, rate limit).
        """
        cache = self._load_cache()
        if not force_refresh and cache is not None:
            logger.info("Odds API games cache hit — zero credits used")
            return cache.get("games", [])

        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — NBA odds fetch skipped")
            return []

        prior_count = cache["meta"].get("paid_fetch_count", 0) if cache else 0
        if not force_refresh and prior_count >= self.max_paid_fetches_per_day:
            logger.warning(
                "Daily paid-fetch budget exhausted (%d) — returning cached/empty",
                self.max_paid_fetches_per_day,
            )
            return cache.get("games", []) if cache else []

        try:
            resp = requests.get(
                _ODDS_API_URL,
                params={
                    "apiKey": self.api_key,
                    "regions": ",".join(self.regions),
                    "markets": "h2h",
                    "oddsFormat": "american",
                },
                timeout=10,
            )
            resp.raise_for_status()
            self._record_quota_headers(resp)
            data: list[dict[str, Any]] = resp.json()
            games = self._parse_games(data)
            self._write_cache(
                games,
                refresh_mode="force_full" if force_refresh else "daily",
                paid_count=prior_count + 1,
            )
            return games
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("Odds API HTTP error %s — skipping sports vertical", status)
        except requests.exceptions.RequestException as exc:
            logger.warning("Odds API network error: %s — skipping sports vertical", exc)
        except Exception as exc:
            logger.warning("Odds API unexpected error: %s — skipping sports vertical", exc)
        return []

    # ------------------------------------------------------------------
    # Internal: cache + quota
    # ------------------------------------------------------------------

    def _cache_file(self) -> Path:
        return self._cache_dir / f"games_{date.today()}.json"

    def _load_cache(self) -> dict | None:
        """Load today's cache.  Legacy list-format caches are upgraded."""
        if self._cache_dir is None:
            return None
        cache_file = self._cache_file()
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt games cache %s — ignoring", cache_file.name)
            return None
        if isinstance(data, list):  # legacy pre-v2 format: flat games list
            return {"meta": {"paid_fetch_count": 1}, "games": data}
        if isinstance(data, dict) and "games" in data:
            return data
        return None

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
            },
            "games": games,
        }
        self._cache_file().write_text(json.dumps(payload), encoding="utf-8")

    def _record_quota_headers(self, resp: requests.Response) -> None:
        """Parse The Odds API quota headers from a paid response."""
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
                "Odds API quota: last=%s used=%s remaining=%s",
                quota["credits_last"], quota["credits_used"], quota["credits_remaining"],
            )

    # ------------------------------------------------------------------
    # Internal: parsing
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
        Extract home/away teams, every bookmaker's h2h odds pair, the best
        price per side, and the median no-vig consensus probability from a
        single Odds-API v4 event object.
        """
        home_team: str = event.get("home_team", "")
        away_team: str = event.get("away_team", "")
        event_id: str = event.get("id", "")
        commence_time: str = event.get("commence_time", "")

        if not home_team or not away_team:
            return None

        bookmaker_odds = self._extract_bookmaker_odds(event, home_team, away_team)
        consensus = build_consensus_moneyline(bookmaker_odds)

        if bookmaker_odds:
            best_home = max(bookmaker_odds, key=lambda b: b["home_odds"])
            best_away = max(bookmaker_odds, key=lambda b: b["away_odds"])
            home_odds, best_home_book = best_home["home_odds"], best_home["bookmaker"]
            away_odds, best_away_book = best_away["away_odds"], best_away["bookmaker"]
        else:
            # No books: keep the long-standing degraded fallback so the
            # pipeline doesn't crash, but flag it via num_books=0 /
            # consensus=None so models can fail closed.
            home_odds, away_odds = -110, -110
            best_home_book = best_away_book = ""

        return {
            "home_team": home_team,
            "away_team": away_team,
            "home_odds": home_odds,
            "away_odds": away_odds,
            "best_home_book": best_home_book,
            "best_away_book": best_away_book,
            "bookmaker_odds": bookmaker_odds,
            "consensus_home_prob": consensus["consensus_home_prob"] if consensus else None,
            "consensus_away_prob": consensus["consensus_away_prob"] if consensus else None,
            "num_books": consensus["num_books"] if consensus else 0,
            "league": "nba",
            "event_id": event_id,
            "commence_time": commence_time,
            "snapshot_timestamp": _utc_now_iso(),
        }

    @staticmethod
    def _extract_bookmaker_odds(
        event: dict, home_team: str, away_team: str
    ) -> list[dict]:
        """Collect EVERY bookmaker's American h2h odds pair for this event."""
        pairs: list[dict] = []
        for bookmaker in event.get("bookmakers", []):
            book_key = bookmaker.get("key", "unknown")
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                if home_team in outcomes and away_team in outcomes:
                    pairs.append({
                        "bookmaker": book_key,
                        "home_odds": int(outcomes[home_team]),
                        "away_odds": int(outcomes[away_team]),
                    })
                    break  # one h2h market per book
        return pairs
