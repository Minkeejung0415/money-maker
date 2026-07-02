"""
CorrelationEngine — empirical correlation matrix for SGP leg pairs.

For each pair of (playerA_stat, playerB_stat), computes Pearson r between
their binary "did they exceed their trailing average?" vectors across games
they BOTH played, matched by game date.

Leakage/alignment guarantees:
  - Vectors are joined on GAME_DATE — never by array index.  Two players'
    entries are only paired when they refer to the same calendar game date;
    pairs with fewer than _MIN_SHARED_GAMES shared dates return r = 0.0.
  - Each game is binarized against the average of up to _ROLLING_WINDOW
    strictly EARLIER games (trailing average).  No future game ever
    influences the flag of a past game.

Key concept:
  Positive r (> 0.25):  true joint prob is HIGHER than naive product
  Negative r (< -0.25): true joint prob is LOWER than naive product — book
                         overprices the joint, so naive market_implied is too high.

Correlation adjustment uses a bivariate normal copula approximation:
  joint_prob = clip(p_a * p_b + r * sqrt(p_a*(1-p_a) * p_b*(1-p_b)), 0.001, 0.999)

NOTE on adjust_multi_leg_prob:
  This is a first-order bivariate copula approximation.  Accuracy degrades
  for N > 3 legs.  For 4+ legs, treat combined_model_prob as a lower bound.

Cache: pickled to data/.corr_cache_v2.pkl with 24-hour TTL.  (v2: the v1
cache stored index-aligned matrices and must not be reused.)
"""
from __future__ import annotations

import logging
import math
import os
import pickle
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import numpy as np
from scipy.stats import pearsonr

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("data/.corr_cache_v2.pkl")
_CACHE_TTL_HOURS = 24
_NBA_API_SLEEP: float = 0.6
_ROLLING_WINDOW: int = 20
# Minimum strictly-earlier games required before a game gets a binary flag.
_MIN_PRIOR_GAMES: int = 10
# Minimum shared game dates required to estimate r for a pair.
_MIN_SHARED_GAMES: int = 10

_MARKET_COL: dict[str, str] = {
    "player_points":   "PTS",
    "player_rebounds": "REB",
    "player_assists":  "AST",
    "player_threes":   "FG3M",
}


class CorrelationType(Enum):
    POSITIVE = "positive"
    NEUTRAL  = "neutral"
    NEGATIVE = "negative"


