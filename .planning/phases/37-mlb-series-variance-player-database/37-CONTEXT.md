# Phase 37: MLB Series Variance and Player Database - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase fixes MLB moneyline predictions that stay too similar across games in the same series, then adds the first live player-data foundation for MLB picks. The target is not a full prop system yet; it is better MLB moneyline context from major player/team inputs: probable starters, basic batter strength, bullpen state, lineup availability, and CSV-backed player stat ingestion.

</domain>

<decisions>
## Implementation Decisions

### Phase Scope
- **D-01:** Treat this as **Phase 37**.
- **D-02:** Phase 37 should include both an immediate bug audit/fix and the first player-data database layer for MLB moneyline picks.
- **D-03:** The repeated-probability symptom should be investigated first, especially same-series games where team-level features are identical but starters, lineups, and bullpen state should differ.

### Data Depth
- **D-04:** Start with **major stats first** rather than attempting a full player model all at once.
- **D-05:** First ingestable data should cover probable starters, starter quality, batter basics, lineup strength, bullpen quality/workload, and basic injury/absence impact.
- **D-06:** CSV downloads from public/stat websites are acceptable for the first version, as long as schemas are normalized into canonical local tables/files before model use.
- **D-07:** Grow later into deeper features such as handedness splits, park/weather, pitch mix, platoon matchups, catcher effects, fatigue, rolling batter form, and more granular bullpen availability.
- **D-08:** Use **CSV-first major stat loading**, but design it so daily updates are easy and repeatable.
- **D-09:** Do not blindly trust precomputed website stats when raw components are available. Store raw components and compute derived stats locally, such as ERA = earned runs / innings pitched * 9 and batting average = hits / at-bats.
- **D-10:** Append daily game logs rather than only overwriting season totals, so the system can recompute both season-to-date and recent-form stats.
- **D-11:** Compute both cumulative and rolling stats. Rolling windows should include useful recent-form windows such as last 7, 14, and 30 days where data supports it.
- **D-12:** DuckDB/parquet is preferred for the first local player database because it fits growing CSV-style sports data while staying local, inspectable, and queryable.

### Runtime Behavior
- **D-13:** When fresh player data is incomplete, the scanner should **label and suppress** low-confidence picks rather than quietly outputting them as trusted bets.
- **D-14:** Probabilities may still be displayed for research, but pick eligibility should be false when starters, lineups, or bullpen features are missing or stale.
- **D-15:** Scanner output should expose the data freshness/source behind the probability so repeated outcomes are explainable.
- **D-16:** Before confirmed lineups are available, the scanner may use probable starters plus projected/basic lineup context for research probabilities, but betting picks should remain suppressed unless lineup confidence is acceptable.

### Specific Bug To Investigate
- **D-17:** `scripts/mlb_scanner.py` added `--date`, but currently calls `build_live_player_features(games, team_quality_override=...)` without passing `game_date=args.date`.
- **D-18:** Because `build_live_player_features()` defaults to `date.today()`, running a past/future slate can use the wrong probable-pitcher date.
- **D-19:** If named pitchers are missing, the live feature builder falls back to team-level quality, which can make all games in a three-game matchup look nearly identical.
- **D-20:** The v1.8 runtime currently uses a shallow starter-only live feature builder even though deeper lineup/bullpen/player feature code already exists.
- **D-21:** Rollout should fix live inference first: date propagation, starter variance, visible feature context, and database-fed live features should come before retraining a new MLB artifact.

### the agent's Discretion
- Choose the storage format for the first local player database, but prefer simple, inspectable files and deterministic schemas over a heavy service.
- Choose exact feature names to match existing modeling conventions, as long as output clearly labels missing/stale player data.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### MLB Scanner And Runtime
- `scripts/mlb_scanner.py` - CLI date handling, live player feature injection, output labeling, and pick suppression behavior.
- `alpha/engines/sports/mlb_model.py` - v1.8 player-aware runtime, fallback behavior, uncertainty flags, and feature context.
- `alpha/data/ingestion/mlb_live_player_features.py` - current live starter-only feature builder; likely date propagation bug lives at this integration.

### Existing Player Data Foundation
- `alpha/data/ingestion/mlb_player_data.py` - canonical game/player-slot normalization, day-of context assembly, ID mapping, unmatched player reporting.
- `alpha/engines/sports/mlb_player_features.py` - existing leakage-safe starter, lineup, bullpen, absence, and player-aware game feature construction.
- `alpha/engines/sports/mlb_player_modeling.py` - feature set definitions including starter, lineup, and bullpen feature groups.
- `scripts/build_mlb_player_v18.py` - current v1.8 player-aware artifact builder; starts from team/starter proxy features only.

### Tests
- `tests/unit/test_mlb_live_player_features.py` - starter/live feature behavior and fallback tests.
- `tests/unit/test_mlb_player_data.py` - canonical player data normalization tests.
- `tests/unit/engines/test_mlb_player_features.py` - lineup and bullpen feature behavior.
- `tests/unit/engines/test_mlb_artifact_gate.py` - player-aware artifact gating, uncertainty flags, and suppression behavior.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `build_live_player_features()` already computes starter-only features and can be fixed to use scanner `--date`.
- `fetch_day_of_player_context()` already normalizes schedule, lineups, injuries, and unmatched player reports through injectable providers.
- `build_player_aware_game_rows()` already computes lineup strength, top-order strength, bullpen workload, bullpen quality, absence value, and missing-data flags.
- `MLBModel._player_uncertainty_flags()` already supports suppressing picks for missing player, lineup, starter, and bullpen data.

### Established Patterns
- Runtime should not silently trust incomplete artifacts or data; v2.0 established explicit fallback labels.
- Betting recommendations should be suppressed when uncertainty flags are present, while research probabilities can still be displayed.
- Existing player-aware training is leakage-conscious; live feature work should preserve pregame-only data boundaries.

### Integration Points
- `scripts/mlb_scanner.py` should pass `args.date` into live player feature builders.
- The live player-data database should feed `game["player_features"]` before `MLBModel.predict(game)`.
- The model context output should add data-source/freshness fields so same-series repeated probabilities are diagnosable.

</code_context>

<specifics>
## Specific Ideas

- The user specifically noticed same matchup probabilities repeating across a three-game MLB series and wants a check for an error.
- The user wants to start by downloading/importing CSV data from websites for major stats, then grow into a more diverse and deeper algorithm.
- Major-stats-first should prioritize useful moneyline context before attempting player prop expansion.
- The user wants stats to update from daily raw inputs. Example: if a pitcher allows 3 runs in 4 innings, the local derived ERA should change from the raw component update rather than waiting for a precomputed stat export.
- The desired first database should support complex stats from the start by keeping raw components available for formulas, not just storing final aggregate columns.

</specifics>

<deferred>
## Deferred Ideas

- Full MLB player-prop odds ingestion remains a separate phase unless a dependable prop-line source is chosen.
- Deep algorithm expansion beyond major stats, such as pitch-level modeling, weather/park interaction, umpire effects, and advanced platoon modeling, should follow after the first database and suppression behavior are proven.

</deferred>

---

*Phase: 37-MLB Series Variance and Player Database*
*Context gathered: 2026-06-28*
