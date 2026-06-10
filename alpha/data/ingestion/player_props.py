"""
PlayerPropsClient — fetches live NBA player prop lines from The Odds API v4.

Uses the same API key (ODDS_API_KEY) as OddsAPIClient (moneyline odds).
Supported markets: player_points, player_rebounds, player_assists, player_threes
(player_threes is supported but DISABLED by default until PropModel fully
supports FG3M — enable via the ``markets`` constructor argument).

Correctness: raw records are preserved per
    (event_id, player, market, line, bookmaker)
so that alternative lines (e.g. Over 25.5 -110 vs Over 26.5 +105) are never
collapsed into one another.  ``aggregate_prop_lines()`` groups records by
(event_id, player, market, line) and computes best/median prices per line.

Budget policy: paid odds fetches are cached to disk once per day by default
(``max_paid_fetches_per_day=1``).  Manual ``force_refresh=True`` and
selected-event refresh are supported; there is intentionally NO automatic
polling loop.  Quota headers (x-requests-remaining/used/last) are recorded
in the cache metadata.

Degrades gracefully: returns [] on any failure.
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

# Budget-first defaults: player_threes is excluded until PropModel fully
# supports FG3M.  Pass markets=[..., "player_threes"] to opt in.
DEFAULT_MARKETS = ["player_points", "player_rebounds", "player_assists"]

_CACHE_SCHEMA_VERSION = 2


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _american_to_implied(odds: int | float) -> float:
    """Convert American odds to raw implied probability (vig included)."""
    odds = float(odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _implied_to_american(p: float) -> int:
    """Convert implied probability back to (rounded) American odds."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def _median_american(prices: list[int]) -> int:
    """
    Median of American odds, computed in implied-probability space so that
    the +/- discontinuity around even money does not distort the result.
    """
    if not prices:
        return 0
    med_p = median(_american_to_implied(p) for p in prices)
    return _implied_to_american(med_p)


def aggregate_prop_lines(raw_records: list[dict]) -> list[dict]:
    """
    Group raw bookmaker records by (event_id, player, market, line) and
    compute, per group:
      - best_over_odds / best_over_book   (highest over price)
      - best_under_odds / best_under_book (highest under price)
      - median_over_odds / median_under_odds (across books)

    Alternative lines are preserved as separate output records.  Best over
    and best under may come from different bookmakers; the back-compat
    over_odds/under_odds/bookmaker fields always come from the SAME book
    (the best-over book) so the pair stays internally consistent for
    no-vig calculations.
    """
    groups: dict[tuple, list[dict]] = {}
    for rec in raw_records:
        key = (rec["event_id"], rec["player"], rec["market"], rec["line"])
        groups.setdefault(key, []).append(rec)

    aggregated: list[dict] = []
    for (event_id, player, market, line), recs in groups.items():
        best_over = max(recs, key=lambda r: r["over_odds"])
        best_under = max(recs, key=lambda r: r["under_odds"])
        first = recs[0]
        aggregated.append({
            "event_id": event_id,
            "home_team": first.get("home_team", ""),
            "away_team": first.get("away_team", ""),
            "player": player,
            "market": market,
            "line": line,
            # Back-compat pair: both sides from the best-over book.
            "over_odds": best_over["over_odds"],
            "under_odds": best_over["under_odds"],
            "bookmaker": best_over["bookmaker"],
            # Cross-book aggregates.
            "best_over_odds": best_over["over_odds"],
            "best_over_book": best_over["bookmaker"],
            "best_under_odds": best_under["under_odds"],
            "best_under_book": best_under["bookmaker"],
            "median_over_odds": _median_american([r["over_odds"] for r in recs]),
            "median_under_odds": _median_american([r["under_odds"] for r in recs]),
            "num_books": len(recs),
            "fetched_at_utc": first.get("fetched_at_utc", ""),
            "commence_time": first.get("commence_time", ""),
        })
    return aggregated


