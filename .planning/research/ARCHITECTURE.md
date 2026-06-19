# Architecture Research: MLB Win Probability Model

## Data Flow

1. Historical collector downloads completed games and pregame-available statistics.
2. Dataset builder sorts chronologically and shifts/rolls every statistic so the target game never contributes to its own features.
3. Trainer compares logistic and boosted-tree candidates, calibrates on a separate validation window, and evaluates on untouched future games.
4. Artifact writer stores the estimator and metadata atomically under `mlb_outcomes/models/`.
5. `MLBModel` loads only artifacts whose feature schema and validation metadata pass checks.
6. `mlb_scanner.py` shows every matchup, home/away probability, fair odds, model version, and validation status.

## Integration Points

- Extend `alpha/data/ingestion/mlb_stats.py` for historical game retrieval and team-name normalization.
- Add a shared pregame feature builder used by both trainer and live inference.
- Keep `MLBModel.predict()` as the public runtime contract.
- Reuse `alpha/engines/sports/evaluation.py` for Brier score, log loss, reliability, and walk-forward splits.

## Build Order

Data contract and leakage tests, then trainer/evaluation, then artifact gate, then scanner presentation.
