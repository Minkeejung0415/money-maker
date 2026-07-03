# Phase 44: Role Strength Snapshot and Projected XI Inputs - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Load projected-XI role strengths for GK, CB, FB, DM, winger, and striker with coverage, source, update time, and missing-role diagnostics.
</domain>

<decisions>
## Implementation Decisions

### Snapshot Contract
- Snapshots may be keyed by `event_id` or `Home|Away`.
- Role payloads live under `home.roles` and `away.roles`.
- Missing required roles reduce coverage and shrink route offsets.
- Critical missing role data suppresses route-offset pick eligibility.
</decisions>

<code_context>
## Existing Code Insights

The repo already has player role feature ideas in `wc_player_features.py`; v2.4 uses a runtime snapshot instead of a trained player model.
</code_context>

<specifics>
## Specific Ideas

Use compact JSON so projected XI data can be manually supplied or generated later.
</specifics>

<deferred>
## Deferred Ideas

Automated projected-XI fetching remains future work.
</deferred>
