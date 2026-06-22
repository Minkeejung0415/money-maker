---
phase: 20-tactical-calibration-and-deployment-gate
status: passed
verified_at: 2026-06-22T01:20:00Z
score: 5/5
---

# Phase 20 Verification

## Goal

Replace hand-set tactical influence with validated, regularized residual adjustments while preserving the no-tactics baseline whenever evidence is insufficient.

## Must-Haves

1. **Coverage before modeling: PASS.** Dataset construction has strict as-of contracts, deterministic sealed splits, and an immutable 200/50/30 gate.
2. **Chronological probability evaluation: PASS.** Expanding folds, fixed offsets, L2 shrinkage, four controls, 10,000 paired bootstraps, Holm correction, and numeric promotion thresholds are implemented.
3. **Bounded residual effects: PASS.** Outcome residuals cap at 40 Elo and goal multipliers at 0.90-1.10.
4. **Independent markets with coherent SGPs: PASS.** Single markets gate independently; every SGP uses one tactical distribution or the complete baseline distribution.
5. **Fail-closed production behavior: PASS.** Missing, corrupt, stale, undersized, mismatched, or failed artifacts show fallback status and cannot activate archived fixed weights.

## Automated Evidence

- Focused Wave 1: 8 passed.
- Focused Wave 2: 10 passed.
- Focused Wave 3: 65 passed.
- Full suite: 792 passed, 5 skipped.

## Requirements

| Requirement | Source Plan | Status | Evidence |
|-------------|-------------|--------|----------|
| WCCAL-01 | 20-01 | Passed | Versioned historical row contract and deterministic split writer |
| WCCAL-02 | 20-01 | Passed | Strict pre-kickoff timestamp validation and leakage tests |
| WCCAL-03 | 20-01 | Passed | Coverage, red-card, extra-time, and missing-card gates |
| WCCAL-04 | 20-01 | Passed | Content-hashed dataset manifest and exclusion diagnostics |
| WCCAL-05 | 20-02 | Passed | Fixed-baseline L2 outcome and goal residuals |
| WCCAL-06 | 20-02 | Passed | Expanding chronological folds and fold-local standardizers |
| WCCAL-07 | 20-02 | Passed | Separate 50-match validation and sealed 30-match audit contracts |
| WCCAL-08 | 20-02 | Passed | Four controls, bootstrap intervals, and Holm correction |
| WCCAL-09 | 20-02 | Passed | Numeric sample, materiality, and uncertainty promotion gates |
| WCCAL-10 | 20-03 | Passed | Versioned schema-checked artifact with cutoff and fingerprint |
| WCCAL-11 | 20-03 | Passed | Independent single-market and whole-SGP fallback tests |
| WCCAL-12 | 20-03 | Passed | Elo/goal caps, normalization, and stage regression tests |
| WCCAL-13 | 20-03 | Passed | Scanner artifact and per-market gate status output |
| WCCAL-14 | 20-03 | Passed | 65 focused and 791 full-suite tests passed |

## Deployment Result

The real cache audit discovered 198 ESPN summaries but produced only 16 strict rows (0 development, 6 validation, 10 World Cup audit). No tactical artifact was promoted because this fails 200/50/30. Production remains baseline-only. This is the required safe result, not a validation failure.

## Live Audit

The football-data source returned no fixtures for June 21 or the June 19 retry. Scanner behavior was therefore verified through integration tests rather than invented live output.
