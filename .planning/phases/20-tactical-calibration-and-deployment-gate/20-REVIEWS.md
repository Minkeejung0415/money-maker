---
phase: 20
reviewers: [codex]
reviewed_at: 2026-06-22T00:51:27Z
plans_reviewed: [20-01-PLAN.md, 20-02-PLAN.md, 20-03-PLAN.md]
---

# Cross-AI Plan Review - Phase 20

## Cycle 1 - Codex Review

### Summary

The phase has the right philosophy but four execution gaps could block completion or allow misleading tactical probabilities.

### Strengths

- Uses chronological validation and keeps the current World Cup sample out of training.
- Models tactical effects as residual influence rather than replacing the baseline.
- Defaults to the no-tactics model when evidence is insufficient.
- Plans versioned artifacts and explicit market gates.

### HIGH Concerns

1. ESPN historical summary coverage was not proven before requiring 200 development rows.
2. Requiring 50 completed 2026 World Cup holdout rows was impossible as of June 21, when only 35 were available, and the holdout manifest was not sealed precisely.
3. Independently gated totals and BTTS could cause SGP legs to use marginals from different scoreline distributions.
4. Promotion statistics lacked numeric confidence levels, bootstrap repetitions, multiplicity handling, materiality thresholds, and a requirement to beat baseline-only recalibration.

### MEDIUM Concerns

- Historical baseline reconstruction did not explicitly require as-of Elo and goal-rate provenance.
- Red-card and score-state handling was named but not operationalized.

### Required Revisions

- Add a source-coverage preflight that can block modeling without weakening gates.
- Separate a minimum 50-match pre-tournament chronological validation set from a frozen minimum 30-match 2026 World Cup external audit.
- Require every SGP combination to use exactly one coherent distribution; mixed gate states fall back for the whole combination.
- Specify deterministic 10,000-replicate paired bootstrap tests, 95% intervals, Holm correction across markets, minimum metric deltas, and comparison with both no-tactics and baseline-only recalibration.
- Persist as-of baseline features and exclude red-card source matches when card status is known; missing card status is a documented coverage failure.

CYCLE_SUMMARY: current_high=4

## Current HIGH Concerns

- Historical ESPN data attainability is not proven.
- The World Cup holdout definition is infeasible and under-specified.
- Mixed market gates can break coherent SGP probabilities.
- Promotion statistics are under-specified.

---

## Cycle 2 - Claude Review

### Prior HIGH Resolution

- **ESPN coverage: RESOLVED.** The coverage preflight makes attainability an explicit fail-closed gate before fitting.
- **Holdout definition: RESOLVED.** The plan now separates 50 pre-tournament validation matches from a sealed 30+ match 2026 World Cup external audit with explicit IDs, hashes, and immutable versions.
- **SGP coherence: RESOLVED.** Every SGP uses one complete tactical or baseline scoreline distribution; mixed marginals are forbidden.
- **Promotion statistics: RESOLVED.** The plan locks 10,000 paired bootstrap replicates, two-sided 95% intervals, Holm correction, 0.002 Brier/log-loss materiality, and comparisons against both controls.

### New HIGH Concerns

None. The stringent promotion rule may produce no promoted market, but that is an intended fail-safe outcome rather than a phase failure.

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns

None.
