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
import time
from statistics import mean, stdev
from typing import Any

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)

_MARKET_COL: dict[str, str] = {
    "player_points":   "PTS",
    "player_rebounds": "REB",
    "player_assists":  "AST",
    "player_threes":   "FG3M",
}

_MIN_MINUTES: int = 20
_MIN_GAMES: int = 5
_NBA_API_SLEEP: float = 0.6
_LEAGUE_AVG_DEF_RTG: float = 112.0  # approximate 2024-25 season average


class PropModel:
    def __init__(self, season: str = "2024-25"):
        self._season = season
        self._def_rtg_cache: dict[str, float] | None = None

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

        # Opponent defensive adjustment (points only)
        if market == "player_points":
            opp_adj = self._apply_opp_adjustment(proj_stat, opponent_team)
        else:
            opp_adj = proj_stat

        p_over = float(1 - norm.cdf(line, loc=opp_adj, scale=std_stat))
        p_over = float(np.clip(p_over, 0.01, 0.99))

        market_implied = self._american_to_implied(over_odds)
        confidence = self._classify_confidence(p_over, market_implied)

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

    def _apply_opp_adjustment(self, proj: float, opponent_team: str) -> float:
        """Scale projection by opponent defensive rating relative to league average."""
        def_rtgs = self._fetch_def_ratings()
        if not def_rtgs:
            return proj
        opp_def_rtg = def_rtgs.get(opponent_team)
        if opp_def_rtg is None or opp_def_rtg <= 0:
            return proj
        return proj * (_LEAGUE_AVG_DEF_RTG / opp_def_rtg)

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
        Fetch recent game logs for a player.  Returns list of dicts with
        stat columns, or None on any failure.
        """
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

            return rows
        except Exception as exc:
            logger.warning("nba_api game logs failed for %s: %s", player_name, exc)
            return None

    def _fetch_def_ratings(self) -> dict[str, float] | None:
        """Fetch team defensive ratings from nba_api (cached per instance)."""
        if self._def_rtg_cache is not None:
            return self._def_rtg_cache

        try:
            from nba_api.stats.endpoints.leaguedashteamstats import LeagueDashTeamStats  # noqa: PLC0415

            time.sleep(_NBA_API_SLEEP)
            stats = LeagueDashTeamStats(
                season=self._season,
                measure_type_detailed_defense="Defense",
            )
            df = stats.get_data_frames()[0]

            ratings: dict[str, float] = {}
            for _, row in df.iterrows():
                team_name = row.get("TEAM_NAME", "")
                def_rtg = row.get("DEF_RATING", None)
                if team_name and def_rtg is not None:
                    ratings[team_name] = float(def_rtg)

            self._def_rtg_cache = ratings
            return ratings
        except Exception as exc:
            logger.warning("nba_api defensive ratings fetch failed: %s", exc)
            self._def_rtg_cache = {}
            return {}
