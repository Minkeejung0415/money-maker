"""
WC model calibration, metrics, and promotion gate.

All evaluation code lives here — wc_eval.py imports from this module.
No live-data imports allowed in this file.

Label convention:
    LABEL_TO_INT = {"W": 0, "D": 1, "L": 2}
    W = home team wins, D = draw, L = away team wins

References:
    - Multiclass Brier: Murphy 1973 / meteorological forecasting convention
      Formula A: mean(sum_k((p_ik - o_ik)^2)) — range [0, 2] for 3 classes
    - Isotonic regression calibration: Zadrozny & Elkan 2002
    - A-grade: top-class probability >= 0.65 threshold
"""
from __future__ import annotations

import logging

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import accuracy_score, log_loss

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label encoding
# ---------------------------------------------------------------------------

LABEL_TO_INT: dict[str, int] = {"W": 0, "D": 1, "L": 2}
INT_TO_LABEL: dict[int, str] = {0: "W", 1: "D", 2: "L"}

# ---------------------------------------------------------------------------
# Promotion gate constant
# ---------------------------------------------------------------------------

_MIN_DELTA: float = 0.001
"""Minimum improvement on both metrics for promotion gate to pass."""

# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def multiclass_brier(
    y_true_labels: list[int],
    y_pred_probs: list[list[float]],
) -> float:
    """
    Multiclass Brier score using Formula A (Murphy 1973).

    Formula: mean over samples of sum_k((p_ik - o_ik)^2)
    Range: [0.0 (perfect), 2.0 (worst for 3 classes)]

    Do NOT use sklearn's brier_score_loss — that function is binary-only
    and produces Formula B (1/3 of this value).

    Parameters
    ----------
    y_true_labels : list[int]
        Integer outcome labels. 0=W (home win), 1=D (draw), 2=L (away win).
    y_pred_probs : list[list[float]]
        Predicted probability matrix, shape (N, 3). Each row must sum to ~1.

    Returns
    -------
    float
        Multiclass Brier score. Lower is better.
    """
    n = len(y_true_labels)
    if n == 0:
        raise ValueError("y_true_labels must be non-empty")
    # Build one-hot matrix
    y_true = np.zeros((n, 3))
    for i, label in enumerate(y_true_labels):
        y_true[i, label] = 1.0
    y_pred = np.array(y_pred_probs, dtype=float)
    if y_pred.shape != (n, 3):
        raise ValueError(
            f"y_pred_probs must have shape (N, 3), got {y_pred.shape}"
        )
    return float(np.mean(np.sum((y_pred - y_true) ** 2, axis=1)))


def compute_a_grade(
    y_true_labels: list[int],
    y_pred_probs: list[list[float]],
) -> dict:
    """
    Compute A-grade metric: high-confidence predictions that are correct.

    A prediction is 'A-grade eligible' when max(predicted_probs) >= 0.65.
    A-grade rate = (eligible AND correct) / eligible.
    A-grade coverage = eligible / total.

    Parameters
    ----------
    y_true_labels : list[int]
        Integer outcome labels.
    y_pred_probs : list[list[float]]
        Predicted probability matrix, shape (N, 3).

    Returns
    -------
    dict with keys:
        a_grade_rate     : float — fraction of eligible predictions that are correct
        a_grade_count    : int   — number of eligible correct predictions
        a_grade_eligible : int   — number of eligible predictions (top_prob >= 0.65)
        a_grade_coverage : float — fraction of all games with top_prob >= 0.65
    """
    y_true = np.array(y_true_labels)
    y_pred = np.array(y_pred_probs, dtype=float)

    top_class = np.argmax(y_pred, axis=1)
    top_prob = np.max(y_pred, axis=1)

    eligible = top_prob >= 0.65
    correct = top_class == y_true

    n_eligible = int(eligible.sum())
    n_correct = int((eligible & correct).sum())

    return {
        "a_grade_rate": n_correct / n_eligible if n_eligible > 0 else 0.0,
        "a_grade_count": n_correct,
        "a_grade_eligible": n_eligible,
        "a_grade_coverage": float(eligible.mean()),
    }


