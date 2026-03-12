"""
PropBacktester — validates PropModel calibration against historical outcomes.

This is the accuracy check.  Without running this, the model's predictions
are unvalidated.  The scanner warns the user unless --validate is passed.

Approach (calibration-based):
  For each game i (using game i-1 as the outcome to predict):
    synthetic_line = rolling avg of last 10 games (games[i:i+10])
    actual         = logs[i-1][col]
    pred_prob      = model's P(actual > synthetic_line)
    actual_hit     = 1 if actual > synthetic_line else 0
    → bucket pred_prob into deciles and compare to actual hit rate

Reliability thresholds:
  RELIABLE   : Brier score < 0.22 AND high_conf_hit_rate > 0.60
  MARGINAL   : Brier score < 0.25
  UNRELIABLE : Brier score ≥ 0.25 (no better than random)

Minimum data: players with < 25 games available are excluded.
"""
from __future__ import annotations

import logging
import math
import time
from statistics import mean, stdev
from typing import Any

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)

_NBA_API_SLEEP: float = 0.6
_MIN_GAMES_REQUIRED: int = 25   # need ≥ 20 history + a few predictions
_HISTORY_WINDOW: int = 20
_SYNTHETIC_LINE_WINDOW: int = 10

_MARKET_COL: dict[str, str] = {
    "player_points":   "PTS",
    "player_rebounds": "REB",
    "player_assists":  "AST",
    "player_threes":   "FG3M",
}

_CALIBRATION_BUCKETS = [
    (0.00, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40),
    (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80),
    (0.80, 0.90), (0.90, 1.00),
]


