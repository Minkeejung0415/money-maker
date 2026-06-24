# Phase 23 Summary: Walk-Forward Modeling and Ablations

## Completed

- Added `alpha/engines/sports/mlb_player_modeling.py` for player-aware MLB moneyline walk-forward evaluation.
- Defined side-by-side ablation feature sets:
  - `baseline_v1_3`
  - `starter_only`
  - `starter_lineup`
  - `starter_lineup_bullpen`
  - `full_player_aware`
- Implemented expanding date-based train/calibration/test folds.
- Added candidate model factories for logistic regression, HistGradientBoosting, and optional LightGBM.
- Added sigmoid calibration and probability scoring with Brier score, log loss, accuracy, and reliability buckets.
- Added promotion helper and metadata builder for Phase 24 runtime gating.
- Added deterministic unit tests covering feature-set contracts, chronological splits, ablation reporting, optional LightGBM, and metadata fields.

## Integration Notes

- Runtime MLB scanner behavior is unchanged.
- The v1.3 eight-feature schema is preserved exactly through `BASELINE_FEATURES = FEATURE_NAMES`.
- Missing player-aware columns are converted to `NaN` and handled by model imputers.
- Tiny or one-class training folds fall back to a prior-probability model instead of crashing.

## Follow-Up

- Phase 24 should consume the artifact metadata fields and enforce runtime fallback, uncertainty labeling, and scanner reporting gates.

