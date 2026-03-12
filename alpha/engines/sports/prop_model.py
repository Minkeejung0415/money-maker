"""
PropModel — predicts P(player hits OVER the line) for NBA player props.

Algorithm:
  proj_stat = 0.5 * avg(last 5g) + 0.3 * avg(last 10g) + 0.2 * avg(last 20g)
              (only games where player played ≥ 20 minutes)
  std_stat  = stddev(last 20g values, floor=1.0)
  opp_adj   = proj_stat * (league_avg_def_rtg / opp_def_rtg)  # points only
  p_over    = 1 - norm.cdf(line, loc=opp_adj, scale=std_stat)
  p_over    = clip(p_over, 0.01, 0.99)

Confidence tiers (based on gap vs market-implied probability):
  HIGH   : |model_prob - market_implied| > 0.08
  MEDIUM : gap 0.04–0.08
  LOW    : gap < 0.04 — do not use in SGP combinations

Requires nba_api. Sleeps 0.6 s between API calls to respect rate limits.
Returns None if < 5 qualifying games are available.
"""
from __future__ import annotations

import logging
import pickle
import time
from datetime import date
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)

# Keep production defaults aligned with the scanner and validation entrypoints.
CANONICAL_SEASON = "2025-26"

_MARKET_COL: dict[str, str] = {
    "player_points":   "PTS",
    "player_rebounds": "REB",
    "player_assists":  "AST",
    "player_threes":   "FG3M",
}

_MIN_MINUTES: int = 20
_MIN_GAMES: int = 5
_NBA_API_SLEEP: float = 0.3          # reduced from 0.6 — nba_api handles this fine
_LEAGUE_AVG_DEF_RTG: float = 112.0
_CACHE_DIR: Path = Path("data/.prop_cache")

# League averages per game (used when opp data is missing)
_LEAGUE_AVGS: dict[str, float] = {
    "reb_pg":   43.5,
    "ast_pg":   25.5,
    "stl_pg":    7.8,
    "fg3m_pg":  13.0,
}

# How strongly each market reacts to opponent quality (max ± adjustment)
# e.g. 0.15 = cap at 15% up or down from raw projection
_OPP_ADJ_CAP: dict[str, float] = {
    "player_points":   0.15,
    "player_rebounds": 0.15,
    "player_assists":  0.12,
    "player_threes":   0.12,
    "player_steals":   0.10,
    "player_blocks":   0.10,
}


