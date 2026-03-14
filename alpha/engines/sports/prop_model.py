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
from scipy.stats import nbinom, norm, poisson

logger = logging.getLogger(__name__)

# Keep production defaults aligned with the scanner and validation entrypoints.
CANONICAL_SEASON = "2025-26"

# Exponential decay factor: weight[i] = DECAY_LAMBDA ** i (index 0 = most recent)
DECAY_LAMBDA: float = 0.85

# Days-rest multipliers applied to projection before CDF
_REST_MULTIPLIER: dict[int, float] = {
    0: 0.94,   # back-to-back
    1: 0.97,
    2: 1.00,   # neutral
}
_REST_DEFAULT: float = 1.02   # 3+ days rest

# Rebound volatility dampening: single-game rebounds have ~40-50% CoV,
# and exponential-decay averages overweight outlier games.
_REB_DAMP: float = 0.90

# Markets that use Poisson CDF vs Negative Binomial CDF
_POISSON_MARKETS = {"player_assists", "player_blocks", "player_steals"}
_NEGBIN_MARKETS  = {"player_points", "player_rebounds"}

_MARKET_COL: dict[str, str] = {
    "player_points":   "PTS",
    "player_rebounds": "REB",
    "player_assists":  "AST",
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
    "player_rebounds": 0.10,  # tightened from 0.15 — OPP-04
    "player_assists":  0.12,
    "player_steals":   0.10,
    "player_blocks":   0.10,
}

_LEAGUE_AVG_DREB_PG: float = 34.0
_LEAGUE_AVG_PACE: float = 100.0

# OPP-02: Position-level scaling for opponent adjustments.
# Bigs are more affected by opponent defensive strength than guards.
_POSITION_OPP_WEIGHT: dict[str, float] = {
    "C":  1.00,
    "PF": 0.85,
    "SF": 0.65,
    "SG": 0.45,
    "PG": 0.40,
}


