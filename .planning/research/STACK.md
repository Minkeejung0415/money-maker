# Stack Research: MLB Win Probability Model

## Existing Stack to Reuse

- Python 3.11+ project runtime
- MLB StatsAPI (`statsapi`) for schedules, final scores, and probable pitchers
- `pybaseball` for season/team/pitcher statistics
- Existing `MLBModel`, `MLBScanner`, `EVCalculator`, and probability metrics
- Existing `walkforward_splits`, Brier score, log loss, and reliability tables

## Additions

- A deterministic training script under `scripts/` using pandas and scikit-learn/XGBoost already available in the project environment
- A versioned model artifact plus JSON metadata containing feature schema, training window, validation metrics, calibration method, and creation time
- Optional isotonic or sigmoid calibration selected using validation data only

## Recommendation

Start with regularized logistic regression as the transparent benchmark, then compare gradient-boosted trees. Ship whichever wins out-of-time Brier score and log loss after calibration. Do not add deep learning or paid data.