def log_calibration_summary(
    y_true_labels: list[int],
    y_pred_probs: list[list[float]],
    class_names: tuple[str, ...] | list[str] = ("W", "D", "L"),
) -> None:
    """
    Print calibration curve data as text (no matplotlib dependency).

    Uses sklearn.calibration.calibration_curve with strategy='uniform' and
    n_bins=5. Safe to use in CI environments.

    Parameters
    ----------
    y_true_labels : list[int]
        Integer outcome labels.
    y_pred_probs : list[list[float]]
        Predicted probability matrix, shape (N, 3).
    class_names : sequence of str
        Display names for each class (default: W, D, L).
    """
    y_pred = np.array(y_pred_probs, dtype=float)
    y_true_arr = np.array(y_true_labels)

    print("Calibration curve (pred vs actual fraction positive):")
    for k, name in enumerate(class_names):
        binary = (y_true_arr == k).astype(int)
        probs_k = y_pred[:, k]
        try:
            frac_pos, mean_pred = calibration_curve(
                binary, probs_k, n_bins=5, strategy="uniform"
            )
            print(f"  [{name}]:")
            for fp, mp in zip(frac_pos, mean_pred):
                gap = fp - mp
                bar_len = int(abs(gap) * 40)
                bar = ("+" if gap > 0 else "-") * bar_len
                print(f"    pred={mp:.2f} actual={fp:.2f} gap={gap:+.3f} {bar}")
        except ValueError:
            print(f"  [{name}]: insufficient data for calibration curve")


# ---------------------------------------------------------------------------
# Calibration class
# ---------------------------------------------------------------------------


class WCIsotonicCalibrator:
    """
    Per-class binary isotonic calibration for 3-outcome (W/D/L) predictions.

    Fits a separate IsotonicRegression on each outcome class (binary one-vs-rest).
    After fitting, predict() renormalizes rows so probabilities sum to 1.

    Must be fitted on the validation fold ONLY (EVAL-03). Never fit on test data.

    Example
    -------
    calibrator = WCIsotonicCalibrator()
    calibrator.fit(train_probs, train_labels)
    cal_probs = calibrator.predict(test_probs)
    """

    def __init__(self) -> None:
        self._calibrators: list[IsotonicRegression] | None = None

    def fit(
        self,
        probs: np.ndarray,
        outcomes: list[int],
    ) -> "WCIsotonicCalibrator":
        """
        Fit per-class isotonic regressors on validation fold data.

        Parameters
        ----------
        probs : np.ndarray, shape (N, 3)
            Model output probabilities for each of N samples.
        outcomes : list[int]
            Integer outcome labels (0=W, 1=D, 2=L) for each sample.

        Returns
        -------
        self
        """
        probs = np.array(probs, dtype=float)
        outcomes_arr = np.array(outcomes)
        self._calibrators = []
        for k in range(3):
            binary = (outcomes_arr == k).astype(float)
            ir = IsotonicRegression(out_of_bounds="clip", increasing=True)
            ir.fit(probs[:, k], binary)
            self._calibrators.append(ir)
            logger.debug(
                "Fitted IR calibrator for class %d (%s) on %d samples",
                k,
                INT_TO_LABEL[k],
                len(outcomes),
            )
        return self

    def predict(self, probs: np.ndarray) -> np.ndarray:
        """
        Apply calibration and renormalize so each row sums to 1.

        Parameters
        ----------
        probs : np.ndarray, shape (M, 3)
            Raw model output probabilities for M samples.

        Returns
        -------
        np.ndarray, shape (M, 3)
            Calibrated probabilities, each row sums to 1.0.

        Raises
        ------
        RuntimeError
            If fit() has not been called yet.
        """
        if self._calibrators is None:
            raise RuntimeError(
                "WCIsotonicCalibrator.fit() must be called before predict()"
            )
        probs = np.array(probs, dtype=float)
        calibrated = np.column_stack([
            self._calibrators[k].predict(probs[:, k]) for k in range(3)
        ])
        # Renormalize rows to sum to 1 (zero-safe)
        row_sums = calibrated.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums == 0, 1.0, row_sums)
        return calibrated / row_sums


# ---------------------------------------------------------------------------
# Promotion gate
# ---------------------------------------------------------------------------


