# Phase 1 Research: Data Hygiene

## Scope
This research is limited to Phase 1 (Data Hygiene) planning inputs only:
- DATA-01
- DATA-02
- DATA-03
- VAL-03

No Phase 2-4 implementation work is included.

## Inputs Reviewed
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `.planning/STATE.md`
- Code touchpoints:
  - `alpha/engines/sports/prop_model.py`
  - `alpha/data/ingestion/nba_stats_cache.py`
  - `scripts/validate_picks.py`
  - `scripts/sgp_scanner.py`

## Phase 1 Goal (from roadmap)
Model runs on verified current-season data with clean cache state and a recorded baseline:
- pts=49.3%
- reb=34.2%
- ast=49.3%
- 3pm=41.1%
- overall=43.5%

## Current State Findings
1. Cache reality (DATA-01 impact)
- `data/.prop_cache/` currently contains many `.pkl` files.
- `PropModel` writes per-player daily cache files to `data/.prop_cache` (`_fetch_game_logs`).
- If not cleared before baseline runs, validation can silently use stale prior-day artifacts.

2. Season defaults (DATA-02 impact)
- `PropModel.__init__` default season is already `"2025-26"`.
- `NBAStatsCache` fetch methods default to `"2025-26"`.
- `scripts/sgp_scanner.py` instantiates `PropModel()` and `NBAStatsCache()` without explicit season, so defaults are operationally critical.
- Some non-Phase-1 modules/tests still reference `"2024-25"`; this is acceptable for test fixtures but should not leak into production scanner path.

3. Baseline methodology risk (DATA-03 + VAL-03 impact)
- `scripts/validate_picks.py` currently mixes multiple modes and includes synthetic-line workflows.
- One path explicitly states synthetic projection-line usage and prints `"cached .pkl = 2024-25 season history for projections"`, which can conflict with the Phase 1 objective of current-season hygiene.
- Requirement intent for DATA-03 is pre-game-only evaluation logic correctness; this must be explicit and auditable in the validation output.

## Planning Constraints for Phase 1
- Order is mandatory: clear cache -> verify season defaults/logging -> run baseline -> record results.
- Phase 1 should not tune model math yet; only hygiene and measurement correctness.
- Validation must produce per-stat and overall numbers in a single run artifact for future comparison phases.
- Baseline should be treated as reference calibration context, not proof of betting edge (known synthetic-line limitation from STATE).

## Implementation Targets (Phase 1 Planning)
1. DATA-01: deterministic cache reset
- Add a clear, explicit pre-run cache purge step for `data/.prop_cache/*.pkl`.
- Enforce this before any baseline run path.
- Emit count of deleted files in logs so Phase success can be verified.

2. DATA-02: season default verification
- Keep `"2025-26"` as canonical default in `PropModel` and `NBAStatsCache`.
- Add startup logging in the validation/scanner path to print active season and source of season value.
- Planning check: ensure no production entrypoint overrides to older seasons unless intentional CLI argument is added.

3. DATA-03: pre-game-only validation guardrail
- Ensure validation logic uses only pre-game historical rows when producing prediction-vs-actual comparisons.
- Make mode output explicit so run logs state which validation mode is active and whether synthetic or live box-score path was used.
- Tighten baseline script output to avoid ambiguous wording that could imply post-game leakage.

4. VAL-03: baseline recording artifact
- Capture required baseline percentages in a stable run artifact under `.planning/phases/01-data-hygiene/`.
- Include timestamp, command used, and per-stat denominator counts.

## Validation Architecture
Phase 1 validation should be executed as a strict gate sequence:

1. Hygiene gate
- Verify `data/.prop_cache/` exists.
- Delete `*.pkl` files.
- Log deletion count.
- Fail gate if deletion step errors.

2. Season gate
- Initialize `NBAStatsCache` and `PropModel` through production path.
- Log effective season for both components.
- Fail gate if season is not `"2025-26"`.

3. Baseline run gate
- Execute `scripts/validate_picks.py` in a pre-defined baseline mode.
- Ensure output includes per-stat rates (`pts/reb/ast/3pm`) and overall.
- Ensure logic path documents pre-game filtering assumptions.

4. Recording gate
- Write baseline snapshot with required percentages and run metadata.
- Mark Phase 1 done only when snapshot exists and values are parsable.

Recommended pass/fail evidence for planning:
- Cache purge log line with deleted count > 0 or explicit zero-count clean state.
- Season verification log lines showing `2025-26` for both model and stats cache.
- Baseline block containing all five required metrics.
- Stored artifact path confirmed.

## Risks to Address in Phase 1 Plan
- Hidden stale cache reuse if any code path reads `.prop_cache` before purge.
- Ambiguous validation mode messaging causing baseline interpretation drift.
- Non-production test defaults (`2024-25`) being mistaken for production defaults during manual checks.

## Recommended Deliverables for Phase 1 Plan
- A small cache hygiene utility or explicit command sequence used by baseline workflow.
- A season verification check (and log) in the validation run path.
- A standardized baseline output section that can be parsed and copied into planning/state docs.
- A Phase evidence note under `.planning/phases/01-data-hygiene/` with command + metrics.

## RESEARCH COMPLETE