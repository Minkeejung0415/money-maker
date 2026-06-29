---
phase: 37
plan: "03"
status: complete
completed_at: "2026-06-28"
---

# Phase 37 Plan 03 Summary: Database-Fed MLB Live Features and Suppression

## Completed

- Added optional event-id keyed database feature merging to `build_live_player_features(...)`.
- Added scanner `--player-features-file` JSON hook for local player database features.
- Added feature-source, source-confidence, stale-flag, and last-updated context support.
- Extended player-aware uncertainty flags for stale player data and low lineup confidence.
- Kept default scanner behavior functional when no local player database file exists.

## Verification

- `./venv/Scripts/python.exe -m pytest tests/unit/test_mlb_live_player_features.py tests/unit/test_mlb_scanner.py tests/unit/test_mlb_player_database.py tests/unit/engines/test_mlb_artifact_gate.py tests/unit/engines/test_mlb_player_features.py`
- `./venv/Scripts/python.exe ./scripts/mlb_scanner.py --date 2026-06-28 --validate --individual-only`
- Smoke run produced 15 June 28 MLB individual probabilities and printed feature context for each game.
