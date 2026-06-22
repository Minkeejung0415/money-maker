---
phase: 13-soccer-models
verified: 2026-06-20T08:15:00Z
status: passed
score: 14/14 must-haves verified
overrides_applied: 0
---

# Phase 13: Soccer Model Upgrade Verification Report

**Phase Goal:** EPL XGBoost training pipeline (Plan 13-01) and UCLEloModel + SoccerModel EPL artifact gate (Plan 13-02)
**Verified:** 2026-06-20T08:15:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | EPL_FEATURE_NAMES is a tuple of exactly 14 features covering xG, form, H2H, rest, set pieces | VERIFIED | `len(EPL_FEATURE_NAMES) == 14` confirmed by runtime check and test_feature_names_count PASSED |
| 2  | build_epl_pregame_rows(games) returns leakage-safe rows (target game result not in its own features) | VERIFIED | test_build_rows_leakage_safe PASSED: row[0].home_form_points==0.0 (initial state), row[1].home_form_points>0.0 (after game1 update) |
| 3  | live_epl_feature_vector(home, away, date, {}) returns dict with all 14 EPL_FEATURE_NAMES keys, no KeyError | VERIFIED | test_live_feature_vector_keys PASSED: `set(fv.keys()) == set(EPL_FEATURE_NAMES)` with empty state_map |
| 4  | train_epl_moneyline.py with 300+ synthetic rows produces bundle["kind"] == "epl_win_probability_bundle" | VERIFIED | test_bundle_kind PASSED with 400 synthetic games |
| 5  | train() raises ValueError for <300 rows; main() raises SystemExit when model fails Brier gate | VERIFIED | test_too_few_rows_raises PASSED (ValueError confirmed); SystemExit logic verified in source: `if not meta["validated"]: raise SystemExit(...)` |
| 6  | calibrated() is defined in epl_training.py (not in train script) | VERIFIED | `from alpha.engines.sports.epl_training import ... calibrated` imported at line 14 of train_epl_moneyline.py; defined at line 238 of epl_training.py |
| 7  | UCLEloModel.predict() returns win_prob, draw_prob, loss_prob summing to 1.0 | VERIFIED | test_predict_equal_elo_probs_sum PASSED (tolerance 1e-3 for 4dp rounding); all 18 UCL tests pass |
| 8  | UCLEloModel applies +40 Elo home advantage (_UCL_HOME_ADVANTAGE=40.0) | VERIFIED | `_UCL_HOME_ADVANTAGE: float = 40.0` at line 34; `elo_adj = float(elo_diff) + _UCL_HOME_ADVANTAGE` at line 97; test_predict_home_advantage_applied PASSED |
| 9  | UCLEloModel.predict() raises ValueError when game["league"] != "ucl" | VERIFIED | test_league_guard_epl and test_league_guard_wc PASSED; ValueError raised at lines 83-86 of ucl_model.py |
| 10 | model_name == "ucl_elo_logistic" in UCLEloModel.predict() output | VERIFIED | test_predict_model_name PASSED; `game["model_name"] = "ucl_elo_logistic"` at line 119 of ucl_model.py |
| 11 | SoccerModel._epl_artifact_loaded=True with valid bundle (kind+validated+feature_names gates pass) | VERIFIED | test_valid_bundle_accepted PASSED; _load_epl_artifact() sets _epl_artifact_loaded=True only after all 3 schema checks pass |
| 12 | SoccerModel rejects unvalidated bundles and feature_names mismatches | VERIFIED | test_unvalidated_bundle_rejected, test_wrong_kind_rejected, test_feature_mismatch_rejected — all 3 PASSED |
| 13 | SoccerModel.predict() includes model_name field in all return paths | VERIFIED | test_predict_fallback_has_model_name and test_predict_artifact_model_name PASSED; market_implied path returns "model_name": "market_implied" at line 233; EPL artifact path returns "model_name": "epl_xgboost_v1" at line 101 |
| 14 | All 666+ existing tests still pass (current count should be 715) | VERIFIED | Full suite run: 715/715 passed in 212.65s — zero regressions |

