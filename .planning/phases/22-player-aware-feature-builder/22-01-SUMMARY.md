---
phase: 22-player-aware-feature-builder
plan: "01"
status: complete
completed: 2026-06-24
subsystem: mlb-player-features
tags:
  - mlb
  - features
  - leakage-safe
key-files:
  - alpha/engines/sports/mlb_player_features.py
  - tests/unit/engines/test_mlb_player_features.py
metrics:
  focused_tests: "15 passed"
---

# Phase 22 Plan 01 Summary

Implemented the additive MLB player-aware feature builder for v1.8.

## Completed Tasks

- Added `alpha/engines/sports/mlb_player_features.py`.
- Added `build_player_aware_game_rows(...)` returning one pregame modeling row per game.
- Added shifted starter quality/workload/rest features with missing flags.
- Added lineup strength, top-order strength, lefty-share, missing-count, and confirmation-share features.
- Added shifted bullpen recent-pitch workload and bullpen quality features.
- Added structured absence value/count features from game/team absence rows.
- Added explicit `allow_between_games` handling for same-day doubleheaders.
- Added deterministic unit tests proving target-game exclusion and default no-leak doubleheader behavior.

## Verification

- `.venv\Scripts\python.exe -m pytest tests/unit/engines/test_mlb_player_features.py tests/unit/test_mlb_player_data.py tests/unit/engines/test_mlb_training.py -q --tb=short --basetemp=.tmp-tests\pytest-phase22`  
  Result: 15 passed.
- `git diff --check -- alpha/engines/sports/mlb_player_features.py tests/unit/engines/test_mlb_player_features.py`  
  Result: passed.

## Deviations

None.

## Self-Check

PASSED - Phase 22 requirements MLBFEAT-01 through MLBFEAT-05 are implemented and covered by focused tests.
