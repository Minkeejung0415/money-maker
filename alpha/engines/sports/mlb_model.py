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
from typing import Any

from alpha.engines.sports.ev_calculator import EVCalculator

logger = logging.getLogger(__name__)

MARKET_BLEND = 0.0
MAX_XGB_CONF = 0.72
PLAYER_AWARE_KIND = "mlb_player_moneyline_artifact"
BASELINE_KIND = "mlb_win_probability_bundle"
PLAYER_AWARE_VERSION = "mlb-player-v1.8"

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
        self._player_bundle: dict | None = None
        self._xgb_models_loaded: bool = False
        self._artifact_rejections: list[str] = []
        self._last_fallback_reason: str | None = None

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

        self._last_fallback_reason = None
        if self._xgb_models_loaded:
            try:
                probs = None
                source = "unsupported"
                model_label = "unsupported artifact"
                if self._player_bundle:
                    probs = self._predict_player_bundle(game)
                    source = "player_aware"
                    model_label = "v1.8 player-aware"
                if probs is None and self._player_bundle:
                    self._last_fallback_reason = self._last_fallback_reason or "player_features_unavailable"
                if probs is None and self._model_bundle:
                    probs = self._predict_bundle(game)
                    source = "trained_calibrated"
                    model_label = "v1.3 baseline fallback"
                if probs is not None:
                    home_prob, away_prob, extras = probs
                    if home_prob > MAX_XGB_CONF:
                        home_prob = MAX_XGB_CONF
                        away_prob = 1.0 - MAX_XGB_CONF
                    elif away_prob > MAX_XGB_CONF:
                        away_prob = MAX_XGB_CONF
                        home_prob = 1.0 - MAX_XGB_CONF
                    home_prob, away_prob = self._credibility_filter(
                        home_team, away_team, home_prob, away_prob, game
                    )
                    uncertainty_flags = extras.get("uncertainty_flags", [])
                    confidence = "LOW" if uncertainty_flags else ("HIGH" if source == "player_aware" else "MEDIUM")
                    return {
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_win_prob": round(home_prob, 4),
                        "away_win_prob": round(away_prob, 4),
                        "source": source,
                        "model_label": model_label,
                        "fallback_reason": self._last_fallback_reason,
                        "uncertainty_flags": uncertainty_flags,
                        "confidence": confidence,
                        "pick_eligible": not uncertainty_flags,
                        "feature_context": extras.get("feature_context", {}),
                        "metrics": extras.get("metrics", {}),
                    }
            except Exception as exc:
                logger.debug("MLB trained prediction failed, using market-implied: %s", exc)
                self._last_fallback_reason = str(exc)

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

    def runtime_report(self) -> dict:
        bundle = self._player_bundle or self._model_bundle or {}
        if self._player_bundle:
            source = "v1.8 player-aware"
        elif self._model_bundle:
            source = "v1.3 baseline fallback"
        else:
            source = "market-implied fallback"
        metrics = bundle.get("metrics") or {}
        return {
            "source": source,
            "model_version": bundle.get("model_version") or bundle.get("version"),
            "validated": bool(bundle.get("validated")),
            "promotion_gates": bundle.get("promotion_gates") or {},
            "metrics": metrics,
            "selective_report": {
                "coverage": metrics.get("coverage"),
                "selective_win_rate": metrics.get("selective_win_rate"),
                "all_games_accuracy": metrics.get("accuracy"),
                "brier_score": metrics.get("brier_score"),
                "log_loss": metrics.get("log_loss"),
            },
            "rejections": list(self._artifact_rejections),
        }

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
            "model_label": "market-implied fallback",
            "fallback_reason": self._last_fallback_reason or "trained_model_unavailable",
            "uncertainty_flags": [],
            "confidence": "LOW",
            "pick_eligible": False,
            "feature_context": {},
            "metrics": {},
        }

    # ------------------------------------------------------------------
    # Internal: XGBoost loading
    # ------------------------------------------------------------------

    def _load_legacy_xgb_models_disabled(self) -> None:
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

    def _load_xgb_models(self) -> None:
        try:
            import joblib  # noqa: PLC0415

            for model_path in self._find_model_paths():
                try:
                    loaded = joblib.load(str(model_path))
                except Exception as exc:
                    self._artifact_rejections.append(f"{model_path.name}: load_failed:{exc}")
                    continue
                if self._accept_loaded_artifact(loaded, model_path):
                    logger.info("Loaded MLB model: %s", model_path.name)
                    return
            logger.debug("No validated MLB model file found - using market-implied")
        except Exception as exc:
            logger.debug("MLB model load skipped: %s", exc)

    def _find_model_paths(self) -> list[Path]:
        paths: list[Path] = []
        preferred = [
            Path("alpha/models/mlb_player_moneyline.pkl"),
            self._find_model_path(),
            Path("alpha/models/mlb_win_probability.pkl"),
        ]
        for path in preferred:
            if path is not None and path.exists() and path not in paths:
                paths.append(path)
        for search_dir in _MODEL_SEARCH_DIRS:
            if not search_dir.exists():
                continue
            for pattern in ("*.pkl", "*.json"):
                candidates = sorted(search_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
                for candidate in candidates:
                    if candidate not in paths:
                        paths.append(candidate)
        return paths

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

    def _accept_loaded_artifact(self, loaded: Any, model_path: Path) -> bool:
        if not isinstance(loaded, dict):
            self._artifact_rejections.append(f"{model_path.name}: legacy_artifact_unsupported")
            return False
        kind = loaded.get("kind")
        if kind == PLAYER_AWARE_KIND:
            reason = self._player_bundle_rejection_reason(loaded)
            if reason:
                self._artifact_rejections.append(f"{model_path.name}: {reason}")
                return False
            self._player_bundle = loaded
            self._xgb_model = loaded["model"]
            self._xgb_models_loaded = True
            return True
        if kind == BASELINE_KIND:
            from alpha.engines.sports.mlb_training import FEATURE_NAMES

            if not loaded.get("validated") or tuple(loaded.get("feature_names", ())) != FEATURE_NAMES:
                self._artifact_rejections.append(f"{model_path.name}: baseline_validation_or_schema_failed")
                logger.warning("MLB artifact failed validation/schema gate")
                return False
            self._model_bundle = loaded
            self._xgb_model = loaded["model"]
            self._xgb_models_loaded = True
            return True
        self._artifact_rejections.append(f"{model_path.name}: unknown_artifact_kind")
        return False

    def _player_bundle_rejection_reason(self, bundle: dict) -> str | None:
        from alpha.engines.sports.mlb_player_modeling import PLAYER_FEATURE_SETS

        version = bundle.get("schema_version") or bundle.get("model_version")
        gates = bundle.get("promotion_gates") or {}
        feature_names = tuple(bundle.get("feature_names") or ())
        known_feature_sets = {tuple(features) for features in PLAYER_FEATURE_SETS.values()}
        if version != PLAYER_AWARE_VERSION:
            return "player_schema_version_failed"
        if not bundle.get("validated"):
            return "player_validation_failed"
        if not gates or not all(bool(value) for value in gates.values()):
            return "player_promotion_gates_failed"
        if feature_names not in known_feature_sets:
            return "player_feature_schema_unknown"
        if bundle.get("model") is None or bundle.get("calibrator") is None:
            return "player_model_or_calibrator_missing"
        return None

    # ------------------------------------------------------------------
    # Internal: XGBoost prediction
    # ------------------------------------------------------------------

    def _predict_player_bundle(self, game: dict) -> tuple[float, float, dict] | None:
        """Predict with a validated v1.8 bundle and precomputed player-aware features."""
        import numpy as np

        bundle = self._player_bundle
        if not bundle:
            return None
        feature_names = list(bundle.get("feature_names") or [])
        values, missing = self._player_feature_values(game, feature_names)
        if missing:
            self._last_fallback_reason = "missing_player_features:" + ",".join(missing[:5])
            return None
        raw = bundle["model"].predict_proba(np.asarray([values], dtype=float))[:, 1]
        home = float(self._calibrated_player_probability(bundle["calibrator"], raw)[0])
        uncertainty_flags = self._player_uncertainty_flags(game)
        return home, 1.0 - home, {
            "uncertainty_flags": uncertainty_flags,
            "feature_context": self._player_feature_context(game),
            "metrics": bundle.get("metrics") or {},
        }

    def _predict_bundle(self, game: dict) -> tuple[float, float, dict] | None:
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
        return home, 1.0 - home, {"metrics": bundle.get("metrics") or {}}

    def _player_feature_values(self, game: dict, feature_names: list[str]) -> tuple[list[float], list[str]]:
        features = game.get("player_features") or {}
        values: list[float] = []
        missing: list[str] = []
        for name in feature_names:
            value = features.get(name, game.get(name))
            if value in (None, ""):
                missing.append(name)
                values.append(0.0)
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                missing.append(name)
                values.append(0.0)
        return values, missing

    def _calibrated_player_probability(self, calibrator: Any, raw_probs: Any) -> list[float]:
        import numpy as np

        if hasattr(calibrator, "predict"):
            calibrated = calibrator.predict(raw_probs.tolist())
            return [float(p) for p in calibrated]
        if hasattr(calibrator, "predict_proba"):
            probs = np.clip(raw_probs, 1e-6, 1.0 - 1e-6)
            logits = np.log(probs / (1.0 - probs)).reshape(-1, 1)
            return [float(p) for p in calibrator.predict_proba(logits)[:, 1]]
        return [float(p) for p in raw_probs]

    def _player_uncertainty_flags(self, game: dict) -> list[str]:
        features = game.get("player_features") or game
        flags: list[str] = []
        if float(features.get("player_feature_missing_flag") or 0.0) >= 1.0:
            flags.append("player_feature_missing")
        if float(features.get("lineup_missing_count_total") or 0.0) > 0.0:
            flags.append("lineup_missing")
        for key, label in (
            ("home_sp_missing", "home_starter_missing"),
            ("away_sp_missing", "away_starter_missing"),
            ("home_bp_missing", "home_bullpen_missing"),
            ("away_bp_missing", "away_bullpen_missing"),
        ):
            if float(features.get(key) or 0.0) >= 1.0:
                flags.append(label)
        confidence = features.get("player_source_confidence")
        if confidence is not None and float(confidence) < 0.8:
            flags.append("low_player_source_confidence")
        return flags

    def _player_feature_context(self, game: dict) -> dict:
        features = game.get("player_features") or game
        keys = (
            "sp_quality_diff",
            "lineup_strength_diff",
            "bullpen_quality_diff",
            "absence_value_diff",
            "lineup_missing_count_total",
            "player_feature_missing_flag",
        )
        return {key: features.get(key) for key in keys if key in features}

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