**Score:** 14/14 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `alpha/engines/sports/epl_training.py` | EPL_FEATURE_NAMES, EPLTeamState, build_epl_pregame_rows, live_epl_feature_vector, calibrated | VERIFIED | 243 lines, all exports present and tested |
| `scripts/train_epl_moneyline.py` | fetch_epl_games, train(), main() with Brier gate and SystemExit | VERIFIED | 174 lines, calibrated() imported from epl_training (not redefined) |
| `tests/unit/engines/test_epl_training.py` | 17 unit tests for EPL feature contract | VERIFIED | 17/17 tests pass |
| `tests/unit/engines/test_train_epl_moneyline.py` | 5 unit tests for bundle schema and ValueError gate | VERIFIED | 5/5 tests pass |
| `alpha/engines/sports/ucl_model.py` | UCLEloModel class: predict(), evaluate_bet(), evaluate_batch() | VERIFIED | 140 lines, all methods implemented |
| `alpha/engines/sports/soccer_model.py` | _load_epl_artifact(), _predict_epl_bundle(), model_name in predict() | VERIFIED | Modified with EPL artifact gate (lines 259-326) and model_name in all return paths |
| `tests/unit/engines/test_ucl_model.py` | 18 unit tests for UCLEloModel | VERIFIED | 18/18 tests pass |
| `tests/unit/engines/test_soccer_model.py` | 9 unit tests for SoccerModel EPL artifact gate | VERIFIED | 9/9 tests pass |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `scripts/train_epl_moneyline.py` | `alpha/engines/sports/epl_training.py` | `from alpha.engines.sports.epl_training import EPL_FEATURE_NAMES, build_epl_pregame_rows, calibrated` | WIRED | Line 14 of train script, confirmed by grep |
| `scripts/train_epl_moneyline.py` | `alpha/engines/sports/evaluation.py` | `from alpha.engines.sports.evaluation import probability_metrics` | WIRED | Line 13 of train script |
| `alpha/engines/sports/ucl_model.py` | `alpha/data/ingestion/club_elo.py` | `from alpha.data.ingestion.club_elo import load_club_elo_ratings, get_club_elo_rating` | WIRED | Line 17 of ucl_model.py; tests mock this successfully |
| `alpha/engines/sports/ucl_model.py` | `alpha/engines/sports/ev_calculator.py` | `from alpha.engines.sports.ev_calculator import EVCalculator` | WIRED | Line 16 of ucl_model.py |
| `alpha/engines/sports/soccer_model.py` | `alpha/engines/sports/epl_training.py` | `from alpha.engines.sports.epl_training import EPL_FEATURE_NAMES` (lazy import in _load_epl_artifact) | WIRED | Line 281 of soccer_model.py inside _load_epl_artifact(); lazy import confirmed |
| `alpha/engines/sports/soccer_model.py` | `alpha/models/epl_win_probability.pkl` | `_EPL_ARTIFACT = Path("alpha/models/epl_win_probability.pkl"); joblib.load(_EPL_ARTIFACT)` | WIRED | Lines 35 and 272 of soccer_model.py; file absent at test time — handled by gate (returns early, no crash) |

---

## Data-Flow Trace (Level 4)

UCLEloModel and SoccerModel are runtime-computed models — no dynamic data rendering in the traditional sense. The data flows are:

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `ucl_model.py` | `self._elo_ratings` | `load_club_elo_ratings()` from clubelo.com (mocked in tests) | Yes — club Elo float values per team | FLOWING (mocked in tests; real data at runtime) |
| `soccer_model.py` | `self._epl_model`, `self._epl_calibrator`, `self._epl_team_state` | `joblib.load(_EPL_ARTIFACT)` | Yes — trained sklearn model bundle when pkl exists | FLOWING (gate blocks on absent pkl — backward compatible) |
| `epl_training.py` | `rows`, `state_map` | `build_epl_pregame_rows(games)` | Yes — chronological game dicts processed into feature rows | FLOWING — tested with synthetic data producing real Elo/form accumulation |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| EPL_FEATURE_NAMES is 14 features | `python -c "from alpha.engines.sports.epl_training import EPL_FEATURE_NAMES, calibrated; print(len(EPL_FEATURE_NAMES), EPL_FEATURE_NAMES)"` | `14 ('home_xg_for', 'home_xg_against', ...)` — all 14 printed | PASS |
| UCLEloModel imports cleanly | `python -c "from alpha.engines.sports.ucl_model import UCLEloModel; print('UCLEloModel OK')"` | `UCLEloModel OK` | PASS |
| 17 EPL training tests | `pytest tests/unit/engines/test_epl_training.py -v` | 17 passed in 0.15s | PASS |
| 5 EPL moneyline training tests | `pytest tests/unit/engines/test_train_epl_moneyline.py -v` | 5 passed in 6.19s | PASS |
| 18 UCL model tests | `pytest tests/unit/engines/test_ucl_model.py -v` | 18 passed in 1.21s | PASS |
| 9 soccer model tests | `pytest tests/unit/engines/test_soccer_model.py -v` | 9 passed in 3.04s | PASS |
| Full suite regression | `pytest tests/ -q` | 715 passed in 212.65s (0:03:32) | PASS |

---

## Probe Execution

No probe scripts declared in PLAN.md files. Step 7c: SKIPPED (no declared probes for this phase).

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SMODEL-01 | 13-01-PLAN.md | EPL XGBoost training pipeline: feature contract, leakage-safe row builder, training script | SATISFIED | epl_training.py + train_epl_moneyline.py implemented; 22 tests pass |
| SMODEL-02 | 13-02-PLAN.md | UCLEloModel: Club Elo-logistic W/D/L with +40 home advantage | SATISFIED | ucl_model.py implemented; 18 tests verify all behaviors including home boost and league guard |
| SMODEL-03 | 13-02-PLAN.md | SoccerModel EPL artifact gate: schema validation, model_name field, backward-compatible fallback | SATISFIED | soccer_model.py updated with 3-check gate (_load_epl_artifact); 9 tests verify accepted/rejected bundles and model_name in all paths |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | — | — | — |

No TBD, FIXME, XXX, TODO, HACK, or PLACEHOLDER markers found in any of the 4 phase-modified files. No stub return patterns (return null, return {}, return []) found in implementation paths. No hardcoded empty data in rendering paths.

---

## Human Verification Required

None. All observable truths are verifiable programmatically. The EPL XGBoost model artifact (`alpha/models/epl_win_probability.pkl`) requires a live run of `scripts/train_epl_moneyline.py` (needs `FOOTBALL_API_KEY` and network access) to produce the pkl — but this is an intentional offline training step, not a phase deliverable. The schema contract that SoccerModel will use when the pkl exists has been verified via the unit tests (test_valid_bundle_accepted).

---

## Gaps Summary

No gaps found. All 14 must-haves are verified with direct evidence from the codebase and live test execution.

---

_Verified: 2026-06-20T08:15:00Z_
_Verifier: Claude (gsd-verifier)_
