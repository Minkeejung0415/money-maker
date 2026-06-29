# Phase 37 Research: MLB Series Variance and Player Database

**Status:** Complete
**Date:** 2026-06-28

## Research Summary

Phase 37 should be planned as three waves:

1. Fix the live inference date/series variance bug.
2. Add a local DuckDB/parquet player-stat database fed by daily raw logs.
3. Wire database-derived live features into MLB scanner output with visible freshness and suppression labels.

## Key Findings

### Same-Series Repeated Probability Risk

`scripts/mlb_scanner.py` passes `args.date` to `fetch_today_games(args.date)`, but does not pass `args.date` to `build_live_player_features(...)`. The feature builder defaults to `date.today()`, so a scanner run for an explicit slate can use probable pitchers from the wrong date. When named starters are missing, it falls back to team-level quality, which can make three-game series outputs look nearly identical.

Primary files:

- `scripts/mlb_scanner.py`
- `alpha/data/ingestion/mlb_live_player_features.py`
- `tests/unit/test_mlb_live_player_features.py`
- `tests/unit/test_mlb_scanner.py`

### Existing Player-Aware Foundation

The repo already has deeper player-aware feature code that the live scanner does not yet use:

- `alpha/data/ingestion/mlb_player_data.py` normalizes games, player slots, ID maps, injuries, and unmatched players.
- `alpha/engines/sports/mlb_player_features.py` computes starter, lineup, bullpen, and absence features with leakage guards.
- `alpha/engines/sports/mlb_player_modeling.py` defines feature sets from `starter_only` through `full_player_aware`.
- `MLBModel._player_uncertainty_flags()` already supports suppression for missing player, lineup, starter, and bullpen data.

### Database Direction

The first player database should be local, inspectable, and append-friendly:

- Use DuckDB/parquet for queryable local analytics over CSV-style data.
- Append raw daily player/team logs instead of only overwriting season totals.
- Compute derived stats locally from raw components, such as ERA from earned runs and innings pitched, and batting average from hits and at-bats.
- Produce cumulative and rolling features, with first rolling windows at 7, 14, and 30 days where data exists.

### Runtime Rollout

The first implementation should not immediately retrain a new artifact. It should:

- Fix live inference date propagation first.
- Add richer database-fed live features.
- Keep research probabilities visible.
- Suppress betting picks when player-data freshness, lineup confidence, starters, or bullpen features are incomplete.
- Make repeated series outputs diagnosable through printed feature context.

## Recommended Plan Structure

### Wave 1: Fix Live Inference Variance

Patch `scripts/mlb_scanner.py` to pass `args.date` into `build_live_player_features()`. Add tests proving explicit date propagation and same-series starter variance.

### Wave 2: Build Local Player Stats Store

Add a small local database module that can ingest CSV/raw daily rows, persist normalized parquet/DuckDB data, and compute cumulative plus rolling derived stats.

### Wave 3: Use Database Features In Scanner

Merge database-derived features into `game["player_features"]`, print freshness/source context, and suppress picks when required player-data gates are weak.

## Open Risks

- DuckDB may not be installed in the environment; plans should allow a graceful optional dependency or a parquet/CSV fallback if the repo does not already depend on it.
- Public CSV source schemas may vary; ingestion should normalize from internal row dictionaries and keep source-specific adapters thin.
- A database-fed live feature path can change probabilities without retraining, but a future artifact retrain will still be needed for full value.

## Research Complete
