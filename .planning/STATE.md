---
gsd_state_version: 1.0
milestone: v2.4
milestone_name: WC Hybrid Route Offset
status: planning
last_updated: "2026-07-03T20:50:19.953Z"
last_activity: 2026-07-03 - v2.4 requirements and roadmap drafted
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every prop line the scanner outputs must have a >55% historical hit rate; if the model cannot beat a coin flip, it is not worth betting.
**Current focus:** v2.4 - WC Hybrid Route Offset

## Current Position

Phase: 43 (Route Offset Contracts and Baseline Harness) - planned
Plan: Not started
Status: Requirements and roadmap drafted; awaiting operator approval before implementation
Last activity: 2026-07-03 - v2.4 milestone started from the WC route-offset brief

## Milestone v2.4 Summary

| Phase | Name | Status |
|-------|------|--------|
| 43 | Route Offset Contracts and Baseline Harness | Planned |
| 44 | Role Strength Snapshot and Projected XI Inputs | Planned |
| 45 | Tactical Duel Engine and Capped Route Deltas | Planned |
| 46 | Route xG Integration and Shadow Scanner Output | Planned |
| 47 | Paired Validation and Promotion Gates | Planned |

## Accumulated Context

### Decisions

- Keep the current WC hybrid model as the production prior.
- Model projected-XI player data and tactical matchups as route-level xG offsets, not raw WDL inputs.
- Run route-offset behavior in shadow mode before it can affect picks.
- Require paired validation against the hybrid baseline on identical fixtures.
- Fail closed to hybrid baseline on missing, stale, or schema-mismatched route-offset inputs.
- Preserve MLB retrain package sequencing separately; do not mix MLB feature-semantics changes into this milestone.

### Pending Todos

- Create Phase 43 plan after operator approval.
- Implement route-offset runtime contract and baseline harness.
- Build projected-XI role-strength snapshot support.
- Implement capped tactical duel rules.
- Integrate route-level xG deltas into scoreline-derived markets.
- Validate route-offset shadow logs against the hybrid baseline before promotion.
- Populate real daily MLB CSV/stat inputs under the local database workflow.
- Run a full historical MLB retrain once richer local player database coverage exists.
- Ship the MLB retrain package as one unit (see docs/ACCURACY-AUDIT-2026-07.md, "Deferred: MLB retrain package").
- Re-save MLB artifacts under the current sklearn version to remove model-persistence warnings.

### Blockers/Concerns

- WC route-offset quality depends on projected-XI coverage and trustworthy role-strength inputs.
- Route offsets can double count team quality already present in Elo/xG/FIFA/SUM priors unless caps and shrinkage are strict.
- Promotion should remain blocked until paired validation shows no probability-quality regression.
- MLB artifact sklearn warnings remain outside this milestone.

## Operator Next Steps

- Review .planning/REQUIREMENTS.md and .planning/ROADMAP.md.
- Approve Phase 43 planning/execution when ready.
- Continue grading WC shadow output as results settle.
