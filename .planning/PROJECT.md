# Alpha Terminal — Multi-Asset Prediction Engine

## What This Is

A unified multi-asset trading and prediction engine covering NBA, soccer (EPL/UCL/World Cup), and MLB sports betting alongside stocks and crypto. The sports layer predicts prop outcomes and constructs SGP parlays with positive expected value, using a combination of statistical models, opponent adjustments, and odds-implied signals.

## Current Milestone: v2.4 - WC Hybrid Route Offset

**Goal:** Improve the World Cup hybrid model by adding projected-XI role strengths and capped tactical duel offsets that adjust route-level expected goals before scoreline, BTTS, totals, and WDL probabilities are produced.

**Target features:**
- Runtime projected-XI and role-strength inputs for high-leverage roles: GK, CB, FB, DM, winger, and striker
- Capped duel rules for wing isolation, aerial/set-piece mismatch, and press-vs-build interactions
- Route-level xG offsets for center, wing, set-piece, and counterattack components layered over the existing hybrid baseline
- Shadow-mode scanner output that logs baseline lambdas, adjusted lambdas, active duel rules, cap hits, missing-role coverage, and uncertainty shrinkage
- Paired validation against the current WC hybrid baseline using Brier, log loss, calibration, route diagnostics, BTTS, and over/under 2.5 behavior
- Explicit artifact identity and fail-closed promotion gates before any route-offset model can affect production picks

**Current state:** v2.4 complete. WC route-offset runtime, projected-XI role snapshots, capped tactical duels, shadow scanner diagnostics, and paired validation gates are implemented. Production remains shadow-first until real graded route-offset rows pass validation.

## Previous Milestone: v2.3 - Automated MLB Player Data and Accuracy Upgrade (Complete)

**Goal:** Replace fragile live MLB stat scraping with an automated local player-data pipeline, then improve and promote a richer MLB player-aware algorithm whose stats meaningfully change win probabilities.

**Target features:**
- Runtime MLB data source policy that treats Fangraphs/pybaseball scraping as optional enrichment, not a required scanner dependency
- Automated daily MLB schedule, probable pitcher, player-stat, bullpen, lineup, and absence import/update scripts
- Local player-stat database snapshots and event-level feature files keyed by MLB game id
- Accuracy-focused feature interpretation layer for rolling form, starter quality, lineup strength, bullpen fatigue, absence impact, and uncertainty
- Walk-forward retraining, ablation, calibration, and promotion gates for a richer MLB player-aware moneyline artifact
- MLB scanner auto-loads date-specific local player features and prints source/freshness/confidence context

**Current state:** v2.3 complete. The MLB scanner no longer depends on live Fangraphs scraping by default, local player database update/build scripts exist, event-level player features can be auto-loaded, and promotion metadata now includes accuracy and selective-pick metrics.

## Previous Milestone: v1.7 - Tactical Calibration and Validation (Complete)

**Goal:** Replace hand-set tactical weights with leakage-safe, regularized estimates and deploy them only where chronological out-of-sample probability quality improves.

**Target features:**
- Historical international-match training rows built only from information available before kickoff
- Regularized residual tactical weights that complement, rather than duplicate, the baseline model
- Chronological validation using Brier score and log loss as primary metrics
- Independent deployment gates for 1X2, totals, and BTTS
- Versioned model artifacts with baseline fallback on missing, stale, or unvalidated weights

**Current state:** v1.7 complete. The learned tactical path is implemented, but the real 16-row eligible sample fails the 200/50/30 gate, so production remains on the no-tactics baseline.

## Previous Milestone: v1.3 — MLB Win Probability Model (Complete)

**Goal:** Replace the 50/50 MLB fallback with independently trained, historically validated home/away win probabilities for every daily MLB game.

**Target features:**
- Leakage-free historical game dataset from free MLB data
- Calibrated pregame model using team, pitcher, rest, and home-field features
- Chronological validation against simple and market benchmarks
- Daily scanner output with win percentages and fair odds
- Optional manual sportsbook odds for edge comparison

## Previous Milestone: v1.2 — Draw Algorithm (Complete)

**Goal:** Replace the flat 25% draw rate with a match-strength-dependent draw probability calibrated to historical WC group-stage data.

**Target features:**
- Dynamic draw probability function: p_draw decreases as Elo difference grows
- Calibration against historical WC group-stage draw rates by Elo band
- Updated `wc_model.py` and full test coverage

## Previous Milestone: v1.1 — World Cup Soccer Mode (Complete)

