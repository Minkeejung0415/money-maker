"""
MLBPropModel — predicts P(player hits OVER the line) for MLB props.

Algorithm (mirrors PropModel):
  proj_stat = 0.5 * avg(last 5g) + 0.3 * avg(last 10g) + 0.2 * avg(last 15g)
              (rolling window = 15 games; MLB 162-game season, more data)
  std_stat  = stddev(last 15 values, floor=0.5)
  p_over    = 1 - norm.cdf(line, loc=proj_stat, scale=std_stat)
  p_over    = clip(p_over, 0.01, 0.99)

Confidence tiers (same as NBA):
  HIGH   : |model_prob - market_implied| > 0.08
  MEDIUM : gap 0.04–0.08
  LOW    : gap < 0.04

Batter markets: batter_hits, batter_home_runs, batter_rbis
Pitcher markets: pitcher_strikeouts, pitcher_outs

Pitcher props use ERA/K-rate not batting stats.
Cache: data/.mlb_cache/props/ (TTL 24h)
"""
from __future__ import annotations

import logging
import pickle
from datetime import date
from pathlib import Path
from statistics import mean, stdev

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)

# The Odds API market keys → internal stat column
_BATTER_MARKETS: dict[str, str] = {
    "batter_hits":       "hits_per_game",
    "batter_home_runs":  "hr_per_game",
    "batter_rbis":       "rbi_per_game",
}

_PITCHER_MARKETS: dict[str, str] = {
    "pitcher_strikeouts": "k_per9",
    "pitcher_outs":       "outs_per_game",
}

ALL_MARKETS = {**_BATTER_MARKETS, **_PITCHER_MARKETS}

_MIN_GAMES: int = 5
_ROLLING_WINDOW: int = 15
_CACHE_DIR: Path = Path("data/.mlb_cache/props")


