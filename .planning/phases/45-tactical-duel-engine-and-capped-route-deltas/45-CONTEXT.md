# Phase 45: Tactical Duel Engine and Capped Route Deltas - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Convert role-strength matchups into capped xG deltas for wing, set-piece, and counterattack routes.
</domain>

<decisions>
## Implementation Decisions

### Duel Rules
- Start with three explainable deterministic rules.
- Every active duel emits rule id, side, route, raw value, delta, and shrink factor.
- Rule caps and team caps are enforced by config.
</decisions>

<code_context>
## Existing Code Insights

Existing tactical comparison modules keep explainability separate from production gates. Route offsets follow the same pattern.
</code_context>

<specifics>
## Specific Ideas

Implement wing isolation, aerial/set-piece mismatch, and press-vs-build first.
</specifics>

<deferred>
## Deferred Ideas

Learned duel weights are deferred until enough graded route-offset data exists.
</deferred>