class PropBacktester:
    def __init__(self, season: str = "2025-26"):
        self._season = season

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def backtest(
        self,
        player_names: list[str],
        markets: list[str],
        season: str | None = None,
    ) -> list[dict]:
        """
        Run calibration backtests for each (player, market) combination.

        Returns a list of result dicts — one per (player, market) pair
        that had enough data.  Players with insufficient data are silently
        skipped.
        """
        season = season or self._season
        results: list[dict] = []
        for player_name in player_names:
            logs = self._fetch_logs(player_name, season)
            if logs is None or len(logs) < _MIN_GAMES_REQUIRED:
                logger.debug(
                    "Skipping %s — insufficient game logs (%d)",
                    player_name,
                    len(logs) if logs else 0,
                )
                continue
            for market in markets:
                col = _MARKET_COL.get(market)
                if col is None:
                    continue
                result = self._backtest_player_market(player_name, market, col, logs)
                if result is not None:
                    results.append(result)
        return results

    def print_report(self, results: list[dict]) -> None:
        """Print a human-readable calibration report."""
        if not results:
            print("No backtest results available.")
            return

        print("\n=== PROP MODEL VALIDATION ===")
        for r in results:
            print(
                f"{r['player']} / {r['market']:20s}  "
                f"{r['recommendation']:10s}  "
                f"(Brier: {r['brier_score']:.3f}, "
                f"HC hit rate: {r['high_conf_hit_rate']:.1%}, "
                f"n={r['n_predictions']})"
            )

    # ------------------------------------------------------------------
    # Internal: per-player backtest
    # ------------------------------------------------------------------

    def _backtest_player_market(
        self,
        player_name: str,
        market: str,
        col: str,
        logs: list[dict],
    ) -> dict | None:
        """
        Run the calibration backtest for one player/market.
        Returns result dict or None if not enough predictions.
        """
        values = [g.get(col, 0.0) for g in logs]

        predictions: list[tuple[float, int]] = []  # (pred_prob, actual_hit)

        # Start at index HISTORY_WINDOW so we have enough prior history
        for i in range(_HISTORY_WINDOW, len(values) - 1):
            # Synthetic line = rolling avg of the next SYNTHETIC_LINE_WINDOW games
            # (in the past relative to game i-1 we're predicting)
            history_slice = values[i: i + _SYNTHETIC_LINE_WINDOW]
            if len(history_slice) < 2:
                continue

            synthetic_line = mean(history_slice)
            std = max(1.0, stdev(history_slice))

            actual = values[i - 1]
            pred_prob = float(1 - norm.cdf(synthetic_line, loc=mean(history_slice), scale=std))
            pred_prob = float(np.clip(pred_prob, 0.01, 0.99))
            actual_hit = 1 if actual > synthetic_line else 0

            predictions.append((pred_prob, actual_hit))

        if not predictions:
            return None

        preds_arr = [p for p, _ in predictions]
        hits_arr  = [h for _, h in predictions]

        brier = self._brier_score(preds_arr, hits_arr)
        calibration = self._calibration_table(preds_arr, hits_arr)
        overall_hit_rate = mean(hits_arr) if hits_arr else 0.0
        hc_hit_rate = self._high_conf_hit_rate(predictions)
        recommendation = self._recommend(brier, hc_hit_rate)

        return {
            "player": player_name,
            "market": market,
            "n_predictions": len(predictions),
            "overall_hit_rate": round(overall_hit_rate, 4),
            "brier_score": round(brier, 4),
            "calibration": calibration,
            "high_conf_hit_rate": round(hc_hit_rate, 4),
            "recommendation": recommendation,
        }

    # ------------------------------------------------------------------
    # Internal: metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _brier_score(preds: list[float], hits: list[int]) -> float:
        """Brier score = mean((pred - actual)^2). Lower = better. Random = 0.25."""
        if not preds:
            return 0.25
        return float(mean((p - h) ** 2 for p, h in zip(preds, hits)))

    @staticmethod
    def _calibration_table(
        preds: list[float], hits: list[int]
    ) -> dict[str, dict]:
        """Group predictions into decile buckets and compute mean predicted vs actual."""
        buckets: dict[str, dict] = {}
        for lo, hi in _CALIBRATION_BUCKETS:
            key = f"{lo:.2f}-{hi:.2f}"
            indices = [i for i, p in enumerate(preds) if lo <= p < hi]
            if not indices:
                buckets[key] = {"predicted": round((lo + hi) / 2, 3), "actual": 0.0, "n": 0}
            else:
                pred_mean = mean(preds[i] for i in indices)
                actual_mean = mean(hits[i] for i in indices)
                buckets[key] = {
                    "predicted": round(pred_mean, 4),
                    "actual": round(actual_mean, 4),
                    "n": len(indices),
                }
        return buckets

    @staticmethod
    def _high_conf_hit_rate(predictions: list[tuple[float, int]]) -> float:
        """
        Hit rate for predictions where pred_prob > 0.60 (proxy for HIGH confidence).
        """
        high_conf = [(p, h) for p, h in predictions if p > 0.60]
        if not high_conf:
            return 0.0
        return mean(h for _, h in high_conf)

    @staticmethod
    def _recommend(brier: float, hc_hit_rate: float) -> str:
        if brier < 0.22 and hc_hit_rate > 0.60:
            return "RELIABLE"
        if brier < 0.25:
            return "MARGINAL"
        return "UNRELIABLE"

    # ------------------------------------------------------------------
    # Internal: nba_api
    # ------------------------------------------------------------------

    def _fetch_logs(self, player_name: str, season: str) -> list[dict] | None:
        """Fetch up to 60 game logs for a player via nba_api."""
        try:
            from nba_api.stats.static import players as nba_players  # noqa: PLC0415
            from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs  # noqa: PLC0415

            all_players = nba_players.get_players()
            matched = [p for p in all_players if p["full_name"].lower() == player_name.lower()]
            if not matched:
                logger.debug("Player not found: %s", player_name)
                return None

            player_id = matched[0]["id"]
            time.sleep(_NBA_API_SLEEP)
            gl = PlayerGameLogs(
                player_id_nullable=str(player_id),
                season_nullable=season,
                last_n_games_nullable="60",
            )
            df = gl.get_data_frames()[0]
            if df.empty:
                return None

            rows: list[dict[str, Any]] = [dict(row) for _, row in df.iterrows()]
            # Convert numeric columns
            for col in list(_MARKET_COL.values()):
                for row in rows:
                    if col in row:
                        try:
                            row[col] = float(row[col])
                        except (ValueError, TypeError):
                            row[col] = 0.0
            return rows
        except Exception as exc:
            logger.warning("nba_api logs failed for %s: %s", player_name, exc)
            return None
