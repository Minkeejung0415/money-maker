---
gsd_state_version: 1.0
milestone: v2.2
milestone_name: World Cup Game Prop Probability Output
status: Complete
stopped_at: Phase 36 complete - WC game props-only output delivered
last_updated: "2026-06-28T00:00:00.000-07:00"
last_activity: 2026-06-28 - v2.2 Round of 32 game prop probabilities generated
progress:
  total_phases: 1
  completed_phases: 1
  total_plans: 1
  completed_plans: 1
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every prop line the scanner outputs must have a >55% historical hit rate; if the model cannot beat a coin flip, it is not worth betting.
**Current focus:** v2.2 - COMPLETE

## Current Position

Phase: 36 (World Cup Game Prop Probability Output) - COMPLETE
Status: Milestone v2.2 COMPLETE
Last activity: 2026-06-28 - Round of 32 props-only run complete

## Milestone v2.2 Summary

| Phase | Name | Status |
|-------|------|--------|
| 36 | Game Prop Probability Output | Complete |

## Accumulated Context

### Decisions

- No unlabelled predictions: every scanner run must expose requested model, active model, fallback status, and fallback reason.
- `elo` remains the always-available WC baseline.
- `hybrid` remains an explicit WC challenger and can be shadow-logged.
- `auto` and `player` fail closed unless an explicit `--allow-fallback` is supplied.
- Runtime artifact registry starts as simple JSON metadata, not a service.

### Pending Todos

- Add the same runtime truth flags to MLB scanner.
- Implement real WC player-aware runtime before allowing `--model player` to produce picks.
- Score shadow logs after results settle.

### Blockers/Concerns

- No promoted WC player runtime artifact exists yet.
- WC `auto` intentionally errors until a promoted artifact metadata file is available.

## Operator Next Steps

- Review June 28 Pacific pick files in `picks/`.
- Continue with MLB runtime truth parity or WC player runtime implementation.
