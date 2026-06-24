# Phase 22: Player-Aware Feature Builder - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Build leakage-safe MLB player-aware feature rows from the Phase 21 canonical game and player-slot contracts. This phase should create starter, lineup, bullpen, and absence feature builders plus tests proving target-game exclusion. It should not train, calibrate, tune, or deploy a model.

</domain>

<decisions>
## Implementation Decisions

### Feature Module Boundary
- Add a new additive module at `alpha/engines/sports/mlb_player_features.py`.
- Keep `alpha/engines/sports/mlb_training.py` and the v1.3 `FEATURE_NAMES` baseline unchanged.
- Expose dict/list feature builders usable by Phase 23 modeling.
- Treat Phase 21 canonical `games`, `game_player_slots`, ID-map, and day-of context outputs as the input contract.

### Feature Semantics
- Represent starter features as differential pregame features from shifted pitcher rows: quality, rest, workload, and missing flags.
- Represent lineup features as aggregates: lineup strength, top-order strength, handedness/platoon proxy, missing count, confirmed share, and source-confidence flags.
- Represent bullpen features as team-day summaries from shifted recent relief appearances: workload and available quality proxies.
- Represent injuries and absences as structured absence deltas by player slots and player values, never average/HR-only team penalties.

### Leakage Rules
- Sort by entity/date/game, apply `shift(1)` before rolling/expanding/aggregation, and test target-game exclusion directly.
- Same-day doubleheaders default to no same-day leakage: game two cannot consume game one unless an explicit `allow_between_games=True` flag is used.
- Missing player values should emit missing counts/flags and use conservative neutral fills only at final aggregation boundaries.
- Confirmed and projected lineups should both compute aggregate values plus confidence fields such as `lineup_confirmed_share` for later runtime gating.

### Validation Scope
- Tests should prove starter, lineup, bullpen, and absence features are computed from shifted prior data and include missing/confidence fields.
- Use tiny deterministic in-memory game/player logs with two dates and a doubleheader edge case.
- Expose stable `build_player_aware_game_rows(...)` returning one row per game with `home_win` target when available.
- Do not add modeling in this phase. LightGBM/training/calibration belongs in Phase 23.

### the agent's Discretion
Implementation details such as exact helper names, neutral fallback constants, and small internal dataclasses are at the agent's discretion as long as the public row-builder contract and leakage guarantees are preserved.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 21 added `alpha/data/ingestion/mlb_player_data.py` with canonical `normalize_games`, `normalize_player_slots`, `build_player_id_map`, `report_unmatched_players`, and `fetch_day_of_player_context`.
- Phase 21 tests prove the v1.3 `FEATURE_NAMES` path remains unchanged.
- Existing v1.3 `alpha/engines/sports/mlb_training.py` shows the desired leakage-safe style: chronological ordering, target rows before state updates, and a stable feature schema.

### Established Patterns
- Sports engine modules use small dict-returning helpers and focused pytest coverage.
- Current MLB model artifacts rely on explicit feature names, sorted rows, and fail-closed validation.
- Unit tests should be fully in-memory and should not require network calls.

### Integration Points
- Phase 23 will consume `build_player_aware_game_rows(...)` for ablation modeling.
- Phase 24 can consume missing/confidence fields for runtime gating.
- Existing v1.3 team-only baseline remains the comparison path and should not be modified in this phase.

</code_context>

<specifics>
## Specific Ideas

Prioritize the report's highest-impact player-aware blocks: starting-pitcher quality/rest, lineup strength and platoon context, bullpen workload/freshness, and injury/absence deltas. Accuracy and high-confidence win rate remain the goal; odds/EV and model training are deferred.

</specifics>

<deferred>
## Deferred Ideas

- Model ablations, LightGBM tuning, calibration, and artifact persistence belong in Phase 23.
- Runtime pick suppression/downgrade behavior belongs in Phase 24.
- Defense, catcher, and baserunning feature blocks remain future requirements unless they become cheap additions after the core four blocks are validated.

</deferred>
