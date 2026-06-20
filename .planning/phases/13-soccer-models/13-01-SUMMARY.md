---
phase: 13-soccer-models
plan: 01
subsystem: sports-ml
tags: [xgboost, epl, soccer, training-pipeline, feature-engineering, platt-calibration]

# Dependency graph
requires:
  - phase: 12-soccer-ingestion
    provides: soccer_form.py, soccer_fbref.py, football_data_client.py — ingestion modules called by live_epl_feature_vector()
  - phase: 08-dynamic-draw
    provides: mlb_training.py pattern for feature contract + row builder
provides:
  - EPL_FEATURE_NAMES tuple (14 features covering xG, form, H2H, rest, set pieces)
  - EPLTeamState dataclass with form_buffer for rolling W2-fix
  - build_epl_pregame_rows() leakage-safe row builder (draws update state, skip rows)
  - live_epl_feature_vector() offline + live inference paths
  - calibrated() Platt utility shared by train script and SoccerModel
  - train_epl_moneyline.py training script: fetch -> build rows -> train -> calibrate -> validate -> save
  - alpha/models/epl_win_probability.pkl artifact schema (produced by running script)
affects:
  - 13-02 (SoccerModel XGBoost integration — imports epl_training)
  - 13-03 (scanner integration — uses live_epl_feature_vector)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EPL feature module mirrors mlb_training.py: EPL_FEATURE_NAMES, EPLTeamState, build_epl_pregame_rows, live_epl_feature_vector"
    - "Draws update form_buffer and h2h_log but never append rows (binary classifier skips draws)"
    - "calibrated() defined in epl_training.py, imported by train script (not re-defined)"
    - "fetch_live=False default in live_epl_feature_vector for safe offline/training use"
    - "form_buffer capped at FORM_WINDOW*2 entries for bounded memory"

key-files:
  created:
    - alpha/engines/sports/epl_training.py
    - scripts/train_epl_moneyline.py
    - tests/unit/engines/test_epl_training.py
    - tests/unit/engines/test_train_epl_moneyline.py
  modified: []

key-decisions:
  - "calibrated() lives in epl_training.py (not train script) so SoccerModel can import it without pulling in training dependencies"
  - "Draws skip rows but update form_buffer and h2h_log — fixes W2 training distribution bug where form features were always 0"
  - "fetch_live flag in live_epl_feature_vector: False default keeps module import-clean; live ingestion lazily imported inside try/except"
  - "FOOTBALL_API_KEY raises RuntimeError if missing — no silent empty-string fallback (T-13-02 threat mitigation)"
  - "bundle kind=epl_win_probability_bundle enables schema gate in SoccerModel (T-13-01 threat mitigation)"

patterns-established:
  - "TDD: RED (ImportError/FileNotFoundError) → GREEN (all pass) → commit per task"
  - "Feature contract module pattern: EPL_FEATURE_NAMES tuple + dataclass + build_pregame_rows + live_feature_vector"

requirements-completed: [SMODEL-01]

# Metrics
duration: 17min
completed: 2026-06-20
---

# Phase 13 Plan 01: EPL XGBoost Training Pipeline Summary

**Leakage-safe EPL XGBoost training pipeline: 14-feature contract (xG + form + H2H + rest + set pieces), W2-correct row builder that accumulates form through draws, and train_epl_moneyline.py with Brier gate and joblib bundle save**

## Performance

- **Duration:** ~17 min
- **Started:** 2026-06-20T07:12:17Z
- **Completed:** 2026-06-20T07:29:15Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- EPL_FEATURE_NAMES tuple with exactly 14 features across 5 categories (xG, form, H2H, rest, set pieces)
- build_epl_pregame_rows() is leakage-safe: features extracted before each game's result; draws update form_buffer and h2h_log but do not add rows (fixing W2 training distribution bug)
- live_epl_feature_vector() returns all 14 EPL_FEATURE_NAMES keys with safe defaults on empty state_map
- train_epl_moneyline.py mirrors train_mlb_moneyline.py: 60/20/20 split, Brier gate, joblib bundle, .meta.json sidecar
- 22 new tests (17 + 5), all passing; 292 engine tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: epl_training.py — feature contract and row builder** - `c0241a0` (feat)
2. **Task 2: train_epl_moneyline.py — training script with Brier gate** - `1324c3a` (feat)

**Plan metadata:** (this commit)

_Note: Both tasks used TDD (RED → GREEN per task)_

## Files Created/Modified
- `alpha/engines/sports/epl_training.py` — EPL_FEATURE_NAMES, EPLTeamState, build_epl_pregame_rows, live_epl_feature_vector, calibrated
- `scripts/train_epl_moneyline.py` — fetch_epl_games, train, main with Brier gate
- `tests/unit/engines/test_epl_training.py` — 17 tests: schema (6), row builder (8), live vector (3)
- `tests/unit/engines/test_train_epl_moneyline.py` — 5 tests: bundle schema, meta.json, ValueError gate, validated field

## Decisions Made
- calibrated() defined in epl_training.py (not the train script) so SoccerModel can import it without pulling in sklearn training dependencies
- Draws skip rows but update form_buffer and h2h_log — this is the W2 fix; without it, form features would be zero for most EPL training rows since EPL has ~25% draw rate
- FOOTBALL_API_KEY raises RuntimeError if missing rather than falling back to empty string (T-13-02 threat mitigation)
- bundle["kind"] = "epl_win_probability_bundle" enables schema gate in SoccerModel when loading pkl (T-13-01 threat mitigation)

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required for this plan. The training script (train_epl_moneyline.py) requires FOOTBALL_API_KEY when run, but that is already configured in .env from Phase 12.

## Next Phase Readiness
- epl_training.py is ready for Plan 13-02 (SoccerModel integration): import EPL_FEATURE_NAMES, build_epl_pregame_rows, calibrated
- train_epl_moneyline.py can be run when FOOTBALL_API_KEY is set to produce alpha/models/epl_win_probability.pkl
- live_epl_feature_vector() ready for scanner integration in Plan 13-03

---
*Phase: 13-soccer-models*
*Completed: 2026-06-20*

## Self-Check: PASSED

- `alpha/engines/sports/epl_training.py` — FOUND
- `scripts/train_epl_moneyline.py` — FOUND
- `tests/unit/engines/test_epl_training.py` — FOUND
- `tests/unit/engines/test_train_epl_moneyline.py` — FOUND
- Commit `c0241a0` — FOUND (feat(13-01): implement EPL feature contract and row builder)
- Commit `1324c3a` — FOUND (feat(13-01): add EPL moneyline training script and tests)
- 17 test_epl_training.py tests: PASSED
- 5 test_train_epl_moneyline.py tests: PASSED
- 292 engine tests (regression check): PASSED
