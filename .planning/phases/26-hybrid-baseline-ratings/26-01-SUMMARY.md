# Phase 26-01 Summary: Hybrid Baseline Ratings

**Status:** Complete
**Date:** 2026-06-24

## What was built

- `data/wc_fifa_rankings.py` — June 2026 FIFA rankings for 48+ WC teams + confederation map + WC_2026_HOSTS
- `alpha/engines/sports/wc_ratings.py` — `WCTeamRatings`: sequential Elo replay (K=30), xG EWMA from stats cache, composite Elo formula (xG±40 + FIFA±20 + host+50 + conf±10)
- `alpha/engines/sports/wc_hybrid_model.py` — `WCHybridModel`: injects composite Elo as home/away_elo_override into WCMatchModel (scanner unchanged)
- `scripts/wc_eval.py` — extended with hybrid model section + promotion gate comparison
- `tests/unit/engines/test_wc_ratings.py` — 12 tests (features, host flag, confederation, Elo bounds)
- `tests/unit/engines/test_wc_hybrid_model.py` — 8 tests (fields, WDL sum, copy safety, host boost)

## Evaluation Results (2022 holdout, 64 matches)

| Model | Brier | LogLoss | Accuracy |
|-------|-------|---------|----------|
| Elo-only baseline (Phase 25) | 0.5181 | 0.8805 | 60.9% |
| Hybrid (Phase 26) | 0.4889 | 0.8439 | 65.6% |
| Delta | -0.0292 ✅ | -0.0366 ✅ | +4.7% |

**Promotion gate: PASS** (both Brier and LogLoss improve by >0.001)

## Key decisions

- Injection pattern (elo_override) keeps wc_model.py and wc_scanner.py unchanged
- K=30 for Elo updates (WC literature standard)
- xG EWMA seeded from wc_stats.pkl (goals as proxy when per-match xG unavailable)
- Host adjustment: +50 Elo for US/Mexico/Canada (2026 hosts)
- Confederation: ±10 Elo (same conf = +10, cross-conf = -10)
