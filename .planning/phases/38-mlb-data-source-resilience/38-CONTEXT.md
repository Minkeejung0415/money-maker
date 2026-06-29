# Phase 38: MLB Data Source Resilience - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Remove Fangraphs/pybaseball scraping as a required MLB scanner runtime dependency and make source/fallback labels visible.
</domain>

<decisions>
## Implementation Decisions

### Runtime Policy
- MLB StatsAPI remains the schedule/game-id/probable-pitcher source.
- pybaseball/Fangraphs-backed stats are optional enrichment only.
- The scanner defaults to local/artifact features and requires an explicit flag for external player-stat lookups.
- Every fallback should produce visible source labels.

### the agent's Discretion
Use existing scanner and live-feature-builder patterns with minimal CLI additions.
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/mlb_scanner.py`
- `alpha/data/ingestion/mlb_live_player_features.py`
- `alpha/data/ingestion/mlb_stats.py`

### Established Patterns
- Scanner output already prints feature context.
- Existing v1.8 artifact team state can provide fallback quality.

### Integration Points
- `build_live_player_features(...)` is the runtime feature boundary.
</code_context>

<specifics>
## Specific Ideas

Add `--allow-external-player-stats` and keep external stats disabled by default.
</specifics>

<deferred>
## Deferred Ideas

Paid MLB data feeds remain out of scope.
</deferred>
