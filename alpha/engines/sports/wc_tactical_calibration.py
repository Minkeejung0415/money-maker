"""Regularized tactical residual calibration with fail-closed promotion gates."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Callable, Iterable, Sequence

import numpy as np
from scipy.optimize import minimize

from alpha.data.ingestion.wc_tactical_history import TACTICAL_COMPONENTS, TacticalHistoryRow

MAX_TACTICAL_ELO = 40.0
MAX_LOG_GOAL_ADJUSTMENT = math.log(1.10)
MIN_LOG_GOAL_ADJUSTMENT = math.log(0.90)
REGULARIZATION_GRID = (0.1, 1.0, 10.0, 100.0)
FIXED_V16_WEIGHTS = np.asarray((0.035, 0.015, 0.015, 0.010, 0.010, 0.015, 0.015))


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values, axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def _outcome_index(row: TacticalHistoryRow) -> int:
    return 0 if row.home_goals > row.away_goals else 2 if row.home_goals < row.away_goals else 1


def _features(row: TacticalHistoryRow) -> np.ndarray:
    return np.asarray(
        [float(row.home_components[name]) - float(row.away_components[name]) for name in TACTICAL_COMPONENTS],
        dtype=float,
    )


def _side_features(row: TacticalHistoryRow, side: str) -> np.ndarray:
    values = row.home_components if side == "home" else row.away_components
    return np.asarray([float(values[name]) for name in TACTICAL_COMPONENTS], dtype=float)


@dataclass(frozen=True)
class Standardizer:
    mean: tuple[float, ...]
    scale: tuple[float, ...]

    @classmethod
    def fit(cls, values: np.ndarray) -> "Standardizer":
        mean = values.mean(axis=0)
        scale = values.std(axis=0)
        scale[scale < 1e-8] = 1.0
        return cls(tuple(mean.tolist()), tuple(scale.tolist()))

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (values - np.asarray(self.mean)) / np.asarray(self.scale)


@dataclass(frozen=True)
class OutcomeResidualModel:
    weights: tuple[float, ...]
    standardizer: Standardizer
    regularization: float

    def probabilities(self, row: TacticalHistoryRow) -> tuple[float, float, float]:
        feature = self.standardizer.transform(_features(row)[None, :])[0]
        adjustment = float(np.dot(feature, np.asarray(self.weights)))
        max_logit = MAX_TACTICAL_ELO * math.log(10.0) / 400.0
        adjustment = max(-max_logit, min(max_logit, adjustment))
        baseline = np.log(np.asarray([[row.baseline_home, row.baseline_draw, row.baseline_away]]))
        logits = baseline + np.asarray([[adjustment, 0.0, -adjustment]])
        result = _softmax(logits)[0]
        return tuple(float(value) for value in result)


@dataclass(frozen=True)
class GoalResidualModel:
    weights: tuple[float, ...]
    standardizer: Standardizer
    regularization: float

    def rates(self, row: TacticalHistoryRow) -> tuple[float, float]:
        weights = np.asarray(self.weights)
        home = self.standardizer.transform(_side_features(row, "home")[None, :])[0]
        away = self.standardizer.transform(_side_features(row, "away")[None, :])[0]
        home_adjustment = max(MIN_LOG_GOAL_ADJUSTMENT, min(MAX_LOG_GOAL_ADJUSTMENT, float(home @ weights)))
        away_adjustment = max(MIN_LOG_GOAL_ADJUSTMENT, min(MAX_LOG_GOAL_ADJUSTMENT, float(away @ weights)))
        return row.baseline_home_lambda * math.exp(home_adjustment), row.baseline_away_lambda * math.exp(away_adjustment)


def fit_outcome(rows: Sequence[TacticalHistoryRow], regularization: float) -> OutcomeResidualModel:
    if not rows:
        raise ValueError("outcome training rows are required")
    raw = np.vstack([_features(row) for row in rows])
    standardizer = Standardizer.fit(raw)
    x = standardizer.transform(raw)
    baseline = np.log(np.asarray([[row.baseline_home, row.baseline_draw, row.baseline_away] for row in rows]))
    actual = np.asarray([_outcome_index(row) for row in rows])

    def objective(weights: np.ndarray) -> float:
        adjustment = x @ weights
        probabilities = _softmax(baseline + np.column_stack([adjustment, np.zeros(len(rows)), -adjustment]))
        loss = -np.log(np.clip(probabilities[np.arange(len(rows)), actual], 1e-12, 1.0)).mean()
        return float(loss + regularization * np.dot(weights, weights) / len(rows))

    result = minimize(objective, np.zeros(x.shape[1]), method="L-BFGS-B")
    if not result.success or not np.all(np.isfinite(result.x)):
        raise RuntimeError(f"outcome residual optimization failed: {result.message}")
    return OutcomeResidualModel(tuple(result.x.tolist()), standardizer, regularization)


def fit_goals(rows: Sequence[TacticalHistoryRow], regularization: float) -> GoalResidualModel:
    if not rows:
        raise ValueError("goal training rows are required")
    raw = np.vstack([_side_features(row, side) for row in rows for side in ("home", "away")])
    standardizer = Standardizer.fit(raw)
    x = standardizer.transform(raw)
    actual = np.asarray([goals for row in rows for goals in (row.home_goals, row.away_goals)], dtype=float)
    baseline = np.asarray([rate for row in rows for rate in (row.baseline_home_lambda, row.baseline_away_lambda)], dtype=float)

    def objective(weights: np.ndarray) -> float:
        adjustment = np.clip(x @ weights, MIN_LOG_GOAL_ADJUSTMENT, MAX_LOG_GOAL_ADJUSTMENT)
        rates = np.clip(baseline * np.exp(adjustment), 1e-8, None)
        loss = np.mean(rates - actual * np.log(rates))
        return float(loss + regularization * np.dot(weights, weights) / len(rows))

    result = minimize(objective, np.zeros(x.shape[1]), method="L-BFGS-B")
    if not result.success or not np.all(np.isfinite(result.x)):
        raise RuntimeError(f"goal residual optimization failed: {result.message}")
    return GoalResidualModel(tuple(result.x.tolist()), standardizer, regularization)


def expanding_folds(rows: Sequence[TacticalHistoryRow], folds: int = 4) -> list[tuple[list[int], list[int]]]:
    """Return expanding train/validation indices with strictly later validation."""
    if len(rows) < folds + 2:
        raise ValueError("not enough rows for expanding validation")
    ordered = sorted(range(len(rows)), key=lambda index: rows[index].kickoff)
    block = max(1, len(rows) // (folds + 1))
    result = []
    for fold in range(1, folds + 1):
        boundary = block * fold
        end = len(rows) if fold == folds else min(len(rows), boundary + block)
        train, validation = ordered[:boundary], ordered[boundary:end]
        if not validation:
            continue
        if max(rows[index].kickoff for index in train) >= min(rows[index].kickoff for index in validation):
            raise ValueError("chronological fold leakage detected")
        result.append((train, validation))
    return result


def select_regularization(
    rows: Sequence[TacticalHistoryRow],
    fit: Callable[[Sequence[TacticalHistoryRow], float], object],
    loss: Callable[[object, Sequence[TacticalHistoryRow]], float],
    grid: Sequence[float] = REGULARIZATION_GRID,
) -> float:
    scores: dict[float, list[float]] = {float(value): [] for value in grid}
    for train_indices, validation_indices in expanding_folds(rows):
        train = [rows[index] for index in train_indices]
        validation = [rows[index] for index in validation_indices]
        for value in scores:
            scores[value].append(loss(fit(train, value), validation))
    return min(scores, key=lambda value: (sum(scores[value]) / len(scores[value]), -value))


def outcome_log_loss(model: OutcomeResidualModel, rows: Sequence[TacticalHistoryRow]) -> float:
    return float(np.mean([-math.log(max(1e-12, model.probabilities(row)[_outcome_index(row)])) for row in rows]))


def goal_nll(model: GoalResidualModel, rows: Sequence[TacticalHistoryRow]) -> float:
    losses = []
    for row in rows:
        for actual, rate in zip((row.home_goals, row.away_goals), model.rates(row)):
            losses.append(rate - actual * math.log(max(rate, 1e-12)))
    return float(np.mean(losses))


@dataclass(frozen=True)
class BootstrapDelta:
    mean: float
    lower: float
    upper: float
    p_value: float


def paired_bootstrap_delta(
    candidate_losses: Sequence[float],
    control_losses: Sequence[float],
    *,
    repetitions: int = 10_000,
    seed: int = 20260621,
) -> BootstrapDelta:
    candidate = np.asarray(candidate_losses, dtype=float)
    control = np.asarray(control_losses, dtype=float)
    if candidate.shape != control.shape or candidate.size == 0:
        raise ValueError("paired non-empty losses are required")
    deltas = candidate - control
    rng = np.random.default_rng(seed)
    samples = np.empty(repetitions)
    for index in range(repetitions):
        samples[index] = deltas[rng.integers(0, deltas.size, deltas.size)].mean()
    return BootstrapDelta(
        mean=float(deltas.mean()),
        lower=float(np.quantile(samples, 0.025)),
        upper=float(np.quantile(samples, 0.975)),
        p_value=float((np.count_nonzero(samples >= 0.0) + 1) / (repetitions + 1)),
    )


def holm_rejections(p_values: Sequence[float], alpha: float = 0.05) -> tuple[bool, ...]:
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    rejected = [False] * len(p_values)
    for rank, index in enumerate(order):
        if p_values[index] <= alpha / (len(p_values) - rank):
            rejected[index] = True
        else:
            break
    return tuple(rejected)


@dataclass(frozen=True)
class MarketGate:
    market: str
    passed: bool
    reason: str
    comparisons: tuple[dict[str, float], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def promotion_gate(
    market: str,
    comparisons: Sequence[tuple[str, BootstrapDelta]],
    *,
    minimum_improvement: float = 0.002,
    holm_passed: Sequence[bool] | None = None,
) -> MarketGate:
    corrected = tuple(holm_passed) if holm_passed is not None else holm_rejections([item.p_value for _, item in comparisons])
    details = tuple({"control": name, **asdict(delta)} for name, delta in comparisons)
    passed = all(
        delta.mean <= -minimum_improvement and delta.upper < 0 and corrected[index]
        for index, (_, delta) in enumerate(comparisons)
    )
    reason = "passed numeric probability-quality gate" if passed else "failed materiality or corrected uncertainty gate"
    return MarketGate(market, passed, reason, details)


def goal_market_probabilities(home_rate: float, away_rate: float) -> tuple[float, float]:
    """Return coherent Over 2.5 and BTTS probabilities for Poisson goal rates."""
    total = home_rate + away_rate
    under = math.exp(-total) * (1.0 + total + total * total / 2.0)
    over = 1.0 - under
    btts = (1.0 - math.exp(-home_rate)) * (1.0 - math.exp(-away_rate))
    return over, btts


def fixed_v16_predictions(row: TacticalHistoryRow) -> tuple[tuple[float, float, float], tuple[float, float]]:
    """Reproduce the archived hand-set tactical layer as an evaluation control."""
    home = _side_features(row, "home")
    away = _side_features(row, "away")
    home_multiplier = max(0.90, min(1.10, math.exp(float(home @ FIXED_V16_WEIGHTS))))
    away_multiplier = max(0.90, min(1.10, math.exp(float(away @ FIXED_V16_WEIGHTS))))
    tactical_elo = max(-MAX_TACTICAL_ELO, min(MAX_TACTICAL_ELO, 400.0 * math.log10(home_multiplier / away_multiplier)))
    adjustment = tactical_elo * math.log(10.0) / 400.0
    baseline = np.log(np.asarray([[row.baseline_home, row.baseline_draw, row.baseline_away]]))
    outcome = _softmax(baseline + np.asarray([[adjustment, 0.0, -adjustment]]))[0]
    goals = goal_market_probabilities(
        row.baseline_home_lambda * home_multiplier,
        row.baseline_away_lambda * away_multiplier,
    )
    return tuple(float(value) for value in outcome), goals


def _temperature_multiclass(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    return _softmax(np.log(np.clip(probabilities, 1e-12, 1.0)) / temperature)


def _temperature_binary(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-8, 1.0 - 1e-8)
    logits = np.log(clipped / (1.0 - clipped)) / temperature
    return 1.0 / (1.0 + np.exp(-logits))


def fit_outcome_temperature(rows: Sequence[TacticalHistoryRow]) -> float:
    baseline = np.asarray([[row.baseline_home, row.baseline_draw, row.baseline_away] for row in rows])
    actual = np.asarray([_outcome_index(row) for row in rows])

    def objective(log_temperature: np.ndarray) -> float:
        probabilities = _temperature_multiclass(baseline, math.exp(float(log_temperature[0])))
        return float(-np.log(np.clip(probabilities[np.arange(len(rows)), actual], 1e-12, 1.0)).mean())

    result = minimize(objective, np.zeros(1), method="L-BFGS-B", bounds=[(-2.0, 2.0)])
    return math.exp(float(result.x[0])) if result.success else 1.0


def fit_binary_temperature(probabilities: Sequence[float], actual: Sequence[int]) -> float:
    values = np.asarray(probabilities, dtype=float)
    labels = np.asarray(actual, dtype=float)

    def objective(log_temperature: np.ndarray) -> float:
        calibrated = _temperature_binary(values, math.exp(float(log_temperature[0])))
        return float(-np.mean(labels * np.log(calibrated) + (1.0 - labels) * np.log(1.0 - calibrated)))

    result = minimize(objective, np.zeros(1), method="L-BFGS-B", bounds=[(-2.0, 2.0)])
    return math.exp(float(result.x[0])) if result.success else 1.0


def _multiclass_losses(probabilities: Sequence[Sequence[float]], actual: Sequence[int]) -> dict[str, list[float]]:
    brier, logloss = [], []
    for values, label in zip(probabilities, actual):
        brier.append(sum((value - (1.0 if index == label else 0.0)) ** 2 for index, value in enumerate(values)))
        logloss.append(-math.log(max(1e-12, values[label])))
    return {"brier": brier, "logloss": logloss}


def _binary_losses(probabilities: Sequence[float], actual: Sequence[int]) -> dict[str, list[float]]:
    brier, logloss = [], []
    for value, label in zip(probabilities, actual):
        brier.append((value - label) ** 2)
        logloss.append(-math.log(max(1e-12, value if label else 1.0 - value)))
    return {"brier": brier, "logloss": logloss}


def evaluate_candidate(
    outcome_model: OutcomeResidualModel,
    goal_model: GoalResidualModel,
    validation: Sequence[TacticalHistoryRow],
    audit: Sequence[TacticalHistoryRow],
    *,
    repetitions: int = 10_000,
) -> dict[str, object]:
    """Evaluate once on a sealed audit and return strict market promotion gates."""
    if len(validation) < 50 or len(audit) < 30:
        return {"status": "blocked", "reason": "evaluation requires 50 validation and 30 audit rows"}
    outcome_temperature = fit_outcome_temperature(validation)
    validation_goal_probs = [goal_market_probabilities(row.baseline_home_lambda, row.baseline_away_lambda) for row in validation]
    over_temperature = fit_binary_temperature([item[0] for item in validation_goal_probs], [int(row.home_goals + row.away_goals >= 3) for row in validation])
    btts_temperature = fit_binary_temperature([item[1] for item in validation_goal_probs], [int(row.home_goals > 0 and row.away_goals > 0) for row in validation])

    outcome_actual = [_outcome_index(row) for row in audit]
    baseline_outcome = [[row.baseline_home, row.baseline_draw, row.baseline_away] for row in audit]
    learned_outcome = [outcome_model.probabilities(row) for row in audit]
    recal_outcome = _temperature_multiclass(np.asarray(baseline_outcome), outcome_temperature).tolist()
    fixed_predictions = [fixed_v16_predictions(row) for row in audit]
    fixed_outcome = [item[0] for item in fixed_predictions]
    baseline_goals = [goal_market_probabilities(row.baseline_home_lambda, row.baseline_away_lambda) for row in audit]
    learned_goals = [goal_market_probabilities(*goal_model.rates(row)) for row in audit]
    actual_over = [int(row.home_goals + row.away_goals >= 3) for row in audit]
    actual_btts = [int(row.home_goals > 0 and row.away_goals > 0) for row in audit]
    recal_over = _temperature_binary(np.asarray([item[0] for item in baseline_goals]), over_temperature).tolist()
    recal_btts = _temperature_binary(np.asarray([item[1] for item in baseline_goals]), btts_temperature).tolist()

    variants = {
        "1x2": {
            "actual": outcome_actual,
            "baseline": _multiclass_losses(baseline_outcome, outcome_actual),
            "recalibrated": _multiclass_losses(recal_outcome, outcome_actual),
            "fixed_v16": _multiclass_losses(fixed_outcome, outcome_actual),
            "learned": _multiclass_losses(learned_outcome, outcome_actual),
        },
        "totals": {
            "actual": actual_over,
            "baseline": _binary_losses([item[0] for item in baseline_goals], actual_over),
            "recalibrated": _binary_losses(recal_over, actual_over),
            "fixed_v16": _binary_losses([item[1][0] for item in fixed_predictions], actual_over),
            "learned": _binary_losses([item[0] for item in learned_goals], actual_over),
        },
        "btts": {
            "actual": actual_btts,
            "baseline": _binary_losses([item[1] for item in baseline_goals], actual_btts),
            "recalibrated": _binary_losses(recal_btts, actual_btts),
            "fixed_v16": _binary_losses([item[1][1] for item in fixed_predictions], actual_btts),
            "learned": _binary_losses([item[1] for item in learned_goals], actual_btts),
        },
    }
    comparisons: list[tuple[str, str, str, BootstrapDelta]] = []
    for market, values in variants.items():
        for metric in ("brier", "logloss"):
            for control in ("baseline", "recalibrated"):
                delta = paired_bootstrap_delta(
                    values["learned"][metric], values[control][metric],
                    repetitions=repetitions,
                )
                comparisons.append((market, metric, control, delta))
    corrected = holm_rejections([item[3].p_value for item in comparisons])
    gates = {}
    for market in variants:
        selected = [(item, corrected[index]) for index, item in enumerate(comparisons) if item[0] == market]
        gate = promotion_gate(
            market,
            [(f"{metric}:{control}", delta) for (_, metric, control, delta), _ in selected],
            holm_passed=[passed for _, passed in selected],
        )
        gates[market] = gate.to_dict()
    metrics = {
        market: {
            variant: {
                metric: float(np.mean(losses)) for metric, losses in values[variant].items()
            }
            for variant in ("baseline", "fixed_v16", "recalibrated", "learned")
        }
        for market, values in variants.items()
    }
    return {
        "status": "evaluated",
        "audit_rows": len(audit),
        "temperatures": {"outcome": outcome_temperature, "totals": over_temperature, "btts": btts_temperature},
        "metrics": metrics,
        "gates": gates,
    }
