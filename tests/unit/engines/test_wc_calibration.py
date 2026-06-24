"""Tests for alpha/engines/sports/wc_calibration.py."""
from __future__ import annotations

import numpy as np
import pytest

from alpha.engines.sports.wc_calibration import (
    LABEL_TO_INT,
    WCIsotonicCalibrator,
    compute_a_grade,
    multiclass_brier,
    promotion_gate,
)


# ---------------------------------------------------------------------------
# multiclass_brier
# ---------------------------------------------------------------------------


def test_multiclass_brier_perfect_prediction():
    """All-correct one-hot predictions -> Brier = 0.0."""
    y_true = [0, 1, 2, 0, 1, 2]
    y_pred = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    assert multiclass_brier(y_true, y_pred) == pytest.approx(0.0, abs=1e-10)


def test_multiclass_brier_worst_prediction():
    """
    All-wrong confident predictions -> Brier = 2.0.

    For each sample: sum of squared errors = (0-1)^2 + (0-0)^2 + (1-0)^2 = 2.0
    where prob=1 is assigned to wrong class and true class gets prob=0.
    """
    y_true = [0, 1, 2]
    y_pred = [
        [0.0, 0.0, 1.0],  # true=W, pred=L (confident wrong)
        [1.0, 0.0, 0.0],  # true=D, pred=W (confident wrong)
        [0.0, 1.0, 0.0],  # true=L, pred=D (confident wrong)
    ]
    assert multiclass_brier(y_true, y_pred) == pytest.approx(2.0, abs=1e-10)


def test_multiclass_brier_formula_a():
    """
    Formula A = 3 x mean(per-class binary Brier).

    This test catches formula confusion (A vs B convention).
    For uniform probs [1/3, 1/3, 1/3] and true label 0:
    Per-class binary Brier for class 0: mean((1/3 - 1)^2) = (2/3)^2 = 4/9
    Per-class binary Brier for class 1: mean((1/3 - 0)^2) = (1/3)^2 = 1/9
    Per-class binary Brier for class 2: mean((1/3 - 0)^2) = (1/3)^2 = 1/9
    Mean binary Brier = (4/9 + 1/9 + 1/9) / 3 = 6/27 = 2/9 ≈ 0.2222
    Formula A = sum per sample = (2/3)^2 + (1/3)^2 + (1/3)^2 = 4/9+1/9+1/9 = 6/9 ≈ 0.6667
    Formula A = 3 x Formula B: 3 * 0.2222 = 0.6667 ✓
    """
    from sklearn.metrics import brier_score_loss

    y_true = [0, 0, 0]
    y_pred = [
        [1 / 3, 1 / 3, 1 / 3],
        [1 / 3, 1 / 3, 1 / 3],
        [1 / 3, 1 / 3, 1 / 3],
    ]
    formula_a = multiclass_brier(y_true, y_pred)
    # Per-class binary brier using sklearn (binary only, so compute for class 0)
    y_prob_class0 = [1 / 3, 1 / 3, 1 / 3]
    y_binary_class0 = [1, 1, 1]  # all true class is 0
    formula_b_class0 = brier_score_loss(y_binary_class0, y_prob_class0)

    # For balanced uniform probs: formula_a ≈ 6/9, formula_b_class0 = 4/9
    # The 3x relationship: multiclass_brier = mean(sum_k(err_k^2)) per sample
    # sklearn brier_score_loss returns mean((p - o)^2) for one class
    # 3 x mean binary Brier (averaged over 3 classes): harder to compute in-test
    # Simplest check: formula_a result is approx 3 x average of per-class briers
    assert formula_a == pytest.approx(6 / 9, abs=1e-9)
    # And it's NOT equal to any single binary brier value
    assert formula_a != pytest.approx(formula_b_class0, abs=1e-6)


# ---------------------------------------------------------------------------
# compute_a_grade
# ---------------------------------------------------------------------------


def test_a_grade_basic():
    """
    Two correct eligible (prob>=0.65), one wrong eligible.
    rate = 2/3, eligible = 3.
    """
    y_true = [0, 1, 2]
    y_pred = [
        [0.80, 0.15, 0.05],  # eligible, correct (top=0, true=0)
        [0.05, 0.90, 0.05],  # eligible, correct (top=1, true=1)
        [0.70, 0.20, 0.10],  # eligible, WRONG (top=0, true=2)
    ]
    result = compute_a_grade(y_true, y_pred)
    assert result["a_grade_eligible"] == 3
    assert result["a_grade_count"] == 2
    assert result["a_grade_rate"] == pytest.approx(2 / 3, abs=1e-9)
    assert result["a_grade_coverage"] == pytest.approx(1.0, abs=1e-9)


