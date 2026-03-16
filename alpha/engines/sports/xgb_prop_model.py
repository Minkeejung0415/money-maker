"""
XGBoostPropModel — replaces the hand-tuned weighted average in PropModel.

Instead of manually computing:
    proj = weighted_avg(values) * opp_adj * pace * rest

We train a gradient-boosted tree that learns these relationships from
2-3 seasons of historical game logs.

Output: projected stat value (regression).
PropModel still applies the NegBin/ZIP CDF to compute P(over line).

Features:
    roll5        — decay-weighted avg last 5 qualifying games
    roll10       — decay-weighted avg last 10 qualifying games
    roll20       — decay-weighted avg last 20 qualifying games
    min_recent   — avg minutes last 5 games
    opp_def_rtg  — opponent defensive rating
    is_home      — 1 if home, 0 if away
    rest_days    — days since last game (capped at 4)
    pace         — opponent pace
"""
from __future__ import annotations

import pickle
from pathlib import Path

_FEATURE_COLS = [
    "roll5", "roll10", "roll20", "min_recent",
    "opp_def_rtg", "is_home", "rest_days", "pace",
]


class XGBoostPropModel:
    def __init__(self, target: str) -> None:
        """target: one of 'pts', 'reb', 'ast'"""
        self._target = target
        self._model = None

    def fit(self, features: list[dict], targets: list[float]) -> None:
        """Train XGBoost regressor on feature dicts + target values."""
        import xgboost as xgb
        import numpy as np

        if len(features) < 20:
            raise ValueError(f"Need at least 20 samples; got {len(features)}")

        X = np.array([[f.get(col, 0.0) for col in _FEATURE_COLS] for f in features])
        y = np.array(targets)

        self._model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        self._model.fit(X, y)

    def predict(self, features: dict) -> float:
        """Predict projected stat value for one game."""
        if self._model is None:
            raise RuntimeError("Model not trained — call fit() or load()")
        import numpy as np
        X = np.array([[features.get(col, 0.0) for col in _FEATURE_COLS]])
        return float(max(0.0, self._model.predict(X)[0]))

    def feature_importance(self) -> dict[str, float]:
        """Return feature importances as a dict (requires fitted model)."""
        if self._model is None:
            raise RuntimeError("Model not fitted")
        return dict(zip(_FEATURE_COLS, self._model.feature_importances_))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"target": self._target, "model": self._model}, f)

    @classmethod
    def load(cls, path: Path) -> "XGBoostPropModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls(target=data["target"])
        obj._model = data["model"]
        return obj
