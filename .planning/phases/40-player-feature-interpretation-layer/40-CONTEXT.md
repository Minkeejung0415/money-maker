# Phase 40: Player Feature Interpretation Layer - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Convert local player database rows into event-level MLB moneyline features.
</domain>

<decisions>
## Implementation Decisions

### Feature Interpretation
- Convert raw stats into starter, lineup, bullpen, absence, coverage, stale, and confidence features.
- Emit event-id keyed JSON files for scanner runtime.
- Prefer deterministic local snapshots over runtime scraping.
- Keep same-series variance visible through event-level starter/lineup/bullpen context.

### the agent's Discretion
Start with simple interpretable formulas and leave deeper pitch-level modeling for future requirements.
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/data/ingestion/mlb_player_database.py`
- `alpha/engines/sports/mlb_player_features.py`

### Established Patterns
- Event ids are scanner/runtime keys.

### Integration Points
- New interpreter module feeds scanner feature JSON files.
</code_context>

<specifics>
## Specific Ideas

Use source confidence and stale flags to gate betting picks.
</specifics>

<deferred>
## Deferred Ideas

Handedness splits, catcher effects, pitch mix, park/weather, and umpire features.
</deferred>