class PropModel:
    def __init__(self, season: str = "2025-26", stats_cache=None):
        self._season = season
        self._def_rtg_cache: dict[str, float] | None = None
        self._team_stats_cache: dict[str, dict] | None = None  # replaces per-market caches
        self._log_cache: dict[str, list[dict]] = {}
        self._stats_cache = stats_cache
        self._team_fg_cache: dict[str, tuple] = {}
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
        location: str = "all",
        position: str = "",
        team_win_prob: float = 0.50,
        player_team: str = "",
    ) -> dict | None:
        """
        Predict P(player > line) for the given market.

        Parameters:
            location: "home", "away", or "all" — filters game logs to matching
                      venue before computing the projection.
            position: Player position (C, PF, SF, SG, PG) for OPP-02
                      position-level opponent scaling.

        Returns dict with model_prob or None if insufficient data.
        """
        col = self._market_col(market)
        if col is None:
            logger.debug("Unknown market: %s", market)
            return None

        logs = self._fetch_game_logs(player_name)
        if logs is None:
            return None

        qualifying = [g for g in logs if g.get("MIN_float", 0) >= _MIN_MINUTES]
        if len(qualifying) < _MIN_GAMES:
            logger.debug(
                "%s: only %d qualifying games (need %d)",
                player_name, len(qualifying), _MIN_GAMES,
            )
            return None

        # ALGO-02: Home/Away location split
        if location in ("home", "away"):
            filtered = self._filter_by_location(qualifying, location)
            if len(filtered) >= _MIN_GAMES:
                qualifying = filtered

        values = [g[col] for g in qualifying if col in g]
        if len(values) < _MIN_GAMES:
            return None

        proj_stat = self._weighted_avg(values)
        var_stat = max(1.0, stdev(values[:20]) ** 2 if len(values[:20]) >= 2 else 1.0)
        std_stat = max(1.0, var_stat ** 0.5)

        # ALGO-04: Days-rest multiplier
        rest_mult = self._rest_multiplier(qualifying)
        proj_stat *= rest_mult

        # TEAMMATE-01: 3-signal assist context
        # Signal 1: teammate FG% trend  (40%)
        # Signal 2: team AST/FGM rate trend  (35%)
        # Signal 3: opponent ASTs allowed vs league avg  (25%)
        if market == "player_assists" and player_team:
            fg_mult, ast_rate_mult = self._fetch_team_assist_context(player_team)
            ts = self._fetch_team_per_game_stats()
            opp_data = ts.get(opponent_team, {})
            opp_ast_pg = opp_data.get("opp_ast_pg", _LEAGUE_AVGS["ast_pg"])
            league_ast = _LEAGUE_AVGS["ast_pg"]
            opp_ast_mult = max(0.92, min(1.08, opp_ast_pg / league_ast)) if league_ast > 0 else 1.0
            delta = 0.40 * (fg_mult - 1) + 0.35 * (ast_rate_mult - 1) + 0.25 * (opp_ast_mult - 1)
            proj_stat *= max(0.90, min(1.10, 1.0 + delta))

        # Rebound volatility dampening
        if market == "player_rebounds":
            proj_stat *= _REB_DAMP

        # OPP-03: Compute pace ratio for rebounds
        pace_ratio = self._compute_pace_ratio(opponent_team) if market == "player_rebounds" else 1.0

        # Opponent adjustment (OPP-02: position-level scaling)
        opp_adj = self._apply_opp_adjustment_for_market(
            proj_stat, opponent_team, market, pace_ratio=pace_ratio,
            position=position,
        )

        # ALGO-03: Appropriate CDF per market
        p_over = self._compute_p_over(market, line, opp_adj, std_stat, var_stat)
        p_over = float(np.clip(p_over, 0.01, 0.99))

        market_implied = self._american_to_implied(over_odds)
        confidence = self._classify_confidence(p_over, market_implied)

        # CONF-01: Blowout gate — downgrade when player's team is a heavy underdog
        if team_win_prob < 0.30 and confidence == "HIGH":
            confidence = "MEDIUM"

        # CONF-02: Low-line skepticism — suspiciously easy lines are traps
        if p_over > 0.85 and line < opp_adj - 1.5 * std_stat:
            if confidence == "HIGH":
                confidence = "MEDIUM"

        # CONF-03: 60% confidence floor
        if p_over < 0.60:
            confidence = "LOW"

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
            "rest_multiplier": rest_mult,
            "location_filter": location,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _market_col(self, market: str) -> str | None:
        return _MARKET_COL.get(market)

    @staticmethod
    def _weighted_avg(values: list[float]) -> float:
        """Exponential-decay weighted average: weight[i] = DECAY_LAMBDA ** i."""
        if not values:
            return 0.0
        total_w = 0.0
        total_v = 0.0
        for i, v in enumerate(values):
            w = DECAY_LAMBDA ** i
            total_w += w
            total_v += v * w
        return total_v / total_w if total_w > 0 else 0.0

    @staticmethod
    def _filter_by_location(games: list[dict], location: str) -> list[dict]:
        """Filter game logs to home or away games based on MATCHUP field."""
        result = []
        for g in games:
            matchup = str(g.get("MATCHUP", ""))
            if location == "home" and "vs." in matchup:
                result.append(g)
            elif location == "away" and "@" in matchup:
                result.append(g)
        return result

    @staticmethod
    def _rest_multiplier(qualifying: list[dict]) -> float:
        """Derive days-rest multiplier from most recent game date vs today."""
        if not qualifying:
            return 1.0
        try:
            most_recent_str = str(qualifying[0].get("GAME_DATE", ""))[:10]
            if not most_recent_str:
                return 1.0
            from datetime import datetime
            most_recent = datetime.strptime(most_recent_str, "%Y-%m-%d").date()
            rest_days = (date.today() - most_recent).days - 1
            if rest_days < 0:
                rest_days = 2
            mult = _REST_MULTIPLIER.get(rest_days, _REST_DEFAULT)
            logger.debug("Rest days=%d, multiplier=%.2f", rest_days, mult)
            return mult
        except Exception:
            return 1.0

    @staticmethod
    def _compute_p_over(
        market: str, line: float, projection: float, std: float, var: float
    ) -> float:
        """Select appropriate CDF based on market type."""
        if market in _POISSON_MARKETS:
            return float(1 - poisson.cdf(line, mu=projection))
        if market in _NEGBIN_MARKETS:
            mean_ = projection
            if var > mean_ and mean_ > 0:
                r = mean_ ** 2 / max(1e-9, var - mean_)
                p = mean_ / max(1e-9, var)
                if r > 0:
                    return float(1 - nbinom.cdf(int(line), r, p))
            return float(1 - norm.cdf(line, loc=projection, scale=std))
        return float(1 - norm.cdf(line, loc=projection, scale=std))

    def _apply_opp_adjustment_for_market(
        self, proj: float, opponent_team: str, market: str,
        player_team: str = "", pace_ratio: float = 1.0,
        position: str = "",
    ) -> float:
        """
        Scale a player's projected stat by opponent defensive quality.

        OPP-01: Rebounds use opponent DREB_pg (defensive rebounds allowed).
                High DREB_pg → strong def rebounder → REDUCE player projection.
        OPP-02: Position-level scaling — bigs get full opponent adjustment,
                guards get partial (opponent defense affects bigs more).
        OPP-03: Pace ratio applied to rebounds before opponent adjustment.
        OPP-04: Rebound cap tightened to ±10%.
        """
        cap = _OPP_ADJ_CAP.get(market, 0.10)
        lo, hi = 1.0 - cap, 1.0 + cap

        if market == "player_points":
            def_rtgs = self._fetch_def_ratings()
            opp_def_rtg = def_rtgs.get(opponent_team) if def_rtgs else None
            if opp_def_rtg and opp_def_rtg > 0:
                scale = max(lo, min(hi, _LEAGUE_AVG_DEF_RTG / opp_def_rtg))
                return proj * scale
            return proj

        ts = self._fetch_team_per_game_stats()
        opp = ts.get(opponent_team) if ts else None
        if not opp:
            return proj

        if market == "player_rebounds":
            # OPP-03: Apply pace ratio first
            proj = proj * pace_ratio

            # OPP-01: Use opponent DREB_pg with correct direction
            # High DREB_pg = strong defensive rebounder = REDUCE projection
            opp_dreb = opp.get("dreb_pg", _LEAGUE_AVG_DREB_PG)
            scale = max(lo, min(hi, _LEAGUE_AVG_DREB_PG / opp_dreb)) if opp_dreb > 0 else 1.0
            logger.debug("Reb opp adj: opp_dreb=%.1f, league_avg=%.1f, scale=%.3f",
                         opp_dreb, _LEAGUE_AVG_DREB_PG, scale)

        elif market == "player_assists":
            league_avg = _LEAGUE_AVGS["stl_pg"]
            opp_val = opp.get("stl_pg", league_avg)
            scale = max(lo, min(hi, league_avg / opp_val)) if opp_val > 0 else 1.0

        elif market == "player_threes":
            league_avg = _LEAGUE_AVGS["fg3m_pg"]
            opp_val = opp.get("opp_fg3m_pg", league_avg)
            scale = max(lo, min(hi, opp_val / league_avg)) if opp_val > 0 else 1.0

        elif market == "player_steals":
            league_avg = _LEAGUE_AVGS["ast_pg"]
            opp_val = opp.get("ast_pg", league_avg)
            scale = max(lo, min(hi, opp_val / league_avg)) if opp_val > 0 else 1.0

        elif market == "player_blocks":
            league_avg = 84.0
            opp_val = opp.get("fga_pg", league_avg)
            scale = max(lo, min(hi, opp_val / league_avg)) if opp_val > 0 else 1.0

        else:
            return proj

        # OPP-02: Dampen the adjustment toward 1.0 for non-big positions
        pos_weight = _POSITION_OPP_WEIGHT.get(position.upper(), 0.70) if position else 1.0
        scale = 1.0 + (scale - 1.0) * pos_weight

        return proj * scale

    def _compute_pace_ratio(self, opponent_team: str) -> float:
        """OPP-03: Pace ratio = matchup_avg_pace / league_avg_pace."""
        ts = self._fetch_team_per_game_stats()
        opp = ts.get(opponent_team) if ts else None
        if not opp or "pace" not in opp:
            return 1.0
        opp_pace = opp["pace"]
        if opp_pace <= 0:
            return 1.0
        return opp_pace / _LEAGUE_AVG_PACE

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

    def _fetch_team_assist_context(self, team_name: str) -> tuple[float, float]:
        """
        Returns (fg_trend_mult, ast_rate_trend_mult) for the player's team.

        Signal 1 — teammate FG% trend: last-5g FG% / season FG%
        Signal 2 — team AST rate trend: last-5g (AST/FGM) / season (AST/FGM)
          High AST rate = ball-movement offense = more assist opportunities.

        Both capped at ±8%. Returns (1.0, 1.0) on any error.
        Uses one TeamGameLogs API call, cached per team.
        """
        if team_name in self._team_fg_cache:
            return self._team_fg_cache[team_name]
        try:
            from nba_api.stats.static import teams as nba_teams  # noqa: PLC0415
            from nba_api.stats.endpoints.teamgamelogs import TeamGameLogs  # noqa: PLC0415
            all_teams = nba_teams.get_teams()
            matched = [t for t in all_teams if t["full_name"].lower() == team_name.lower()
                       or t["nickname"].lower() == team_name.lower()]
            if not matched:
                return 1.0, 1.0
            tid = matched[0]["id"]
            time.sleep(_NBA_API_SLEEP)
            gl = TeamGameLogs(team_id_nullable=str(tid), season_nullable=self._season)
            df = gl.get_data_frames()[0]
            if df.empty or len(df) < 5:
                return 1.0, 1.0

            # Signal 1: FG% trend
            fg_mult = 1.0
            if "FG_PCT" in df.columns:
                season_fg = float(df["FG_PCT"].mean())
                recent_fg = float(df["FG_PCT"].iloc[:5].mean())
                if season_fg > 0:
                    fg_mult = max(0.92, min(1.08, recent_fg / season_fg))

            # Signal 2: AST/FGM rate trend
            ast_rate_mult = 1.0
            if "AST" in df.columns and "FGM" in df.columns:
                fgm = df["FGM"].replace(0, float("nan"))
                ast_rate = df["AST"] / fgm
                season_rate = float(ast_rate.mean())
                recent_rate = float(ast_rate.iloc[:5].mean())
                if season_rate > 0 and not (season_rate != season_rate):  # nan check
                    ast_rate_mult = max(0.92, min(1.08, recent_rate / season_rate))

            result = (fg_mult, ast_rate_mult)
            self._team_fg_cache[team_name] = result
            return result
        except Exception:
            return 1.0, 1.0

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
                    "dreb_pg": _pg("DREB"),
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
                opp_ast = row.get("OPP_AST")
                if def_rtg is not None:
                    entry["def_rtg"] = float(def_rtg)
                if opp_fg3m is not None and gp > 0:
                    entry["opp_fg3m_pg"] = float(opp_fg3m) / gp
                if opp_ast is not None and gp > 0:
                    entry["opp_ast_pg"] = float(opp_ast) / gp

            # ── Pass 3: Advanced stats (PACE) ──
            try:
                time.sleep(_NBA_API_SLEEP)
                adv_df = LeagueDashTeamStats(
                    season=self._season,
                    measure_type_detailed_defense="Advanced",
                ).get_data_frames()[0]
                for _, row in adv_df.iterrows():
                    name = row.get("TEAM_NAME", "")
                    if not name:
                        continue
                    entry = result.setdefault(name, {})
                    pace = row.get("PACE")
                    if pace is not None:
                        entry["pace"] = float(pace)
            except Exception:
                pass

        except Exception as exc:
            logger.warning("nba_api team stats fetch failed: %s", exc)

        self._team_stats_cache = result
        return result
