---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Runtime Truth and Artifact Registry
status: Complete
stopped_at: Phase 34 complete - runtime truth and artifact metadata gates delivered
last_updated: "2026-06-28T00:00:00.000-07:00"
last_activity: 2026-06-28 - v2.0 implemented and June 28 Pacific scanners run
progress:
  total_phases: 2
  completed_phases: 2
  total_plans: 2
  completed_plans: 2
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every prop line the scanner outputs must have a >55% historical hit rate; if the model cannot beat a coin flip, it is not worth betting.
**Current focus:** v2.0 - COMPLETE

## Current Position

Phase: 34 (Lightweight Artifact Registry) - COMPLETE
Status: Milestone v2.0 COMPLETE
Last activity: 2026-06-28 - Runtime truth, artifact registry, and June 28 Pacific scanner run complete

## Milestone v2.0 Summary

| Phase | Name | Status |
|-------|------|--------|
| 33 | Runtime Truth | Complete |
| 34 | Lightweight Artifact Registry | Complete |

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