def test_a_grade_no_eligible():
    """All top probabilities < 0.65 -> eligible=0, rate=0.0."""
    y_true = [0, 1, 2]
    y_pred = [
        [0.50, 0.30, 0.20],  # top=0.50 < 0.65
        [0.40, 0.35, 0.25],  # top=0.40 < 0.65
        [0.45, 0.35, 0.20],  # top=0.45 < 0.65
    ]
    result = compute_a_grade(y_true, y_pred)
    assert result["a_grade_eligible"] == 0
    assert result["a_grade_count"] == 0
    assert result["a_grade_rate"] == pytest.approx(0.0, abs=1e-9)
    assert result["a_grade_coverage"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# WCIsotonicCalibrator
# ---------------------------------------------------------------------------


@pytest.fixture
def small_calibrator():
    """Calibrator fitted on 10 synthetic samples."""
    rng = np.random.default_rng(42)
    n = 10
    probs = rng.dirichlet(alpha=[2, 1, 1], size=n)  # shape (10, 3)
    labels = list(np.argmax(probs, axis=1))  # use most confident class as true
    cal = WCIsotonicCalibrator()
    cal.fit(probs, labels)
    return cal


def test_calibrator_fit_predict_shape(small_calibrator):
    """fit() on 10 samples, predict(5) -> output shape (5, 3)."""
    rng = np.random.default_rng(99)
    test_probs = rng.dirichlet(alpha=[1, 1, 1], size=5)  # shape (5, 3)
    out = small_calibrator.predict(test_probs)
    assert out.shape == (5, 3), f"Expected (5, 3), got {out.shape}"


def test_calibrator_probs_sum_to_one(small_calibrator):
    """After predict(), every row sums to 1.0 within 1e-6."""
    rng = np.random.default_rng(7)
    test_probs = rng.dirichlet(alpha=[1, 1, 1], size=20)
    out = small_calibrator.predict(test_probs)
    row_sums = out.sum(axis=1)
    assert np.allclose(row_sums, 1.0, atol=1e-6), (
        f"Rows not summing to 1: min={row_sums.min():.8f}, max={row_sums.max():.8f}"
    )


def test_calibrator_not_fitted_raises():
    """predict() before fit() raises RuntimeError."""
    cal = WCIsotonicCalibrator()
    probs = np.array([[0.5, 0.3, 0.2]])
    with pytest.raises(RuntimeError, match="fit()"):
        cal.predict(probs)


# ---------------------------------------------------------------------------
# promotion_gate
# ---------------------------------------------------------------------------


def test_promotion_gate_identical_fail():
    """Same dict as baseline and candidate -> (False, ...)."""
    metrics = {"brier": 0.50, "log_loss": 1.00, "n_samples": 64}
    passes, reason = promotion_gate(metrics, metrics)
    assert passes is False
    assert "FAIL" in reason


def test_promotion_gate_real_improvement():
    """Both Brier and log_loss improve by 0.05 -> (True, ...)."""
    baseline = {"brier": 0.50, "log_loss": 1.00, "n_samples": 64}
    candidate = {"brier": 0.45, "log_loss": 0.95, "n_samples": 64}
    passes, reason = promotion_gate(baseline, candidate)
    assert passes is True
    assert "PASS" in reason


def test_promotion_gate_one_metric_fails():
    """Brier improves but log_loss is identical -> (False, ...)."""
    baseline = {"brier": 0.50, "log_loss": 1.00, "n_samples": 64}
    candidate = {"brier": 0.45, "log_loss": 1.00, "n_samples": 64}
    passes, reason = promotion_gate(baseline, candidate)
    assert passes is False
    assert "FAIL" in reason
    assert "log_loss" in reason.lower()


def test_promotion_gate_subthreshold():
    """Both deltas = 0.0005 (< min_delta=0.001) -> (False, ...)."""
    baseline = {"brier": 0.5000, "log_loss": 1.0000, "n_samples": 64}
    candidate = {"brier": 0.4995, "log_loss": 0.9995, "n_samples": 64}
    passes, reason = promotion_gate(baseline, candidate)
    assert passes is False
    assert "FAIL" in reason


def test_promotion_gate_custom_min_delta():
    """Custom min_delta allows tuning the threshold."""
    # Use exact floats to avoid floating point edge cases
    baseline = {"brier": 0.500, "log_loss": 1.000, "n_samples": 64}
    # delta = 0.05 on both metrics — clearly above any reasonable min_delta
    candidate = {"brier": 0.450, "log_loss": 0.950, "n_samples": 64}
    # With default min_delta=0.001 -> PASS
    passes_default, reason_default = promotion_gate(baseline, candidate)
    assert passes_default is True
    # With very large min_delta=0.1 -> FAIL (delta=0.05 < 0.1)
    passes_strict, reason_strict = promotion_gate(baseline, candidate, min_delta=0.1)
    assert passes_strict is False
    assert "FAIL" in reason_strict
