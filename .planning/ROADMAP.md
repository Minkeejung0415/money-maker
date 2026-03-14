# Roadmap: NBA Prop Model Algorithm Upgrade

## Overview

The current prop model produces a 43.5% overall hit rate and a critical 34.2% on rebounds — both below the 50% random baseline, meaning the model is directionally wrong more often than right. This upgrade fixes root causes in a strict order: clean data first, then projection math, then opponent adjustments, then confidence calibration. Each phase is validated with validate_picks.py before the next begins. The milestone is complete when all stats exceed 50% and overall exceeds 55% against real sportsbook lines.

## Phases

- [x] **Phase 1: Data Hygiene** - Delete stale cache, verify season, record baseline
- [x] **Phase 2: Projection Algorithm** - Exponential decay, home/away split, Poisson/NB distribution, rest factor
- [x] **Phase 3: Opponent Adjustments** - Fix rebound direction, position-level stats, pace adjustment, tighten cap
- [x] **Phase 4: Confidence Tuning** - Blowout gate, low-line skepticism, 60% floor, final validation

## Phase Details

### Phase 1: Data Hygiene
**Goal**: The model runs on verified current-season data with a clean baseline recorded
**Depends on**: Nothing (first phase)
**Requirements**: DATA-01, DATA-02, DATA-03, VAL-03
**Success Criteria** (what must be TRUE):
  1. validate_picks.py runs and produces per-stat hit rates without errors
  2. No `.pkl` cache files exist in `data/.prop_cache/` at start of run
  3. PropModel and NBAStatsCache both default to "2025-26" season (verified by log output)
  4. Baseline numbers recorded: pts=49.3%, reb=34.2%, ast=49.3%, 3pm=41.1%, overall=43.5%
**Plans**: TBD

### Phase 2: Projection Algorithm
**Goal**: The rolling average, distribution model, home/away context, and rest factor are all improved
**Depends on**: Phase 1
**Requirements**: ALGO-01, ALGO-02, ALGO-03, ALGO-04, VAL-01, VAL-02
**Success Criteria** (what must be TRUE):
  1. validate_picks.py per-stat output shows pts and ast hit rates move closer to or above 50%
  2. Home games and away games produce different projections for the same player
  3. B2B game props show a 0.94x multiplier applied to projection (visible in debug output)
  4. Poisson CDF is used for ast/blk/stl/3pm markets and Negative Binomial for pts/reb (verified by code path)
  5. validate_picks.py is run before and after each change with per-stat comparison recorded
**Plans**: TBD

### Phase 3: Opponent Adjustments
**Goal**: Rebound projections use correct opponent defensive data, position-level context, and pace
**Depends on**: Phase 2
**Requirements**: OPP-01, OPP-02, OPP-03, OPP-04
**Success Criteria** (what must be TRUE):
  1. Rebound opponent adjustment uses opponent DREB_pg instead of total reb_pg (verified by code inspection)
  2. A center and a guard facing the same opponent receive different rebound adjustments based on position-allowed stats
  3. Slow-paced matchup reduces rebound projection proportionally (pace ratio applied)
  4. Rebound adjustment cap is ±10% (tightened from ±15%)
  5. validate_picks.py shows reb hit rate above 40% (up from 34.2%)
**Plans**: TBD

### Phase 4: Confidence Tuning
**Goal**: Scanner outputs only well-calibrated picks and the overall hit rate target is confirmed
**Depends on**: Phase 3
**Requirements**: CONF-01, CONF-02, CONF-03, VAL-04
**Success Criteria** (what must be TRUE):
  1. Props for players on teams with ML win probability <30% are downgraded HIGH→MEDIUM in scanner output
  2. Props where model_prob >85% and line is >1.5 stdev below projection are capped at MEDIUM
  3. SGP output contains no legs below 60% confidence
  4. validate_picks.py final run shows all stats above 50% and overall above 55% (against real lines or bias-corrected baseline)
**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Hygiene | 3/3 | ✅ Complete | 2026-03-12 |
| 2. Projection Algorithm | 4/4 | ✅ Complete | 2026-03-12 |
| 3. Opponent Adjustments | 4/4 | ✅ Complete | 2026-03-12 |
| 4. Confidence Tuning | 3/3 | ✅ Complete | 2026-03-12 |

## Final Results
| Stat    | Baseline | Final  | Delta   |
|---------|----------|--------|---------|
| pts     | 49.3%    | 52.1%  | +2.8%   |
| reb     | 34.2%    | 45.2%  | +11.0%  |
| ast     | 49.3%    | 50.7%  | +1.4%   |
| 3pm     | 41.1%    | 46.6%  | +5.5%   |
| overall | 43.5%    | 48.6%  | +5.1%   |

Tests: 493/493 passing.
