# Phase 22 Research: Player-Aware Feature Builder

## RESEARCH COMPLETE

### Existing Inputs

- Phase 21 created canonical game rows with `game_id`, `game_date`, teams, starters, scores, target, doubleheader metadata, confirmation, and missing-reason fields.
- Phase 21 created canonical player slots with `game_id`, `team`, `side`, `player_id`, `player_name`, batting order, position, confirmation, source, and missing-reason fields.
- The existing v1.3 MLB baseline remains in `alpha/engines/sports/mlb_training.py` and should not be modified.

### Recommended Shape

- Add `alpha/engines/sports/mlb_player_features.py`.
- Expose `build_player_aware_game_rows(...)` as the main Phase 23 contract.
- Keep helper functions pure and list/dict based so tests can use small in-memory fixtures.
- Use "strictly before game" as the default history rule. Same-day doubleheaders should not leak by default.
- Add `allow_between_games=True` as an explicit opt-in for workflows that intend to predict between doubleheader games.

### Feature Blocks

- Starter features: shifted pitcher quality, workload, rest, and missing flags.
- Lineup features: mean/top-order batting value, handedness/platoon proxy, missing count, confirmed share.
- Bullpen features: shifted recent relief workload and quality proxies.
- Absence features: structured missing-player value deltas from absence rows, not crude average/HR penalties.

### Risk Controls

- No model training in this phase.
- No live data fetches in tests.
- No v1.3 feature schema edits.
- Direct tests for target-game exclusion and same-day doubleheader behavior.
