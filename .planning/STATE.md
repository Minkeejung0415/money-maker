---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: Soccer Mode Upgrade
status: executing
stopped_at: Completed 08-01-PLAN.md
last_updated: "2026-06-20T07:30:28.293Z"
last_activity: 2026-06-20
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 4
  completed_plans: 3
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-18)

**Core value:** Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.
**Current focus:** Phase 13 — Soccer Model Upgrade

## Current Position

Phase: 13 (Soccer Model Upgrade) — EXECUTING
Plan: 2 of 2
Status: Ready to execute
Last activity: 2026-06-20

## Performance Metrics

**Velocity:**

- Total plans completed: 2 (v1.2)
- Average duration: - min
- Total execution time: 0 hours

**By Phase:**

*Roadmap not yet created*

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions (carried from v1.0)

- Validate via validate_picks.py not live runs (zero API cost, uses real box scores)
- Synthetic line = own projection produces a meaningless baseline — real lines needed for final validation
- NBA Odds API usage reserved exclusively for NBA (soccer and MLB do NOT use it)
- World Cup scanner goes in scripts/wc_scanner.py (separate from soccer_scanner.py) — keeps WC isolated

### Decisions (v1.1 — from research)

- wc_model.py is a completely separate class — never routes WC games through SoccerModel or ProphitBet XGBoost
- Elo-logistic (chess formula) is the correct model — XGBoost explicitly rejected for WC data volume (~7k international games)
- Player props deferred to v1.2 — Odds API Business tier required for WC prop markets beyond anytime goalscorer
- StatsBomb 2018+2022 data (128 matches) cached to data/.wc_cache/ (separate namespace from data/.soccer_cache/)
- Neutral-venue correction applied: no +100 Elo home-field boost for WC (all matches at US/Canada/Mexico venues)
- Knockout round SGPs: Draw legs and standard moneyline legs are hard-gated out (settle on 90-min result only)
- WC Odds API daily budget: 20 requests max; 2h cache TTL (WC odds move faster than club soccer)

### Pending Todos

- Run Odds API market discovery scan (`GET /v4/sports/soccer_fifa_world_cup/events/<id>/odds?markets=`) to confirm which player prop market names exist before building any prop pipeline
- Confirm per-request credit cost for `soccer_fifa_world_cup` h2h endpoint on existing free tier
- Decide Elo data source for v1.1: static Kaggle CSV (saifalnimri/international-football-elo-ratings, covers through 2025) vs. live eloratings.net scrape
- Check whether football_data_client.py has retry/backoff for 429 responses before extending

### Blockers/Concerns

- World Cup 2026 group stage is LIVE (started June 11) — urgency is high, Phase 1 must ship within first week
- StatsBomb 2026 live data is NOT available mid-tournament (historical pattern: released post-tournament) — wc_stats.py uses 2018/2022 data only as priors
- If most group stage games complete before Phase 6 ships, the prop mode has limited live testing window before knockout begins

## Session Continuity

Last session: 2026-06-20T07:30:28.283Z
Stopped at: Completed 08-01-PLAN.md
Resume file: None
