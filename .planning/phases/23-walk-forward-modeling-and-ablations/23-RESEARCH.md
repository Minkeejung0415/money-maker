# Phase 23 Research: Walk-Forward Modeling and Ablations

## Existing Assets

- `alpha/engines/sports/mlb_training.py` defines the v1.3 baseline feature schema through `FEATURE_NAMES`.
- `scripts/train_mlb_moneyline.py` already trains logistic and HistGradientBoosting candidates with chronological train/calibration/test windows and Platt calibration.
- `alpha/engines/sports/evaluation.py` provides Brier score, log loss, and reliability bucket helpers.
- Phase 22 added player-aware row columns for starter, lineup, bullpen, and absence feature blocks.

## Constraints

- Runtime scanner behavior should remain unchanged in this phase.
- Modeling helpers must be deterministic and testable in memory.
- LightGBM must be optional because it is not guaranteed in local or CI environments.
- Promotion metadata must be serializable and must carry enough detail for Phase 24 runtime gates.

## Direction

Add a reusable MLB player-aware modeling module with:

- Named feature-set ablations, including exact v1.3 baseline reproduction.
- Date-ordered expanding walk-forward folds with separate train, calibration, and test blocks.
- Candidate model factories for logistic regression, HistGradientBoosting, and optional LightGBM.
- Platt-style sigmoid calibration on the calibration block.
- Fold and aggregate metrics: Brier score, log loss, accuracy, and calibration buckets.
- Promotion artifact metadata containing schema version, features, split dates, fingerprints, metrics, and gates.