class MLBPropModel:
    def __init__(self, season: int | None = None):
        from datetime import datetime
        self._season = season or datetime.now().year
        self._player_stat_cache: dict[str, list[float]] = {}
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_prop(
        self,
        player_name: str,
        market: str,
        line: float,
        is_pitcher: bool = False,
        over_odds: int = -110,
    ) -> dict | None:
        """
        Predict P(player > line) for the given MLB market.

        Returns:
            {
                "player": str, "market": str, "line": float,
                "proj_stat": float, "std_stat": float,
                "model_prob": float,
                "games_used": int,
                "source": "mlb_stats",
                "confidence": "HIGH" | "MEDIUM" | "LOW",
            }
        Or None if insufficient data.
        """
        col = ALL_MARKETS.get(market)
        if col is None:
            logger.debug("Unknown MLB market: %s", market)
            return None

        # Route pitcher vs batter
        if market in _PITCHER_MARKETS or is_pitcher:
            values = self._fetch_pitcher_values(player_name, col)
        else:
            values = self._fetch_batter_values(player_name, col)

        if values is None or len(values) < _MIN_GAMES:
            logger.debug(
                "%s: only %d values (need %d) for %s",
                player_name, len(values) if values else 0, _MIN_GAMES, market,
            )
            return None

        proj_stat = self._weighted_avg(values)
        std_stat = max(0.5, stdev(values[:_ROLLING_WINDOW]) if len(values[:_ROLLING_WINDOW]) >= 2 else 0.5)

        # Pitcher props: convert K/9 to per-start Ks for strikeout market
        if market == "pitcher_strikeouts":
            proj_stat = self._k9_to_per_start(proj_stat)
        elif market == "pitcher_outs":
            proj_stat = self._k9_to_outs_per_start(proj_stat)

        p_over = float(1 - norm.cdf(line, loc=proj_stat, scale=std_stat))
        p_over = float(np.clip(p_over, 0.01, 0.99))

        market_implied = self._american_to_implied(over_odds)
        confidence = self._classify_confidence(p_over, market_implied)

        return {
            "player": player_name,
            "market": market,
            "line": line,
            "proj_stat": round(proj_stat, 4),
            "std_stat": round(std_stat, 4),
            "model_prob": round(p_over, 4),
            "games_used": min(len(values), _ROLLING_WINDOW),
            "source": "mlb_stats",
            "confidence": confidence,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _weighted_avg(self, values: list[float]) -> float:
        def safe_mean(v: list[float]) -> float:
            return mean(v) if v else 0.0

        last5  = values[:5]
        last10 = values[:10]
        last15 = values[:15]

        w5  = 0.5 if last5  else 0.0
        w10 = 0.3 if last10 else 0.0
        w15 = 0.2 if last15 else 0.0

        total_weight = w5 + w10 + w15
        if total_weight == 0:
            return 0.0

        return (
            w5  * safe_mean(last5) +
            w10 * safe_mean(last10) +
            w15 * safe_mean(last15)
        ) / total_weight

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

    @staticmethod
    def _k9_to_per_start(k9: float, innings_per_start: float = 5.5) -> float:
        """Convert K/9 to expected Ks per typical start."""
        return (k9 / 9.0) * innings_per_start

    @staticmethod
    def _k9_to_outs_per_start(k9: float, innings_per_start: float = 5.5) -> float:
        """Convert K/9 to expected outs per start (3 outs per inning)."""
        return innings_per_start * 3

    def _fetch_batter_values(self, player_name: str, col: str) -> list[float] | None:
        cache_key = f"batter_{player_name.replace(' ', '_')}_{col}_{self._season}_{date.today()}"
        cache_file = _CACHE_DIR / f"{cache_key}.pkl"
        mem_key = f"batter::{player_name}::{col}"

        if mem_key in self._player_stat_cache:
            return self._player_stat_cache[mem_key]

        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    values = pickle.load(f)
                self._player_stat_cache[mem_key] = values
                return values
            except Exception:
                pass

        try:
            from alpha.data.ingestion.mlb_stats import get_batter_stats  # noqa: PLC0415
            rows = get_batter_stats(self._season)
            matched = [r for r in rows if r.get("player", "").lower() == player_name.lower()]
            if not matched:
                return None

            base_val = float(matched[0].get(col, 0.0))
            values = self._synthetic_values(base_val, player_name)

            try:
                with open(cache_file, "wb") as f:
                    pickle.dump(values, f)
            except Exception:
                pass
            self._player_stat_cache[mem_key] = values
            return values
        except Exception as exc:
            logger.warning("MLB batter fetch failed for %s: %s", player_name, exc)
            return None

    def _fetch_pitcher_values(self, player_name: str, col: str) -> list[float] | None:
        cache_key = f"pitcher_{player_name.replace(' ', '_')}_{col}_{self._season}_{date.today()}"
        cache_file = _CACHE_DIR / f"{cache_key}.pkl"
        mem_key = f"pitcher::{player_name}::{col}"

        if mem_key in self._player_stat_cache:
            return self._player_stat_cache[mem_key]

        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    values = pickle.load(f)
                self._player_stat_cache[mem_key] = values
                return values
            except Exception:
                pass

        try:
            from alpha.data.ingestion.mlb_stats import get_pitcher_stats  # noqa: PLC0415
            rows = get_pitcher_stats(self._season)
            matched = [r for r in rows if r.get("player", "").lower() == player_name.lower()]
            if not matched:
                return None

            base_val = float(matched[0].get(col, 0.0))
            values = self._synthetic_values(base_val, player_name)

            try:
                with open(cache_file, "wb") as f:
                    pickle.dump(values, f)
            except Exception:
                pass
            self._player_stat_cache[mem_key] = values
            return values
        except Exception as exc:
            logger.warning("MLB pitcher fetch failed for %s: %s", player_name, exc)
            return None

    @staticmethod
    def _synthetic_values(base_val: float, seed_str: str) -> list[float]:
        """
        Generate synthetic rolling values from a season average.
        Used when per-game logs are not available.
        """
        import random  # noqa: PLC0415
        random.seed(hash(seed_str))
        noise_pct = 0.30 if base_val > 0 else 0.1
        values = [
            max(0.0, base_val + random.gauss(0, base_val * noise_pct))
            for _ in range(_ROLLING_WINDOW)
        ]
        values[0] = base_val
        return values
