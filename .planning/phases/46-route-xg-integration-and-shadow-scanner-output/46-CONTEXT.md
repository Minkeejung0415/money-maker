# Phase 46: Route xG Integration and Shadow Scanner Output - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Integrate route deltas into the scoreline surface and expose baseline-vs-adjusted diagnostics in scanner output.
</domain>

<decisions>
## Implementation Decisions

### Scoreline Integration
- Baseline scoreline calibration remains unchanged.
- Route-offset adjusted distributions can skip baseline WDL recalibration so WDL, BTTS, and totals are regenerated from adjusted lambdas.
- Promoted mode can apply adjusted WDL only when route-offset eligibility passes.
</decisions>

<code_context>
## Existing Code Insights

`WCScorelineModel.build()` already centralizes scoreline-derived markets. `wc_scanner.py` already has props-only and individual-only reporting paths.
</code_context>

<specifics>
## Specific Ideas

Print xG movement, O/U2.5, BTTS, status, reason, eligibility, and applied flag.
</specifics>

<deferred>
## Deferred Ideas

No automatic sportsbook/EV use of route offsets until validation.
</deferred>
