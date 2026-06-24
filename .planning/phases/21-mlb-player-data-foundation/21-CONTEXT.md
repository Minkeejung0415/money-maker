# Phase 21: MLB Player Data Foundation - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the canonical MLB game and player-slot data foundation needed for later player-aware moneyline features. This phase should define stable normalized row contracts for games, starters, lineups, player identity joins, day-of availability, and explicit uncertainty. It should not replace the v1.3 team-only moneyline row builder or train a new model.

</domain>

<decisions>
## Implementation Decisions

### Table Boundaries
- Put the canonical Phase 21 data layer in `alpha/data/ingestion/mlb_player_data.py` with tests under `tests/unit/test_mlb_player_data.py`, matching existing MLB ingestion placement.
- Return normalized row lists/dicts first, with optional cache helpers only where useful. Later phases can choose durable feature-store persistence.
- Every game/player row should carry source, confirmation, and missing-reason fields where relevant so downstream models can gate uncertainty.
- Keep the v1.3 `build_pregame_rows` path untouched and build this as an additive player-data foundation.

### Source Priority
- Use MLB StatsAPI schedule data as the canonical schedule/game source because the repo already uses `statsapi.schedule()` for training and daily games.
- Add parser contracts and normalization hooks for Retrosheet/boxscore-style historical lineup rows, but keep network-heavy backfill behind explicit functions.
- Build an ID map schema that supports MLBAM, Retrosheet, Baseball Reference/FanGraphs placeholders, and explicit unmatched-player reporting.
- Prefer MLB StatsAPI/official game data for day-of availability; keep ESPN injuries as fallback only and document/test the current duplicate ESPN team ID risk.

### Failure Modes
- Preserve game rows when starters are missing, set starter fields to null, and attach missing-reason/source-confidence flags.
- Emit projected or unknown player-slot placeholders with `confirmed=false` only when game identity is known.
- Use `game_id` as the primary game identity and carry doubleheader/game-number fields; never dedupe by date/team alone.
- Produce an unmatched-ID report and continue with names plus source IDs so completeness can improve in later phases.

### Validation Surface
- Tests should prove normalization, deduplication, source/missing flags, ID matching, and no paid/network dependency in unit tests.
- Mock network calls in unit tests. Optional live smoke usage can exist outside default tests.
- Later phases should rely on stable functions such as `normalize_games`, `normalize_player_slots`, `build_player_id_map`, and `fetch_day_of_player_context`.
- Phase 21 is done when canonical tables can be built from representative mocked StatsAPI/lineup/ID inputs and all uncertainty is explicit.

### the agent's Discretion
No additional discretionary choices were delegated beyond following existing codebase conventions, keeping changes additive, and preserving leakage-safe modeling boundaries.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/data/ingestion/mlb_stats.py` already fetches team stats, player stats, probable pitchers, and today's games through pybaseball and MLB StatsAPI with `data/.mlb_cache`.
- `alpha/data/ingestion/mlb_injuries.py` already has ESPN injury ingestion, but it is a fallback-quality source and currently has a duplicate static ESPN ID for Milwaukee and New York Mets.
- `alpha/engines/sports/mlb_training.py` contains the validated v1.3 leakage-safe team-state feature builder and should remain the baseline path.
- `scripts/train_mlb_moneyline.py` already fetches historical completed MLB games via `statsapi.schedule()` and trains the current artifact.

### Established Patterns
- Existing ingestion functions return lists of dictionaries and fail closed to empty collections on external-source failures.
- Unit tests mock pybaseball/statsapi imports and patch cache directories, avoiding live network dependency.
- The sports modeling code values deterministic chronological ordering, stable feature schemas, and explicit artifact metadata.

### Integration Points
- Phase 21 should add a new ingestion module and tests without changing `FEATURE_NAMES` or the current v1.3 model.
- Later Phase 22 feature builders can consume the canonical `games`, `game_player_slots`, ID-map, and day-of context outputs.
- Runtime gating in Phase 24 can use the source/confirmed/missing fields created here to suppress or downgrade uncertain predictions.

</code_context>

<specifics>
## Specific Ideas

Use the user's report as the source of truth: prioritize starters, lineups, bullpen, and injury/absence availability; use free/official sources where practical; treat the current eight-feature MLB model as a baseline; optimize for accuracy and selective win rate before odds/EV expansion.

</specifics>

<deferred>
## Deferred Ideas

- Historical bulk Retrosheet/Chadwick downloads can be added after the normalization contracts exist.
- Starter, lineup, bullpen, and injury feature engineering belongs in Phase 22.
- Model ablations and LightGBM tuning belong in Phase 23.
- Scanner confidence-gating and explanation output belong in Phase 24.

</deferred>
