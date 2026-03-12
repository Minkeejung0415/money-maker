# Phase 2: Projection Algorithm — SUMMARY

## Status: COMPLETE

## Per-Stat Before/After Table

| Stat | Phase 1 Baseline | After Phase 2 | Change |
|------|-----------------|---------------|--------|
| pts  | 49.3% (36/73)   | 52.1% (38/73) | +2.8%  |
| reb  | 34.2% (25/73)   | 35.6% (26/73) | +1.4%  |
| ast  | 49.3% (36/73)   | 50.7% (37/73) | +1.4%  |
| 3pm  | 41.1% (30/73)   | 46.6% (34/73) | +5.5%  |
| overall | 43.5% (127/292) | 46.2% (135/292) | +2.7% |

## Changes Applied

### ALGO-01: Exponential Decay Rolling Average
- Replaced bucket-weighted average (50%/30%/20% over last 5/10/20 games) with
  true exponential decay: `weight[i] = 0.85^i` where i=0 is most recent game
- Applied in both `prop_model.py` and `validate_picks.py`
- DECAY_LAMBDA = 0.85 (configurable constant)

### ALGO-02: Home/Away Location Split
- Before computing projection, game logs are filtered to matching location
  (home = "vs." in MATCHUP, away = "@" in MATCHUP)
- Fallback: if filtered set has <5 qualifying games, use all games
- `predict_prop()` accepts `location` parameter ("home", "away", "all")
- Validation script detects locations via box score API and applies splits

### ALGO-03: Poisson / Negative Binomial CDF
- Poisson CDF for: ast, blk, stl, 3pm (discrete low-count stats)
- Negative Binomial CDF for: pts, reb (overdispersed count data)
- Fallback to Normal CDF if NegBin parameters are invalid (r <= 0)
- `_compute_p_over()` method selects CDF based on market type

### ALGO-04: Days-Rest Multiplier
- B2B (0 rest days): ×0.94
- 1 day rest: ×0.97
- 2 days rest: ×1.00 (neutral)
- 3+ days rest: ×1.02
- Applied after exponential decay, before opponent adjustment
- Rest derived from most recent game date vs today's date

## Success Criteria

- ✓ pts hit rate moved ≥1% from baseline: 49.3% → 52.1% (+2.8%)
- ✓ ast hit rate moved ≥1% from baseline: 49.3% → 50.7% (+1.4%)
- ✓ Home/away games produce different projections (location filter applied)
- ✓ B2B players receive 0.94x multiplier via `_rest_multiplier()`
- ✓ Poisson CDF used for ast/blk/stl/3pm (code: `_POISSON_MARKETS`)
- ✓ Negative Binomial CDF used for pts/reb (code: `_NEGBIN_MARKETS`)
- ✓ All 493 tests pass
