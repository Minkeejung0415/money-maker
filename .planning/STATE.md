# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-12)

**Core value:** Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.
**Current focus:** Phase 1 — Data Hygiene

## Current Position

Phase: 1 of 4 (Data Hygiene)
Plan: 0 of TBD in current phase
Status: Ready to plan
Last activity: 2026-03-12 — Roadmap created, phases derived from requirements

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: - min
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions

- Project: Validate via validate_picks.py not live runs (zero API cost, uses real box scores)
- Project: Fix rebounds before other stats (34.2% hit rate is 15% below random — biggest win)
- Project: Phase 1 must delete stale cache before any baseline is recorded
- Project: Synthetic line = own projection produces a meaningless baseline — real lines needed for final validation

### Pending Todos

None yet.

### Blockers/Concerns

- The 43.5% baseline is measured against synthetic lines (model's own projection), not real sportsbook lines. VAL-04 final target needs real Odds API lines to be meaningful. This is a known limitation — document when VAL-04 runs.
- Context evaluators (PropContextEvaluator) run 18 min and cut 61% of legs — not addressed in this upgrade. Separate concern.

## Session Continuity

Last session: 2026-03-12
Stopped at: Roadmap created — Phase 1 ready to plan
Resume file: None
