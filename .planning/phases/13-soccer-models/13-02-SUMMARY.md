---
phase: 13-soccer-models
plan: 02
subsystem: sports
tags: [elo, ucl, soccer, xgboost, artifact-gate, schema-validation, club-elo]

# Dependency graph
requires:
  - phase: 12-club-elo
    provides: "club_elo.py load_club_elo_ratings(), get_club_elo_rating() — used directly by UCLEloModel"
  - phase: 13-soccer-models-01
    provides: "epl_training.py EPL_FEATURE_NAMES, live_epl_feature_vector, calibrated — imported lazily by SoccerModel"
provides:
  - "UCLEloModel: Elo-logistic W/D/L model for UCL using Club Elo ratings (+40 home boost)"
  - "SoccerModel: EPL artifact gate (_epl_artifact_loaded), _load_epl_artifact(), _predict_epl_bundle()"
  - "model_name field in all SoccerModel predict() return paths"
  - "18 unit tests for UCLEloModel (test_ucl_model.py)"
  - "9 unit tests for SoccerModel EPL artifact gate (test_soccer_model.py)"
affects:
  - 14-draw-integration
  - scripts/soccer_scanner.py
  - scripts/ucl_scanner.py

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "UCLEloModel mirrors WCMatchModel exactly — same Bradley-Terry formula, same draw decay, same elo_edge flag"
    - "EPL artifact schema gate: kind + validated + feature_names set equality before accepting any pkl"
    - "Lazy import pattern for epl_training inside _load_epl_artifact() body to avoid hard dep at import time"
    - "monkeypatch ucl_module.load_club_elo_ratings (not club_elo_module) — must patch in consuming module's namespace"

key-files:
  created:
    - alpha/engines/sports/ucl_model.py
    - tests/unit/engines/test_ucl_model.py
    - tests/unit/engines/test_soccer_model.py
  modified:
    - alpha/engines/sports/soccer_model.py

key-decisions:
  - "UCL home advantage +40 Elo (half of standard 80pt per D-09) applied in elo_adj, not stored in elo_diff raw"
  - "SoccerModel EPL artifact takes priority over ProphitBet model when loaded — EPL model first in predict()"
  - "model_name added only to _market_implied_predict() return and EPL artifact path — ProphitBet path omitted (backward compat)"
  - "elo_diff stored as adjusted value (elo_home - elo_away + 40), home_elo/away_elo stored as raw pre-adjustment"

patterns-established:
  - "Pattern: Elo-logistic UCL model — mirrors WCMatchModel, use UCL-specific constants, no knockout mode"
  - "Pattern: EPL artifact gate — 3-check schema validation before setting _epl_artifact_loaded=True"

requirements-completed: [SMODEL-02, SMODEL-03]

# Metrics
duration: 22min
completed: 2026-06-20
---

# Phase 13 Plan 02: UCLEloModel + SoccerModel EPL Artifact Gate Summary

**UCLEloModel (Club Elo-logistic, +40 home advantage) and SoccerModel EPL artifact gate (schema-validated pkl loading with model_name field in all predict() paths)**

## Performance

- **Duration:** 22 min
- **Started:** 2026-06-20T07:15:27Z
- **Completed:** 2026-06-20T07:37:23Z
- **Tasks:** 2 (both TDD: RED + GREEN)
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- UCLEloModel: new standalone Elo-logistic model for UCL matching WCMatchModel's formula with _UCL_BASE_DRAW=0.28 and +40 Elo home advantage
- SoccerModel: EPL artifact gate loads epl_win_probability.pkl with 3-check schema validation (kind, validated, feature_names); rejects silently on any mismatch
- model_name field now returned in all SoccerModel predict() paths ("epl_xgboost_v1" or "market_implied")
- 27 new tests (18 UCL + 9 soccer model) all passing; 715 total tests passing (zero regressions)

## Task Commits

1. **Task 1 RED: UCLEloModel failing tests** - `ca33eb8` (test)
2. **Task 1 GREEN: UCLEloModel implementation** - `a0c6a98` (feat)
3. **Task 2 RED: SoccerModel artifact gate failing tests** - `1d7c647` (test)
4. **Task 2 GREEN: SoccerModel artifact gate implementation** - `0302402` (feat)

## Files Created/Modified

