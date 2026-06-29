# Phase 41: MLB Accuracy Retraining and Promotion - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Extend MLB player-aware evaluation and promotion plumbing so richer stats can be trusted only when they improve probability quality.
</domain>

<decisions>
## Implementation Decisions

### Accuracy Gates
- Evaluate Brier score, log loss, accuracy, selective win rate, and coverage.
- Keep walk-forward ablations as the main proof.
- Promotion metadata should stay compatible with runtime artifact registry concepts.
- Do not silently promote a richer artifact unless it beats baseline.

### the agent's Discretion
Implement evaluation metadata plumbing without forcing a heavyweight retraining run during this phase.
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/engines/sports/mlb_player_modeling.py`
- `scripts/build_mlb_player_v18.py`

### Established Patterns
- Walk-forward splits and ablations already exist.

### Integration Points
- New `scripts/evaluate_mlb_player_accuracy.py`.
</code_context>

<specifics>
## Specific Ideas

Add selective metrics so confidence-gated picks can be judged separately from all-game accuracy.
</specifics>

<deferred>
## Deferred Ideas

Running a full historical retrain depends on richer historical local database coverage.
</deferred>
