---
plan: 05-03
phase: 05-data-foundation
status: complete
requirements_addressed:
  - INGEST-02
  - INGEST-03
commits:
  - 8bc185c  # feat(05-03): build_wc_priors.py
  - 8530998  # fix(05-03): Korea Republic slug + Unicode
---

# Plan 05-03 Summary: WC Data Build Script

## What Was Built

`scripts/build_wc_priors.py` — one-time offline data builder for the WC pipeline.

### Script structure
- `_fetch_team_elo(team_name)` — fetches eloratings.net TSV, column index 10, with 0.1s sleep and fallback=1500 on failure
- `_fetch_elo_ratings(teams)` — iterates 48 WC teams with progress printing
- `_fetch_statsbomb_stats()` — fetches StatsBomb 2018+2022 WC matches (competition_id=43, season_id=3 + 106), aggregates shots/xG/goals/defense per team
- `build_wc_priors()` — orchestrates both, writes both output files

### statsbombpy 1.19.0 installed

## Checkpoint Verification (Approved)

**wc_priors.json:**
- 48 teams ✓
- All values in range 1000-2200 ✓
- No invalid values ✓
- Korea Republic: 1500 (fallback — slug fixed for re-runs via `_ELO_SLUG_OVERRIDES`)

**wc_stats.pkl:**
- 40 teams (2018+2022 WC participants) ✓
- All entries have `{avg_goals, avg_xG, avg_shots, defense_score}` ✓
- No bad shape entries ✓
- built_at: 2026-06-18T21:35:09

## Team Name Mapping Discovered

StatsBomb uses "South Korea" — football-data.org uses "Korea Republic".
Added `"South Korea": "Korea Republic"` to `_TEAM_NAME_MAP` in `wc_stats.py`.

## Sample Output

| Team | avg_goals | avg_xG | avg_shots | defense_score |
|------|-----------|--------|-----------|---------------|
| Brazil | 1.8 | 2.595 | 20.2 | 0.751 |
| Belgium | 1.6 | 1.642 | 14.3 | 1.357 |

defense_score = xG conceded per game (lower = better defense).
