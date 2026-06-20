---
phase: 12-feature-data-pipeline
plan: 02
subsystem: data-ingestion
tags: [club-elo, fbref, soccerdata, pandas, caching]
requires:
  - phase: 12-01
    provides: isolated EPL/UCL ingestion namespace
provides:
  - Daily Club Elo ratings with stale-cache fallback
  - FBref corners, aerial-win, and pressing features
affects: [13-soccer-models, epl, ucl]
tech-stack:
  added: [soccerdata]
  patterns: [deferred optional scraper import, resilient dataframe column matching]
key-files:
  created: [alpha/data/ingestion/club_elo.py, alpha/data/ingestion/soccer_fbref.py, tests/unit/data/test_club_elo.py, tests/unit/data/test_soccer_fbref.py]
  modified: [pyproject.toml]
key-decisions:
  - "Club Elo network failures may use a cache no more than two days old."
  - "FBref ingestion defers soccerdata import and returns an empty mapping on scrape failure."
patterns-established:
  - "External soccer datasets are cached independently under data/.soccer_cache."
requirements-completed: [SDATA-04]
duration: 45min
completed: 2026-06-19
---

# Phase 12 Plan 02: Club Elo and FBref Ingestion Summary

**Daily Club Elo ratings and cached FBref set-piece features now feed EPL/UCL model development without touching WC data**

## Performance

- **Duration:** 45 min
- **Started:** 2026-06-19T22:26:08Z
- **Completed:** 2026-06-19T23:11:39Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added Club Elo CSV parsing, aliases, daily cache, and two-day stale fallback.
- Added cached FBref corners/game, aerial-win percentage, and pressing-proxy extraction.
- Added 14 focused tests; the full suite passes with 661 passed and 5 skipped.

## Task Commits

1. **Task 1: Create Club Elo loader** - `c7eb4ec`
2. **Task 2: Create FBref set-piece loader** - `c7eb4ec`

## Files Created/Modified

- `alpha/data/ingestion/club_elo.py` - Club Elo retrieval, parsing, aliases, and fallback.
- `alpha/data/ingestion/soccer_fbref.py` - FBref feature extraction and cache.
- `tests/unit/data/test_club_elo.py` - Eight network-free Club Elo tests.
- `tests/unit/data/test_soccer_fbref.py` - Six network-free FBref tests.
- `pyproject.toml` - Declares the soccerdata runtime dependency.

## Decisions Made

- Sanitize league names before using them in cache filenames.
- Support MultiIndex and flattened FBref column labels to tolerate soccerdata schema presentation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Declared missing soccerdata dependency**
- **Found during:** Task 2 discovery
- **Issue:** The plan assumed soccerdata was installed, but it was absent from the active environment and project dependencies.
- **Fix:** Added soccerdata to project dependencies and retained a deferred import with graceful failure.
- **Files modified:** `pyproject.toml`, `alpha/data/ingestion/soccer_fbref.py`
- **Verification:** pyproject parses successfully; mocked FBref tests pass.
- **Committed in:** `c7eb4ec`

**2. [Rule 3 - Blocking] Used documented fallback FBref columns**
- **Found during:** Task 2 discovery
- **Issue:** Live column discovery could not run before the missing dependency was installed.
- **Fix:** Documented and tested the plan-approved fallback paths: `Corner Kicks/CK`, `Aerial Duels/Won%`, and `Pressures/Press`.
- **Files modified:** `alpha/data/ingestion/soccer_fbref.py`, `tests/unit/data/test_soccer_fbref.py`
- **Verification:** 6/6 FBref tests pass with MultiIndex fixtures.
- **Committed in:** `c7eb4ec`

**Total deviations:** 2 blocking issues auto-fixed. **Impact:** The repository declares the live dependency and remains resilient when scraping is unavailable.

## Issues Encountered

soccerdata 1.9.0 is installed. Live discovery reached ChromeDriver setup but external downloads were blocked, so the documented fallback columns remain in use.

## User Setup Required

Install project dependencies before live FBref ingestion. No new credentials are required for FBref or Club Elo.

## Next Phase Readiness

All Phase 12 feature contracts are ready for EPL and UCL model work in Phase 13.

---
*Phase: 12-feature-data-pipeline*
*Completed: 2026-06-19*
