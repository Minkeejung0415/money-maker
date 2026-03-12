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
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_DB = Path("data/.nba_api_cache.sqlite")
_CACHE_TTL_HOURS = 6
_CACHE_TTL_H2H_HOURS = 24
_API_SLEEP: float = 0.5
_API_TIMEOUT: int = 10
CANONICAL_SEASON = "2025-26"


def _call_with_timeout(fn, timeout: int = _API_TIMEOUT) -> Any:
    """Run *fn()* in a thread with a wall-clock timeout. Raises TimeoutError on expiry."""
    result_box: list[Any] = []
    exc_box: list[Exception] = []

    def _worker():
        try:
            result_box.append(fn())
        except Exception as e:
            exc_box.append(e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise TimeoutError(f"nba_api call timed out after {timeout}s")
    if exc_box:
        raise exc_box[0]
    return result_box[0]


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
        Uses a 10-second thread-based timeout on the fetch call.
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
            result = _call_with_timeout(fetch_fn, timeout=10)
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
        self, season: str = "2025-26", per_mode: str = "Per36"
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
        self, season: str = CANONICAL_SEASON, measure_type: str = "Base"
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
        self, player_id: int, season: str = CANONICAL_SEASON
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
        self, season: str = CANONICAL_SEASON, defense_category: str = "Overall"
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
        self, player_id: int, season: str = CANONICAL_SEASON
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

    def fetch_matchup_defender(self, player_name: str, season: str = CANONICAL_SEASON) -> str | None:
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
        self, team_name: str, last_n: int = 10, season: str = CANONICAL_SEASON
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

    def fetch_head_to_head(
        self,
        home_team: str,
        away_team: str,
        seasons: tuple[str, ...] = (CANONICAL_SEASON, "2024-25"),
    ) -> dict | None:
        """
        Return H2H record between two teams over recent seasons.
        Returns None if fewer than 4 games found.
        Cached with 24-hour TTL (H2H doesn't change intraday).
        """
        home_id = self._resolve_team_id(home_team, seasons[0])
        away_id = self._resolve_team_id(away_team, seasons[0])
        if home_id is None or away_id is None:
            return None

        home_wins = 0
        away_wins = 0

        for season in seasons:
            try:
                def _fetch_home(tid=home_id, s=season):
                    from nba_api.stats.endpoints.teamgamelog import TeamGameLog
                    gl = TeamGameLog(team_id=tid, season=s)
                    df = gl.get_data_frames()[0]
                    return df.to_dict(orient="records")

                home_logs = self.get_or_fetch(
                    "TeamGameLog_h2h",
                    {"team_id": home_id, "season": season},
                    _fetch_home,
                )

                for g in home_logs:
                    matchup = str(g.get("MATCHUP", ""))
                    opp_in_matchup = away_team.split()[-1].lower()
                    if opp_in_matchup not in matchup.lower():
                        continue
                    if str(g.get("WL", "")).upper() == "W":
                        home_wins += 1
                    else:
                        away_wins += 1
            except Exception as exc:
                logger.debug("H2H fetch failed for season %s: %s", season, exc)

        total = home_wins + away_wins
        if total < 4:
            return None

        return {
            "home_wins": home_wins,
            "away_wins": away_wins,
            "total_games": total,
            "home_win_pct_h2h": home_wins / total,
        }

    def fetch_player_team_game_count(
        self, player_name: str, season: str = CANONICAL_SEASON
    ) -> dict | None:
        """
        Return how many games a player has played for their current team vs total.
        Used to detect recently traded players.
        """
        player_id = self.resolve_player_id(player_name)
        if player_id is None:
            return None

        try:
            logs = self.fetch_player_game_logs(player_id, season)
            if not logs:
                return None

            info = self.fetch_player_info(player_id)
            current_team_abbr = info.get("team_abbreviation", "")
            if not current_team_abbr:
                return None

            total = len(logs)
            current = sum(
                1 for g in logs
                if current_team_abbr in str(g.get("MATCHUP", ""))
            )

            return {"current_team_games": current, "total_games": total}
        except Exception as exc:
            logger.debug("Player team game count failed for %s: %s", player_name, exc)
            return None

    def fetch_player_team_map(self, season: str = CANONICAL_SEASON) -> dict[str, str]:
        """
        Return {player_name_lower: full_team_name} for all active players.

        Builds the map by cross-referencing:
          - LeagueDashPlayerStats (Totals) → player → team abbreviation
          - LeagueDashTeamStats (Base)     → team abbreviation → full team name
        """
        try:
            team_rows = self.fetch_league_dash_team_stats(season=season, measure_type="Base")
            abbrev_to_full: dict[str, str] = {
                str(r.get("TEAM_ABBREVIATION", "")): str(r.get("TEAM_NAME", ""))
                for r in team_rows
                if r.get("TEAM_ABBREVIATION") and r.get("TEAM_NAME")
            }
            player_rows = self.fetch_league_dash_player_stats(season=season, per_mode="Totals")
            result: dict[str, str] = {}
            for row in player_rows:
                name = str(row.get("PLAYER_NAME", "")).strip()
                abbr = str(row.get("TEAM_ABBREVIATION", "")).strip()
                if name and abbr:
                    full = abbrev_to_full.get(abbr, abbr)
                    result[name.lower()] = full
            return result
        except Exception as exc:
            logger.warning("fetch_player_team_map failed: %s", exc)
            return {}

    def clear_stale(self) -> int:
        """Remove entries older than TTL. Returns count of deleted rows."""
        cutoff = (datetime.now() - timedelta(hours=_CACHE_TTL_HOURS)).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM api_cache WHERE created_at < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount
