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

## Previous Milestone: v1.1 — World Cup Soccer Mode (Complete)

## Phases (v1.1 — Complete)

- [x] **Phase 5: Data Foundation** - WC fixture ingestion, Elo ratings, and StatsBomb historical data layer (completed 2026-06-19)
- [x] **Phase 6: Match Model** - Elo-logistic W/D/L model with neutral-venue correction, stage metadata, knockout gate, and market divergence flag (completed 2026-06-19)
- [x] **Phase 7: SGP Builder + Scanner Integration** - WC SGP builder with stage-aware correlation, scanner routing, and full test coverage (completed 2026-06-19)

## Phase Details (v1.1 — Complete)

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
**Plans**: 2 plans
Plans:
- [x] 07-01-PLAN.md — WCSGPBuilder: stage-aware correlation gate, SGP combo assembly, scanner routing
- [x] 07-02-PLAN.md — wc_scanner.py entry point, full test suite, regression validation
**UI hint**: no

---

## Current Milestone: v1.2 — Draw Algorithm

## Phases (v1.2)

- [x] **Phase 8: Dynamic Draw Algorithm** - Replace flat draw constant with Elo-calibrated draw probability function in wc_model.py, with full test coverage (completed 2026-06-19)

## Phase Details (v1.2)

### Phase 8: Dynamic Draw Algorithm
**Goal**: Group-stage draw probability in wc_model.py reflects actual match balance — evenly-matched teams draw more often than mismatches — calibrated to historical WC data, with knockout behavior unchanged and full parameterized test coverage
**Depends on**: Phase 7
**Requirements**: DRAW-01, DRAW-02, DRAW-03, TEST-01
**Success Criteria** (what must be TRUE):
  1. Calling `wc_model.predict()` on a group-stage match with Elo difference near 0 returns a draw probability at or near 30%
  2. Calling `wc_model.predict()` on a group-stage match with Elo difference near 500 returns a draw probability at or near 8%
  3. Calling `wc_model.predict()` on any knockout round match returns draw probability exactly 0.0 regardless of Elo difference
  4. Parameterized tests pass at Elo difference values of 0, 100, 300, 500, and 750 — all 619 existing tests continue to pass with zero regressions
**Plans**: 1 plan
Plans:
- [x] 08-01-PLAN.md — _draw_prob() exponential decay function: replace flat constant, update tests

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
| 7. SGP Builder + Scanner Integration | 2/2 | Complete    | 2026-06-19 |

## Progress (v1.2)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 8. Dynamic Draw Algorithm | 1/1 | Complete | 2026-06-19 |

## v1.0 Final Results
| Stat    | Baseline | Final  | Delta   |
|---------|----------|--------|---------|
| pts     | 49.3%    | 52.1%  | +2.8%   |
| reb     | 34.2%    | 45.2%  | +11.0%  |
| ast     | 49.3%    | 50.7%  | +1.4%   |
| 3pm     | 41.1%    | 46.6%  | +5.5%   |
| overall | 43.5%    | 48.6%  | +5.1%   |

Tests: 493/493 passing.
---

## Previous Milestone: v1.3 — MLB Win Probability Model (Complete)

## Phases (v1.3)

- [x] **Phase 9: Historical Data and Feature Contract** - Build leakage-safe historical game rows and one shared pregame feature schema
- [x] **Phase 10: Training, Calibration, and Validation** - Train candidates, calibrate probabilities, benchmark chronologically, and persist validated artifacts
- [x] **Phase 11: Runtime and Scanner Integration** - Load validated artifacts and show daily percentages, fair odds, and optional manual market comparison

## Phase Details (v1.3)

### Phase 9: Historical Data and Feature Contract
**Goal**: Historical completed games can be transformed into deterministic pregame feature rows without future information.
**Requirements**: MLBD-01, MLBD-02, MLBD-03, MLBV-01
**Success Criteria**:
1. Dataset rows contain canonical teams, date, binary home-win target, and only shifted/rolling pregame features.
2. Chronology tests prove target-game results cannot influence features.
3. Trainer and runtime call the same feature schema helper.
**Plans**: 1 plan

### Phase 10: Training, Calibration, and Validation
**Goal**: A calibrated model is selected on untouched future games and saved with auditable metadata.
**Requirements**: MLBM-01, MLBM-02, MLBM-03, MLBM-04, MLBV-01
**Success Criteria**:
1. Logistic and boosted candidates are evaluated with chronological train/calibration/test windows.
2. Report includes Brier score, log loss, accuracy, reliability buckets, and baseline comparisons.
3. Saved artifact includes exact feature schema and validation metadata.
**Plans**: 1 plan

### Phase 11: Runtime and Scanner Integration
**Goal**: Today's MLB slate displays validated independent win percentages and fair odds, never misleading fallback output.
**Requirements**: MLBR-01, MLBR-02, MLBR-03, MLBR-04, MLBV-01, MLBV-02
**Success Criteria**:
1. MLBModel rejects incompatible or unvalidated artifacts.
2. Scanner prints every game's home/away probabilities, fair odds, and source.
3. Manual odds enable no-vig edge comparison; absent odds are labeled unavailable.
4. Full test suite passes.
**Plans**: 1 plan

## Progress (v1.3)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 9. Historical Data and Feature Contract | 1/1 | Complete | 2026-06-19 |
| 10. Training, Calibration, and Validation | 1/1 | Complete | 2026-06-19 |
| 11. Runtime and Scanner Integration | 1/1 | Complete | 2026-06-19 |

---

## Current Milestone: v1.4 — Soccer Mode Upgrade

## Phases (v1.4)

- [x] **Phase 12: Soccer Feature Data Pipeline** - Form (last 5), H2H (last 5), days-rest ingestion from football-data.org + FBref set pieces + Club Elo ratings (completed 2026-06-19)
- [x] **Phase 13: Soccer Model Upgrade** - Retrain EPL XGBoost with expanded feature schema + UCL Elo-logistic model (UCLEloModel) (completed 2026-06-20)
- [x] **Phase 14: Draw Betting + Scanner Integration** - Enable draw legs in SGP builder when model EV > 5%, update scanner routing, full test coverage (completed 2026-06-21)

## Phase Details (v1.4)

### Phase 12: Soccer Feature Data Pipeline
**Goal**: Form, H2H, days-rest, FBref set piece stats, and Club Elo ratings are all accessible to downstream EPL/UCL model code
**Depends on**: Nothing (first phase of v1.4)
**Requirements**: SDATA-01, SDATA-02, SDATA-03, SDATA-04
**Success Criteria** (what must be TRUE):
  1. `fetch_team_form(team_id, n=5)` returns last-5-game W/D/L record + goals scored/conceded from football-data.org
  2. `fetch_h2h(home_id, away_id, n=5)` returns last 5 meetings between the two teams
  3. `fetch_days_rest(team_id, match_date)` returns integer days since last game (for fatigue multiplier)
  4. FBref set piece stats (corners/game, aerial duels %, PPDA) accessible via soccerdata for EPL teams
  5. Club Elo ratings for UCL teams load from clubelo.com (daily cache in `data/.soccer_cache/club_elo.csv`)
  6. All new ingestion modules are isolated from the WC pipeline (separate cache namespace)
**Plans**: 2 plans
Plans:
- [x] 12-01-PLAN.md — FootballDataClient extension (fetch_team_matches + team IDs) + soccer_form.py (form/H2H/rest) + tests
- [x] 12-02-PLAN.md — club_elo.py (Club Elo CSV loader) + soccer_fbref.py (FBref set pieces) + tests

### Phase 13: Soccer Model Upgrade
**Goal**: EPL uses a retrained XGBoost model with 5 expanded features; UCL uses a Club Elo-logistic model instead of market-implied fallback
**Depends on**: Phase 12
**Requirements**: SMODEL-01, SMODEL-02, SMODEL-03
**Success Criteria** (what must be TRUE):
  1. EPL XGBoost retrained on 3 seasons of historical data (~1,140 games) with form + H2H + days-rest + set pieces + xG features
  2. EPL model calibrated (Platt scaling preferred) and benchmarked on chronological test set — Brier score vs. market-implied baseline recorded
  3. `UCLEloModel` produces W/D/L probabilities using Club Elo-logistic formula with +40 Elo home advantage (half of standard 80pt — UCL elite clubs)
  4. `soccer_scanner.py` routes EPL games to XGBoost, UCL games to UCLEloModel — no cross-routing (Phase 14)
  5. Existing fallback chain preserved: EPL = XGBoost → market_implied; UCL = UCLEloModel → market_implied
