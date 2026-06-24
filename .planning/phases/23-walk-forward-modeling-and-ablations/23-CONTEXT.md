# Phase 23: Walk-Forward Modeling and Ablations - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Build the model-evaluation scaffold for player-aware MLB moneyline rows: baseline reproduction, ablation feature sets, date-based walk-forward train/calibration/test splits, model comparison, metrics, and artifact metadata. This phase should not change scanner runtime behavior.

</domain>

<decisions>
## Implementation Decisions

### the agent's Discretion
All implementation choices are at the agent's discretion. Use the roadmap, requirements, Phase 21 player-data contracts, Phase 22 feature-row contract, and existing v1.3 training style to guide implementation.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/engines/sports/mlb_training.py` defines the v1.3 baseline feature schema and leakage-safe team-state rows.
- `alpha/engines/sports/mlb_player_features.py` now exposes `build_player_aware_game_rows(...)`.
- `scripts/train_mlb_moneyline.py` has existing logistic/HistGradientBoosting training and Platt calibration patterns.
- `alpha/engines/sports/evaluation.py` provides probability metric helpers used by existing sports models.

### Established Patterns
- Keep model artifacts metadata-rich and fail closed when validation is insufficient.
- Keep tests deterministic and in-memory.
- Treat v1.3 as the baseline scorecard and compare player-aware ablations against it.

### Integration Points
- Phase 24 will consume artifact metadata and promotion gates for runtime gating/reporting.
- This phase can add modeling helpers and tests without deploying them in `mlb_model.py` yet.

</code_context>

<specifics>
## Specific Ideas

Run starter-only, starter-plus-lineup, starter-plus-lineup-plus-bullpen, and full player-aware ablations. Compare regularized logistic regression, HistGradientBoosting, and LightGBM when installed. Report all-games accuracy, Brier score, log loss, and calibration buckets.

</specifics>

<deferred>
## Deferred Ideas

Runtime scanner labels, pick suppression, confidence-gated output, and explanation display belong in Phase 24.

</deferred>
