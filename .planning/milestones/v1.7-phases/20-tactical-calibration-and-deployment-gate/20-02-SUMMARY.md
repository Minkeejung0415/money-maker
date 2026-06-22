---
phase: 20-tactical-calibration-and-deployment-gate
plan: 02
subsystem: wc-tactical-model
tags: [regularization, chronological-validation, bootstrap, calibration]
requires: [20-01]
provides: [outcome-residual, goal-residual, promotion-gates]
affects: [20-03]
tech-stack:
  added: []
  patterns: [fixed-baseline-offsets, expanding-window-selection, paired-bootstrap-gates]
key-files:
  created:
    - alpha/engines/sports/wc_tactical_calibration.py
    - scripts/train_wc_tactical_model.py
    - tests/unit/engines/test_wc_tactical_calibration.py
  modified: []
key-decisions:
  - Fit one outcome offset and one coherent home/away goal-rate residual with L2 shrinkage.
  - Correct all promotion claims together with Holm and require improvement over baseline and recalibration.
requirements-completed: [WCCAL-05, WCCAL-06, WCCAL-07, WCCAL-08, WCCAL-09]
duration: 22 min
completed: 2026-06-21
---

# Phase 20 Plan 02: Regularized Residual Training and Evaluation Summary

Implemented bounded residual estimators, expanding chronological folds, deterministic paired bootstrap evaluation, baseline/fixed/recalibrated controls, and independent fail-closed market gates.

## Verification

- `python -m pytest tests/unit/engines/test_wc_tactical_calibration.py tests/unit/engines/test_validate_wc_tactics.py -q`
- Result: 10 passed.

## Deviations from Plan

None - the real-data execution remains intentionally blocked until Plan 20-01's coverage manifest meets the locked sample gates.

## Commits

- `069b7ba` - residual fitting, chronological selection, controls, and promotion tests

## Issues Encountered

No eligible sealed historical dataset exists in the repository yet, so no tactical market has been promoted.

## Self-Check: PASSED

Synthetic signal recovery, shrinkage, caps, chronological folds, deterministic uncertainty, and undersized-audit blocking all pass.
