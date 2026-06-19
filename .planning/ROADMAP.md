# Roadmap: Alpha Terminal — Multi-Milestone

## Previous Milestone: v1.0 — NBA Prop Model Algorithm Upgrade (Complete)

## Phases (v1.0 — Complete)

- [x] **Phase 1: Data Hygiene** - Delete stale cache, verify season, record baseline
- [x] **Phase 2: Projection Algorithm** - Exponential decay, home/away split, Poisson/NB distribution, rest factor
- [x] **Phase 3: Opponent Adjustments** - Fix rebound direction, position-level stats, pace adjustment, tighten cap
- [x] **Phase 4: Confidence Tuning** - Blowout gate, low-line skepticism, 60% floor, final validation

## Phase Details (v1.0 — Complete)

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

---

## Current Milestone: v1.1 — World Cup Soccer Mode

## Phases (v1.1)

- [x] **Phase 5: Data Foundation** - WC fixture ingestion, Elo ratings, and StatsBomb historical data layer (completed 2026-06-19)
- [x] **Phase 6: Match Model** - Elo-logistic W/D/L model with neutral-venue correction, stage metadata, knockout gate, and market divergence flag (completed 2026-06-19)
- [ ] **Phase 7: SGP Builder + Scanner Integration** - WC SGP builder with stage-aware correlation, scanner routing, and full test coverage

## Phase Details (v1.1)

### Phase 5: Data Foundation
**Goal**: WC 2026 fixtures, national team Elo ratings, and StatsBomb historical event data are all accessible to downstream model and builder code
**Depends on**: Nothing (first phase of v1.1 milestone)
**Requirements**: INGEST-01, INGEST-02, INGEST-03
**Success Criteria** (what must be TRUE):
  1. Calling `fetch_wc_games(date_from, date_to, stage)` returns a list of WC fixtures including `stage` and `group` fields for both group stage and knockout round games
  2. Elo ratings for all 48 WC 2026 nations load from `data/wc_priors.json` without a network call (cached from Kaggle CSV)
  3. StatsBomb 2018 + 2022 WC event data is accessible via `wc_stats.py` returning national-team attack/defense rates and player career per-90 stats, cached to `data/.wc_cache/`
  4. All three data sources are isolated from the EPL/UCL pipeline — no shared cache namespace, no calls to `soccer_stats.py` or `get_team_rolling_stats_all()`
**Plans**: 3 plans
Plans:
- [x] 05-01-PLAN.md — FootballDataClient WC extension: _COMP_MAP update, _get_with_retry(), fetch_wc_games() with stage/group fields, tests
- [x] 05-02-PLAN.md — WC reader modules: wc_elo.py (Elo JSON loader) + wc_stats.py (StatsBomb pkl loader), tests
- [x] 05-03-PLAN.md — build_wc_priors.py one-time script: eloratings.net Elo download + StatsBomb 2018/2022 event aggregation, produces wc_priors.json + wc_stats.pkl

### Phase 6: Match Model
**Goal**: WC match predictions output calibrated Win/Draw/Loss probabilities (or Win-to-Advance in knockouts) using Elo-logistic logic, with stage-aware behavior and a market divergence flag — and are never routed through SoccerModel
**Depends on**: Phase 5
**Requirements**: MODEL-01, MODEL-02, MODEL-03, MODEL-04
**Success Criteria** (what must be TRUE):
  1. `wc_model.py` produces W/D/L probabilities for a group stage match using the Elo-logistic formula with neutral-venue correction applied (no +100 home-field boost)
  2. For a knockout round game, `wc_model.py` outputs Win-to-Advance probability only — Draw probability is suppressed entirely
  3. Each game dict returned by the WC pipeline contains a `stage` field with one of `GROUP_STAGE`, `LAST_16`, `QUARTER_FINALS`, `SEMI_FINALS`, or `FINAL` extracted from football-data.org fixture response
  4. Picks where the Elo model win probability diverges from sportsbook implied odds by more than 5 percentage points carry `"elo_edge": true` in the output dict
  5. Passing a WC game dict to `SoccerModel` raises an error or is explicitly blocked — WC games never silently enter the EPL/UCL code path
**Plans**: 1 plan
Plans:
- [x] 06-01-PLAN.md — WCMatchModel: Elo-logistic predict(), knockout gate, elo_edge flag, evaluate_bet(), full TDD test suite

### Phase 7: SGP Builder + Scanner Integration
**Goal**: Users can run `python scripts/wc_scanner.py --mode parlay` and receive ranked WC match picks with Elo confidence, EV vs. market odds, divergence flag annotation, and valid multi-leg SGP combos — with all new components covered by tests and zero regressions against existing suite
**Depends on**: Phase 6
**Requirements**: SGP-01, SGP-02, SCAN-01, SCAN-02, TEST-01
**Success Criteria** (what must be TRUE):
  1. `wc_scanner.py --mode parlay --stage group` outputs ranked WC match picks showing Elo confidence, implied EV vs. market odds, and `*ELO EDGE*` annotation where model diverges from market by more than 5 percentage points
  2. `wc_scanner.py --mode parlay --stage knockout` produces SGP combos that contain zero Draw legs and zero standard moneyline legs for elimination-round games
  3. `wc_scanner.py --league wc` routes exclusively through the WC data pipeline, WC match model, and WC SGP builder — no EPL/UCL code paths are invoked
  4. All new WC components (`wc_model.py`, `wc_sgp_builder.py`, `wc_stats.py`, WC routes in `soccer_scanner.py` or `wc_scanner.py`) have unit tests, and the total test count meets or exceeds 535 with zero regressions
**Plans**: TBD
**UI hint**: no

## Progress (v1.0)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Hygiene | 3/3 | Complete | 2026-03-12 |
| 2. Projection Algorithm | 4/4 | Complete | 2026-03-12 |
| 3. Opponent Adjustments | 4/4 | Complete | 2026-03-12 |
| 4. Confidence Tuning | 3/3 | Complete | 2026-03-12 |

## Progress (v1.1)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 5. Data Foundation | 3/3 | Complete   | 2026-06-19 |
| 6. Match Model | 1/1 | Complete    | 2026-06-19 |
| 7. SGP Builder + Scanner Integration | 0/5 | Not started | - |

## v1.0 Final Results
| Stat    | Baseline | Final  | Delta   |
|---------|----------|--------|---------|
| pts     | 49.3%    | 52.1%  | +2.8%   |
| reb     | 34.2%    | 45.2%  | +11.0%  |
| ast     | 49.3%    | 50.7%  | +1.4%   |
| 3pm     | 41.1%    | 46.6%  | +5.5%   |
| overall | 43.5%    | 48.6%  | +5.1%   |

Tests: 493/493 passing.
