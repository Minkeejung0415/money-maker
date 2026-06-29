# Phase 39: Automated Player Database Updates - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Add repeatable date-based local MLB player database update commands from CSV-style inputs.
</domain>

<decisions>
## Implementation Decisions

### Database Update Shape
- Use a JSON database snapshot for the first automated version.
- Preserve raw components and metadata rather than only derived stats.
- Make imports idempotent and safe to re-run.
- Keep tests network-free with local fixtures.

### the agent's Discretion
Add CSV helpers and normalizers where the existing database module already owns raw row shapes.
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/data/ingestion/mlb_player_database.py`

### Established Patterns
- Pure functions and deterministic test fixtures.

### Integration Points
- New script under `scripts/update_mlb_player_database.py`.
</code_context>

<specifics>
## Specific Ideas

Support batter, pitcher, bullpen, lineup, and absence CSV inputs.
</specifics>

<deferred>
## Deferred Ideas

Fully automatic web downloading remains follow-up once source contracts are stable.
</deferred>
