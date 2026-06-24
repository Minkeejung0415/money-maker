#!/usr/bin/env python3
"""
WC Evaluation Framework -- chronological backtest runner.

Evaluates the Elo-only WCMatchModel against embedded historical match data.
No live-data imports. Uses 2018 data for calibration, 2022 data for test.

Chronological split (EVAL-01, EVAL-03):
    Calibration train : WC 2018 group stage (48 matches)
    Test              : WC 2022 all matches (64 matches)

Usage:
    python scripts/wc_eval.py
    python scripts/wc_eval.py --help

Exit code: 0 on success.
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup (must come before local imports)
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Encode stdout/stderr as UTF-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Local imports (no live-data fetchers allowed)
# ---------------------------------------------------------------------------

import numpy as np

from data.wc_historical_matches import WC_HISTORICAL, get_matches, GROUP_STAGE, KNOCKOUT_STAGES
from alpha.engines.sports.wc_calibration import (
    LABEL_TO_INT,
    WCIsotonicCalibrator,
    compute_a_grade,
    evaluate_model,
    log_calibration_summary,
    multiclass_brier,
    promotion_gate,
)
from alpha.engines.sports.wc_model import WCMatchModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("wc_eval")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_probs(model: WCMatchModel, matches: list[dict]) -> tuple[list[int], list[list[float]]]:
    """Run model.predict on each match (via copy) and collect probs + labels."""
    y_true: list[int] = []
    y_pred: list[list[float]] = []
    for match in matches:
        game = dict(match)
        result = model.predict(game)
        y_pred.append([result["win_prob"], result["draw_prob"], result["loss_prob"]])
        y_true.append(LABEL_TO_INT[match["outcome"]])
    return y_true, y_pred


def _print_results_table(label: str, metrics: dict) -> None:
    """Print a formatted metrics table for one evaluation pass."""
    ag = metrics["a_grade"]
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Samples   : {metrics['n_samples']}")
    print(f"  Accuracy  : {metrics['accuracy']:.4f}  ({metrics['accuracy']*100:.1f}%)")
    print(f"  Brier     : {metrics['brier']:.4f}  (lower=better; random~1.33, Elo~0.50)")
    print(f"  Log Loss  : {metrics['log_loss']:.4f}  (lower=better; random~1.10)")
    print(f"  A-grade   : {ag['a_grade_rate']:.4f}  "
          f"({ag['a_grade_count']}/{ag['a_grade_eligible']} eligible, "
          f"coverage={ag['a_grade_coverage']*100:.1f}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="WC Evaluation Framework — chronological backtest runner."
    )
    parser.parse_args()  # raises SystemExit on --help or bad args

    # -----------------------------------------------------------------------
    # Dataset summary
    # -----------------------------------------------------------------------
    print(f"WC Historical Dataset: {len(WC_HISTORICAL)} total matches")
    print(f"  2018: {len(get_matches(year=2018))} matches "
          f"({len(get_matches(year=2018, stage=GROUP_STAGE))} group + "
          f"{len([m for m in get_matches(year=2018) if m['stage'] != GROUP_STAGE])} knockout)")
    print(f"  2022: {len(get_matches(year=2022))} matches "
          f"({len(get_matches(year=2022, stage=GROUP_STAGE))} group + "
          f"{len([m for m in get_matches(year=2022) if m['stage'] != GROUP_STAGE])} knockout)")

    # -----------------------------------------------------------------------
    # Chronological split
    # EVAL-01: Use 2018 for calibration train, 2022 for test
    # EVAL-03: Isotonic calibration fitted on train fold ONLY
    # -----------------------------------------------------------------------
    train_matches = get_matches(year=2018)  # 64 matches — calibration fold
    test_matches = get_matches(year=2022)   # 64 matches — evaluation fold

    print(f"\nChronological split:")
    print(f"  Calibration train : 2018 ({len(train_matches)} matches)")
    print(f"  Test              : 2022 ({len(test_matches)} matches)")

    # -----------------------------------------------------------------------
    # Instantiate model
    # -----------------------------------------------------------------------
    model = WCMatchModel()

    # -----------------------------------------------------------------------
    # Fit calibrator on 2018 train fold (EVAL-03)
    # -----------------------------------------------------------------------
    print("\nFitting isotonic calibrator on 2018 matches...")
    train_labels, train_probs = _collect_probs(model, train_matches)
    train_probs_arr = np.array(train_probs, dtype=float)

    calibrator = WCIsotonicCalibrator()
    calibrator.fit(train_probs_arr, train_labels)
    print(f"  Calibrator fitted on {len(train_matches)} samples.")

    # -----------------------------------------------------------------------
    # Evaluate on 2022 test set — uncalibrated and calibrated
    # -----------------------------------------------------------------------
    print("\nEvaluating on 2022 test set...")
    metrics_uncal = evaluate_model(model, test_matches, calibrator=None)
    metrics_cal = evaluate_model(model, test_matches, calibrator=calibrator)

    # -----------------------------------------------------------------------
    # Print results tables
    # -----------------------------------------------------------------------
    _print_results_table("UNCALIBRATED (Elo-only baseline)", metrics_uncal)

    _print_results_table(
        "CALIBRATED (Isotonic on 2018 fold)",
        {
            "n_samples": metrics_cal["n_samples"],
            "accuracy": metrics_cal.get("accuracy_calibrated", metrics_cal["accuracy"]),
            "brier": metrics_cal["brier_calibrated"],
            "log_loss": metrics_cal["log_loss_calibrated"],
            "a_grade": metrics_cal.get("a_grade_calibrated", metrics_cal["a_grade"]),
        },
    )

    # -----------------------------------------------------------------------
    # Calibration curve (text, CI safe)
    # -----------------------------------------------------------------------
    print(f"\n--- Calibration Summary (uncalibrated, 2022 test) ---")
    test_labels, test_probs = _collect_probs(model, test_matches)
    log_calibration_summary(test_labels, test_probs)

    # -----------------------------------------------------------------------
    # Promotion gate: calibrated vs uncalibrated (sanity check — EVAL-04)
    # Calibration should improve Brier; if it doesn't, something is wrong.
    # -----------------------------------------------------------------------
    print(f"\n--- Promotion Gate (calibrated vs uncalibrated, sanity check) ---")
    gate_baseline = {
        "brier": metrics_uncal["brier"],
        "log_loss": metrics_uncal["log_loss"],
        "n_samples": metrics_uncal["n_samples"],
    }
    gate_candidate = {
        "brier": metrics_cal["brier_calibrated"],
        "log_loss": metrics_cal["log_loss_calibrated"],
        "n_samples": metrics_cal["n_samples"],
    }
    passes, reason = promotion_gate(gate_baseline, gate_candidate)
    print(f"  Result: {reason}")
    if not passes:
        print("  NOTE: Calibration did not improve both metrics by >0.001.")
        print("  This is expected on small datasets (64 test matches).")
        print("  Baseline Brier and Log Loss are the Phase 26+ comparison target.")

    # -----------------------------------------------------------------------
    # Summary baseline metrics for SUMMARY.md
    # -----------------------------------------------------------------------
    print(f"\n--- Baseline Metrics (for Phase 26+ comparison) ---")
    print(f"  Uncalibrated Brier     : {metrics_uncal['brier']:.4f}")
    print(f"  Uncalibrated Log Loss  : {metrics_uncal['log_loss']:.4f}")
    print(f"  Uncalibrated Accuracy  : {metrics_uncal['accuracy']:.4f}")
    print(f"  Calibrated Brier       : {metrics_cal['brier_calibrated']:.4f}")
    print(f"  Calibrated Log Loss    : {metrics_cal['log_loss_calibrated']:.4f}")
    print(f"  Calibrated Accuracy    : {metrics_cal.get('accuracy_calibrated', 0):.4f}")

    print(f"\nwc_eval.py complete. Exit 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
