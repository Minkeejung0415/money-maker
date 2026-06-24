---
phase: "25"
plan: "01"
subsystem: "sports/wc"
tags: ["evaluation", "backtest", "calibration", "metrics", "wc"]
depends_on: []
provides: ["wc_historical_matches", "wc_calibration", "wc_eval_framework"]
affects: ["alpha/engines/sports/wc_model.py"]
tech_stack:
  added: ["scikit-learn IsotonicRegression calibration", "multiclass Brier Formula A"]
  patterns: ["chronological backtest split", "per-class binary isotonic calibration", "promotion gate"]
key_files:
  created:
    - "data/__init__.py"
    - "data/wc_historical_matches.py"
    - "alpha/engines/sports/wc_calibration.py"
    - "scripts/wc_eval.py"
    - "tests/unit/engines/test_wc_calibration.py"
    - "tests/unit/engines/test_wc_eval.py"
  modified:
    - ".gitignore"
decisions:
  - "Multiclass Brier uses Formula A (sum per sample, not per-class mean) — consistent with Murphy 1973 / forecasting literature"
  - "IsotonicRegression with out_of_bounds=clip and epsilon floor 1e-9 — prevents zero-row rows after renormalization"
  - "promotion_gate min_delta=0.001 — prevents trivial pass for identical models"
  - "WCMatchModel.predict() input always copied via dict(match) — avoids mutation side effects"
  - "data/ Python source files force-added to git with gitignore negation (data/*.py are tracked, large data files remain ignored)"
metrics:
  duration_minutes: 14
  tasks_completed: 5
  files_created: 6
  tests_added: 26
  total_tests_after: 868
  completed_date: "2026-06-24"
---

# Phase 25 Plan 01: Evaluation Framework Summary

**Status:** Complete
**Date:** 2026-06-24

## What was built

Isotonic calibration + multiclass Brier/log-loss/A-grade harness on embedded WC 2018/2022 dataset, giving every subsequent WC phase a concrete numeric baseline to beat via a promotion gate.

- `data/wc_historical_matches.py` — 128 embedded WC 2018+2022 match results with Elo overrides for 11 missing teams (Russia=1685, Peru=1810, Denmark=1835, Iceland=1767, Nigeria=1655, Costa Rica=1698, Serbia=1720, Korea Republic=1770, Poland=1780, Wales=1799, Cameroon=1625); `get_matches()` returns deep copies to prevent WCMatchModel.predict() mutation leakage
- `alpha/engines/sports/wc_calibration.py` — `multiclass_brier()` (Formula A), `compute_a_grade()`, `log_calibration_summary()` (text-only, CI-safe), `WCIsotonicCalibrator` (per-class binary IR), `promotion_gate()`, `evaluate_model()`
- `scripts/wc_eval.py` — chronological backtest runner: 2018 all (64 matches) for calibration train, 2022 all (64 matches) for test; prints results table, calibration curve, promotion gate sanity check
- `tests/unit/engines/test_wc_calibration.py` — 13 tests for calibration module (Brier formula, A-grade, IR shape/sum/error, promotion gate variants)
- `tests/unit/engines/test_wc_eval.py` — 13 tests for backtest infrastructure (year/stage filters, copy isolation, Elo override, knockout no-draw, 128 count)

## Baseline metrics (Elo-only, 2022 test set — 64 matches)

| Metric | Uncalibrated | Calibrated (IR on 2018 fold) |
|--------|-------------|------------------------------|
| Brier (Formula A) | 0.5181 | 0.5718 |
| Log Loss | 0.8805 | 2.3182 |
| Accuracy | 60.9% | 59.4% |
| A-grade rate | 75.9% (22/29 eligible) | 68.6% (24/35 eligible) |
| A-grade coverage | 45.3% | 54.7% |

**Notes on calibrated metrics:** The IR calibrator trained on only 64 matches (2018) overfits and worsens log_loss on the 2022 test set. This is expected — isotonic regression needs 200+ samples for reliable calibration. The uncalibrated metrics are the authoritative Phase 26+ baseline targets.

**Calibration curve insight (uncalibrated [W] class):** The model underestimates home-win probability in the low range (pred=0.13, actual=0.33 — a +0.206 gap). This is the primary miscalibration the Elo model has on group stage. Phase 26+ player features should help narrow this.

## Key decisions