class PropModel:
    def __init__(self, season: str = "2025-26", stats_cache=None):
        self._season = season
        self._def_rtg_cache: dict[str, float] | None = None
        self._team_stats_cache: dict[str, dict] | None = None  # replaces per-market caches
        self._log_cache: dict[str, list[dict]] = {}
        self._stats_cache = stats_cache
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_prop(
        self,
        player_name: str,
        market: str,
        line: float,
        opponent_team: str,
        over_odds: int = -110,
    ) -> dict | None:
        """
        Predict P(player > line) for the given market.

        Returns:
            {
                "player": str, "market": str, "line": float,
                "proj_stat": float, "std_stat": float,
                "model_prob": float,   # P(over)
                "games_used": int,
                "source": "nba_api",
                "confidence": "HIGH" | "MEDIUM" | "LOW",
            }
        Or None if insufficient data.
        """
        col = self._market_col(market)
        if col is None:
            logger.debug("Unknown market: %s", market)
            return None

        logs = self._fetch_game_logs(player_name)
        if logs is None:
            return None

        # Filter to games with ≥ MIN_MINUTES played
        qualifying = [g for g in logs if g.get("MIN_float", 0) >= _MIN_MINUTES]
        if len(qualifying) < _MIN_GAMES:
            logger.debug(
                "%s: only %d qualifying games (need %d)",
                player_name, len(qualifying), _MIN_GAMES,
            )
            return None

        values = [g[col] for g in qualifying if col in g]
        if len(values) < _MIN_GAMES:
            return None

        proj_stat = self._weighted_avg(values)
        std_stat = max(1.0, stdev(values[:20]) if len(values[:20]) >= 2 else 1.0)

        # Opponent adjustment — all markets scaled by opponent defensive profile
        opp_adj = self._apply_opp_adjustment_for_market(proj_stat, opponent_team, market)

        p_over = float(1 - norm.cdf(line, loc=opp_adj, scale=std_stat))
        p_over = float(np.clip(p_over, 0.01, 0.99))

        market_implied = self._american_to_implied(over_odds)
        confidence = self._classify_confidence(p_over, market_implied)

        recent_trade = False
        if self._stats_cache:
            try:
                tc = self._stats_cache.fetch_player_team_game_count(player_name, self._season)
                if tc and tc["current_team_games"] < 5:
                    recent_trade = True
                    if confidence == "HIGH":
                        confidence = "MEDIUM"
            except Exception:
                pass

        return {
            "player": player_name,
            "market": market,
            "line": line,
            "proj_stat": round(opp_adj, 2),
            "std_stat": round(std_stat, 2),
            "model_prob": round(p_over, 4),
            "games_used": min(len(qualifying), 20),
            "source": "nba_api",
            "confidence": confidence,
            "recent_trade": recent_trade,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _market_col(self, market: str) -> str | None:
        return _MARKET_COL.get(market)

    def _weighted_avg(self, values: list[float]) -> float:
        """
        Weighted rolling average:
          0.5 × avg(last 5) + 0.3 × avg(last 10) + 0.2 × avg(last 20)
        Falls back gracefully if fewer values are available.
        """
        def safe_mean(v: list[float]) -> float:
            return mean(v) if v else 0.0

        last5  = values[:5]
        last10 = values[:10]
        last20 = values[:20]

        w5  = 0.5 if len(last5)  >= 1 else 0.0
        w10 = 0.3 if len(last10) >= 1 else 0.0
        w20 = 0.2 if len(last20) >= 1 else 0.0

        total_weight = w5 + w10 + w20
        if total_weight == 0:
            return 0.0

        weighted = (
            w5  * safe_mean(last5) +
            w10 * safe_mean(last10) +
            w20 * safe_mean(last20)
        ) / total_weight

        return weighted

    def _apply_opp_adjustment_for_market(
        self, proj: float, opponent_team: str, market: str
    ) -> float:
        """
        Scale a player's projected stat by opponent defensive quality for that market.

        Points   → opponent DEF_RTG  (higher = worse defense = more points allowed)
        Rebounds → opponent REB/game (higher = more boards grabbed = fewer for us)
        Assists  → opponent STL/game (higher = more disruption = fewer assists)
        Threes   → opponent FG3M allowed/game (higher = allows more 3s = easier)
        Steals   → opponent AST/game (more ball movement = more steal opportunities)
        Blocks   → opponent FG2A/game (more paint attempts = more block opportunities)

        All adjustments are capped per _OPP_ADJ_CAP to avoid extreme swings.
        Returns proj unchanged for unknown markets or missing data.
        """
        cap = _OPP_ADJ_CAP.get(market, 0.10)
        lo, hi = 1.0 - cap, 1.0 + cap

        # Points: use existing DEF_RTG path
        if market == "player_points":
            def_rtgs = self._fetch_def_ratings()
            opp_def_rtg = def_rtgs.get(opponent_team) if def_rtgs else None
            if opp_def_rtg and opp_def_rtg > 0:
                scale = max(lo, min(hi, _LEAGUE_AVG_DEF_RTG / opp_def_rtg))
                return proj * scale
            return proj

        # All other markets: pull from the unified team stats cache
        ts = self._fetch_team_per_game_stats()
        opp = ts.get(opponent_team) if ts else None
        if not opp:
            return proj

        if market == "player_rebounds":
            # High-rebounding opponent → leaves fewer boards → scale down
            league_avg = _LEAGUE_AVGS["reb_pg"]
            opp_val = opp.get("reb_pg", league_avg)
            scale = max(lo, min(hi, league_avg / opp_val)) if opp_val > 0 else 1.0

        elif market == "player_assists":
            # High-steal opponent → disrupts passing lanes → scale down
            league_avg = _LEAGUE_AVGS["stl_pg"]
            opp_val = opp.get("stl_pg", league_avg)
            scale = max(lo, min(hi, league_avg / opp_val)) if opp_val > 0 else 1.0

        elif market == "player_threes":
            # Opponent allows many 3s → easier to hit → scale up (and vice versa)
            league_avg = _LEAGUE_AVGS["fg3m_pg"]
            opp_val = opp.get("opp_fg3m_pg", league_avg)
            scale = max(lo, min(hi, opp_val / league_avg)) if opp_val > 0 else 1.0

        elif market == "player_steals":
            # Opponent with high AST → more ball movement → more steal chances → scale up
            league_avg = _LEAGUE_AVGS["ast_pg"]
            opp_val = opp.get("ast_pg", league_avg)
            scale = max(lo, min(hi, opp_val / league_avg)) if opp_val > 0 else 1.0

        elif market == "player_blocks":
            # Opponent with more paint attempts → more block chances → scale up
            league_avg = 84.0  # approx FGA/game league avg
            opp_val = opp.get("fga_pg", league_avg)
            scale = max(lo, min(hi, opp_val / league_avg)) if opp_val > 0 else 1.0

        else:
            return proj

        return proj * scale

    def _classify_confidence(self, model_prob: float, market_implied: float) -> str:
        gap = abs(model_prob - market_implied)
        if gap > 0.08:
            return "HIGH"
        if gap >= 0.04:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _american_to_implied(american_odds: int) -> float:
        if american_odds > 0:
            return 100 / (american_odds + 100)
        return abs(american_odds) / (abs(american_odds) + 100)

    # ------------------------------------------------------------------
    # nba_api calls
    # ------------------------------------------------------------------

    def _fetch_game_logs(self, player_name: str) -> list[dict] | None:
        """
        Fetch recent game logs for a player. Caches to disk (same-day TTL)
        and in memory — repeat calls for the same player are instant.
        """
        # 1. In-memory cache (within same run)
        if player_name in self._log_cache:
            return self._log_cache[player_name]

        # 2. Disk cache (same-day TTL)
        cache_file = _CACHE_DIR / f"{player_name.replace(' ', '_')}_{date.today()}.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    rows = pickle.load(f)
                self._log_cache[player_name] = rows
                return rows
            except Exception:
                pass  # corrupt cache — refetch

        # 3. Live fetch from nba_api
        try:
            from nba_api.stats.static import players as nba_players  # noqa: PLC0415
            from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs  # noqa: PLC0415

            all_players = nba_players.get_players()
            matched = [p for p in all_players if p["full_name"].lower() == player_name.lower()]
            if not matched:
                logger.debug("Player not found in nba_api: %s", player_name)
                return None

            player_id = matched[0]["id"]
            time.sleep(_NBA_API_SLEEP)
            gl = PlayerGameLogs(
                player_id_nullable=str(player_id),
                season_nullable=self._season,
                last_n_games_nullable="0",
            )
            df = gl.get_data_frames()[0]

            if df.empty:
                return None

            rows: list[dict] = []
            for _, row in df.iterrows():
                entry: dict[str, Any] = dict(row)
                # Parse minutes played to float
                min_val = entry.get("MIN", 0)
                try:
                    if isinstance(min_val, str) and ":" in min_val:
                        parts = min_val.split(":")
                        entry["MIN_float"] = float(parts[0]) + float(parts[1]) / 60
                    else:
                        entry["MIN_float"] = float(min_val)
                except (ValueError, TypeError):
                    entry["MIN_float"] = 0.0
                rows.append(entry)

            # Save to disk + memory cache
            try:
                with open(cache_file, "wb") as f:
                    pickle.dump(rows, f)
            except Exception:
                pass
            self._log_cache[player_name] = rows
            return rows
        except Exception as exc:
            logger.warning("nba_api game logs failed for %s: %s", player_name, exc)
            return None

    def _fetch_def_ratings(self) -> dict[str, float]:
        """Fetch opponent DEF_RTG from the unified team stats cache."""
        ts = self._fetch_team_per_game_stats()
        return {team: v["def_rtg"] for team, v in ts.items() if "def_rtg" in v}

    def _fetch_team_per_game_stats(self) -> dict[str, dict]:
        """
        Fetch per-game stats for all 30 teams in one API call (cached per instance).

        Two requests total (Base + Defense measure types), merged into one dict:
          {team_name: {reb_pg, ast_pg, stl_pg, blk_pg, fga_pg, fg3m_pg,
                       opp_fg3m_pg, def_rtg}}

        Falls back gracefully — returns {} on any error so callers skip adjustment.
        """
        if self._team_stats_cache is not None:
            return self._team_stats_cache

        result: dict[str, dict] = {}

        try:
            from nba_api.stats.endpoints.leaguedashteamstats import LeagueDashTeamStats  # noqa: PLC0415

            # ── Pass 1: Base stats (REB, AST, STL, BLK, FGA, FG3M per game) ──
            time.sleep(_NBA_API_SLEEP)
            base_df = LeagueDashTeamStats(season=self._season).get_data_frames()[0]
            for _, row in base_df.iterrows():
                name = row.get("TEAM_NAME", "")
                gp = float(row.get("GP", 0) or 0)
                if not name or gp == 0:
                    continue

                def _pg(col: str) -> float:
                    v = row.get(col)
                    return float(v) / gp if v is not None else 0.0

                result[name] = {
                    "reb_pg":  _pg("REB"),
                    "ast_pg":  _pg("AST"),
                    "stl_pg":  _pg("STL"),
                    "blk_pg":  _pg("BLK"),
                    "fga_pg":  _pg("FGA"),
                    "fg3m_pg": _pg("FG3M"),
                }

            # ── Pass 2: Defense stats (DEF_RTG + opp FG3M) ──
            time.sleep(_NBA_API_SLEEP)
            def_df = LeagueDashTeamStats(
                season=self._season,
                measure_type_detailed_defense="Defense",
            ).get_data_frames()[0]
            for _, row in def_df.iterrows():
                name = row.get("TEAM_NAME", "")
                if not name:
                    continue
                entry = result.setdefault(name, {})
                def_rtg = row.get("DEF_RATING")
                opp_fg3m = row.get("OPP_FG3M")
                gp = float(row.get("GP", 0) or 0)
                if def_rtg is not None:
                    entry["def_rtg"] = float(def_rtg)
                if opp_fg3m is not None and gp > 0:
                    entry["opp_fg3m_pg"] = float(opp_fg3m) / gp

        except Exception as exc:
            logger.warning("nba_api team stats fetch failed: %s", exc)

        self._team_stats_cache = result
        return result
