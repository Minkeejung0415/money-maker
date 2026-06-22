---
phase: 20-tactical-calibration-and-deployment-gate
plan: 03
subsystem: wc-tactical-runtime
tags: [artifact, deployment-gate, scanner, sgp]
requires: [20-02]
provides: [versioned-artifact, market-fallback, coherent-sgp-gate]
affects: [wc-model, wc-goal-markets, wc-sgp-builder, wc-scanner]
tech-stack:
  added: []
  patterns: [schema-checked-artifacts, one-distribution-per-sgp, explicit-fallback-status]
key-files:
  created: []
  modified:
    - alpha/engines/sports/wc_tactical_calibration.py
    - alpha/engines/sports/wc_model.py
    - alpha/engines/sports/wc_goal_markets.py
    - alpha/engines/sports/wc_sgp_builder.py
    - scripts/wc_scanner.py
key-decisions:
  - Archived v1.6 multipliers are descriptive only unless a validated artifact authorizes learned effects.
  - An SGP falls back as a whole when every constituent family is not approved on one distribution.
requirements-completed: [WCCAL-10, WCCAL-11, WCCAL-12, WCCAL-13, WCCAL-14]
duration: 28 min
completed: 2026-06-21
---

# Phase 20 Plan 03: Versioned Artifact and Deployment Gate Summary

Implemented schema/version/cutoff/sample validation, bounded runtime residuals, independent single-market gates, whole-SGP distribution fallback, and visible scanner artifact/gate status.

## Verification

- Focused runtime suite: 65 passed.
- Complete repository suite: 791 passed, 5 skipped.
- Scanner audit for June 21 and cached June 19: source returned no fixtures, so no live probabilities were generated.

## Deviations from Plan

**[Rule 3 - Blocker] Explicit empty API keys fell back to `.env`.** The full suite exposed import-order-dependent failures in FootballDataClient and OddsAPIClient. Constructors now distinguish `None` (environment fallback) from `""` (intentionally unconfigured). Affected 54-test subset and full suite pass.

## Commits

- `3e03364` - runtime artifacts, fail-closed gates, SGP coherence, scanner status, and API-key isolation fix

## Issues Encountered

No source dataset currently satisfies the 200/50/30 evidence gate. The runtime therefore remains on the no-tactics baseline, as designed.

## Self-Check: PASSED

All artifact failure modes, market gate combinations, probability sums, knockout rules, SGP coherence, scanner fallback output, and the complete regression suite pass.
