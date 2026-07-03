# Phase 47: Paired Validation and Promotion Gates - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Provide paired validation for route-offset shadow output against the baseline on identical fixtures and block promotion unless gates pass.
</domain>

<decisions>
## Implementation Decisions

### Promotion Gates
- Require minimum sample size.
- Require no Brier regression.
- Require no log-loss regression.
- Require no BTTS/O/U2.5 Brier regression when those market labels are present.
</decisions>

<code_context>
## Existing Code Insights

Existing validation scripts use Brier/log-loss and fail-closed gates. v2.4 mirrors that pattern with a smaller route-offset-specific validator.
</code_context>

<specifics>
## Specific Ideas

Accept JSON and JSONL paired rows so scanner logs or manually curated shadow rows can be validated.
</specifics>

<deferred>
## Deferred Ideas

Real promotion remains blocked until actual graded route-offset shadow rows exist.
</deferred>
