# Phase 24 Summary: Runtime Gating and MLB Scanner Reporting

## Completed

- Added v1.8 player-aware artifact gates to `MLBModel`.
- Added runtime support for `mlb_player_moneyline_artifact` bundles when all metadata gates pass.
- Rejected legacy non-bundle MLB moneyline artifacts so old heuristic injury-adjusted model paths are not used for live moneyline output.
- Added v1.8 prediction support for games carrying precomputed player-aware feature fields.
- Added fallback labels and reasons for v1.8, v1.3, and market-implied runtime paths.
- Added player-aware uncertainty flags for missing starters, lineups, bullpen, missing feature flags, and low source confidence.
- Added `runtime_report()` with source, validation metrics, promotion gates, rejections, and selective report fields.
- Updated `scripts/mlb_scanner.py` to print model labels, fallback/suppression reasons, validation metrics, and high-confidence feature context.
- Excluded suppressed or ineligible MLB games from moneyline parlay construction.
- Expanded artifact-gate tests for valid v1.8 scoring, uncertainty suppression, invalid artifact rejection, and legacy artifact rejection.

## Runtime Behavior

- Preferred path: validated v1.8 player-aware artifact with precomputed game features.
- Fallback path: validated v1.3 baseline bundle.
- Final fallback: market-implied probabilities, labeled and not pick-eligible.
- Player-aware predictions with uncertainty still display probabilities but are marked `LOW` confidence and excluded from pick/parlay output.

## Deferred

- A full live player-aware feature refresh/build pipeline remains deferred. Phase 24 enforces the runtime contract for precomputed player-aware features and artifact metadata.

