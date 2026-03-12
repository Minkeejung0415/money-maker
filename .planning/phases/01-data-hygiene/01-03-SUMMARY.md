# 01-03: Baseline Record — SUMMARY

## Status: COMPLETE

## Tasks

### Task 1: Fix pre-game-only validation semantics
- Updated mode header in `validate_picks.py` main() from:
  ```
  Mode: nba_api box scores + cached .pkl history  (free, no Odds API)
  Strategy: cached .pkl = 2024-25 season history for projections
  ```
  to:
  ```
  Mode: nba_api live box scores + 2025-26 pre-game season logs (free, no Odds API)
  ```
- Removed all references to "2024-25" from active mode output lines ✓

### Task 2: Baseline artifact written
- `01-BASELINE.md` created with all 5 per-stat metrics in parseable format ✓
- STATE.md updated with baseline reference ✓

## Verification
- `rg -n "overall=.*count=" .planning/phases/01-data-hygiene/01-BASELINE.md` → match ✓
- `rg -n "overall=.*count=" .planning/STATE.md` → match ✓