1. **Formula A for multiclass Brier** — `mean(sum_k((p_ik - o_ik)^2))` per Murphy 1973. Range [0, 2] for 3 classes. NOT sklearn's `brier_score_loss` (binary only, gives Formula B = 1/3 of Formula A).
2. **Epsilon floor 1e-9 in WCIsotonicCalibrator.predict()** — Prevents all-zero rows when out-of-range IR outputs 0.0 for all 3 classes. Without this, renormalization produces NaN/0 rows, causing test failures.
3. **promotion_gate min_delta=0.001** — Phase 26+ model must improve BOTH Brier AND log_loss by more than 0.001. Identical models always FAIL (delta=0.0 < 0.001). Prevents float rounding from producing a trivial pass.
4. **dict(match) copy in evaluate_model()** — WCMatchModel.predict() mutates the input dict in place. Always copy before passing to prevent accumulation of prediction fields on historical records.
5. **data/*.py force-added to git** — The `data/` directory was fully gitignored (designed for large binary files). Python source modules embedded in data/ need to be tracked. Updated .gitignore with a negation exception and force-added the files.
6. **Probe normalization before log_loss** — WCMatchModel rounds probs to 4dp, producing row sums of 0.9999 or 1.0001. Normalized probs_arr before calling sklearn's log_loss to suppress UserWarning.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] data/ directory fully gitignored**
- **Found during:** Task 1 commit attempt
- **Issue:** `.gitignore` had `/data/` blanket-ignoring the entire directory; `git add data/__init__.py` failed
- **Fix:** Added negation exceptions `!/data/*.py` and `!/data/__init__.py` to `.gitignore`, then force-added the Python files with `git add -f`
- **Files modified:** `.gitignore`
- **Commit:** ff75880

**2. [Rule 1 - Bug] WCMatchModel row sums not exactly 1.0 triggering sklearn UserWarning**
- **Found during:** Task 3 (wc_eval.py) first run
- **Issue:** WCMatchModel rounds probs to 4dp (e.g., win_prob=0.6094, draw_prob=0.2002, loss_prob=0.1905 → sum=0.9999); sklearn `log_loss()` emits UserWarning
- **Fix:** Added row normalization in `evaluate_model()` before passing probs to `log_loss()`
- **Files modified:** `alpha/engines/sports/wc_calibration.py`
- **Commit:** a9986da

**3. [Rule 1 - Bug] WCIsotonicCalibrator producing all-zero rows on out-of-range test inputs**
- **Found during:** Task 4 test `test_calibrator_probs_sum_to_one`
- **Issue:** With small training sets (10 samples), IR can output 0.0 for all 3 class probabilities for test points outside the training range; renormalization of 0/0 leaves rows as all-zeros
- **Fix:** Added `np.clip(calibrated, 1e-9, None)` before renormalization in `WCIsotonicCalibrator.predict()`
- **Files modified:** `alpha/engines/sports/wc_calibration.py`
- **Commit:** 16a42f4

**4. [Rule 1 - Bug] Floating point arithmetic in promotion_gate test**
- **Found during:** Task 4 test `test_promotion_gate_custom_min_delta`
- **Issue:** `0.500 - 0.499` in Python float64 = `0.001000...9 > 0.001` (True, not False), causing the test assertion to fail
- **Fix:** Rewrote test to use delta=0.05 (well above 0.001) and test with min_delta=0.1 for the FAIL case
- **Files modified:** `tests/unit/engines/test_wc_calibration.py`
- **Commit:** 16a42f4

## Known Stubs

None. All code paths are fully implemented and produce real output.

## Threat Flags

None. This phase is pure local metrics/data code — no network calls, no user input, no credentials.

## Self-Check: PASSED

All files exist on disk. All commits verified in git log.

| Check | Status |
|-------|--------|
| data/__init__.py | FOUND |
| data/wc_historical_matches.py | FOUND |
| alpha/engines/sports/wc_calibration.py | FOUND |
| scripts/wc_eval.py | FOUND |
| tests/unit/engines/test_wc_calibration.py | FOUND |
| tests/unit/engines/test_wc_eval.py | FOUND |
| commit ff75880 (historical data module) | FOUND |
| commit 897268a (calibration module) | FOUND |
| commit a9986da (backtest runner) | FOUND |
| commit 16a42f4 (calibration tests + IR fix) | FOUND |
| commit 107c4ba (eval tests) | FOUND |
| 868/868 tests passing | VERIFIED |
| wc_eval.py exits 0 | VERIFIED |
| wc_scanner.py --mode parlay unchanged | VERIFIED |
