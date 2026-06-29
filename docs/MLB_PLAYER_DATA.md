# MLB Player Data Runtime Policy

## Runtime-Required Sources

- MLB StatsAPI schedule data for slate identity, teams, event ids, and probable pitcher fields when available.
- Local MLB player database snapshots under `data/mlb/player_database/`.
- Date-specific event feature files under `data/mlb/player_features/`.

## Optional Enrichment

- pybaseball/Fangraphs-derived season stats are optional only.
- The MLB scanner does not call those sources by default because live scraping can fail with blocked requests.
- Use `--allow-external-player-stats` only when intentionally allowing external enrichment during a scanner run.

## Daily Flow

1. Update local database:

   ```powershell
   ./venv/Scripts/python.exe ./scripts/update_mlb_player_database.py --date 2026-06-28 --batters-csv data/mlb/raw/batters_2026-06-28.csv --pitchers-csv data/mlb/raw/pitchers_2026-06-28.csv
   ```

2. Build slate features:

   ```powershell
   ./venv/Scripts/python.exe ./scripts/build_mlb_player_features.py --date 2026-06-28
   ```

3. Run scanner:

   ```powershell
   ./venv/Scripts/python.exe ./scripts/mlb_scanner.py --date 2026-06-28 --individual-only
   ```

## Runtime Labels

Scanner context includes:

- `player_data_source`
- `player_data_last_updated`
- `player_source_confidence`
- `lineup_source_confidence`
- `player_data_stale_flag`
- suppression reasons when data is weak or stale

## Promotion Rule

Richer player stats should not be trusted just because they exist. A candidate MLB artifact must beat the current runtime baseline in walk-forward evaluation before promotion metadata sets `promotion_passed=true` and `allowed_runtime=true`.
