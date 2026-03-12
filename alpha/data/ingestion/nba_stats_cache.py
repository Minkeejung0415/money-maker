"""
Cached nba_api wrapper — rate-limited with 0.5s sleep, SQLite-backed 6-hour TTL.

All nba_api calls in the system should route through this module to avoid
rate-limiting and redundant fetches.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_DB = Path("data/.nba_api_cache.sqlite")
_CACHE_TTL_HOURS = 6
_API_SLEEP: float = 0.5


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_cache (
            cache_key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _cache_key(endpoint: str, params: dict) -> str:
    raw = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _is_fresh(created_at: str) -> bool:
    ts = datetime.fromisoformat(created_at)
    return datetime.now() - ts < timedelta(hours=_CACHE_TTL_HOURS)


class NBAStatsCache:
    """Rate-limited, SQLite-cached wrapper around nba_api endpoints."""

    def __init__(self, cache_path: Path | None = None):
        self._db_path = cache_path or _CACHE_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            _ensure_db(conn)

    def get_or_fetch(
        self,
        endpoint: str,
        params: dict,
        fetch_fn,
    ) -> Any:
        """
        Check cache first; if miss or stale, call fetch_fn() with rate-limit sleep.
        fetch_fn should return a JSON-serializable object (list/dict).
        """
        key = _cache_key(endpoint, params)

        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT data, created_at FROM api_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            if row and _is_fresh(row[1]):
                return json.loads(row[0])

        time.sleep(_API_SLEEP)
        try:
            result = fetch_fn()
        except Exception as exc:
            logger.warning("nba_api call failed (%s): %s", endpoint, exc)
            if row:
                logger.info("Returning stale cache for %s", endpoint)
                return json.loads(row[0])
            raise

        with sqlite3.connect(self._db_path) as conn:
            _ensure_db(conn)
            conn.execute(
                "INSERT OR REPLACE INTO api_cache (cache_key, data, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(result), datetime.now().isoformat()),
            )
            conn.commit()

        return result

    def fetch_player_info(self, player_id: int) -> dict:
        """Fetch CommonPlayerInfo for position data."""
        def _call():
            from nba_api.stats.endpoints.commonplayerinfo import CommonPlayerInfo
            info = CommonPlayerInfo(player_id=player_id)
            df = info.get_data_frames()[0]
            if df.empty:
                return {}
            row = df.iloc[0]
            return {
                "player_id": int(row.get("PERSON_ID", player_id)),
                "position": str(row.get("POSITION", "")),
                "team_id": int(row.get("TEAM_ID", 0)),
                "team_name": str(row.get("TEAM_NAME", "")),
                "team_abbreviation": str(row.get("TEAM_ABBREVIATION", "")),
            }
        return self.get_or_fetch("CommonPlayerInfo", {"player_id": player_id}, _call)

    def fetch_league_dash_player_stats(
        self, season: str = "2024-25", per_mode: str = "Per36"
    ) -> list[dict]:
        """Fetch league-wide player stats (per 36 min by default)."""
        def _call():
            from nba_api.stats.endpoints.leaguedashplayerstats import LeagueDashPlayerStats
            stats = LeagueDashPlayerStats(season=season, per_mode_detailed=per_mode)
            df = stats.get_data_frames()[0]
            return df.to_dict(orient="records")
        return self.get_or_fetch(
            "LeagueDashPlayerStats", {"season": season, "per_mode": per_mode}, _call
        )

    def fetch_league_dash_team_stats(
        self, season: str = "2024-25", measure_type: str = "Base"
    ) -> list[dict]:
        """Fetch league-wide team stats."""
        def _call():
            from nba_api.stats.endpoints.leaguedashteamstats import LeagueDashTeamStats
            kwargs: dict[str, Any] = {"season": season}
            if measure_type == "Defense":
                kwargs["measure_type_detailed_defense"] = "Defense"
            elif measure_type == "Advanced":
                kwargs["measure_type_detailed_defense"] = "Advanced"
            stats = LeagueDashTeamStats(**kwargs)
            df = stats.get_data_frames()[0]
            return df.to_dict(orient="records")
        return self.get_or_fetch(
            "LeagueDashTeamStats", {"season": season, "measure_type": measure_type}, _call
        )

    def fetch_player_dash_pt_shots(
        self, player_id: int, season: str = "2024-25"
    ) -> list[dict]:
        """Fetch shot distance breakdown for a player."""
        def _call():
            from nba_api.stats.endpoints.playerdashptshots import PlayerDashPtShots
            shots = PlayerDashPtShots(player_id=player_id, season=season)
            frames = shots.get_data_frames()
            if len(frames) < 2:
                return []
            df = frames[1]  # ClosestDefenderPlayerDashPtShots or general shot area
            return df.to_dict(orient="records")
        return self.get_or_fetch(
            "PlayerDashPtShots", {"player_id": player_id, "season": season}, _call
        )

    def fetch_league_dash_pt_defend(
        self, season: str = "2024-25", defense_category: str = "Overall"
    ) -> list[dict]:
        """Fetch defensive dashboard (rim protection stats)."""
        def _call():
            from nba_api.stats.endpoints.leaguedashptdefend import LeagueDashPtDefend
            defend = LeagueDashPtDefend(
                season=season,
                defense_category=defense_category,
                league_id="00",
            )
            df = defend.get_data_frames()[0]
            return df.to_dict(orient="records")
        return self.get_or_fetch(
            "LeagueDashPtDefend",
            {"season": season, "defense_category": defense_category},
            _call,
        )

    def fetch_player_game_logs(
        self, player_id: int, season: str = "2024-25"
    ) -> list[dict]:
        """Fetch player game logs for the season."""
        def _call():
            from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs
            gl = PlayerGameLogs(
                player_id_nullable=str(player_id),
                season_nullable=season,
                last_n_games_nullable="0",
            )
            df = gl.get_data_frames()[0]
            return df.to_dict(orient="records")
        return self.get_or_fetch(
            "PlayerGameLogs", {"player_id": player_id, "season": season}, _call
        )

    def resolve_player_id(self, player_name: str) -> int | None:
        """Look up player ID by full name (uses nba_api static data, no API call)."""
        try:
            from nba_api.stats.static import players as nba_players
            all_p = nba_players.get_players()
            matched = [p for p in all_p if p["full_name"].lower() == player_name.lower()]
            return matched[0]["id"] if matched else None
        except Exception:
            return None

    def fetch_matchup_defender(self, player_name: str, season: str = "2024-25") -> str | None:
        """Find the defender who guards *player_name* the most minutes."""
        def _call():
            from nba_api.stats.endpoints.leagueseasonmatchups import LeagueSeasonMatchups
            matchups = LeagueSeasonMatchups(
                off_player_id_nullable="",
                def_player_id_nullable="",
                season=season,
            )
            df = matchups.get_data_frames()[0]
            return df.to_dict(orient="records")

        try:
            rows = self.get_or_fetch(
                "LeagueSeasonMatchups",
                {"player_name": player_name, "season": season},
                _call,
            )
            best, best_min = None, 0.0
            for row in rows:
                off_name = row.get("OFF_PLAYER_NAME", "")
                if off_name.lower() != player_name.lower():
                    continue
                poss = float(row.get("PARTIAL_POSS", 0) or 0)
                if poss > best_min:
                    best_min = poss
                    best = row.get("DEF_PLAYER_NAME")
            return best if best else None
        except Exception as exc:
            logger.warning("fetch_matchup_defender failed for %s: %s", player_name, exc)
            return None

    def fetch_team_recent_form(
        self, team_name: str, last_n: int = 10, season: str = "2024-25"
    ) -> dict | None:
        """Return recent-form stats for *team_name* over the last *last_n* games."""
        team_id = self._resolve_team_id(team_name, season)
        if team_id is None:
            return None

        def _call():
            from nba_api.stats.endpoints.teamgamelog import TeamGameLog
            gl = TeamGameLog(team_id=team_id, season=season)
            df = gl.get_data_frames()[0]
            return df.to_dict(orient="records")

        try:
            rows = self.get_or_fetch(
                "TeamGameLog",
                {"team_id": team_id, "season": season},
                _call,
            )
            recent = rows[:last_n]
            if not recent:
                return None

            wins = sum(1 for g in recent if str(g.get("WL", "")).upper() == "W")
            pts = [float(g.get("PTS", 0) or 0) for g in recent]
            pts_allowed = [
                float(g.get("PTS", 0) or 0) - float(g.get("PLUS_MINUS", 0) or 0)
                for g in recent
            ]
            n = len(recent)
            return {
                "win_pct_last_n": wins / n,
                "avg_pts_last_n": sum(pts) / n,
                "avg_pts_allowed_last_n": sum(pts_allowed) / n,
            }
        except Exception as exc:
            logger.warning("fetch_team_recent_form failed for %s: %s", team_name, exc)
            return None

    def _resolve_team_id(self, team_name: str, season: str) -> int | None:
        """Look up a team ID by name from the league-wide team stats cache."""
        try:
            rows = self.fetch_league_dash_team_stats(season=season, measure_type="Base")
            for row in rows:
                if row.get("TEAM_NAME", "").lower() == team_name.lower():
                    return int(row["TEAM_ID"])
            return None
        except Exception:
            return None

    def clear_stale(self) -> int:
        """Remove entries older than TTL. Returns count of deleted rows."""
        cutoff = (datetime.now() - timedelta(hours=_CACHE_TTL_HOURS)).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM api_cache WHERE created_at < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount
