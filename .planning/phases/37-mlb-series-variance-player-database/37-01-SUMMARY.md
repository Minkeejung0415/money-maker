---
phase: 37
plan: "01"
status: complete
completed_at: "2026-06-28"
---

# Phase 37 Plan 01 Summary: MLB Live Inference Date and Series Variance

## Completed

- Passed `--date` from `scripts/mlb_scanner.py` into `build_live_player_features(...)` so explicit slate dates drive probable-pitcher lookup.
- Preserved StatsAPI `game_date`, `game_number`, and probable pitcher fields in `fetch_today_games(...)`.
- Made live player features prefer event-level probable starters before team-level probable-pitcher lookup.
- Added diagnostic feature context output for all individual MLB rows, including suppressed or medium-confidence rows.

## Verification

- `./venv/Scripts/python.exe -m pytest tests/unit/test_mlb_scanner.py tests/unit/test_mlb_live_player_features.py tests/unit/engines/test_mlb_artifact_gate.py`
- Covered explicit date propagation and same-matchup/different-starter feature variance.