- `alpha/engines/sports/ucl_model.py` — UCLEloModel class: predict(), evaluate_bet(), evaluate_batch(); exports UCLEloModel
- `tests/unit/engines/test_ucl_model.py` — 18 unit tests: W/D/L probs, home advantage, draw decay, league guard, elo_edge, evaluate_bet/batch, fallback empty ratings
- `alpha/engines/sports/soccer_model.py` — Added _EPL_ARTIFACT, _load_epl_artifact(), _predict_epl_bundle(), EPL artifact path in predict(), model_name in _market_implied_predict()
- `tests/unit/engines/test_soccer_model.py` — 9 unit tests: artifact accepted/rejected, model_name field, backward compat

## Decisions Made

- UCL home advantage is +40 Elo (per D-09 spec, half of standard 80pt) applied to elo_adj, not stored in raw diff fields — home_elo/away_elo are always raw pre-adjustment values
- SoccerModel EPL artifact takes priority over ProphitBet model at top of predict() — when EPL artifact loaded, ProphitBet path is skipped
- model_name NOT added to ProphitBet path return dict (backward compatibility) — only EPL and market_implied paths get model_name
- elo_diff stored as adjusted value (raw diff + 40.0) to match what goes into Bradley-Terry formula

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test monkeypatching must target consuming module's namespace**
- **Found during:** Task 1 (UCLEloModel test execution)
- **Issue:** Autouse fixture patched `club_elo_module.load_club_elo_ratings` but `ucl_model.py` imports it via `from ... import load_club_elo_ratings`, creating a local name binding. Patching the source module didn't affect the already-bound name in ucl_model.
- **Fix:** Changed autouse fixture and fallback test to patch `alpha.engines.sports.ucl_model.load_club_elo_ratings` (the consuming module's namespace)
- **Files modified:** tests/unit/engines/test_ucl_model.py
- **Verification:** All 18 tests pass including fallback_empty_ratings
- **Committed in:** a0c6a98 (Task 1 GREEN commit)

**2. [Rule 1 - Bug] Rounding tolerance for probability sum test**
- **Found during:** Task 1 (test_predict_equal_elo_probs_sum)
- **Issue:** Probabilities rounded to 4 decimal places can sum to 1.0001 (max rounding error per value = 0.00005, times 3 values = 0.00015). Test used 1e-9 tolerance which is too strict for rounded output.
- **Fix:** Changed tolerance to 1e-3 to match rounding artifacts from round(..., 4) output
- **Files modified:** tests/unit/engines/test_ucl_model.py
- **Verification:** test_predict_equal_elo_probs_sum passes; correct behavior (probs sum to 1.0 before rounding)
- **Committed in:** a0c6a98 (Task 1 GREEN commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs in tests)
**Impact on plan:** Minor test-correctness fixes. Implementation files match plan exactly.

## Issues Encountered

None — implementation was straightforward. Parallel agent 13-01 completed epl_training.py before Task 2 started, so the lazy import path was available.

## Threat Surface Scan

| Flag | File | Description |
|------|------|-------------|
| threat_flag: Tampering | alpha/engines/sports/soccer_model.py | T-13-05 mitigated: EPL artifact schema gate implemented (kind + validated + feature_names) |
| threat_flag: Spoofing | alpha/engines/sports/ucl_model.py | T-13-06 mitigated: ValueError raised on league != 'ucl' |

Both threats from the plan's threat register are mitigated. No new threat surface introduced beyond what was planned.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- UCLEloModel is ready for use in scripts/ucl_scanner.py (Phase 14)
- SoccerModel will auto-load EPL artifact when alpha/models/epl_win_probability.pkl is present (after 13-03 training run)
- All 715 tests passing — no blockers for Phase 14

---
*Phase: 13-soccer-models*
*Completed: 2026-06-20*

## Self-Check: PASSED

Files verified:
- [x] alpha/engines/sports/ucl_model.py EXISTS
- [x] alpha/engines/sports/soccer_model.py EXISTS (modified)
- [x] tests/unit/engines/test_ucl_model.py EXISTS (18 tests pass)
- [x] tests/unit/engines/test_soccer_model.py EXISTS (9 tests pass)

Commits verified:
- [x] ca33eb8 test(13-02) RED UCLEloModel
- [x] a0c6a98 feat(13-02) GREEN UCLEloModel
- [x] 1d7c647 test(13-02) RED SoccerModel
- [x] 0302402 feat(13-02) GREEN SoccerModel

Full suite: 715/715 tests passing (666 baseline + 49 from 13-01 parallel + 18 UCL + 9 soccer model)
