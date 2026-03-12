# Requirements: NBA Prop Model Algorithm Upgrade

**Defined:** 2026-03-12
**Core Value:** Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.

## v1 Requirements

### Data Hygiene

- [ ] **DATA-01**: Delete stale `data/.prop_cache/*.pkl` files before any validation run
- [ ] **DATA-02**: Verify PropModel default season is "2025-26" in all files (prop_model.py, nba_stats_cache.py)
- [ ] **DATA-03**: validate_picks.py uses pre-game only logs (actual > own-projection filtering is correct)

### Projection Algorithm

- [ ] **ALGO-01**: Replace equal-weighted bucket average with exponential decay (lambda=0.85) across individual games
- [ ] **ALGO-02**: Add home/away split — filter qualifying games to match today's location; fall back to all games if <5 split games
- [ ] **ALGO-03**: Replace Normal CDF with Poisson CDF for low-count stats (ast, blk, stl, 3pm) and Negative Binomial for pts/reb
- [ ] **ALGO-04**: Add days-rest multiplier (B2B=0.94, 1-day=0.97, 3+days=1.02) to projection before CDF

### Opponent Adjustments

- [ ] **OPP-01**: Fix rebound opponent adjustment direction — use opponent DREB_pg not total reb_pg
- [ ] **OPP-02**: Add position-level opponent allowed stats (Guard/Forward/Center) for reb, pts, ast adjustments
- [ ] **OPP-03**: Add pace adjustment for rebounds — slow-paced matchup reduces rebound projection proportionally
- [ ] **OPP-04**: Tighten rebound cap from ±15% to ±10%

### Confidence & Filtering

- [ ] **CONF-01**: Add blowout gate — downgrade HIGH→MEDIUM for props on teams where ML model win prob <30%
- [ ] **CONF-02**: Add low-line skepticism — when model_prob >85% AND line is >1.5 stdev below projection, cap confidence at MEDIUM
- [ ] **CONF-03**: Minimum 60% confidence floor — exclude legs below 60% from SGP output

### Validation

- [ ] **VAL-01**: Run validate_picks.py before and after EACH algorithm change to measure per-stat improvement
- [ ] **VAL-02**: Report per-stat hit rates (pts/reb/ast/3pm) separately — not just overall
- [ ] **VAL-03**: Baseline recorded: pts=49.3%, reb=34.2%, ast=49.3%, 3pm=41.1%, overall=43.5%
- [ ] **VAL-04**: Target: all stats >50%, rebounds >50%, overall >55% after all changes

## v2 Requirements

### Real Sportsbook Lines

- **REAL-01**: Compare model projection vs actual Odds API lines instead of synthetic lines
- **REAL-02**: Compute EV (edge) vs market-implied probability per pick
- **REAL-03**: Track live hit rate vs sportsbook lines over 3+ game days

### Per-Minute Normalization

- **MIN-01**: Normalize all stats to per-36-minute rate, then multiply back by expected minutes
- **MIN-02**: Expected minutes = rolling avg of qualifying game minutes

### Multi-Day Validation

- **MDAY-01**: Validate across 5+ game days for statistical significance (300+ props needed for p<0.05)
- **MDAY-02**: Holdout set — designate March 6-10 as held-out validation (never tuned against)

## Out of Scope

| Feature | Reason |
|---------|--------|
| New XGBoost prop model trained on historical lines | Requires labeled prop data (line + result) for 2+ seasons — not available without paid source |
| Neural network ensemble | Over-engineering before basic stat corrections in place |
| PropContextEvaluator rewrite | Architecturally sound — tune thresholds, don't rewrite |
| Soccer/MLB model changes | NBA only for this upgrade |
| Real-time lineup scraping | High maintenance, fragile — injury pipeline covers most cases |
| Discord bot / Stripe | Separate monetization milestone |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1 | Pending |
| DATA-02 | Phase 1 | Pending |
| DATA-03 | Phase 1 | Pending |
| VAL-03 | Phase 1 | Pending |
| ALGO-01 | Phase 2 | Pending |
| ALGO-02 | Phase 2 | Pending |
| ALGO-03 | Phase 2 | Pending |
| ALGO-04 | Phase 2 | Pending |
| VAL-01 | Phase 2 | Pending |
| VAL-02 | Phase 2 | Pending |
| OPP-01 | Phase 3 | Pending |
| OPP-02 | Phase 3 | Pending |
| OPP-03 | Phase 3 | Pending |
| OPP-04 | Phase 3 | Pending |
| CONF-01 | Phase 4 | Pending |
| CONF-02 | Phase 4 | Pending |
| CONF-03 | Phase 4 | Pending |
| VAL-04 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 18 total
- Mapped to phases: 18
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-12*
*Last updated: 2026-03-12 after roadmap creation — VAL-01/VAL-02 moved from "Phase 1-4" to Phase 2 (first phase where changes occur)*
