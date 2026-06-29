---
gsd_state_version: 1.0
milestone: v2.3
milestone_name: Automated MLB Player Data and Accuracy Upgrade
status: Complete
stopped_at: Phase 42 complete - v2.3 autonomous execution delivered
last_updated: "2026-06-28T00:00:00.000-07:00"
last_activity: 2026-06-28 - v2.3 MLB player data runtime and accuracy pipeline delivered
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
**Current focus:** v2.3 - COMPLETE

## Current Position

Phase: 42 (MLB Scanner Auto-Load Runtime) - COMPLETE
Status: Milestone v2.3 COMPLETE
Last activity: 2026-06-28 - MLB runtime no longer requires Fangraphs scraping and local player-data feature pipeline is in place

## Milestone v2.3 Summary

| Phase | Name | Status |
|-------|------|--------|
| 38 | MLB Data Source Resilience | Complete |
| 39 | Automated Player Database Updates | Complete |
| 40 | Player Feature Interpretation Layer | Complete |
| 41 | MLB Accuracy Retraining and Promotion | Complete |
| 42 | MLB Scanner Auto-Load Runtime | Complete |

## Accumulated Context

### Decisions

- No unlabelled predictions: every scanner run must expose source/fallback context where applicable.
- Runtime MLB probabilities no longer depend on live Fangraphs scraping by default.
- `pybaseball` and Fangraphs-derived data are optional enrichment behind `--allow-external-player-stats`.
- Local player database snapshots and date-specific event feature files are the runtime player-data path.
- Player stats should improve probability quality through walk-forward evidence before artifact promotion.
- Weak, stale, or missing player-data confidence suppresses betting picks while still returning research probabilities.

### Pending Todos

- Populate real daily MLB CSV/stat inputs under the local database workflow.
- Run a full historical retrain once richer local player database coverage exists.
- Re-save MLB artifacts under the current sklearn version to remove model-persistence warnings.
- Implement real WC player-aware runtime before allowing `--model player` to produce picks.
- Score WC shadow logs after results settle.

### Blockers/Concerns

- The new MLB pipeline is code-complete, but probability improvement still depends on feeding it enough real historical/local player rows for a full retrain.
- Existing promoted MLB artifact loads with sklearn version mismatch warnings; scanner still runs, but artifact maintenance is needed.
- No real sportsbook MLB odds feed is connected, so edge/EV output still requires manual odds overrides.

## Operator Next Steps

- Add or download real MLB player CSVs into the local database pipeline.
- Run `scripts/update_mlb_player_database.py`, then `scripts/build_mlb_player_features.py`, then `scripts/mlb_scanner.py --date YYYY-MM-DD --individual-only`.