def promotion_gate(
    baseline: dict,
    candidate: dict,
    min_delta: float = _MIN_DELTA,
) -> tuple[bool, str]:
    """
    Compare two model result dicts on Brier + log loss (EVAL-04).

    Candidate must beat baseline on BOTH metrics by more than min_delta.
    Identical models always FAIL because delta=0.0 < min_delta=0.001.

    Parameters
    ----------
    baseline : dict
        Result dict with keys: "brier" (float), "log_loss" (float),
        "n_samples" (int).
    candidate : dict
        Same keys as baseline.
    min_delta : float
        Minimum required improvement on each metric. Default: 0.001.

    Returns
    -------
    tuple[bool, str]
        (passes, reason_string)
        passes=True only if candidate beats baseline on both Brier AND log_loss
        by more than min_delta.
    """
    brier_delta = baseline["brier"] - candidate["brier"]
    ll_delta = baseline["log_loss"] - candidate["log_loss"]

    passes_brier = brier_delta > min_delta
    passes_ll = ll_delta > min_delta

    if passes_brier and passes_ll:
        return True, (
            f"PASS: brier -{brier_delta:.4f}, log_loss -{ll_delta:.4f} "
            f"(n={candidate['n_samples']})"
        )

    reasons = []
    if not passes_brier:
        reasons.append(f"Brier delta={brier_delta:.4f} (need >{min_delta})")
    if not passes_ll:
        reasons.append(f"log_loss delta={ll_delta:.4f} (need >{min_delta})")
    return False, "FAIL: " + "; ".join(reasons)


# ---------------------------------------------------------------------------
# Model evaluator
# ---------------------------------------------------------------------------


def evaluate_model(
    model,
    matches: list[dict],
    calibrator: WCIsotonicCalibrator | None = None,
) -> dict:
    """
    Run model.predict() on each match and compute evaluation metrics.

    IMPORTANT: passes dict(match) (shallow copy) to model.predict() to
    prevent mutation of the original match records.

    Parameters
    ----------
    model : object with .predict(game: dict) -> dict
        Model to evaluate. WCMatchModel is the primary target.
    matches : list[dict]
        Match records from wc_historical_matches.WC_HISTORICAL or get_matches().
        Each dict must have: home_team, away_team, outcome (W/D/L), league="wc".
    calibrator : WCIsotonicCalibrator | None
        If provided, calibrated probabilities are also computed and additional
        keys "brier_calibrated" and "log_loss_calibrated" are returned.

    Returns
    -------
    dict with keys:
        brier         : float — multiclass Brier score (Formula A)
        log_loss      : float — sklearn log_loss (multiclass)
        accuracy      : float — fraction of correct predictions
        a_grade       : dict  — see compute_a_grade()
        n_samples     : int   — number of matches evaluated
        [if calibrator:]
        brier_calibrated    : float
        log_loss_calibrated : float
    """
    y_true_labels: list[int] = []
    y_pred_probs: list[list[float]] = []

    for match in matches:
        # COPY — never mutate the original record
        game = dict(match)
        result = model.predict(game)
        win_prob = result["win_prob"]
        draw_prob = result["draw_prob"]
        loss_prob = result["loss_prob"]
        y_pred_probs.append([win_prob, draw_prob, loss_prob])
        y_true_labels.append(LABEL_TO_INT[match["outcome"]])

    probs_arr = np.array(y_pred_probs, dtype=float)
    true_arr = np.array(y_true_labels)
    pred_classes = np.argmax(probs_arr, axis=1)

    result_dict: dict = {
        "brier": multiclass_brier(y_true_labels, y_pred_probs),
        "log_loss": float(log_loss(true_arr, probs_arr, labels=[0, 1, 2])),
        "accuracy": float(accuracy_score(true_arr, pred_classes)),
        "a_grade": compute_a_grade(y_true_labels, y_pred_probs),
        "n_samples": len(matches),
    }

    if calibrator is not None:
        cal_probs = calibrator.predict(probs_arr)
        cal_pred_classes = np.argmax(cal_probs, axis=1)
        result_dict["brier_calibrated"] = multiclass_brier(
            y_true_labels, cal_probs.tolist()
        )
        result_dict["log_loss_calibrated"] = float(
            log_loss(true_arr, cal_probs, labels=[0, 1, 2])
        )
        result_dict["accuracy_calibrated"] = float(
            accuracy_score(true_arr, cal_pred_classes)
        )
        result_dict["a_grade_calibrated"] = compute_a_grade(
            y_true_labels, cal_probs.tolist()
        )

    return result_dict
