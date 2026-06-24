# Phase 24: Runtime Gating and MLB Scanner Reporting - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Deploy the Phase 23 player-aware modeling contract conservatively: load v1.8 artifacts only when metadata and feature gates pass, label every MLB prediction source, fall back visibly to v1.3 or market-implied output, and prevent uncertain player-aware games from entering pick/parlay output.

</domain>

<decisions>
## Implementation Decisions

### Runtime Feature Availability

Do not attempt to infer full player-aware rows from live data inside `MLBModel` in this phase. The model may score v1.8 artifacts only when the game already carries the required precomputed player-aware feature fields. Missing or uncertain features trigger visible fallback.

### Legacy Behavior

Reject legacy non-bundle MLB moneyline artifacts at load time. Runtime should prefer validated v1.8, then validated v1.3, then market-implied fallback.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- `alpha/engines/sports/mlb_model.py` already gates v1.3 `mlb_win_probability_bundle` artifacts by validation flag and feature schema.
- `scripts/mlb_scanner.py` enriches games with `home_model_prob` / `away_model_prob` and prints today's win probabilities.
- Phase 23 added `alpha/engines/sports/mlb_player_modeling.py` with v1.8 feature-set constants and promotion metadata fields.

### Integration Points

- Runtime should accept `kind == "mlb_player_moneyline_artifact"` only if `validated`, `promotion_gates`, schema version, feature names, model, and calibrator are present.
- Scanner should show source labels and reasons:
  - `v1.8 player-aware`
  - `v1.3 baseline fallback`
  - `market-implied fallback`
  - unavailable / suppressed with reason

</code_context>

<specifics>
## Specific Ideas

- Add `MLBModel.runtime_report()` for model source, validation metrics, gates, coverage, and confidence-gated report fields.
- Add uncertainty thresholds for starter, lineup, bullpen, and missing player-aware features.
- Add prediction fields such as `model_label`, `fallback_reason`, `uncertainty_flags`, `confidence`, `pick_eligible`, and `feature_context`.
- Scanner should exclude `pick_eligible == False` moneyline games from parlay construction.

</specifics>

<deferred>
## Deferred Ideas

Building a full live day-of player-aware row generator from schedule, lineups, injuries, and player logs can be a later artifact-building or data-refresh task. Phase 24 only defines and enforces the runtime contract.

</deferred>

