---
gsd_state_version: 1.0
milestone: v1.9
milestone_name: Improving World Cup Win Probability with Team and Player Features
status: In progress
stopped_at: Phase 25 Plan 01 complete — evaluation framework delivered
last_updated: "2026-06-24T17:48:00.000Z"
last_activity: 2026-06-24 — Phase 25-01 evaluation framework executed
progress:
  total_phases: 8
  completed_phases: 1
  total_plans: 8
  completed_plans: 1
  percent: 13
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-24)

**Core value:** Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.
**Current focus:** v1.9 — Improving World Cup Win Probability with Team and Player Features

## Current Position

Phase: 25 (Evaluation Framework) — COMPLETE
Plan: 01 of 01 — COMPLETE
Status: In progress (Phase 26 next)
Last activity: 2026-06-24 — Phase 25-01 complete: 128-match historical dataset + calibration harness + backtest runner (868/868 tests)

## Performance Metrics

**Velocity:**

- Total plans completed: 1 (v1.9)
- Average duration: 14 min
- Total execution time: 0.23 hours

**By Phase:**

| Phase | Plans | Duration | Tests Added |
|-------|-------|----------|-------------|
| 25 Evaluation Framework | 1/1 | 14 min | 26 |

**Recent Trend:**

- Last 5 plans: 14 min
- Trend: baseline

*Updated after each plan completion*

## Accumulated Context

### Decisions (carried from v1.0)

- Validate via validate_picks.py not live runs (zero API cost, uses real box scores)
- Synthetic line = own projection produces a meaningless baseline — real lines needed for final validation
- NBA Odds API usage reserved exclusively for NBA (soccer and MLB do NOT use it)
- World Cup scanner goes in scripts/wc_scanner.py (separate from soccer_scanner.py) — keeps WC isolated

### Decisions (v1.1 — from research)

- wc_model.py is a completely separate class — never routes WC games through SoccerModel or ProphitBet XGBoost
- Elo-logistic (chess formula) is the correct baseline for WC data volume (~7k international games)
- StatsBomb 2018+2022 data (128 matches) cached to data/.wc_cache/ (separate namespace from data/.soccer_cache/)
- Neutral-venue correction applied: no +100 Elo home-field boost for WC (all matches at US/Canada/Mexico venues)
- Knockout round SGPs: Draw legs and standard moneyline legs are hard-gated out (settle on 90-min result only)

### Decisions (v1.9 — from research brief)

- Player data enters through projected XI, not roster averages — structured probabilistic XI model required
- Hybrid Elo + xG states + FIFA SUM is the recommended baseline stack (not sole Elo)
- GK stored as a dedicated submodel separate from generic team defense
- Hierarchical shrinkage required: sparse national-team samples pool toward club-based role priors
- Club data weighted ~70-80%, national-team ~20-30% for repeatable actions; tunable by backtest
- Context features (rest, travel, heat) regularized harder than team/player features
- Isotonic regression calibration fitted on validation fold only — never post-hoc on full dataset
- Player-aware model must beat Elo-only baseline on Brier + log loss before production promotion

### Decisions (Phase 25 — evaluation framework)

- Multiclass Brier uses Formula A (sum per sample, not per-class mean) — consistent with Murphy 1973
- IsotonicRegression with out_of_bounds=clip + epsilon floor 1e-9 — prevents zero-row edge case on small datasets
- promotion_gate min_delta=0.001 — prevents trivial pass for identical models
- WCMatchModel.predict() input always copied — avoids mutation side effects on historical records
- Baseline (Elo-only, 2022 test set, 64 matches): Brier=0.5181, Log Loss=0.8805, Accuracy=60.9%

### Pending Todos

- Run Odds API market discovery scan for WC prop markets (carried from v1.1)
- Confirm per-request credit cost for `soccer_fifa_world_cup` h2h endpoint
- Decide Elo data source for long-run rating: static CSV vs. live scrape
- Check football_data_client.py retry/backoff for 429 responses

### Blockers/Concerns

- World Cup 2026 group stage is LIVE (started June 11) — urgency is high
- StatsBomb 2026 live data is NOT available mid-tournament — wc_stats.py uses 2018/2022 data only as priors
- Free player-stats sources for international players (FBref, Understat) have limited WC-specific coverage

## Session Continuity

Last session: 2026-06-24
Stopped at: Phase 25-01 complete — 868/868 tests passing
Resume file: None

## Operator Next Steps

- Start Phase 26: `Hybrid Baseline Ratings` with `/gsd:plan-phase 26`
