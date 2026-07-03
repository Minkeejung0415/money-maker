# Phase 43: Route Offset Contracts and Baseline Harness - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish a route-offset runtime contract that keeps WC hybrid as the prior and makes missing, stale, or mismatched route-offset inputs fail closed to the baseline.
</domain>

<decisions>
## Implementation Decisions

### Runtime Contract
- Route offsets are schema-versioned as `wc_route_offsets_v1`.
- Rule/config identity is explicit as `wc_route_offsets_rule_config_v1`.
- Missing snapshots return fallback diagnostics and zero deltas.
- Shadow mode is default; promoted application requires explicit scanner mode and eligibility.
</decisions>

<code_context>
## Existing Code Insights

`scripts/wc_scanner.py` already exposes requested/active/fallback labels. `WCScorelineModel` is the safest integration point because it owns BTTS, totals, and scoreline-derived probabilities.
</code_context>

<specifics>
## Specific Ideas

Treat player/tactical data as route-xG offsets, not raw WDL features.
</specifics>

<deferred>
## Deferred Ideas

No automatic production promotion before paired validation.
</deferred>
