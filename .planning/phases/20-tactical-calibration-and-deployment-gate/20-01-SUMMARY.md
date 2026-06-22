---
phase: 20-tactical-calibration-and-deployment-gate
plan: 01
subsystem: wc-tactical-data
tags: [world-cup, tactics, leakage, dataset]
requires: [phase-19]
provides: [versioned-history-rows, coverage-gate, sealed-splits]
affects: [20-02, 20-03]
tech-stack:
  added: []
  patterns: [strict-as-of-validation, content-addressed-manifests]
key-files:
  created:
    - alpha/data/ingestion/wc_tactical_history.py
    - scripts/build_wc_tactical_dataset.py
    - tests/unit/data/test_wc_tactical_history.py
  modified:
    - scripts/validate_wc_tactics.py
    - tests/unit/engines/test_validate_wc_tactics.py
key-decisions:
  - Missing card status fails closed rather than assuming no red card.
  - Validation and World Cup audit event IDs are sealed in content-hashed manifests.
requirements-completed: [WCCAL-01, WCCAL-02, WCCAL-03, WCCAL-04]
duration: 18 min
completed: 2026-06-21
---

# Phase 20 Plan 01: Leakage-Safe Historical Tactical Dataset Summary

Implemented direct ESPN-cache row reconstruction, versioned historical-row contracts, strict pre-kickoff provenance checks, deterministic development/validation/external-audit splitting, content-hashed manifests, and the canonical 200/50/30 coverage gate.

## Verification

- `python -m pytest tests/unit/data/test_wc_tactical_history.py tests/unit/engines/test_validate_wc_tactics.py -q`
- Result: 8 passed.

## Deviations from Plan

The CLI consumes versioned source JSONL rather than silently crawling undocumented endpoints. This keeps source discovery auditable and prevents refreshed schedules from changing a sealed dataset.

## Commits

- `fa83f37` - leakage-safe tactical history dataset and tests

## Issues Encountered

The real cache audit discovered 198 summaries but only 16 eligible rows: 0 development, 6 validation, and 10 World Cup audit. Downstream training is correctly blocked.

## Self-Check: PASSED

All created files exist, focused tests pass, and production code was committed before this summary.
