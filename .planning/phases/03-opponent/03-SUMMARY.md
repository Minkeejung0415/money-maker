# Phase 3 — Opponent Adjustments: Summary

## Changes Implemented

### OPP-01: Rebound Adjustment Direction (prop_model.py)
- Rebounds now use `_LEAGUE_AVG_DREB_PG / opp_dreb` — high DREB_pg (strong
  defensive rebounder) correctly *reduces* the player's projection.

### OPP-02: Position-Level Opponent Scaling (prop_model.py)
- `_POSITION_OPP_WEIGHT` dict scales the raw opponent adjustment by position:
  C=1.00, PF=0.85, SF=0.65, SG=0.45, PG=0.40.
- Interpolation: `scale = 1.0 + (raw_scale - 1.0) * pos_weight`.
- Centers get the full opponent defensive adjustment; guards get ~40%.

### OPP-03: Pace Adjustment for Rebounds (prop_model.py)
- `_compute_pace_ratio` fetches opponent pace from `LeagueDashTeamStats`
  Advanced endpoint and divides by `_LEAGUE_AVG_PACE`.
- Applied as a multiplier to rebound projections before the DREB adjustment.

### OPP-04: Tightened Rebound Cap (prop_model.py)
- `_OPP_ADJ_CAP["player_rebounds"]` reduced from 0.15 to 0.10 (±10%).

### Rebound Volatility Dampening (prop_model.py + validate_picks.py)
- `_REB_DAMP = 0.90` applied to all rebound projections after the weighted
  average + rest multiplier, before CDF/line rounding.
- Addresses the structural overestimation inherent in exponential-decay
  averages for high-variance count stats (rebounds CoV ≈ 40-50%).

## Per-Stat Hit Rates (validate_picks.py --date 2026-03-11)

| Stat | Phase 2        | Phase 3        | Delta   |
|------|----------------|----------------|---------|
| pts  | 38/73 (52.1%)  | 38/73 (52.1%)  | —       |
| reb  | 26/73 (35.6%)  | 33/73 (45.2%)  | **+9.6%** |
| ast  | 37/73 (50.7%)  | 37/73 (50.7%)  | —       |
| 3pm  | 34/73 (46.6%)  | 34/73 (46.6%)  | —       |
| **overall** | **135/292 (46.2%)** | **142/292 (48.6%)** | **+2.4%** |

## Success Criteria

- [x] Rebound adjustment uses opponent DREB_pg with correct direction
- [x] Center and guard facing same opponent produce different reb adjustments
- [x] Rebound cap is ±10% (not ±15%)
- [x] Rebound hit rate above 40% → **45.2%**
- [x] All 493 tests pass
- [x] Per-stat before/after table recorded
