---
phase: 08-dynamic-draw-algorithm
plan: 01
subsystem: sports-modeling
tags: [world-cup, elo, probability-calibration, pytest]

requires:
  - phase: 07-sgp-builder-scanner-integration
    provides: World Cup match model and scanner pipeline
provides:
  - Elo-gap-dependent group-stage draw probabilities
  - Calibration coverage at five representative Elo differences
  - Preserved zero-draw knockout behavior
affects: [wc-model, wc-scanner, wc-sgp-builder]

tech-stack:
  added: []
  patterns: [pure probability helper, exponential-decay calibration]

key-files:
  created: []
  modified:
    - alpha/engines/sports/wc_model.py
    - tests/unit/engines/test_wc_model.py

key-decisions:
  - "Use 0.32 * exp(-abs(elo_adj) / 500) with a 0.05 floor for group-stage draws."
  - "Keep knockout draw probability fixed at exactly 0.0."

patterns-established:
  - "World Cup draw calibration is isolated in the pure _draw_prob() helper."

requirements-completed: [DRAW-01, DRAW-02, DRAW-03, TEST-01]

duration: 10 min
completed: 2026-06-19
---

# Phase 8 Plan 01: Dynamic Draw Algorithm Summary

**World Cup group-stage draw probability now decays with adjusted Elo difference while knockout draws remain disabled.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-19T07:08:00Z
- **Completed:** 2026-06-19T07:18:15Z
- **Tasks:** 4
- **Files modified:** 2

## Accomplishments

- Replaced the flat 25% draw constant with calibrated exponential decay from 32% toward a 5% floor.
- Added parameterized coverage for Elo gaps of 0, 100, 300, 500, and 750 points.
- Verified floor enforcement, monotonic decay, and unchanged knockout behavior.
- Passed the complete 631-test regression suite.

## Task Commits

1. **Tasks 1-3: Dynamic draw model and tests** - `96f0ac6` (feat)
2. **Task 4: Full regression verification** - no file changes

## Files Created/Modified

- `alpha/engines/sports/wc_model.py` - Adds draw calibration constants and `_draw_prob()` integration.
- `tests/unit/engines/test_wc_model.py` - Covers calibration points, floor, and monotonic behavior.

## Decisions Made

- Followed the phase calibration: base 0.32, scale 500 Elo points, floor 0.05.
- Used the post-xG-adjustment Elo difference so draw and win probabilities share the same strength signal.

## Deviations from Plan

None - plan executed as written. A pre-existing xG-cap correction in `wc_model.py` was preserved but excluded from the Phase 8 commit.

## Issues Encountered

- The first full-suite run exceeded a two-minute command timeout. It was rerun with a longer limit and completed successfully: 631 passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 8 is complete and the v1.2 Draw Algorithm milestone is ready for milestone verification/completion.

---
*Phase: 08-dynamic-draw-algorithm*
*Completed: 2026-06-19*
