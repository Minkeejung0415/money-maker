---
gsd_state_version: 1.0
milestone: v2.3
milestone_name: Automated MLB Player Data and Accuracy Upgrade
status: planning
stopped_at: Milestone v2.3 started - requirements and roadmap defined
last_updated: "2026-06-28T00:00:00.000-07:00"
last_activity: 2026-06-28 - v2.3 milestone initialized
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
**Current focus:** v2.3 - Automated MLB Player Data and Accuracy Upgrade

## Current Position

Phase: 38 (MLB Data Source Resilience) - Not started
Plan: -
Status: Ready to discuss Phase 38
Last activity: 2026-06-28 - Milestone v2.3 started

## Milestone v2.3 Summary

| Phase | Name | Status |
|-------|------|--------|
| 38 | MLB Data Source Resilience | Pending |
| 39 | Automated Player Database Updates | Pending |
| 40 | Player Feature Interpretation Layer | Pending |
| 41 | MLB Accuracy Retraining and Promotion | Pending |
| 42 | MLB Scanner Auto-Load Runtime | Pending |

## Accumulated Context

### Decisions

- No unlabelled predictions: every scanner run must expose requested/active model and fallback status where applicable.
- Runtime MLB probabilities should not depend on live Fangraphs scraping.
- `pybaseball` and Fangraphs-derived data can be optional enrichment, but local/official data must keep the scanner usable.
- Player stats must improve probability quality through walk-forward evidence before a richer artifact is promoted.
- Weak, stale, or missing player-data confidence should suppress betting picks while still returning research probabilities.

### Pending Todos

- Add the same runtime truth flags to MLB scanner.
- Implement real WC player-aware runtime before allowing `--model player` to produce picks.
- Score WC shadow logs after results settle.
- Build automated MLB player database updates.
- Retrain/promote richer MLB player-aware model only if metrics beat baseline.

### Blockers/Concerns

- Fangraphs live scraping can return 403 and should not be required for runtime.
- Current Phase 37 local player database is a foundation, not a fully automated daily update pipeline.
- Current promoted MLB artifact may not fully consume richer lineup/bullpen/absence features until retrained.

## Operator Next Steps

- Run `$gsd-discuss-phase 38` to plan MLB data source resilience.
- Run `$gsd-plan-phase 38` if discussion context is already sufficient.