class PlayerPropsClient:
    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: Path | None = _CACHE_DIR,
        markets: list[str] | None = None,
        max_paid_fetches_per_day: int = 1,
    ):
        self.api_key: str = api_key or os.environ.get("ODDS_API_KEY", "")
        self._cache_dir = cache_dir
        self.max_paid_fetches_per_day = max_paid_fetches_per_day
        self.last_quota: dict[str, float | None] = {
            "credits_last": None,
            "credits_used": None,
            "credits_remaining": None,
        }

        requested = list(markets) if markets is not None else list(DEFAULT_MARKETS)
        unsupported = [m for m in requested if m not in SUPPORTED_MARKETS]
        if unsupported:
            logger.warning("Ignoring unsupported prop markets: %s", unsupported)
        self.markets = [m for m in requested if m in SUPPORTED_MARKETS]

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Single-event fetch (PAID — consumes API credits)
    # ------------------------------------------------------------------

    def fetch_game_props_raw(
        self, event_id: str, home_team: str, away_team: str, commence_time: str = ""
    ) -> list[dict]:
        """
        Fetch player prop lines for a single game.  PAID call.

        Returns raw records, one per (player, market, line, bookmaker).
        Records quota headers on self.last_quota.
        """
        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — player props fetch skipped")
            return []

        markets_param = ",".join(self.markets)
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
            self._record_quota_headers(resp)
            data: dict[str, Any] = resp.json()
            return self._parse_props_raw(data, event_id, home_team, away_team, commence_time)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("Props API HTTP error %s for event %s", status, event_id)
        except requests.exceptions.RequestException as exc:
            logger.warning("Props API network error: %s", exc)
        except Exception as exc:
            logger.warning("Props API unexpected error: %s", exc)
        return []

    def fetch_game_props(self, event_id: str, home_team: str, away_team: str) -> list[dict]:
        """
        Fetch player prop lines for a single game, aggregated per
        (player, market, line).  Back-compat wrapper around the raw fetch.
        """
        raw = self.fetch_game_props_raw(event_id, home_team, away_team)
        return aggregate_prop_lines(raw)

    # ------------------------------------------------------------------
    # Multi-game fetch with budget-first daily cache
    # ------------------------------------------------------------------

    def fetch_all_game_props(
        self,
        games: list[dict],
        force_refresh: bool = False,
        selected_event_ids: list[str] | None = None,
    ) -> list[dict]:
        """
        Fetch props for all games (aggregated per player/market/line).

        Budget policy:
          - Default: at most ``max_paid_fetches_per_day`` paid fetch cycles
            per day; re-runs within the same day read from the date-based
            cache and consume ZERO API credits.
          - ``force_refresh=True``: manually re-fetch (paid).
          - ``force_refresh=True`` + ``selected_event_ids``: re-fetch ONLY
            the selected events and merge into today's cache (paid, but
            cheaper than a full refresh).
          - There is NO automatic polling loop.
        """
        cache = self._load_cache() if self._cache_dir is not None else None

        if not force_refresh:
            if cache is not None:
                logger.info("Odds API props cache hit — zero credits used")
                return cache.get("props", [])
            # No cache today.  A fresh daily fetch counts as paid fetch #1.
            paid_count = 0
            if paid_count >= self.max_paid_fetches_per_day:
                logger.warning(
                    "Daily paid-fetch budget exhausted (%d) — returning no props",
                    self.max_paid_fetches_per_day,
                )
                return []
            raw = self._paid_fetch(games)
            return self._write_cache(raw, refresh_mode="daily", paid_count=1)

        # force_refresh=True
        prior_count = cache["meta"].get("paid_fetch_count", 0) if cache else 0

        if selected_event_ids is not None:
            selected = set(selected_event_ids)
            target_games = [g for g in games if g.get("event_id") in selected]
            new_raw = self._paid_fetch(target_games)
            kept = [
                r for r in (cache.get("raw", []) if cache else [])
                if r.get("event_id") not in selected
            ]
            return self._write_cache(
                kept + new_raw, refresh_mode="force_selected", paid_count=prior_count + 1,
            )

        raw = self._paid_fetch(games)
        return self._write_cache(raw, refresh_mode="force_full", paid_count=prior_count + 1)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _paid_fetch(self, games: list[dict]) -> list[dict]:
        """Issue one paid props request per game; returns raw records."""
        all_raw: list[dict] = []
        for game in games:
            event_id = game.get("event_id", "")
            if not event_id:
                continue
            all_raw.extend(
                self.fetch_game_props_raw(
                    event_id,
                    game.get("home_team", ""),
                    game.get("away_team", ""),
                    game.get("commence_time", ""),
                )
            )
        return all_raw

    def _cache_file(self) -> Path:
        return self._cache_dir / f"props_{date.today()}.json"

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
            logger.warning("Corrupt props cache %s — ignoring", cache_file.name)
            return None
        if isinstance(data, list):  # legacy pre-v2 format: flat props list
            return {"meta": {"paid_fetch_count": 1}, "raw": [], "props": data}
        if isinstance(data, dict) and "props" in data:
            return data
        return None

    def _write_cache(self, raw: list[dict], refresh_mode: str, paid_count: int) -> list[dict]:
        """Aggregate raw records, persist cache with metadata, return props."""
        props = aggregate_prop_lines(raw)
        if self._cache_dir is not None:
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
                    "markets": self.markets,
                },
                "raw": raw,
                "props": props,
            }
            self._cache_file().write_text(json.dumps(payload), encoding="utf-8")
        return props

    def _record_quota_headers(self, resp: requests.Response) -> None:
        """Parse The Odds API quota headers from a paid response."""
        def _f(name: str) -> float | None:
            v = resp.headers.get(name)
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

    def _parse_props_raw(
        self,
        data: dict,
        event_id: str,
        home_team: str,
        away_team: str,
        commence_time: str = "",
    ) -> list[dict]:
        """
        Parse Odds-API v4 event props response into raw records, one per
        (player, market, line, bookmaker).  Nothing is deduplicated here:
        different lines from the same book and the same line from different
        books are all preserved.
        """
        fetched_at = _utc_now_iso()
        commence = commence_time or data.get("commence_time", "")
        raw: list[dict] = []
        seen: set[tuple] = set()

        for bookmaker in data.get("bookmakers", []):
            bookmaker_key = bookmaker.get("key", "unknown")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")
                if market_key not in self.markets:
                    continue

                # API format: name="Over"/"Under", description=player name.
                # Group outcomes per (player, line) so alternates stay apart.
                sides: dict[tuple[str, float], dict[str, dict]] = {}
                for outcome in market.get("outcomes", []):
                    player = outcome.get("description", "")
                    if not player:
                        continue
                    try:
                        line = float(outcome.get("point", 0))
                    except (TypeError, ValueError):
                        continue
                    side = outcome.get("name", "").lower()
                    if side not in ("over", "under"):
                        continue
                    sides.setdefault((player, line), {})[side] = outcome

                for (player, line), outs in sides.items():
                    over_out = outs.get("over")
                    under_out = outs.get("under")
                    if over_out is None or under_out is None:
                        continue
                    key = (event_id, player, market_key, line, bookmaker_key)
                    if key in seen:
                        continue
                    seen.add(key)
                    raw.append({
                        "event_id": event_id,
                        "home_team": home_team,
                        "away_team": away_team,
                        "player": player,
                        "market": market_key,
                        "line": line,
                        "over_odds": int(over_out.get("price", -110)),
                        "under_odds": int(under_out.get("price", -110)),
                        "bookmaker": bookmaker_key,
                        "fetched_at_utc": fetched_at,
                        "commence_time": commence,
                    })

        return raw