**Shipped (2026-06-19):** WC fixture ingestion (football-data.org), Elo-logistic match model (neutral venue, knockout gate, elo_edge flag), WC SGP builder, wc_scanner.py entry point. 619 tests passing.

## Core Value

Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.

## Requirements

### Validated (v1.0)

- [x] Exponential decay rolling average for NBA props
- [x] Poisson/Negative Binomial distribution CDFs for probability estimates
- [x] Position-level opponent adjustments for rebounds, points, assists
- [x] Blowout gate (ML win prob <30% → downgrade HIGH picks)
- [x] 60% confidence floor for SGP legs

### Validated (v1.1)

- [x] WC fixture ingestion: live group stage + knockout schedule
- [x] WC match outcome model (Elo-logistic, neutral venue, knockout gate)
- [x] WC SGP builder (stage-aware, correlation gate)
- [x] `scripts/wc_scanner.py` entry point (`--mode parlay`)

### Validated (v1.2)

- [x] Dynamic draw probability function keyed on Elo difference
- [x] Calibration to historical WC group-stage draw rates
- [x] Updated wc_model.py with full test coverage

### Validated (v1.3)

- [x] Build a leakage-free historical MLB game dataset from free sources
- [x] Train and calibrate an independent MLB win-probability model
- [x] Validate chronologically against home-team and market baselines
- [x] Persist model metadata and prevent unvalidated models from being trusted silently
- [x] Show daily home/away probabilities and fair odds in the MLB scanner
- [x] Support optional manually supplied sportsbook odds for edge comparison

### Validated (v1.4)

- [x] Last-five form, H2H, and days-rest features from football-data.org
- [x] Daily Club Elo ratings with two-day stale fallback
- [x] FBref corners, aerial-win, and pressing-proxy feature ingestion
- [x] EPL/UCL cache isolation under `data/.soccer_cache/`

### Validated (v1.5)

- [x] Scoreline-calibrated World Cup goal-market probabilities
- [x] True same-match 2-3 leg combinations with exact joint probability
- [x] Normalized 1X2, total-goals, and BTTS market prices
- [x] Stage-safe scanner mode with complete test coverage

### Validated (v1.6)

- [x] Recent tactical data ingestion and caching
- [x] Explainable team-style comparison
- [x] Bounded scoreline-model integration
- [x] Scanner tactical comparison output and validation

### Validated (v1.7)

- [x] Leakage-safe historical tactical row builder and immutable split manifests
- [x] Regularized chronological residual training and strict probability-quality gates
- [x] Versioned runtime artifact validation with independent market fallback
- [x] One-distribution-per-SGP coherence and visible scanner gate status
- [x] Real coverage audit blocks promotion when evidence is insufficient

### Validated (v1.8)

- [x] Build MLB historical game and player-slot tables from free/official sources with stable IDs
- [x] Add player-aware starter, lineup, bullpen, and injury/absence features without target-game leakage
- [x] Train and calibrate MLB moneyline candidates with date-based walk-forward splits and ablations
- [x] Gate runtime MLB output on validated artifacts, lineup/starter uncertainty, and confidence thresholds
- [x] Quarantine synthetic MLB prop rows and crude injury penalties from the moneyline feature path

### Validated (v1.9)

- [x] Hybrid Elo-like + xG attack/defense + FIFA SUM baseline with host-country and confederation adjustments
- [x] Projected-XI layer: starter probabilities, line scores, replacement-adjusted absence impact, lineup uncertainty band
- [x] Dedicated GK module: goals prevented vs xGOT, save subtypes, cross claims, sweeper, GK-CB continuity
- [x] Position-specific player features with hierarchical shrinkage toward club-based role priors
- [x] Tournament-state logic: qualification pressure, rotation risk, yellow-card accumulation, 2026 best-third format, fair-play tiebreak
- [x] Tactical matchup + set-piece and context feature modules
- [x] Chronological evaluation framework with Brier, log loss, A-grade hit rate, and promotion gates

### Validated (v2.0)

- [x] WC scanner explicit model choices: `--model elo`, `--model hybrid`, `--model player`, and `--model auto`
- [x] Fail-closed `auto` and `player` paths unless `--allow-fallback` is explicitly supplied
- [x] Runtime labels: `requested_model`, `active_model`, `fallback_used`, and `fallback_reason`
- [x] Shadow challenger logging via `--shadow-model` without affecting picks
- [x] Lightweight JSON artifact metadata validation for runtime trust gates


### Validated (v2.3)

