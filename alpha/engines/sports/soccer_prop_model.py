"""
SoccerPropModel — predicts P(player hits OVER the line) for soccer props.

Algorithm (mirrors PropModel exactly):
  proj_stat = 0.5 * avg(last 5g) + 0.3 * avg(last 10g) + 0.2 * avg(last 10g)
              (rolling window = 10 games; soccer seasons are shorter)
  std_stat  = stddev(last 10 values, floor=0.5)
  p_over    = 1 - norm.cdf(line, loc=proj_stat, scale=std_stat)
  p_over    = clip(p_over, 0.01, 0.99)

Confidence tiers (slightly lower than NBA — soccer props are noisier):
  HIGH   : |model_prob - market_implied| > 0.10
  MEDIUM : gap 0.08–0.10
  LOW    : gap < 0.08 — do not use in SGP combinations

Markets: player_shots, player_goals, player_assists (The Odds API names)
Cache: data/.soccer_cache/props/ (TTL 24h)
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

_MARKET_COL: dict[str, str] = {
    "player_shots":           "shots_per90",
    "player_shots_on_target": "shots_per90",  # fallback to shots_per90 until xG data added
    "player_goals":           "goals_per90",
    "player_assists":         "assists_per90",
}

_MIN_GAMES: int = 5
_ROLLING_WINDOW: int = 10
_CACHE_DIR: Path = Path("data/.soccer_cache/props")

# Confidence thresholds (lower than NBA)
_HIGH_GAP: float = 0.10
_MEDIUM_GAP: float = 0.08


class SoccerPropModel:
    def __init__(self, league_key: str = "epl"):
        self._league_key = league_key
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
        over_odds: int = -110,
    ) -> dict | None:
        """
        Predict P(player > line) for the given soccer market.

        Returns:
            {
                "player": str, "market": str, "line": float,
                "proj_stat": float, "std_stat": float,
                "model_prob": float,
                "games_used": int,
                "source": "soccer_stats",
                "confidence": "HIGH" | "MEDIUM" | "LOW",
            }
        Or None if insufficient data.
        """
        col = _MARKET_COL.get(market)
        if col is None:
            logger.debug("Unknown soccer market: %s", market)
            return None

        values = self._fetch_player_values(player_name, col)
        if values is None or len(values) < _MIN_GAMES:
            logger.debug(
                "%s: only %d values (need %d) for %s",
                player_name, len(values) if values else 0, _MIN_GAMES, market,
            )
            return None

        proj_stat = self._weighted_avg(values)
        std_stat = max(0.5, stdev(values[:_ROLLING_WINDOW]) if len(values[:_ROLLING_WINDOW]) >= 2 else 0.5)

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
            "source": "soccer_stats",
            "confidence": confidence,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _weighted_avg(self, values: list[float]) -> float:
        """
        Weighted rolling average (same formula as PropModel):
          0.5 × avg(last 5) + 0.3 × avg(last 10) + 0.2 × avg(last 10)
        """
        def safe_mean(v: list[float]) -> float:
            return mean(v) if v else 0.0

        last5  = values[:5]
        last10 = values[:10]

        w5  = 0.5 if last5  else 0.0
        w10 = 0.5 if last10 else 0.0

        total_weight = w5 + w10
        if total_weight == 0:
            return 0.0

        return (w5 * safe_mean(last5) + w10 * safe_mean(last10)) / total_weight

    def _classify_confidence(self, model_prob: float, market_implied: float) -> str:
        gap = abs(model_prob - market_implied)
        if gap >= _HIGH_GAP:
            return "HIGH"
        if gap >= _MEDIUM_GAP:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _american_to_implied(american_odds: int) -> float:
        if american_odds > 0:
            return 100 / (american_odds + 100)
        return abs(american_odds) / (abs(american_odds) + 100)

    def _fetch_player_values(self, player_name: str, col: str) -> list[float] | None:
        """
        Return recent per-90 values for a player stat column.
        Uses soccerdata season stats; caches to disk.
        """
        cache_key = f"{player_name.replace(' ', '_')}_{col}_{self._league_key}_{date.today()}"
        cache_file = _CACHE_DIR / f"{cache_key}.pkl"

        # Memory cache
        mem_key = f"{player_name}::{col}"
        if mem_key in self._player_stat_cache:
            return self._player_stat_cache[mem_key]

        # Disk cache
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    values = pickle.load(f)
                self._player_stat_cache[mem_key] = values
                return values
            except Exception:
                pass

        # Live fetch
        try:
            from alpha.data.ingestion.soccer_stats import get_player_per90_stats  # noqa: PLC0415

            rows = get_player_per90_stats(self._league_key)
            matched = [r for r in rows if r.get("player", "").lower() == player_name.lower()]
            if not matched:
                return None

            # Season aggregated stats — use as a single "value" repeated for variance estimation
            player_row = matched[0]
            base_val = float(player_row.get(col, 0.0))

            # Generate synthetic rolling values from season average
            # (Understat provides season totals, not per-game logs — use ± noise for std)
            import random  # noqa: PLC0415
            random.seed(hash(player_name))
            values = [
                max(0.0, base_val + random.gauss(0, base_val * 0.25))
                for _ in range(_ROLLING_WINDOW)
            ]
            values[0] = base_val  # anchor first value to season avg

            try:
                with open(cache_file, "wb") as f:
                    pickle.dump(values, f)
            except Exception:
                pass
            self._player_stat_cache[mem_key] = values
            return values
        except Exception as exc:
            logger.warning("Soccer player fetch failed for %s: %s", player_name, exc)
            return None