**Plans**: 2 plans
Plans:
- [x] 13-01-PLAN.md — EPL training pipeline: epl_training.py (14-feature schema + leakage-safe row builder) + train_epl_moneyline.py + tests
- [x] 13-02-PLAN.md — UCLEloModel (ucl_model.py, +40 home advantage, Club Elo) + SoccerModel EPL artifact gate + tests

### Phase 14: Draw Betting + Scanner Integration
**Goal**: Users see draw legs in parlay output (annotated `*DRAW RISK*`) when model EV > 5%, scanner shows independent model probabilities for both EPL and UCL
**Depends on**: Phase 13
**Requirements**: SDRAW-01, SDRAW-02, SSCAN-01, STEST-01
**Success Criteria** (what must be TRUE):
  1. Draw legs appear in SGP combos when model-estimated draw probability produces EV > 5% vs. market draw odds
  2. Draw legs are annotated `*DRAW RISK*` in scanner output — user can identify them at a glance
  3. Draw legs from market-implied fallback are never included (model gate enforced)
  4. `soccer_scanner.py --mode parlay --league epl` shows EPL XGBoost probabilities; `--league ucl` shows UCL Elo probabilities
  5. All new components have unit tests; total test count ≥ 636 with zero regressions
**Plans**: 2 plans
Plans:
- [x] 14-01-PLAN.md — SoccerSGPBuilder draw leg gate: _build_draw_legs() with EV > 5% guard (D-11), is_draw annotation, same-game combo exclusion
- [x] 14-02-PLAN.md — Soccer scanner UCL routing (D-13) + *DRAW RISK* annotation (D-12) + D% probability column + 8 unit tests

## Progress (v1.4)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 12. Soccer Feature Data Pipeline | 2/2 | Complete    | 2026-06-19 |
| 13. Soccer Model Upgrade | 2/2 | Complete   | 2026-06-20 |
| 14. Draw Betting + Scanner Integration | 2/2 | Complete    | 2026-06-21 |

---

## Current Milestone: v1.5 - World Cup True SGP

## Phases (v1.5)

- [ ] **Phase 15: Scoreline Goal-Market Model** - Calibrate a scoreline distribution to WC Elo 1X2 marginals and expose totals, BTTS, and exact joint probabilities.
- [ ] **Phase 16: True SGP Builder and Scanner** - Normalize market prices, build stage-safe same-match combinations, and add `--mode sgp` output.

## Phase Details (v1.5)

### Phase 15: Scoreline Goal-Market Model
**Goal**: Each World Cup match has one coherent scoreline distribution supporting correlated market probabilities.
**Depends on**: Existing WC Elo outcome model and cached WC team statistics
**Requirements**: WCSGP-01, WCSGP-02, WCSGP-03, WCSGP-04, WCSGP-05, WCSGP-12
**Success Criteria**:
1. Goal rates use bounded World Cup attack/defense priors with neutral fallbacks.
2. Scoreline weights reproduce WC Elo home/draw/away marginals within numerical tolerance.
3. Totals and BTTS binary markets each sum to one.
4. Multi-leg probability is evaluated directly against scorelines and rejects contradictions.
5. Focused and full regression tests pass.
**Plans**: 1 plan

### Phase 16: True SGP Builder and Scanner
**Goal**: Users can request ranked, real-price, same-match World Cup combinations without changing classic parlay behavior.
**Depends on**: Phase 15
**Requirements**: WCSGP-06, WCSGP-07, WCSGP-08, WCSGP-09, WCSGP-10, WCSGP-11, WCSGP-12
**Success Criteria**:
1. Normalized odds accept 1X2, over/under 2.5, and BTTS prices.
2. Missing odds are explicit and never replaced with assumptions.
3. Builder emits only compatible 2-3 leg selections from one match and ranks by EV.
4. Knockout matches exclude standard 90-minute 1X2 while permitting compatible goal combinations.
5. `--mode sgp` is tested and `--mode parlay` remains unchanged.
**Plans**: 1 plan

## Progress (v1.5)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 15. Scoreline Goal-Market Model | 0/1 | Not started | - |
| 16. True SGP Builder and Scanner | 0/1 | Not started | - |
