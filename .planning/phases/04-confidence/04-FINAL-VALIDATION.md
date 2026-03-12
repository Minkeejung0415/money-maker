# Phase 4 — Final Validation Results

## Validation Command

```
./venv/Scripts/python.exe scripts/validate_picks.py --date 2026-03-11
```

## Final Per-Stat Hit Rates

| Stat | Baseline (Phase 1) | Phase 2 | Phase 3 | Phase 4 (Final) | Total Delta |
|------|---------------------|---------|---------|-----------------|-------------|
| pts  | 36/73 (49.3%)       | 38/73 (52.1%) | 38/73 (52.1%) | 38/73 (52.1%) | **+2.8%** |
| reb  | 25/73 (34.2%)       | 26/73 (35.6%) | 33/73 (45.2%) | 33/73 (45.2%) | **+11.0%** |
| ast  | 36/73 (49.3%)       | 37/73 (50.7%) | 37/73 (50.7%) | 37/73 (50.7%) | **+1.4%** |
| 3pm  | 30/73 (41.1%)       | 34/73 (46.6%) | 34/73 (46.6%) | 34/73 (46.6%) | **+5.5%** |
| **overall** | **127/292 (43.5%)** | **135/292 (46.2%)** | **142/292 (48.6%)** | **142/292 (48.6%)** | **+5.1%** |

## Phase 4 Changes (Confidence Tuning)

Phase 4 changes affect confidence labels and SGP filtering,
not the underlying projections. The synthetic-line validation hit rates
are therefore unchanged from Phase 3. The value of Phase 4 shows up in
real-money deployment where confidence gates prevent low-quality picks
from reaching output.

### CONF-01: Blowout Gate (prop_model.py)
- `team_win_prob` parameter added to `predict_prop`.
- If team_win_prob < 0.30, HIGH confidence → MEDIUM.
- Prevents starters-rest / garbage-time picks from surfacing as HIGH.

### CONF-02: Low-Line Skepticism (prop_model.py)
- If model_prob > 85% AND line < projection − 1.5 × std, cap at MEDIUM.
- Catches "too good to be true" lines that often signal injury/rest news.

### CONF-03: 60% Confidence Floor (prop_model.py + sgp_scanner.py)
- model_prob < 0.60 → confidence forced to LOW in prop_model.
- sgp_scanner.py default --min-prob=0.60 drops sub-60% legs from combos.
- Single-prop output shows them with LOW label for transparency.

## Target Assessment

| Target | Metric | Result | Status |
|--------|--------|--------|--------|
| Overall > 55% | 48.6% | Short by 6.4% | ⚠ See note |
| All stats > 50% | pts=52.1%, ast=50.7% | reb=45.2%, 3pm=46.6% | Partial |
| Rebounds > 50% | 45.2% | Short by 4.8% | ⚠ See note |
| Tests pass | 493/493 | All green | ✅ |

### Note on Targets

The validation uses **synthetic lines** (projection = line), not real sportsbook lines.
With synthetic lines, an unbiased model produces ~50% hit rate by construction.
The 48.6% overall rate reflects residual overestimation that cannot be fully
eliminated without overfitting to this single validation date.

Key improvements from baseline:
- **Overall**: 43.5% → 48.6% (+5.1 pp)
- **Rebounds**: 34.2% → 45.2% (+11.0 pp) — the single biggest improvement
- **Three-pointers**: 41.1% → 46.6% (+5.5 pp)
- **Points and assists**: both above 50%
