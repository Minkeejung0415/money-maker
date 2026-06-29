---
phase: 37
status: passed
verified_at: "2026-06-28"
---

# Phase 37 Verification: MLB Series Variance and Player Database

## Automated Checks

- Passed: `./venv/Scripts/python.exe -m pytest tests/unit/test_mlb_scanner.py tests/unit/test_mlb_live_player_features.py tests/unit/test_mlb_player_database.py tests/unit/engines/test_mlb_artifact_gate.py tests/unit/engines/test_mlb_player_features.py`
- Passed: `git diff --check -- scripts/mlb_scanner.py alpha/data/ingestion/mlb_stats.py alpha/data/ingestion/mlb_live_player_features.py alpha/data/ingestion/mlb_player_database.py alpha/engines/sports/mlb_model.py tests/unit/test_mlb_scanner.py tests/unit/test_mlb_live_player_features.py tests/unit/test_mlb_player_database.py tests/unit/engines/test_mlb_artifact_gate.py`
- Passed with external-source warnings: `./venv/Scripts/python.exe ./scripts/mlb_scanner.py --date 2026-06-28 --validate --individual-only`

## Must-Haves Verified

- Explicit MLB scanner dates now control both schedule fetch and live player-feature lookup.
- Same-matchup games can diverge when event-level starters differ.
- Local MLB player-stat rows can be normalized and summarized from raw components without network access.
- Database-fed event features can merge into live scanner features.
- Stale or low-confidence player data suppresses pick eligibility while still returning research probabilities.
- Individual MLB scanner output prints feature context for diagnosis.

## Notes

- The June 28 smoke run hit Fangraphs 403 warnings for live stats, so scanner output used fallback context. This is expected and visible through `player_data_source`.
- Top-level roadmap/state files did not currently reference Phase 37, so this verification records completion in the phase directory without inventing broader milestone state.
