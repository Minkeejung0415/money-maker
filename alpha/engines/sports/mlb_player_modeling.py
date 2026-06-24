"""Walk-forward modeling helpers for player-aware MLB moneyline features."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Callable, Sequence

from alpha.engines.sports.evaluation import probability_metrics
from alpha.engines.sports.mlb_training import FEATURE_NAMES

BASELINE_FEATURES = tuple(FEATURE_NAMES)

STARTER_FEATURES = (
    "home_sp_quality",
    "away_sp_quality",
    "sp_quality_diff",
    "home_sp_workload",
    "away_sp_workload",
    "sp_workload_diff",
    "home_sp_rest_days",
    "away_sp_rest_days",
    "home_sp_missing",
    "away_sp_missing",
)

LINEUP_FEATURES = (
    "home_lineup_strength",
    "away_lineup_strength",
    "lineup_strength_diff",
    "home_top_order_strength",
    "away_top_order_strength",
    "top_order_strength_diff",
    "home_lineup_lefty_share",
    "away_lineup_lefty_share",
    "home_lineup_missing_count",
    "away_lineup_missing_count",
    "lineup_missing_count_total",
    "home_lineup_confirmed_share",
    "away_lineup_confirmed_share",
)

BULLPEN_FEATURES = (
    "home_bp_recent_pitches",
    "away_bp_recent_pitches",
    "bullpen_recent_pitches_diff",
    "home_bp_quality",
    "away_bp_quality",
    "bullpen_quality_diff",
    "home_bp_missing",
    "away_bp_missing",
)

ABSENCE_FEATURES = (
    "home_absence_value",
    "away_absence_value",
    "absence_value_diff",
    "home_absence_count",
    "away_absence_count",
    "player_feature_missing_flag",
)

PLAYER_FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "baseline_v1_3": BASELINE_FEATURES,
    "starter_only": BASELINE_FEATURES + STARTER_FEATURES,
    "starter_lineup": BASELINE_FEATURES + STARTER_FEATURES + LINEUP_FEATURES,
    "starter_lineup_bullpen": (
        BASELINE_FEATURES + STARTER_FEATURES + LINEUP_FEATURES + BULLPEN_FEATURES
    ),
    "full_player_aware": (
        BASELINE_FEATURES
        + STARTER_FEATURES
        + LINEUP_FEATURES
        + BULLPEN_FEATURES
        + ABSENCE_FEATURES
    ),
}


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    train_indices: list[int]
    calibration_indices: list[int]
    test_indices: list[int]
    train_start: str
    train_end: str
    calibration_start: str
    calibration_end: str
    test_start: str
    test_end: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "fold": self.fold,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "calibration_start": self.calibration_start,
            "calibration_end": self.calibration_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "train_n": len(self.train_indices),
            "calibration_n": len(self.calibration_indices),
            "test_n": len(self.test_indices),
        }


class PriorProbabilityModel:
    """Predicts the training-set base rate when a fold cannot fit a classifier."""

    def __init__(self, prior: float) -> None:
        self.prior = min(max(float(prior), 1e-6), 1.0 - 1e-6)

    def fit(self, _x: Any, _y: Any) -> "PriorProbabilityModel":
        return self

    def predict_proba(self, x: Any) -> Any:
        import numpy as np

        n = len(x)
        positive = np.full(n, self.prior, dtype=float)
        return np.column_stack((1.0 - positive, positive))


class IdentityCalibrator:
    def predict(self, raw_probs: Sequence[float]) -> list[float]:
        return [min(max(float(p), 1e-6), 1.0 - 1e-6) for p in raw_probs]


class SigmoidCalibrator:
    def __init__(self, model: Any) -> None:
        self.model = model

    def predict(self, raw_probs: Sequence[float]) -> list[float]:
        import numpy as np

        logits = _logit_array(raw_probs)
        return self.model.predict_proba(logits)[:, 1].tolist()


def available_model_factories() -> dict[str, Callable[[], Any]]:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    factories: dict[str, Callable[[], Any]] = {
        "logistic": lambda: Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(max_iter=1000, C=0.5)),
            ]
        ),
        "hist_gradient_boosting": lambda: Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    HistGradientBoostingClassifier(
                        max_depth=3,
                        max_iter=100,
                        learning_rate=0.05,
                        l2_regularization=1.0,
                        random_state=42,
                    ),
                ),
            ]
        ),
    }
    try:
        from lightgbm import LGBMClassifier

        factories["lightgbm"] = lambda: Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    LGBMClassifier(
                        n_estimators=100,
                        max_depth=3,
                        learning_rate=0.05,
                        random_state=42,
                        verbose=-1,
                    ),
                ),
            ]
        )
    except Exception:
        pass
    return factories


def walkforward_train_cal_test_splits(
    rows: Sequence[dict[str, Any]],
    *,
    date_col: str = "game_date",
    min_train: int = 60,
    calibration_size: int = 20,
    test_size: int = 20,
    step_size: int | None = None,
) -> list[WalkForwardFold]:
    ordered = sorted(range(len(rows)), key=lambda i: (str(rows[i][date_col]), str(rows[i].get("game_id", i))))
    n = len(ordered)
    step = step_size or test_size
    folds: list[WalkForwardFold] = []
    fold_no = 1
    test_start = min_train + calibration_size
    while test_start + test_size <= n:
        train_idx = ordered[: test_start - calibration_size]
        calibration_idx = ordered[test_start - calibration_size : test_start]
        test_idx = ordered[test_start : test_start + test_size]
        folds.append(
            WalkForwardFold(
                fold=fold_no,
                train_indices=train_idx,
                calibration_indices=calibration_idx,
                test_indices=test_idx,
                train_start=str(rows[train_idx[0]][date_col]),
                train_end=str(rows[train_idx[-1]][date_col]),
                calibration_start=str(rows[calibration_idx[0]][date_col]),
                calibration_end=str(rows[calibration_idx[-1]][date_col]),
                test_start=str(rows[test_idx[0]][date_col]),
                test_end=str(rows[test_idx[-1]][date_col]),
            )
        )
        fold_no += 1
        test_start += step
    if not folds:
        raise ValueError(
            "Not enough rows for walk-forward train/calibration/test split "
            f"(got {n}, need at least {min_train + calibration_size + test_size})"
        )
    return folds


def fit_sigmoid_calibrator(raw_probs: Sequence[float], outcomes: Sequence[int]) -> IdentityCalibrator | SigmoidCalibrator:
    if len(set(int(y) for y in outcomes)) < 2:
        return IdentityCalibrator()
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression().fit(_logit_array(raw_probs), list(outcomes))
    return SigmoidCalibrator(model)


def score_probabilities(outcomes: Sequence[int], probs: Sequence[float]) -> dict[str, Any]:
    metrics = probability_metrics(list(outcomes), list(probs))
    correct = sum((float(p) >= 0.5) == bool(y) for y, p in zip(outcomes, probs))
    metrics["accuracy"] = correct / len(outcomes)
    return metrics


def run_walkforward_ablations(
    rows: Sequence[dict[str, Any]],
    *,
    feature_sets: dict[str, Sequence[str]] | None = None,
    model_names: Sequence[str] | None = None,
    target_col: str = "home_win",
    date_col: str = "game_date",
    split_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("rows must be non-empty")
    selected_feature_sets = feature_sets or PLAYER_FEATURE_SETS
    factories = available_model_factories()
    selected_models = list(model_names or factories.keys())
    unknown = [name for name in selected_models if name not in factories]
    if unknown:
        raise ValueError(f"Unknown model(s): {', '.join(unknown)}")
    folds = walkforward_train_cal_test_splits(rows, date_col=date_col, **(split_kwargs or {}))

    ablations: list[dict[str, Any]] = []
    for feature_set_name, features in selected_feature_sets.items():
        feature_names = tuple(features)
        for model_name in selected_models:
            fold_reports = [
                _score_fold(
                    rows=rows,
                    fold=fold,
                    feature_names=feature_names,
                    model_factory=factories[model_name],
                    model_name=model_name,
                    target_col=target_col,
                )
                for fold in folds
            ]
            ablations.append(
                {
                    "feature_set": feature_set_name,
                    "model": model_name,
                    "features": list(feature_names),
                    "is_baseline": feature_set_name == "baseline_v1_3",
                    "folds": fold_reports,
                    "mean_metrics": _mean_metrics([f["metrics"] for f in fold_reports]),
                }
            )
    return {
        "schema_version": "mlb-player-v1.8",
        "target": target_col,
        "date_col": date_col,
        "models": selected_models,
        "feature_sets": {name: list(features) for name, features in selected_feature_sets.items()},
        "folds": [fold.as_metadata() for fold in folds],
        "ablations": ablations,
    }


def select_promoted_result(
    report: dict[str, Any],
    *,
    baseline_feature_set: str = "baseline_v1_3",
    metric: str = "brier_score",
) -> dict[str, Any] | None:
    ablations = report.get("ablations", [])
    baselines = [a for a in ablations if a.get("feature_set") == baseline_feature_set]
    candidates = [a for a in ablations if a.get("feature_set") != baseline_feature_set]
    if not baselines or not candidates:
        return None
    baseline_score = min(float(a["mean_metrics"][metric]) for a in baselines)
    best = min(candidates, key=lambda a: float(a["mean_metrics"][metric]))
    if float(best["mean_metrics"][metric]) < baseline_score:
        return best
    return None


def build_model_artifact_metadata(
    result: dict[str, Any],
    report: dict[str, Any],
    *,
    source_fingerprints: dict[str, str] | None = None,
    schema_version: str = "mlb-player-v1.8",
    promotion_metric: str = "brier_score",
) -> dict[str, Any]:
    baseline_scores = [
        float(a["mean_metrics"][promotion_metric])
        for a in report.get("ablations", [])
        if a.get("feature_set") == "baseline_v1_3"
    ]
    baseline_score = min(baseline_scores) if baseline_scores else None
    candidate_score = float(result["mean_metrics"][promotion_metric])
    improves_baseline = baseline_score is not None and candidate_score < baseline_score
    gates = {
        "baseline_available": baseline_score is not None,
        "candidate_improves_baseline_brier": improves_baseline,
        "has_walkforward_folds": bool(result.get("folds")),
        "has_feature_schema": bool(result.get("features")),
    }
    return {
        "kind": "mlb_player_moneyline_artifact",
        "schema_version": schema_version,
        "model_version": schema_version,
        "candidate": {
            "feature_set": result["feature_set"],
            "model": result["model"],
        },
        "feature_names": list(result["features"]),
        "split_dates": [
            {
                "fold": fold["fold"],
                "train_start": fold["train_start"],
                "train_end": fold["train_end"],
                "calibration_start": fold["calibration_start"],
                "calibration_end": fold["calibration_end"],
                "test_start": fold["test_start"],
                "test_end": fold["test_end"],
            }
            for fold in result.get("folds", [])
        ],
        "source_fingerprints": source_fingerprints or {"rows": _rows_fingerprint(report.get("folds", []))},
        "metrics": result["mean_metrics"],
        "promotion_gates": gates,
        "validated": all(gates.values()),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _score_fold(
    *,
    rows: Sequence[dict[str, Any]],
    fold: WalkForwardFold,
    feature_names: Sequence[str],
    model_factory: Callable[[], Any],
    model_name: str,
    target_col: str,
) -> dict[str, Any]:
    x_train, y_train = _matrix(rows, fold.train_indices, feature_names, target_col)
    x_cal, y_cal = _matrix(rows, fold.calibration_indices, feature_names, target_col)
    x_test, y_test = _matrix(rows, fold.test_indices, feature_names, target_col)
    if len(set(y_train.tolist())) < 2:
        model = PriorProbabilityModel(float(y_train.mean()))
    else:
        model = model_factory()
        model.fit(x_train, y_train)
    raw_cal = model.predict_proba(x_cal)[:, 1]
    calibrator = fit_sigmoid_calibrator(raw_cal.tolist(), y_cal.tolist())
    raw_test = model.predict_proba(x_test)[:, 1]
    probs = calibrator.predict(raw_test.tolist())
    return {
        **fold.as_metadata(),
        "model": model_name,
        "metrics": score_probabilities(y_test.tolist(), probs),
    }


def _matrix(
    rows: Sequence[dict[str, Any]],
    indices: Sequence[int],
    feature_names: Sequence[str],
    target_col: str,
) -> tuple[Any, Any]:
    import numpy as np

    x = []
    y = []
    for i in indices:
        row = rows[i]
        x.append([_to_float(row.get(name)) for name in feature_names])
        y.append(int(row[target_col]))
    return np.asarray(x, dtype=float), np.asarray(y, dtype=int)


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return float("nan")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _logit_array(raw_probs: Sequence[float]) -> Any:
    import numpy as np

    probs = np.clip(np.asarray(raw_probs, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(probs / (1.0 - probs)).reshape(-1, 1)


def _mean_metrics(metrics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    keys = ("brier_score", "log_loss", "accuracy")
    total_n = sum(int(m["n"]) for m in metrics)
    means = {
        key: sum(float(m[key]) * int(m["n"]) for m in metrics) / total_n
        for key in keys
    }
    means["n"] = total_n
    return means


def _rows_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