class CorrelationEngine:
    def __init__(self, season: str = "2024-25"):
        self._season = season
        # matrix[(playerA, marketA, playerB, marketB)] = float r
        self._matrix: dict[tuple, float] = {}
        self._built = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        player_names: list[str],
        season: str | None = None,
        force_rebuild: bool = False,
    ) -> None:
        """
        Build (or load from cache) the correlation matrix for the given players.
        Fetches nba_api game logs; slow on first build (~0.6 s/player).
        """
        season = season or self._season

        if not force_rebuild:
            cached = self._load_cache()
            if cached is not None:
                self._matrix = cached
                self._built = True
                logger.info("Correlation matrix loaded from cache (%d pairs)", len(self._matrix))
                return

        logger.info("Building correlation matrix for %d players...", len(player_names))
        game_vectors = self._fetch_all_vectors(player_names, season)
        self._matrix = {}

        markets = list(_MARKET_COL.keys())
        players = list(game_vectors.keys())

        for i, pa in enumerate(players):
            for pb in players[i:]:
                for ma in markets:
                    for mb in markets:
                        key = (pa, ma, pb, mb)
                        rkey = (pb, mb, pa, ma)
                        if key in self._matrix:
                            continue
                        r = self._compute_r(game_vectors, pa, ma, pb, mb)
                        self._matrix[key] = r
                        self._matrix[rkey] = r

        self._built = True
        self._save_cache(self._matrix)
        logger.info("Correlation matrix built (%d pairs)", len(self._matrix))

    def get_correlation(
        self, player_a: str, market_a: str, player_b: str, market_b: str
    ) -> float:
        """Return Pearson r for a pair. Returns 0.0 if pair not in matrix."""
        key = (player_a, market_a, player_b, market_b)
        return self._matrix.get(key, 0.0)

    def adjust_joint_prob(self, p_a: float, p_b: float, r: float) -> float:
        """
        Bivariate normal copula correction.
          joint = clip(p_a * p_b + r * sqrt(p_a*(1-p_a) * p_b*(1-p_b)), 0.001, 0.999)
        """
        correction = r * math.sqrt(p_a * (1 - p_a) * p_b * (1 - p_b))
        result = p_a * p_b + correction
        return float(np.clip(result, 0.001, 0.999))

    def adjust_multi_leg_prob(self, legs: list[tuple[float, str, str]]) -> float:
        """
        Correlation-adjusted joint probability for N legs.
        legs = [(model_prob, player_name, market), ...]

        This is a first-order bivariate copula approximation.  Accuracy degrades
        for N > 3 legs.  For 4+ legs, treat combined_model_prob as a lower bound.

        For a single leg, returns that leg's prob unchanged.
        """
        if not legs:
            return 0.0
        if len(legs) == 1:
            return legs[0][0]

        # Apply pairwise from left to right, blending in each new leg
        result_prob = legs[0][0]
        result_player = legs[0][1]
        result_market = legs[0][2]

        for prob_b, player_b, market_b in legs[1:]:
            r = self.get_correlation(result_player, result_market, player_b, market_b)
            result_prob = self.adjust_joint_prob(result_prob, prob_b, r)
            # For the next iteration, treat the running pair as a pseudo-leg;
            # use the second leg's identity as the representative
            result_player = player_b
            result_market = market_b

        return result_prob

    def classify(self, r: float) -> CorrelationType:
        if r > 0.25:
            return CorrelationType.POSITIVE
        if r < -0.25:
            return CorrelationType.NEGATIVE
        return CorrelationType.NEUTRAL

    # ------------------------------------------------------------------
    # Internal: vector computation
    # ------------------------------------------------------------------

    def _compute_r(
        self,
        game_vectors: dict[str, dict[str, dict[str, float]]],
        player_a: str,
        market_a: str,
        player_b: str,
        market_b: str,
    ) -> float:
        """
        Compute Pearson r between two binary over/under vectors, paired by
        shared game date.  Pairs with insufficient shared games return 0.0
        (assume independence) rather than correlating unrelated games.
        """
        col_a = _MARKET_COL.get(market_a)
        col_b = _MARKET_COL.get(market_b)
        if col_a is None or col_b is None:
            return 0.0

        vec_a = game_vectors.get(player_a, {}).get(col_a, {})
        vec_b = game_vectors.get(player_b, {}).get(col_b, {})

        shared_dates = sorted(set(vec_a) & set(vec_b))
        if len(shared_dates) < _MIN_SHARED_GAMES:
            return 0.0

        va = np.array([vec_a[d] for d in shared_dates])
        vb = np.array([vec_b[d] for d in shared_dates])

        if va.std() == 0 or vb.std() == 0:
            return 0.0 if player_a != player_b or market_a != market_b else 1.0

        try:
            r, _ = pearsonr(va, vb)
            return float(np.clip(r, -1.0, 1.0))
        except Exception:
            return 0.0

    def _fetch_all_vectors(
        self, player_names: list[str], season: str
    ) -> dict[str, dict[str, dict[str, float]]]:
        """
        Returns {player: {col: {game_date: binary over/under flag}}}.
        Binary encoding: 1 if value > trailing avg of prior games, else 0.
        """
        result: dict[str, dict[str, dict[str, float]]] = {}
        for name in player_names:
            vectors = self._fetch_player_vectors(name, season)
            if vectors:
                result[name] = vectors
        return result

    @staticmethod
    def _binarize_trailing(dated_values: list[tuple[str, float]]) -> dict[str, float]:
        """
        Binarize a chronological (oldest-first) series of (game_date, value)
        against the trailing average of up to _ROLLING_WINDOW strictly
        earlier games.

        The first _MIN_PRIOR_GAMES games emit no flag (not enough history).
        Using only prior games means no future value can influence the flag
        of an earlier game (the v1 implementation binarized the whole season
        against the mean of the most RECENT 20 games — future leakage).
        """
        out: dict[str, float] = {}
        prior: list[float] = []
        for date_str, v in dated_values:
            if len(prior) >= _MIN_PRIOR_GAMES:
                window = prior[-_ROLLING_WINDOW:]
                trailing_avg = mean(window)
                out[date_str] = 1.0 if v > trailing_avg else 0.0
            prior.append(v)
        return out

    def _fetch_player_vectors(
        self, player_name: str, season: str
    ) -> dict[str, dict[str, float]] | None:
        """Fetch game logs and encode as date-keyed binary over/under vectors."""
        try:
            from nba_api.stats.static import players as nba_players  # noqa: PLC0415
            from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs  # noqa: PLC0415

            all_players = nba_players.get_players()
            matched = [p for p in all_players if p["full_name"].lower() == player_name.lower()]
            if not matched:
                return None

            player_id = matched[0]["id"]
            time.sleep(_NBA_API_SLEEP)
            gl = PlayerGameLogs(
                player_id_nullable=str(player_id),
                season_nullable=season,
                last_n_games_nullable="0",
            )
            df = gl.get_data_frames()[0]
            if df.empty or "GAME_DATE" not in df.columns:
                return None

            vectors: dict[str, dict[str, float]] = {}
            for col in _MARKET_COL.values():
                if col not in df.columns:
                    continue
                # nba_api returns newest-first; reverse to chronological.
                dated = [
                    (str(d)[:10], float(v))
                    for d, v in zip(df["GAME_DATE"], df[col].astype(float))
                ][::-1]
                if len(dated) < _ROLLING_WINDOW:
                    continue
                binary = self._binarize_trailing(dated)
                if binary:
                    vectors[col] = binary

            return vectors if vectors else None
        except Exception as exc:
            logger.warning("nba_api vectors failed for %s: %s", player_name, exc)
            return None

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    @staticmethod
    def _load_cache() -> dict | None:
        try:
            if not _CACHE_PATH.exists():
                return None
            mtime = datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)
            if datetime.now() - mtime > timedelta(hours=_CACHE_TTL_HOURS):
                logger.info("Correlation cache expired — rebuilding")
                return None
            with open(_CACHE_PATH, "rb") as f:
                return pickle.load(f)
        except Exception as exc:
            logger.debug("Cache load failed: %s", exc)
            return None

    @staticmethod
    def _save_cache(matrix: dict) -> None:
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_CACHE_PATH, "wb") as f:
                pickle.dump(matrix, f)
        except Exception as exc:
            logger.debug("Cache save failed: %s", exc)
