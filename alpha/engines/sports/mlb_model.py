"""
MLBModel — win probability and EV-scored bet opportunities.

Primary:  mlb_outcomes XGBoost model (if .pkl/.json found in mlb_outcomes/).
Fallback: market-implied probabilities.

Key differences from NBAModel:
  - Feature vector: team batting + pitching stats + days rest + home/away indicator.
  - Starting pitcher adjustment: ace → boost pitching; scratched → revert to bullpen ERA.
  - MAX_XGB_CONF = 0.72.
  - Injury adjustment for absent batters (avg_lost, hr_lost).
"""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import date

from alpha.engines.sports.ev_calculator import EVCalculator

logger = logging.getLogger(__name__)

MARKET_BLEND = 0.0
MAX_XGB_CONF = 0.72

_MLB_OUTCOMES_DIR = Path("mlb_outcomes")
_MODEL_SEARCH_DIRS = [
    _MLB_OUTCOMES_DIR / "models",
    _MLB_OUTCOMES_DIR / "code",
    _MLB_OUTCOMES_DIR,
]

# Bullpen ERA fallback when ace scratched
_BULLPEN_ERA = 4.80
_ACE_ERA_BOOST = 0.85  # multiply ERA by this factor when ace pitching (better than average)


class MLBModel:
    def __init__(self, min_edge: float = 0.04, kelly_fraction: float = 0.25):
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self._kelly_fraction = kelly_fraction

        self._xgb_model = None
        self._model_bundle: dict | None = None
        self._xgb_models_loaded: bool = False

        self._injury_impact: dict = {}
        self._injury_loaded: bool = False

        self._pitcher_cache: dict[str, str] = {}
        self._pitcher_loaded: bool = False

        self._load_xgb_models()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def predict(self, game: dict) -> dict:
        """
        Estimate win probabilities for an MLB game.

        Returns:
            {
                "home_team": str,
                "away_team": str,
                "home_win_prob": float,
                "away_win_prob": float,
                "source": "xgboost" | "market_implied",
            }
        """
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")

        if self._xgb_models_loaded:
            try:
                probs = self._predict_bundle(game) if self._model_bundle else self._predict_xgb(game)
                if probs is not None:
                    home_prob, away_prob = probs
                    if home_prob > MAX_XGB_CONF:
                        home_prob = MAX_XGB_CONF
                        away_prob = 1.0 - MAX_XGB_CONF
                    elif away_prob > MAX_XGB_CONF:
                        away_prob = MAX_XGB_CONF
                        home_prob = 1.0 - MAX_XGB_CONF
                    home_prob, away_prob = self._credibility_filter(
                        home_team, away_team, home_prob, away_prob, game
                    )
                    return {
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_win_prob": round(home_prob, 4),
                        "away_win_prob": round(away_prob, 4),
                        "source": "trained_calibrated" if self._model_bundle else "xgboost",
                    }
            except Exception as exc:
                logger.debug("XGBoost prediction failed, using market-implied: %s", exc)

        return self._market_implied_predict(game)

    def evaluate_bet(self, game: dict) -> dict:
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

    def _remove_vig(self, home_impl: float, away_impl: float) -> tuple[float, float]:
        total = home_impl + away_impl
        return home_impl / total, away_impl / total

    def _market_implied_predict(self, game: dict) -> dict:
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)

        home_impl = self._implied_from_american(home_odds)
        away_impl = self._implied_from_american(away_odds)
        home_fair, away_fair = self._remove_vig(home_impl, away_impl)

        home_prob = home_fair * (1 - MARKET_BLEND) + 0.5 * MARKET_BLEND
        away_prob = 1 - home_prob

        return {
            "home_team": game.get("home_team", ""),
            "away_team": game.get("away_team", ""),
            "home_win_prob": round(home_prob, 4),
            "away_win_prob": round(away_prob, 4),
            "source": "market_implied",
        }

    # ------------------------------------------------------------------
    # Internal: XGBoost loading
    # ------------------------------------------------------------------

    def _load_xgb_models(self) -> None:
        try:
            import joblib  # noqa: PLC0415

            model_path = self._find_model_path()
            if model_path is None:
                logger.debug("No mlb_outcomes model file found — using market-implied")
                return

            loaded = joblib.load(str(model_path))
            if isinstance(loaded, dict) and loaded.get("kind") == "mlb_win_probability_bundle":
                from alpha.engines.sports.mlb_training import FEATURE_NAMES
                if not loaded.get("validated") or tuple(loaded.get("feature_names", ())) != FEATURE_NAMES:
                    logger.warning("MLB artifact failed validation/schema gate")
                    return
                self._model_bundle = loaded
                self._xgb_model = loaded["model"]
            else:
                self._xgb_model = loaded
            self._xgb_models_loaded = True
            logger.info("Loaded MLB model: %s", model_path.name)
        except Exception as exc:
            logger.debug("MLB model load skipped: %s", exc)

    def _find_model_path(self) -> Path | None:
        preferred = Path("alpha/models/mlb_win_probability.pkl")
        if preferred.exists():
            return preferred
        for search_dir in _MODEL_SEARCH_DIRS:
            if not search_dir.exists():
                continue
            for pattern in ("*.pkl", "*.json"):
                candidates = list(search_dir.glob(pattern))
                if candidates:
                    return max(candidates, key=lambda p: p.stat().st_mtime)
        return None

    # ------------------------------------------------------------------
    # Internal: XGBoost prediction
    # ------------------------------------------------------------------

    def _predict_bundle(self, game: dict) -> tuple[float, float] | None:
        """Predict with the validated v1.3 bundle and its saved team state."""
        import numpy as np
        from alpha.engines.sports.mlb_training import FEATURE_NAMES, live_feature_vector
        from scripts.train_mlb_moneyline import calibrated
        bundle = self._model_bundle
        if not bundle:
            return None
        game_date = str(game.get("commence_time", ""))[:10] or date.today().isoformat()
        features = live_feature_vector(game.get("home_team", ""), game.get("away_team", ""), game_date, bundle["team_state"])
        X = np.asarray([[features[name] for name in FEATURE_NAMES]], dtype=float)
        raw = bundle["model"].predict_proba(X)[:, 1]
        home = float(calibrated(bundle["calibrator"], raw)[0])
        return home, 1.0 - home
    def _predict_xgb(self, game: dict) -> tuple[float, float] | None:
        try:
            import pandas as pd  # noqa: PLC0415

            features = self._build_game_features(game)
            if features is None:
                return None

            X = pd.DataFrame([features])
            X = X.apply(pd.to_numeric, errors="coerce").fillna(0)

            if hasattr(self._xgb_model, "predict_proba"):
                proba = self._xgb_model.predict_proba(X)
                row = proba[0]
                if len(row) >= 2:
                    return float(row[1]), float(row[0])
            elif hasattr(self._xgb_model, "predict"):
                pred = self._xgb_model.predict(X)
                label = int(pred[0])
                return (0.60, 0.40) if label == 1 else (0.40, 0.60)
        except Exception as exc:
            logger.debug("MLB XGBoost prediction failed: %s", exc)
        return None

    def _build_game_features(self, game: dict) -> dict | None:
        """Build feature dict: team stats + pitcher + home indicator + injuries."""
        try:
            from alpha.data.ingestion.mlb_stats import get_team_stats_map  # noqa: PLC0415

            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")

            team_stats = get_team_stats_map()
            home_s = team_stats.get(home_team, {})
            away_s = team_stats.get(away_team, {})

            self._load_injuries()
            home_impact = self._injury_impact.get(home_team, {})
            away_impact = self._injury_impact.get(away_team, {})

            # Pitcher adjustment
            home_era = self._pitcher_adjusted_era(home_team, home_s.get("era", 4.50))
            away_era = self._pitcher_adjusted_era(away_team, away_s.get("era", 4.50))

            return {
                "home_runs_per_game": home_s.get("runs_per_game", 4.5),
                "home_batting_avg": home_s.get("batting_avg", 0.250) - home_impact.get("avg_lost", 0.0),
                "home_obp": home_s.get("obp", 0.320),
                "home_slg": home_s.get("slg", 0.400),
                "home_era": home_era,
                "home_whip": home_s.get("whip", 1.30),
                "home_k_per9": home_s.get("k_per9", 8.5),
                "away_runs_per_game": away_s.get("runs_per_game", 4.5),
                "away_batting_avg": away_s.get("batting_avg", 0.250) - away_impact.get("avg_lost", 0.0),
                "away_obp": away_s.get("obp", 0.320),
                "away_slg": away_s.get("slg", 0.400),
                "away_era": away_era,
                "away_whip": away_s.get("whip", 1.30),
                "away_k_per9": away_s.get("k_per9", 8.5),
                "home_indicator": 1.0,
                "home_odds_decimal": self.ev_calc.american_to_decimal(game.get("home_odds", -110)),
                "away_odds_decimal": self.ev_calc.american_to_decimal(game.get("away_odds", -110)),
            }
        except Exception as exc:
            logger.debug("_build_game_features failed: %s", exc)
            return None

    def _pitcher_adjusted_era(self, team: str, team_era: float) -> float:
        """
        Adjust ERA based on probable pitcher.
        Ace listed → multiply by ACE_ERA_BOOST (lower ERA = better).
        Scratched / no pitcher data → use bullpen ERA.
        """
        self._load_pitchers()
        pitcher_name = self._pitcher_cache.get(team)
        if not pitcher_name:
            # No probable pitcher found → assume bullpen
            return _BULLPEN_ERA

        try:
            from alpha.data.ingestion.mlb_stats import get_pitcher_stats  # noqa: PLC0415
            pitchers = {r["player"]: r for r in get_pitcher_stats()}
            pitcher_stats = pitchers.get(pitcher_name)
            if pitcher_stats:
                era = pitcher_stats.get("era", team_era)
                logger.debug("Pitcher %s ERA: %.2f", pitcher_name, era)
                return era
        except Exception:
            pass

        # Pitcher found but no stats → apply ace boost heuristically
        return team_era * _ACE_ERA_BOOST

    def _load_pitchers(self) -> None:
        if self._pitcher_loaded:
            return
        self._pitcher_loaded = True
        try:
            from alpha.data.ingestion.mlb_stats import get_probable_pitchers  # noqa: PLC0415
            self._pitcher_cache = get_probable_pitchers()
        except Exception as exc:
            logger.warning("Probable pitchers load failed: %s", exc)
            self._pitcher_cache = {}

    def _load_injuries(self) -> None:
        if self._injury_loaded:
            return
        self._injury_loaded = True
        try:
            from alpha.data.ingestion.mlb_injuries import get_team_injury_impact  # noqa: PLC0415
            self._injury_impact = get_team_injury_impact()
        except Exception as exc:
            logger.warning("MLB injury load failed: %s", exc)
            self._injury_impact = {}

    # ------------------------------------------------------------------
    # Internal: credibility filter (3 checks, mirrors NBAModel)
    # ------------------------------------------------------------------

    def _credibility_filter(
        self,
        home_team: str,
        away_team: str,
        home_prob: float,
        away_prob: float,
        game: dict,
    ) -> tuple[float, float]:
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
            if decimal_odds > 4.0 and abs(adj - mkt_p) > 0.15:
                adj = mkt_p

            # Check 2: very low win-prob team
            if mkt_p < 0.25 and adj > mkt_p:
                adj = mkt_p

            # Check 3: large divergence guard
            if abs(adj - mkt_p) > 0.20:
                adj = 0.5 * adj + 0.5 * mkt_p

            if is_home:
                home_adj = adj
            else:
                away_adj = adj

        total = home_adj + away_adj
        if total > 0:
            home_adj /= total
            away_adj /= total

        return home_adj, away_adj
