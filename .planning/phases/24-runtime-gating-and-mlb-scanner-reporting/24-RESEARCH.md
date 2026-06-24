# Phase 24 Research: Runtime Gating and MLB Scanner Reporting

## Existing Runtime Behavior

- `MLBModel` loads `alpha/models/mlb_win_probability.pkl` first, then legacy model locations under `mlb_outcomes/`.
- Valid v1.3 bundles require:
  - `kind == "mlb_win_probability_bundle"`
  - `validated == True`
  - `feature_names == mlb_training.FEATURE_NAMES`
- Legacy non-bundle models are still accepted and use heuristic team/pitcher/injury feature building.
- Scanner prints win probabilities only when `_model_bundle` is loaded; otherwise it prints `model unavailable`.

## Required Runtime Changes

- Prefer v1.8 player-aware artifacts when valid.
- Fall back to v1.3 bundles when v1.8 is missing, invalid, or cannot score the specific game.
- Label fallback reasons clearly.
- Prevent uncertain v1.8 predictions from becoming picks.
- Reject legacy non-bundle artifacts so old crude injury penalties are not used for moneyline output.

## Artifact Contract

A v1.8 runtime artifact must include:

- `kind: "mlb_player_moneyline_artifact"`
- `schema_version` or `model_version`: `mlb-player-v1.8`
- `validated: true`
- `promotion_gates` with all gates truthy
- `feature_names`
- `model`
- `calibrator`
- `metrics`

## Runtime Scoring Contract

`MLBModel` can score v1.8 only when required feature names exist either at the game top level or under `game["player_features"]`. Missing required features or uncertainty flags produce fallback instead of silent imputation.

