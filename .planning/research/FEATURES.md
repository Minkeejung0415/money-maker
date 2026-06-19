# Feature Research: MLB Win Probability Model

## Table Stakes

- Historical game outcomes with stable team identifiers and dates
- Pregame-only rolling team offense and run-prevention features
- Starting pitcher quality and rest when known, with explicit missingness indicators
- Home-field indicator, team rest, recent form, and season context
- Time-ordered train/validation/test partitions
- Calibrated home/away probabilities summing to 1.0
- Daily output for every game with model source, fair decimal odds, and validation status

## Differentiators

- Reliability table and Brier/log-loss report beside headline accuracy
- Baselines: 50/50, historical home-win rate, and sportsbook no-vig probability when manual odds are supplied
- Model metadata gate that prevents stale or schema-incompatible artifacts from loading silently
- Prediction logging for later grading and recalibration

## Deferred

- Player props
- Parlays and Kelly sizing
- Paid live odds
- In-game predictions
