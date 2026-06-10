"""
XGBoostPropModel — gradient-boosted projection model for NBA player props.

Trains on the SHARED pregame feature schema from
alpha.engines.sports.prop_features — the same builder used at inference —
so there is no train/inference mismatch.

Output: projected stat value (regression).  PropModel applies the
NegBin/Poisson/ZIP CDF on top to compute P(over line).  Because every
contextual input (minutes, rest, opponent, pace, home/away) is already a
model feature, NO post-hoc multipliers may be applied to this projection.

Schema safety:
  - Models persist feature_names + feature_schema_version + model_version.
  - predict() fails closed (PropSchemaError) when a required feature is
    missing — it never silently runs on partial input.
  - load() rejects legacy pickles that lack schema metadata.
"""
from __future__ import annotations

import math
import pickle
from datetime import datetime, timezone
from pathlib import Path

from alpha.engines.sports.prop_features import (
    ALL_FEATURES,
    FEATURE_SCHEMA_VERSION,
    OPTIONAL_FEATURES,
    features_to_vector,
)

MODEL_VERSION = "2.0.0"


class PropSchemaError(ValueError):
    """Raised when model and feature schemas do not match (fail closed)."""


class XGBoostPropModel:
    def __init__(self, target: str) -> None:
        """target: one of 'pts', 'reb', 'ast', 'fg3m'"""
        self._target = target
        self._model = None
        self.feature_names: list[str] = list(ALL_FEATURES)
        self.feature_schema_version: str = FEATURE_SCHEMA_VERSION
        self.model_version: str = MODEL_VERSION
        self.trained_at: str | None = None
        self.validation_metrics: dict = {}

    @property
    def target(self) -> str:
        return self._target

    def fit(
        self,
        features: list[dict],
        targets: list[float],
        val_features: list[dict] | None = None,
        val_targets: list[float] | None = None,
        early_stopping_rounds: int = 30,
    ) -> None:
        """
        Train the XGBoost regressor.  When a validation set is supplied
        (chronologically AFTER the training rows — caller's responsibility),
        early stopping is used and validation metrics are recorded.
        """
        import numpy as np
        import xgboost as xgb

        if len(features) < 20:
            raise ValueError(f"Need at least 20 samples; got {len(features)}")

        X = np.array([features_to_vector(f, self.feature_names) for f in features])
        y = np.array(targets, dtype=float)

        params = dict(
            n_estimators=500,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )

        if val_features and val_targets:
            X_val = np.array([features_to_vector(f, self.feature_names) for f in val_features])
            y_val = np.array(val_targets, dtype=float)
            self._model = xgb.XGBRegressor(
                **params, early_stopping_rounds=early_stopping_rounds,
            )
            self._model.fit(X, y, eval_set=[(X_val, y_val)], verbose=False)
            pred_val = self._model.predict(X_val)
            mae = float(np.mean(np.abs(pred_val - y_val)))
            rmse = float(np.sqrt(np.mean((pred_val - y_val) ** 2)))
            self.validation_metrics = {
                "val_mae": mae,
                "val_rmse": rmse,
                "val_samples": int(len(y_val)),
                "best_iteration": int(getattr(self._model, "best_iteration", -1)),
            }
        else:
            self._model = xgb.XGBRegressor(**params)
            self._model.fit(X, y)
            self.validation_metrics = {}

        self.trained_at = datetime.now(timezone.utc).isoformat()

    def predict(self, features: dict) -> float:
        """
        Predict the projected stat value for one pregame snapshot.

        Raises PropSchemaError when a required feature is missing — the
        caller must fall back explicitly, never run on partial input.
        """
        if self._model is None:
            raise RuntimeError("Model not trained — call fit() or load()")
        import numpy as np

        try:
            vector = features_to_vector(features, self.feature_names)
        except KeyError as exc:
            raise PropSchemaError(
                f"{self._target} model: {exc.args[0]} "
                f"(model schema {self.feature_schema_version})"
            ) from exc

        X = np.array([vector])
        return float(max(0.0, self._model.predict(X)[0]))

    def feature_importance(self) -> dict[str, float]:
        """Return feature importances as a dict (requires fitted model)."""
        if self._model is None:
            raise RuntimeError("Model not fitted")
        return dict(zip(self.feature_names, self._model.feature_importances_))

    def metadata(self) -> dict:
        """Model metadata for the sidecar JSON / audit logs."""
        return {
            "target": self._target,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "feature_names": self.feature_names,
            "trained_at": self.trained_at,
            "validation_metrics": self.validation_metrics,
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "target": self._target,
                "model": self._model,
                "feature_names": self.feature_names,
                "feature_schema_version": self.feature_schema_version,
                "model_version": self.model_version,
                "trained_at": self.trained_at,
                "validation_metrics": self.validation_metrics,
            }, f)

    @classmethod
    def load(cls, path: Path) -> "XGBoostPropModel":
        """
        Load a saved model.  Fails closed (PropSchemaError) on legacy
        pickles without schema metadata or on schema version mismatch —
        a model trained on different features must never serve predictions.
        """
        with open(path, "rb") as f:
            data = pickle.load(f)

        if "feature_names" not in data or "feature_schema_version" not in data:
            raise PropSchemaError(
                f"{path}: legacy model without feature schema metadata — "
                "retrain with scripts/train_xgb_prop_model.py"
            )
        if data["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
            raise PropSchemaError(
                f"{path}: model schema {data['feature_schema_version']} != "
                f"current {FEATURE_SCHEMA_VERSION} — retrain required"
            )

        obj = cls(target=data["target"])
        obj._model = data["model"]
        obj.feature_names = data["feature_names"]
        obj.feature_schema_version = data["feature_schema_version"]
        obj.model_version = data.get("model_version", "unknown")
        obj.trained_at = data.get("trained_at")
        obj.validation_metrics = data.get("validation_metrics", {})
        return obj
