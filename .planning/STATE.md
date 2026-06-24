---
gsd_state_version: 1.0
milestone: v1.9
milestone_name: Improving World Cup Win Probability with Team and Player Features
status: Complete
stopped_at: Phase 32 complete — all 8 phases delivered
last_updated: "2026-06-24T22:00:00.000Z"
last_activity: 2026-06-24 — Phase 25-32 all complete (944+ tests passing)
progress:
  total_phases: 8
  completed_phases: 8
  total_plans: 8
  completed_plans: 8
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-24)

**Core value:** Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.
**Current focus:** v1.9 — COMPLETE

## Current Position

Phase: 32 (Context Features + Full Integration) — COMPLETE
Status: Milestone v1.9 COMPLETE
Last activity: 2026-06-24 — All 8 phases complete

## Milestone v1.9 Summary

| Phase | Name | Tests Added | Commit |
|-------|------|------------|--------|
| 25 | Evaluation Framework | 26 | `wc_calibration.py`, `wc_eval.py` |
| 26 | Hybrid Baseline Ratings | 20 | `wc_ratings.py`, `wc_hybrid_model.py`, `wc_fifa_rankings.py` |
| 27 | Projected XI Layer | 16 | `wc_lineup.py` |
| 28 | Goalkeeper Module | 15 | `wc_goalkeeper.py` |
| 29 | Tournament-State Logic | 27 | `wc_tournament.py` |
| 30 | Position-Specific Player Features | 19 | `wc_player_features.py` |
| 31 | Tactical Matchup + Set-Piece | 20 | `wc_tactics.py` |
| 32 | Context Features + Full Integration | 25 | `wc_context.py` |
| **Total** | | **~168** | |

## Performance Metrics

**Promotion gate (Phase 26):** PASS
- Brier: 0.5181 → 0.4889 (Δ −0.0292)
- LogLoss: 0.8805 → 0.8439 (Δ −0.0366)

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

### Decisions (v1.9)

- Player data enters through projected XI, not roster averages — structured probabilistic XI model required
- Hybrid Elo + xG states + FIFA SUM is the recommended baseline stack (not sole Elo)
- GK stored as a dedicated submodel separate from generic team defense
- Hierarchical shrinkage required: sparse national-team samples pool toward club-based role priors
- Club data weighted ~70-80%, national-team ~20-30%; tunable by backtest
- Context features (rest, travel, heat) regularized harder than team/player features
- CONTEXT regularization max (0.010) < TEAM rating min (0.050) — enforced by constant
- Isotonic regression calibration fitted on validation fold only
- Player-aware model must beat Elo-only baseline on Brier + log loss before production promotion

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
Stopped at: Phase 32 complete — v1.9 milestone COMPLETE
Resume file: None

## Operator Next Steps

- v1.9 milestone complete — start next milestone or run live scanner
- Run `./venv/Scripts/python.exe ./scripts/wc_scanner.py --mode parlay` to generate picks
