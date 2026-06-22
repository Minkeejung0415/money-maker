# Alpha Terminal — Multi-Asset Prediction Engine

## What This Is

A unified multi-asset trading and prediction engine covering NBA, soccer (EPL/UCL/World Cup), and MLB sports betting alongside stocks and crypto. The sports layer predicts prop outcomes and constructs SGP parlays with positive expected value, using a combination of statistical models, opponent adjustments, and odds-implied signals.

## Current Milestone: v1.6 - World Cup Tactical Matchups

**Goal:** Compare how national-team tactical styles interact and apply bounded, explainable matchup adjustments to World Cup probabilities.

**Target features:**
- Recent formation and tactical-stat profiles for every scheduled team
- Symmetric comparison of control, pressing, directness, width, chance creation, set pieces, and defensive block
- Bounded attack-rate adjustments with named tactical explanations
- Scanner display of baseline versus tactics-adjusted probabilities
- Fail-closed data quality and full regression coverage

**Current state:** Complete and verified with 777 passing tests and a live four-game tactical audit.

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

### Out of Scope

- MLB player props — requires a dependable prop-odds source and broader modeling scope
- MLB parlay optimization — deferred until single-game probabilities are validated
- Paid baseball or odds feeds — free data only for v1.3
- World Cup player props - no dependable free player-prop odds source
- Invented SGP prices - recommendations require actual supplied prices

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
*Last updated: 2026-06-21 - v1.6 World Cup Tactical Matchups started*
