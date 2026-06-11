"""
MLBScheduleClient — schedule + probable pitchers from the FREE MLB StatsAPI.

Endpoint: https://statsapi.mlb.com/api/v1/schedule
  params: sportId=1, date=YYYY-MM-DD, hydrate=probablePitcher

Cost model:
  - This feed is FREE and may be refreshed liberally.  It must NEVER touch
    The Odds API or any paid endpoint — schedule discovery and pitcher
    confirmation cost zero credits.
  - Cached separately from paid odds (data/cache/mlb/schedule/).
  - Probable pitchers can change up to game time, so the cache has a
    configurable short TTL (default 15 minutes).

Fail-closed rules:
  - Pitchers are never invented.  A side without an announced probable
    pitcher gets None name/id and the game is marked
    ``probable_pitchers_confirmed=False``.
  - Pitcher changes between refreshes are detected and logged; the latest
    changes are exposed via ``last_pitcher_changes``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_STATSAPI_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache" / "mlb" / "schedule"

DEFAULT_PROBABLES_TTL_SECONDS = 900  # 15 minutes

_CACHE_SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MLBScheduleClient:
    def __init__(
        self,
        cache_dir: Path | None = _CACHE_DIR,
        probables_ttl_seconds: int = DEFAULT_PROBABLES_TTL_SECONDS,
        session: requests.Session | None = None,
    ):
        self._cache_dir = cache_dir
        self.probables_ttl_seconds = probables_ttl_seconds
        self._session = session or requests.Session()
        # Pitcher changes detected during the most recent refresh:
        # [{event_id, side, old_name, new_name, old_id, new_id}]
        self.last_pitcher_changes: list[dict] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def fetch_schedule(self, game_date: str, force_refresh: bool = False) -> list[dict]:
        """
        Return the MLB slate for ``game_date`` (YYYY-MM-DD).

        Served from the free-cache when younger than the probable-pitcher
        TTL; otherwise refetched (free).  Returns [] on any failure.
        """
        cached = self._load_cache(game_date)
        if (
            not force_refresh
            and cached is not None
            and self._cache_age_seconds(cached) < self.probables_ttl_seconds
        ):
            return cached.get("games", [])

        games = self._fetch_from_statsapi(game_date)
        if not games:
            # Network failure: fall back to a stale cache rather than
            # pretending the slate is empty.
            return cached.get("games", []) if cached else []

        self.last_pitcher_changes = self._detect_pitcher_changes(
            cached.get("games", []) if cached else [], games
        )
        self._write_cache(game_date, games)
        return games

    # ------------------------------------------------------------------
    # StatsAPI fetch + parse
    # ------------------------------------------------------------------

    def _fetch_from_statsapi(self, game_date: str) -> list[dict]:
        try:
            resp = self._session.get(
                _STATSAPI_SCHEDULE_URL,
                params={
                    "sportId": 1,
                    "date": game_date,
                    "hydrate": "probablePitcher,team,venue",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("MLB StatsAPI schedule fetch failed for %s: %s", game_date, exc)
            return []

        games: list[dict] = []
        for date_block in data.get("dates", []):
            for raw in date_block.get("games", []):
                parsed = self._parse_game(raw, game_date)
                if parsed is not None:
                    games.append(parsed)
        return games

    @staticmethod
    def _parse_game(raw: dict, game_date: str) -> dict | None:
        game_pk = raw.get("gamePk")
        teams = raw.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        home_team = (home.get("team") or {}).get("name", "")
        away_team = (away.get("team") or {}).get("name", "")
        if not game_pk or not home_team or not away_team:
            return None

        home_pp = home.get("probablePitcher") or {}
        away_pp = away.get("probablePitcher") or {}
        home_name = home_pp.get("fullName") or None
        away_name = away_pp.get("fullName") or None
        home_id = home_pp.get("id")
        away_id = away_pp.get("id")

        # Never invent a pitcher: confirmation requires BOTH sides named.
        confirmed = bool(home_name and away_name)

        # doubleHeader: "N" = no, "Y" = traditional, "S" = split.
        dh = str(raw.get("doubleHeader", "N")).upper()

        status = raw.get("status", {}) or {}
        return {
            "event_id": f"mlb-statsapi-{game_pk}",
            "statsapi_game_id": int(game_pk),
            "game_date": raw.get("officialDate") or game_date,
            "commence_time_utc": raw.get("gameDate", ""),
            "home_team": home_team,
            "away_team": away_team,
            "venue": (raw.get("venue") or {}).get("name"),
            "probable_pitcher_home": home_name,
            "probable_pitcher_away": away_name,
            "probable_pitcher_home_id": int(home_id) if home_id is not None else None,
            "probable_pitcher_away_id": int(away_id) if away_id is not None else None,
            "probable_pitchers_confirmed": confirmed,
            "game_status": status.get("detailedState") or status.get("abstractGameState", ""),
            "doubleheader_flag": dh in ("Y", "S"),
            "game_number": int(raw.get("gameNumber", 1) or 1),
        }

    # ------------------------------------------------------------------
    # Pitcher change detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_pitcher_changes(old_games: list[dict], new_games: list[dict]) -> list[dict]:
        old_by_id = {g["event_id"]: g for g in old_games}
        changes: list[dict] = []
        for game in new_games:
            prev = old_by_id.get(game["event_id"])
            if prev is None:
                continue
            for side in ("home", "away"):
                old_name = prev.get(f"probable_pitcher_{side}")
                new_name = game.get(f"probable_pitcher_{side}")
                if old_name != new_name:
                    change = {
                        "event_id": game["event_id"],
                        "side": side,
                        "old_name": old_name,
                        "new_name": new_name,
                        "old_id": prev.get(f"probable_pitcher_{side}_id"),
                        "new_id": game.get(f"probable_pitcher_{side}_id"),
                    }
                    changes.append(change)
                    logger.warning(
                        "Probable pitcher change %s (%s): %s -> %s",
                        game["event_id"], side, old_name, new_name,
                    )
        return changes

    # ------------------------------------------------------------------
    # Free cache (separate from paid odds cache)
    # ------------------------------------------------------------------

    def _cache_file(self, game_date: str) -> Path:
        return self._cache_dir / f"schedule_{game_date}.json"

    def _load_cache(self, game_date: str) -> dict | None:
        if self._cache_dir is None:
            return None
        path = self._cache_file(game_date)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt schedule cache %s — ignoring", path.name)
            return None
        return data if isinstance(data, dict) and "games" in data else None

    def _write_cache(self, game_date: str, games: list[dict]) -> None:
        if self._cache_dir is None:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "meta": {
                "fetched_at_utc": _utc_now().isoformat(),
                "source": "mlb_statsapi_free",
            },
            "games": games,
        }
        self._cache_file(game_date).write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _cache_age_seconds(cached: dict) -> float:
        fetched_at = (cached.get("meta") or {}).get("fetched_at_utc")
        if not fetched_at:
            return float("inf")
        try:
            ts = datetime.fromisoformat(fetched_at)
        except ValueError:
            return float("inf")
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (_utc_now() - ts).total_seconds()
