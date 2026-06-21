---
phase: 14-draw-integration
verified: 2026-06-21T00:00:00Z
status: passed
score: 8/8 must-haves verified
---

# Phase 14 Verification Report

**Goal:** Model-gated draw betting and league-specific EPL/UCL scanner integration.

## Results

| Requirement | Status | Evidence |
|---|---|---|
| Draw legs require independent model output | PASS | Builder tests reject missing and market-implied model names |
| Draw legs require EV greater than 5% | PASS | Threshold boundary tests pass |
| Draw legs carry `is_draw=True` | PASS | Builder field-completeness test |
| Win and draw legs from one event cannot share a combo | PASS | Same-event exclusion test |
| EPL routes through `SoccerModel` | PASS | Scanner routing test |
| UCL routes through `UCLEloModel` | PASS | Scanner routing test |
| Scanner prints H/D/A probabilities and draw warning | PASS | Output tests and source inspection |
| No repository regressions | PASS | 727 passed, 5 skipped |

## Commands

- Focused: `pytest tests/unit/test_soccer_scanner.py tests/unit/test_sgp_builder.py` -> 18 passed
- Full: `pytest tests` -> 727 passed, 5 skipped

## Verdict

Phase 14 passes all automated gates. No human verification is required.
