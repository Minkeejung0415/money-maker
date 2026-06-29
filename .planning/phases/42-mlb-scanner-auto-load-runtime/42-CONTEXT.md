# Phase 42: MLB Scanner Auto-Load Runtime - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the MLB scanner automatically use local date-specific player feature files when present.
</domain>

<decisions>
## Implementation Decisions

### Scanner Runtime
- Manual `--player-features-file` remains highest priority.
- Auto-load checks `data/mlb/player_features/mlb_player_features_<date>.json`.
- Scanner prints whether local features were found.
- Weak/stale feature metadata continues to suppress picks through MLBModel uncertainty flags.

### the agent's Discretion
Keep auto-load path simple and filesystem-based.
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/mlb_scanner.py`
- `alpha/engines/sports/mlb_model.py`

### Established Patterns
- Scanner already prints individual feature context.

### Integration Points
- `_resolve_player_features_file(...)`
</code_context>

<specifics>
## Specific Ideas

Do not require local feature files; absence should be labeled and scanner should still run.
</specifics>

<deferred>
## Deferred Ideas

Real sportsbook odds auto-ingestion.
</deferred>
