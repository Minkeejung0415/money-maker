---
phase: 15-scoreline-goal-market-model
plan: 01
status: complete
completed: 2026-06-21
requirements: [WCSGP-01, WCSGP-02, WCSGP-03, WCSGP-04, WCSGP-05, WCSGP-12]
---

# Phase 15 Plan 01 Summary

Implemented `WCScorelineModel`, a bounded Poisson scoreline engine calibrated by result bucket to preserve the existing WC Elo 1X2 marginals. It exposes regulation-time outcome, over/under 2.5, BTTS, and exact multi-leg joint probabilities.

Knockout games expose goal markets but reject regulation-time outcome legs because the existing WC model's knockout probabilities mean “to advance.” Invalid, duplicate, and contradictory combinations fail closed.

## Verification

- `pytest tests/unit/engines/test_wc_goal_markets.py -q`
- Result: 10 passed

