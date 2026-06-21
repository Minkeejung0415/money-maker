---
phase: 14-draw-integration
plan: 01
subsystem: sports
tags: [soccer, draw-legs, sgp-builder, ev-gate, tdd, xgboost]

# Dependency graph
requires:
  - phase: 08-dynamic-draw
    provides: "draw_prob field on game dicts from wc_model / soccer_model"

provides:
  - "_build_draw_legs() method with D-11 EV gate in soccer_sgp_builder.py"
  - "Draw legs pooled into classic parlay combos alongside win legs"
  - "Same-game guard blocking draw+win combos from the same event_id"
  - "is_draw=True annotation on qualifying draw leg dicts"

affects:
  - 14-02-scanner-annotation
  - soccer_scanner

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "D-11 EV gate: model_name != None/market_implied AND draw_ev > 0.05 before including draw leg"
    - "Same-game guard via event_ids_by_type set intersection check in combo loop"
    - "is_draw=True flag on draw leg dicts for downstream scanner annotation"

key-files:
  created:
    - tests/unit/engines/test_soccer_sgp_builder.py
  modified:
    - alpha/engines/sports/soccer_sgp_builder.py

key-decisions:
  - "Draw legs use EV > 0.05 threshold (5%), consistent with plan D-11 decision"
  - "Same-game guard implemented via set intersection on event_id per leg type (not filtering by leg order)"
  - "9 tests written (plan specified 8): added test_draw_leg_fields_complete for field completeness coverage"
  - "all_legs = ml_legs + draw_legs pooled in _build_classic_parlay; order does not affect combo enumeration"

requirements-completed:
  - SDRAW-01
  - SDRAW-02
  - STEST-01

# Metrics
duration: 9min
completed: 2026-06-20
---

# Phase 14 Plan 01: SoccerSGPBuilder Draw Legs Summary

**Draw leg support added to SoccerSGPBuilder via D-11 EV gate: qualifies draw legs from real models only (EV > 5%) and pools them into classic parlay combos with same-game win+draw conflict guard**

## Performance

- **Duration:** 9 min
- **Started:** 2026-06-20T10:40:41Z
- **Completed:** 2026-06-20T10:49:43Z
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added `_build_draw_legs(ml_games)` to `SoccerSGPBuilder` with full D-11 gate (model_name check + EV > 5%)
- Modified `_build_classic_parlay` to pool draw legs with win legs and enumerate all combinations
- Implemented same-game guard: combos pairing a draw leg and win leg from the same `event_id` are skipped
- Draw legs carry `is_draw=True` flag for scanner annotation in Plan 14-02
- 9 unit tests written and passing (TDD RED -> GREEN cycle)
- Full suite: 732 tests passing, 0 failures (baseline was 715, +17 from this and prior work)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write draw leg unit tests (RED phase)** - `268a6a0` (test)
2. **Task 2: Implement draw legs in SoccerSGPBuilder (GREEN)** - `039868f` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD tasks have 2 commits (test RED -> feat GREEN)_

## Files Created/Modified

- `tests/unit/engines/test_soccer_sgp_builder.py` - 9 unit tests covering D-11 gate, EV threshold, is_draw annotation, same-game guard, multi-game draw combos, win-leg regression
- `alpha/engines/sports/soccer_sgp_builder.py` - Added `_build_draw_legs()` method + modified `_build_classic_parlay()` to pool and guard combos

## Decisions Made

- **EV threshold 0.05**: Matches D-11 spec; consistent with existing soccer engine conventions
- **9 tests vs 8**: Added `test_draw_leg_fields_complete` to verify all leg dict keys are present with correct values; this provides stronger correctness guarantee for downstream scanner
- **Same-game guard via set intersection**: Checking `draw_eids & ml_eids` on event_id sets is O(n) per combo and cleanly handles edge cases where a game has no draw leg

## Deviations from Plan

### Auto-fixed Issues

None - plan executed exactly as written. One additional test (`test_draw_leg_fields_complete`) was added beyond the 8 specified for stronger field-level correctness coverage; this is additive and does not contradict the plan.

---

**Total deviations:** 0 auto-fixed
**Impact on plan:** Executed exactly as specified.

## Issues Encountered

None - all EV calculations matched plan spec exactly. Both RED and GREEN phases succeeded on first attempt.

## User Setup Required

None - no external service configuration required.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. `_build_draw_legs` reads from game dicts already flowing through the existing soccer scanner pipeline; no new trust boundaries created.

## Known Stubs

None - draw legs are fully wired into `_build_classic_parlay`. Scanner-level annotation (`*DRAW RISK*` display) is deferred to Plan 14-02 per plan spec.

## Next Phase Readiness

- `_build_draw_legs` is complete; ready for Plan 14-02 (scanner annotation layer)
- `is_draw=True` flag on draw leg dicts enables scanner to detect and annotate draw legs
- No blockers

---
*Phase: 14-draw-integration*
*Completed: 2026-06-20*

## Self-Check: PASSED

- `tests/unit/engines/test_soccer_sgp_builder.py`: FOUND
- `alpha/engines/sports/soccer_sgp_builder.py` contains `_build_draw_legs`: FOUND (2 occurrences)
- `alpha/engines/sports/soccer_sgp_builder.py` contains `is_draw`: FOUND (2 occurrences)
- All 9 draw leg tests: PASS (confirmed by pytest run)
- Full suite 732/732: PASS (0 failures, 0 regressions)
- Commit `268a6a0` (test RED): FOUND
- Commit `039868f` (feat GREEN): FOUND