- [x] Runtime MLB scanner does not require Fangraphs/pybaseball scraping by default
- [x] Local MLB player database snapshots support batter, pitcher, bullpen, lineup, and absence rows
- [x] Date-specific event-level player feature files can be generated for scanner runtime
- [x] MLB feature interpretation includes starter, lineup, bullpen, absence, coverage, stale, and confidence context
- [x] MLB walk-forward modeling reports include Brier, log loss, accuracy, coverage, and selective win rate
- [x] MLB scanner auto-loads local player feature files while preserving manual override

### Validated (v2.4)

- [x] WC route-offset runtime keeps hybrid as the production prior and defaults to shadow mode
- [x] Projected-XI role-strength snapshots support GK, CB, FB, DM, winger, and striker with coverage labels
- [x] Tactical duel rules convert wing isolation, aerial/set-piece, and press-vs-build matchups into capped route-xG deltas
- [x] Scoreline integration regenerates adjusted WDL, BTTS, and O/U2.5 probabilities from adjusted lambdas when explicitly applied
- [x] Scanner output reports baseline/adjusted lambdas, route status, eligibility, cap/shrink context, O/U2.5, and BTTS
- [x] Paired validation script blocks route-offset promotion unless baseline-vs-route metrics pass documented gates

### Active

- [ ] Collect real projected-XI route-offset snapshots and grade shadow output after results settle
- [ ] Promote route-offset mode only after paired validation passes on enough real fixtures

### Out of Scope

- MLB player props — requires a dependable prop-odds source and broader modeling scope
- MLB parlay optimization — deferred until single-game probabilities are validated
- Paid baseball or odds feeds — free data only for v1.3
- World Cup player props — no dependable free player-prop odds source
- Invented SGP prices — recommendations require actual supplied prices
- Commercial data sources (Opta, StatsBomb commercial) — free data only constraint continues
- Early-sub and game-plan distribution modeling — medium priority, deferred to v2.0
- Full chemistry/continuity graph — deferred to v2.0

## Context

**Baseline (walk-forward backtest, March 11 2026 games):**
| Stat | Hit rate | Problem |
|------|----------|---------|
| pts  | 49.3%    | Near-random — synthetic line = model's own mean |
| reb  | 34.2%    | Model overprojects — ignores opp rebounding strength |
| ast  | 49.3%    | Near-random |
| 3pm  | 41.1%    | No opp 3P defense adjustment |
| **Overall** | **43.5%** | Below random 50% |

**Root causes already identified:**
1. Season data was wrong (2024-25 instead of 2025-26) — FIXED last session
2. Opponent adjustments existed for some markets but not all — FIXED last session
3. Rebound cap too loose (±15%) — needs tighter tuning
4. Stale .pkl cache in `data/.prop_cache/` — DELETE before re-running
5. No weighted recent-game emphasis — flat season avg used instead

**Key files:**
- `alpha/engines/sports/prop_model.py` — main model
- `alpha/data/ingestion/nba_stats_cache.py` — data fetcher (6h TTL)
- `scripts/validate_picks.py` — zero-cost backtest tool
- `scripts/sgp_scanner.py` — production runner

## Constraints

- **Data**: Only free APIs (nba_api, Odds API for props) — no paid stat providers
- **Performance**: PropModel must run in <5 min for full game slate (no slow NBA API calls per-player)
- **Compatibility**: Must pass existing 482 tests — no regressions

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Validate via validate_picks.py not live runs | Zero API cost, uses real box scores | — Pending |
| Fix rebounds before other stats | 34.2% hit rate is 15% below random — biggest win | — Pending |
| Research algorithm options before building | User wants to see options before committing | — Pending |
| Treat the v1.3 MLB model as the baseline for v1.8 | The current artifact is validated but team-only, so it is the comparison point rather than the target design | — Pending |
| Optimize MLB moneyline for accuracy and selective win rate before EV | The report prioritizes hit rate and confidence gating over odds-driven betting expansion | — Pending |
| Model WC player and tactical data as route-xG offsets, not raw WDL inputs | Keeps the calibrated hybrid prior stable while making player and tactical effects football-native and explainable | — Pending |

## Previous Milestone: v1.0 — NBA Prop Model Algorithm Upgrade (Complete)

**Shipped (2026-03-12):** Exponential decay, Poisson/NB distributions, position-level opponent adjustments, blowout gate, confidence floor. 493 tests passing. Final accuracy: 48.6% overall (up from 43.5% baseline).

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-03 after completing v2.4 WC Hybrid Route Offset*
