"""
SoccerModel — win probability and EV-scored bet opportunities.
EPL + Champions League (3-outcome: home / draw / away).

Primary:  ProphitBet XGBoost models (if .pkl/.json found in
          ProphitBet-Soccer-Bets-Predictor/src/ or Models/).
Fallback: market-implied probabilities (3-way vig removal).

Key differences from NBAModel:
  - Three outcomes (home_win, draw, away_win) — draw probs are tracked
    but draw bets are skipped by evaluate_bet() (illiquid props).
  - MAX_XGB_CONF = 0.70 (lower than NBA — soccer is less predictable).
  - Credibility filter uses the same 3 checks adapted for draw odds.
"""
from __future__ import annotations

import logging
from pathlib import Path

from alpha.engines.sports.ev_calculator import EVCalculator

logger = logging.getLogger(__name__)

MARKET_BLEND = 0.0
MAX_XGB_CONF = 0.70

_PROPHITBET_DIR = Path("ProphitBet-Soccer-Bets-Predictor")
_MODEL_SEARCH_DIRS = [
    _PROPHITBET_DIR / "src" / "models",
    _PROPHITBET_DIR / "Models",
    _PROPHITBET_DIR,
]


class SoccerModel:
    def __init__(self, min_edge: float = 0.04, kelly_fraction: float = 0.25):
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self._kelly_fraction = kelly_fraction

        self._xgb_model = None
        self._xgb_models_loaded: bool = False

        self._injury_impact: dict = {}
        self._injury_loaded: bool = False

        self._load_xgb_models()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def predict(self, game: dict) -> dict:
        """
        Estimate 3-way probabilities for a soccer game.

        Returns:
            {
                "home_team": str,
                "away_team": str,
                "home_win_prob": float,
                "draw_prob": float,
                "away_win_prob": float,
                "source": "xgboost" | "market_implied",
            }
        """
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")

        if self._xgb_models_loaded:
            try:
                probs = self._predict_xgb(game)
                if probs is not None:
                    home_p, draw_p, away_p = probs
                    # Cap any single outcome at MAX_XGB_CONF
                    home_p = min(home_p, MAX_XGB_CONF)
                    away_p = min(away_p, MAX_XGB_CONF)
                    draw_p = min(draw_p, MAX_XGB_CONF)
                    # Re-normalize
                    total = home_p + draw_p + away_p
                    if total > 0:
                        home_p /= total
                        draw_p /= total
                        away_p /= total
                    # Re-clamp after normalization to ensure cap is enforced
                    home_p = min(home_p, MAX_XGB_CONF)
                    away_p = min(away_p, MAX_XGB_CONF)

                    home_p, away_p = self._credibility_filter(
                        home_team, away_team, home_p, away_p, game
                    )
                    draw_p = max(0.01, 1.0 - home_p - away_p)
                    total = home_p + draw_p + away_p
                    home_p /= total
                    draw_p /= total
                    away_p /= total

                    return {
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_win_prob": round(home_p, 4),
                        "draw_prob": round(draw_p, 4),
                        "away_win_prob": round(away_p, 4),
                        "source": "xgboost",
                    }
            except Exception as exc:
                logger.debug("XGBoost prediction failed, using market-implied: %s", exc)

        return self._market_implied_predict(game)

    def evaluate_bet(self, game: dict) -> dict:
        """
        Find the best bet in a game (home or away moneyline).
        Skips draw bets (illiquid props).

        Returns opportunity dict with bet_side, model_prob, decimal_odds, ev.
        """
        probs = self.predict(game)
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)

        home_dec = self.ev_calc.american_to_decimal(home_odds)
        away_dec = self.ev_calc.american_to_decimal(away_odds)

        home_ev = self.ev_calc.expected_value(probs["home_win_prob"], home_dec)
        away_ev = self.ev_calc.expected_value(probs["away_win_prob"], away_dec)

        if home_ev >= away_ev and self.ev_calc.has_edge(probs["home_win_prob"], home_dec):
            return {
                "bet_side": "home",
                "team": probs["home_team"],
                "model_prob": probs["home_win_prob"],
                "decimal_odds": home_dec,
                "ev": round(home_ev, 4),
            }
        elif self.ev_calc.has_edge(probs["away_win_prob"], away_dec):
            return {
                "bet_side": "away",
                "team": probs["away_team"],
                "model_prob": probs["away_win_prob"],
                "decimal_odds": away_dec,
                "ev": round(away_ev, 4),
            }
        return {
            "bet_side": "no_bet",
            "team": "",
            "model_prob": 0.0,
            "decimal_odds": 0.0,
            "ev": max(home_ev, away_ev),
        }

    def evaluate_batch(self, games: list[dict]) -> list[dict]:
        return [self.evaluate_bet(g) for g in games]

    # ------------------------------------------------------------------
    # Internal: market-implied fallback
    # ------------------------------------------------------------------

    def _implied_from_american(self, american_odds: int | float) -> float:
        decimal = self.ev_calc.american_to_decimal(american_odds)
        return self.ev_calc.implied_prob(decimal)

    def _remove_vig_3way(
        self, h: float, d: float, a: float
    ) -> tuple[float, float, float]:
        """Normalize 3-way implied probs to remove bookmaker vig."""
        total = h + d + a
        if total <= 0:
            return 1 / 3, 1 / 3, 1 / 3
        return h / total, d / total, a / total

    def _market_implied_predict(self, game: dict) -> dict:
        home_odds = game.get("home_odds", -110)
        draw_odds = game.get("draw_odds", 300)
        away_odds = game.get("away_odds", 250)

        h = self._implied_from_american(home_odds)
        d = self._implied_from_american(draw_odds)
        a = self._implied_from_american(away_odds)
        h_fair, d_fair, a_fair = self._remove_vig_3way(h, d, a)

        h_prob = h_fair * (1 - MARKET_BLEND) + (1 / 3) * MARKET_BLEND
        a_prob = a_fair * (1 - MARKET_BLEND) + (1 / 3) * MARKET_BLEND
        d_prob = max(0.01, 1.0 - h_prob - a_prob)
        total = h_prob + d_prob + a_prob
        h_prob /= total
        d_prob /= total
        a_prob /= total

        return {
            "home_team": game.get("home_team", ""),
            "away_team": game.get("away_team", ""),
            "home_win_prob": round(h_prob, 4),
            "draw_prob": round(d_prob, 4),
            "away_win_prob": round(a_prob, 4),
            "source": "market_implied",
        }

    # ------------------------------------------------------------------
    # Internal: XGBoost model loading
    # ------------------------------------------------------------------

    def _load_xgb_models(self) -> None:
        """
        Attempt to load a ProphitBet XGBoost model.
        Sets self._xgb_models_loaded on success.
        """
        try:
            import joblib  # noqa: PLC0415

            model_path = self._find_model_path()
            if model_path is None:
                logger.debug("No ProphitBet model file found — using market-implied")
                return

            self._xgb_model = joblib.load(str(model_path))
            self._xgb_models_loaded = True
            logger.info("Loaded ProphitBet model: %s", model_path.name)
        except Exception as exc:
            logger.debug("ProphitBet model load skipped: %s", exc)

    def _find_model_path(self) -> Path | None:
        """Search known locations for a .pkl or .json model file."""
        for search_dir in _MODEL_SEARCH_DIRS:
            if not search_dir.exists():
                continue
            for pattern in ("*.pkl", "*.json"):
                candidates = list(search_dir.glob(pattern))
                if candidates:
                    # Prefer most recently modified
                    return max(candidates, key=lambda p: p.stat().st_mtime)
        return None

    def _predict_xgb(self, game: dict) -> tuple[float, float, float] | None:
        """
        Run ProphitBet model and return (home_prob, draw_prob, away_prob).
        Returns None on any failure.
        """
        try:
            import numpy as np  # noqa: PLC0415

            features = self._build_game_features(game)
            if features is None:
                return None

            import pandas as pd  # noqa: PLC0415
            X = pd.DataFrame([features])
            X = X.apply(pd.to_numeric, errors="coerce").fillna(0)

            # Check if model has predict_proba (sklearn-style)
            if hasattr(self._xgb_model, "predict_proba"):
                proba = self._xgb_model.predict_proba(X)
                row = proba[0]
                if len(row) == 3:
                    return float(row[0]), float(row[1]), float(row[2])
                elif len(row) == 2:
                    return float(row[1]), 0.25, float(row[0])
            elif hasattr(self._xgb_model, "predict"):
                pred = self._xgb_model.predict(X)
                label = int(pred[0])
                if label == 0:
                    return 0.60, 0.20, 0.20
                elif label == 1:
                    return 0.20, 0.60, 0.20
                else:
                    return 0.20, 0.20, 0.60
        except Exception as exc:
            logger.debug("XGBoost soccer prediction failed: %s", exc)
        return None

    def _build_game_features(self, game: dict) -> dict | None:
        """
        Build a feature dict for XGBoost from team rolling stats + odds.
        Returns None if required data is missing.
        """
        try:
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")

            from alpha.data.ingestion.soccer_stats import get_team_rolling_stats_all  # noqa: PLC0415
            team_stats = {r["team"]: r for r in get_team_rolling_stats_all()}

            home_s = team_stats.get(home_team, {})
            away_s = team_stats.get(away_team, {})

            self._load_injuries()
            home_impact = self._injury_impact.get(home_team, {})
            away_impact = self._injury_impact.get(away_team, {})

            return {
                "home_goals_for": home_s.get("goals_for", 1.5) - home_impact.get("goals_lost", 0.0),
                "home_goals_against": home_s.get("goals_against", 1.5),
                "home_xg_for": home_s.get("xG_for", 1.5),
                "home_xg_against": home_s.get("xG_against", 1.5),
                "away_goals_for": away_s.get("goals_for", 1.5) - away_impact.get("goals_lost", 0.0),
                "away_goals_against": away_s.get("goals_against", 1.5),
                "away_xg_for": away_s.get("xG_for", 1.5),
                "away_xg_against": away_s.get("xG_against", 1.5),
                "home_odds": self.ev_calc.american_to_decimal(game.get("home_odds", -110)),
                "draw_odds": self.ev_calc.american_to_decimal(game.get("draw_odds", 300)),
                "away_odds": self.ev_calc.american_to_decimal(game.get("away_odds", 250)),
            }
        except Exception as exc:
            logger.debug("_build_game_features failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal: injuries
    # ------------------------------------------------------------------

    def _load_injuries(self) -> None:
        if self._injury_loaded:
            return
        self._injury_loaded = True
        try:
            from alpha.data.ingestion.soccer_injuries import get_team_injury_impact  # noqa: PLC0415
            self._injury_impact = get_team_injury_impact()
        except Exception as exc:
            logger.warning("Soccer injury load failed: %s", exc)
            self._injury_impact = {}

    # ------------------------------------------------------------------
    # Internal: credibility filter
    # ------------------------------------------------------------------

    def _credibility_filter(
        self,
        home_team: str,
        away_team: str,
        home_prob: float,
        away_prob: float,
        game: dict,
    ) -> tuple[float, float]:
        """
        Dampen XGBoost predictions that diverge too far from market.

        Three checks (same as NBAModel):
          1. Big-underdog artifact: decimal odds > 5.0 AND |model - market| > 0.15
          2. Very low implied probability team (< 0.20): cap at market
          3. Large divergence guard: |model - market| > 0.20 → blend 50/50

        Returns adjusted (home_prob, away_prob) normalized to sum ≤ 1.0.
        """
        market = self._market_implied_predict(game)
        mkt_home = market["home_win_prob"]
        mkt_away = market["away_win_prob"]

        home_adj, away_adj = home_prob, away_prob

        for is_home, odds_key, model_p, mkt_p in [
            (True, "home_odds", home_prob, mkt_home),
            (False, "away_odds", away_prob, mkt_away),
        ]:
            adj = model_p
            decimal_odds = self.ev_calc.american_to_decimal(game.get(odds_key, -110))

            # Check 1: big-underdog artifact
            if decimal_odds > 5.0 and abs(adj - mkt_p) > 0.15:
                logger.debug("Soccer model artifact: reverting to market for %s odds", odds_key)
                adj = mkt_p

            # Check 2: very low implied prob team
            if mkt_p < 0.20 and adj > mkt_p:
                adj = mkt_p

            # Check 3: large divergence guard
            if abs(adj - mkt_p) > 0.20:
                adj = 0.5 * adj + 0.5 * mkt_p

            if is_home:
                home_adj = adj
            else:
                away_adj = adj

        total = home_adj + away_adj
        if total > 0.99:
            home_adj /= (total + 0.01)
            away_adj /= (total + 0.01)

        return home_adj, away_adj
