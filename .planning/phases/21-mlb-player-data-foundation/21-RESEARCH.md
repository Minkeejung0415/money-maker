# Phase 21 Research: MLB Player Data Foundation

## RESEARCH COMPLETE

### Existing Repo Patterns

- MLB ingestion lives under `alpha/data/ingestion/` and returns list/dict records with defensive empty-result behavior on external failures.
- MLB unit tests patch external modules such as `statsapi` and `pybaseball`, and patch cache directories rather than calling live services.
- The v1.3 validated model lives in `alpha/engines/sports/mlb_training.py` and must remain untouched as the baseline.
- `scripts/train_mlb_moneyline.py` already normalizes schedule rows from MLB StatsAPI enough for team-only training, but it does not represent player slots, lineups, or ID mappings.
- `alpha/data/ingestion/mlb_injuries.py` is useful as a fallback but has source-quality risk, including a duplicate static ESPN team ID.

### Recommended Technical Shape

- Add `alpha/data/ingestion/mlb_player_data.py` as an additive module.
- Define dataclasses for canonical row contracts, then expose dict-returning normalizers to stay compatible with existing ingestion style.
- Use `game_id` as the primary identity for deduplication. Keep `doubleheader` / `game_number` metadata where available.
- Normalize lineups from generic dict rows first so Phase 21 can support Retrosheet/boxscore/StatsAPI-shaped inputs without network-heavy backfill.
- Add `build_player_id_map` and `report_unmatched_players` so Phase 22 can safely join MLBAM, Retrosheet, and later Statcast/Savant features.
- Add `fetch_day_of_player_context` with injected schedule/lineup/injury providers, allowing default tests to stay mocked and network-free.

### Risks and Mitigations

- **Risk:** Accidentally replacing the v1.3 training schema.  
  **Mitigation:** New module only; no changes to `FEATURE_NAMES` or `build_pregame_rows`.
- **Risk:** Missing starters or lineups cause row loss.  
  **Mitigation:** Preserve rows with `confirmed=false`, nullable IDs, and explicit `missing_reason`.
- **Risk:** Player-name matching hides bad joins.  
  **Mitigation:** Return unmatched reports rather than fuzzy auto-correcting IDs.
- **Risk:** Day-of fetch tests become flaky.  
  **Mitigation:** Use dependency injection and mocked providers in unit tests.

### Plan Recommendation

One execution plan is sufficient: implement canonical data contracts, normalizers, day-of context assembly, and unit tests in a single wave.
