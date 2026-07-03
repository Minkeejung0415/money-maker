---
gsd_state_version: 1.0
milestone: v2.4
milestone_name: WC Hybrid Route Offset
status: Complete
last_updated: "2026-07-03T20:50:19.953Z"
last_activity: 2026-07-03 - v2.4 route-offset phases 43-47 delivered
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 5
  completed_plans: 5
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every prop line the scanner outputs must have a >55% historical hit rate; if the model cannot beat a coin flip, it is not worth betting.
**Current focus:** v2.4 - COMPLETE

## Current Position

Phase: 47 (Paired Validation and Promotion Gates) - COMPLETE
Plan: Complete
Status: Milestone v2.4 COMPLETE
Last activity: 2026-07-03 - route-offset runtime, scanner diagnostics, and paired validation delivered

## Milestone v2.4 Summary

| Phase | Name | Status |
|-------|------|--------|
| 43 | Route Offset Contracts and Baseline Harness | Complete |
| 44 | Role Strength Snapshot and Projected XI Inputs | Complete |
| 45 | Tactical Duel Engine and Capped Route Deltas | Complete |
| 46 | Route xG Integration and Shadow Scanner Output | Complete |
| 47 | Paired Validation and Promotion Gates | Complete |

## Accumulated Context

### Decisions

- Keep the current WC hybrid model as the production prior.
- Model projected-XI player data and tactical matchups as route-level xG offsets, not raw WDL inputs.
- Run route-offset behavior in shadow mode before it can affect picks.
- Require paired validation against the hybrid baseline on identical fixtures.
- Fail closed to hybrid baseline on missing, stale, or schema-mismatched route-offset inputs.
- Preserve MLB retrain package sequencing separately; do not mix MLB feature-semantics changes into this milestone.

### Pending Todos

- Gather real projected-XI route-offset snapshots in `data/wc_route_offsets.json` before relying on slate diagnostics.
- Score route-offset shadow logs with `scripts/validate_wc_route_offsets.py` after results settle.
- Keep `--route-offset-mode promoted` disabled for production until paired validation passes on enough real rows.
- Populate real daily MLB CSV/stat inputs under the local database workflow.
- Run a full historical MLB retrain once richer local player database coverage exists.
- Ship the MLB retrain package as one unit (see docs/ACCURACY-AUDIT-2026-07.md, "Deferred: MLB retrain package").
- Re-save MLB artifacts under the current sklearn version to remove model-persistence warnings.

### Blockers/Concerns

- WC route-offset quality depends on projected-XI coverage and trustworthy role-strength inputs.
- Route offsets can double count team quality already present in Elo/xG/FIFA/SUM priors; caps and shrinkage are implemented but still need real shadow scoring.
- Promotion remains operationally blocked until paired validation passes on real graded route-offset rows.
- MLB artifact sklearn warnings remain outside this milestone.

## Operator Next Steps

- Add real projected-XI snapshots to `data/wc_route_offsets.json`.
- Run WC scanner in default shadow mode and retain diagnostics.
- After results settle, validate paired rows with `scripts/validate_wc_route_offsets.py`.
