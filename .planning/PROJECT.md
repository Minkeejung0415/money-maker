# Alpha Terminal — Multi-Asset Prediction Engine

## What This Is

A unified multi-asset trading and prediction engine covering NBA, soccer (EPL/UCL/World Cup), and MLB sports betting alongside stocks and crypto. The sports layer predicts prop outcomes and constructs SGP parlays with positive expected value, using a combination of statistical models, opponent adjustments, and odds-implied signals.

## Current Milestone: v1.1 — World Cup Soccer Mode

**Goal:** Ship a full World Cup 2026 prediction stack — match outcome model, player props, and SGP builder — running on live group-stage and knockout-round data.

**Target features:**
- WC fixture ingestion: live group stage + knockout schedule
- WC match model: Win/Draw/Loss predictions tuned to national-team dynamics
- WC player props: goals, shots, assists (odds-implied where historical data is sparse)
- WC SGP builder: combine match + player legs into SGP combos
- `scripts/wc_scanner.py`: new entry point (`--mode props` / `--mode parlay`)

## Core Value

Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.

## Requirements

### Validated (v1.0)

- [x] Exponential decay rolling average for NBA props
- [x] Poisson/Negative Binomial distribution CDFs for probability estimates
- [x] Position-level opponent adjustments for rebounds, points, assists
- [x] Blowout gate (ML win prob <30% → downgrade HIGH picks)
- [x] 60% confidence floor for SGP legs

### Active (v1.1)

- [ ] WC fixture ingestion: live group stage + knockout schedule
- [ ] WC match outcome model (Win/Draw/Loss with calibrated confidence)
- [ ] WC player prop model (goals, shots, assists)
- [ ] WC SGP builder combining match and player legs
- [ ] `scripts/wc_scanner.py` entry point (`--mode props` / `--mode parlay`)
- [ ] Research confirms best data sources for WC stats and odds

### Out of Scope

- EPL/UCL engine changes — WC only for this milestone
- NBA/MLB model changes — sports scope is WC only
- UI/output format changes beyond scanner output

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
*Last updated: 2026-06-18 — Milestone v1.1 started*
