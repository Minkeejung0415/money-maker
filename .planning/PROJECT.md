# NBA Prop Model Algorithm Upgrade

## What This Is

A systematic upgrade to the NBA prop prediction algorithm in `alpha/engines/sports/prop_model.py`. The current model produces a 43.5% overall hit rate (below random 50%), with rebounds at a critical 34.2%. This project researches, implements, and validates better prediction approaches to push accuracy above 55% across all stat categories.

## Core Value

Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Rebound predictions hit >55% (currently 34.2% — model ignores opponent rebounding)
- [ ] Overall hit rate >55% across pts/reb/ast/3pm (currently 43.5%)
- [ ] Research identifies the best algorithm approach (weighted rolling avg, matchup-based, or ensemble)
- [ ] New algorithm implemented and integrated into PropModel
- [ ] Existing tuning fixes applied (rebound cap ±10%, opponent weights for all markets)
- [ ] validate_picks.py confirms improvement vs baseline before any changes ship

### Out of Scope

- Sportsbook line comparison (EV vs market) — future milestone after hit rate is fixed
- Soccer/MLB model changes — NBA only for this upgrade
- UI/output format changes — algorithm only

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

---
*Last updated: 2026-03-12 after initialization*
