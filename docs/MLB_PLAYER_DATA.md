# MLB Player Data Runtime Policy

## Runtime-Required Sources

- MLB StatsAPI schedule data for slate identity, teams, event ids, and probable pitcher fields when available.
- Local MLB player database snapshots under `data/mlb/player_database/`, restricted to value/advanced player inputs.
- Date-specific event feature files under `data/mlb/player_features/`.

## Player Database Stat Contract

The player database should not store raw surface stats for player value
calculation. Batting average, ERA, hits, at-bats, home runs, RBI, wins, losses,
earned runs, and innings pitched are upstream ingredients only. Convert them
before import.

Player stats should not be handed to the final moneyline model as raw,
same-status columns. The runtime translates player inputs into expected run
impact first:

```text
player stat -> runs above replacement today -> game run differential -> calibrated win probability
```

The main runtime deltas are:

- `starter_run_value_diff`
- `lineup_run_value_diff`
- `top_order_run_value_diff`
- `bullpen_run_value_diff`
- `absence_run_value_diff`
- `player_run_value_diff`

The older quality fields are retained for compatibility and diagnostics, but
new modeling should prefer the run-impact deltas.

Current promotion stance:

- Do not train on both `player_run_value_diff` and its component deltas at the same time.
- `top_order_run_value_diff` is diagnostic only for now because it double-counts lineup value.
- Lineup and bullpen run deltas are not active residual adjustments until true absences and bullpen workload/rest exist.
- The only live residual adjustment currently supported by walk-forward diagnostics is a small starter run offset over the starter-only artifact.
- Runtime applies the offset only when the loaded artifact declares `offset_config`; it is not hidden as an unconditional code path.
- Latest walk-forward offset diagnostics:
  - `starter_only`: Brier `0.2566`, accuracy `0.531`
  - `offset_player_run`: Brier `0.2560`, accuracy `0.542`, mean delta Brier `-0.00058`
  - `offset_starter_run`: Brier `0.2559`, accuracy `0.540`, mean delta Brier `-0.00071`, fold improvement rate `0.566`, beta positive fold rate `0.713`
  - `offset_starter_absence_run`: Brier `0.2559`, accuracy `0.540`, with absence beta at `0.000` because absence data is still empty.

The current starter offset candidate metadata is:

```text
model_id: mlb_starter_offset_v23
base_model: starter_only_logistic
offset_feature: starter_run_value_diff
offset_beta: 0.0822
offset_cap: 0.75
```

Promoted runtime:

```text
mlb_starter_offset_v23
```

This is intentionally not promoted as `full_player_aware`. Full player-aware
lineup, bullpen, and absence modeling remains experimental until true lineup
absences, bullpen workload/rest, and historical as-of player snapshots are
available.

Supported hitter inputs:

- `war`
- `xwoba`
- `wrc_plus`
- `platoon_wrc_plus`
- `lineup_spot`
- `vs_opponent_wrc_plus`
- `vs_opponent_xwoba`
- direct adjustments such as `team_matchup_adjustment`

Supported pitcher inputs:

- `war`
- `xera`
- `fip`
- `k_bb_pct`
- `rest_days`
- `pitch_count_workload`
- `velocity_change`
- `projected_innings`
- `vs_opponent_fip`
- direct role/context adjustments

Bullpen rows follow the same pitcher-style contract at team level:
`xera`, `fip`, `k_bb_pct`, `pitch_count_workload`, rest/workload/context
adjustments, and team matchup adjustments.

## Run-Impact Wiring

Hitter value is converted with projected plate appearances by lineup slot.
WAR acts as the replacement-level prior, while `xwoba` acts as the current
offensive rate input. If `wrc_plus` or platoon splits are not available, they
remain absent rather than being approximated from noisier surface stats.

Starter value is converted as:

```text
projected_IP / 9 * (league_RA9 - starter_skill_RA9)
```

where `starter_skill_RA9` is a blended and clamped FIP/xERA estimate. K-BB%
and WAR remain useful upstream, but they should not be equal raw peers in the
final probability model.

Bullpen value is weakly shrunk unless workload/rest is available:

```text
0.0875 * expected_bullpen_IP / 9 * (league_RA9 - bullpen_skill_RA9)
```

Absence value should eventually be replacement-adjusted against the actual
substitute. Until reliable absence rows exist, `absence_run_value_diff` should
stay zero instead of guessing.

## Optional Enrichment

- Online advanced imports are optional only.
- `--online-advanced` uses Baseball Savant expected stats, Baseball-Reference WAR via pybaseball, and MLB StatsAPI components for derived FIP/K-BB%.
- True `wrc_plus`, platoon splits, opponent-specific splits, velocity change, and confirmed lineup/rest context remain `0.0` unless supplied by a stronger local/manual source.
- Fangraphs-derived season stats are not required because live Fangraphs scraping can fail with blocked requests.
- The MLB scanner does not call those sources by default because live scraping can fail or slow runtime.
- Use `--allow-external-player-stats` only when intentionally allowing external enrichment during a scanner run.

## Daily Flow

1. Update local database:

   ```powershell
   ./venv/Scripts/python.exe ./scripts/update_mlb_player_database.py --date 2026-06-28 --batters-csv data/mlb/raw/batters_2026-06-28.csv --pitchers-csv data/mlb/raw/pitchers_2026-06-28.csv --absences-csv data/mlb/raw/absences_2026-06-28.csv
   ```

   Or pull available advanced inputs from online sources:

   ```powershell
   ./venv/Scripts/python.exe ./scripts/update_mlb_player_database.py --date 2026-06-28 --online-advanced
   ```

   Absence rows should use WAR when possible. If `absence_value` is omitted,
   the importer derives `today_player_value` first, then sets
   `absence_value = min(0.50, today_player_value / 20)`. Explicit
   `absence_value` still overrides the derived value for manual review.

   Supported absence columns include:

   - Common: `today_player_value`, `war`, `batting_war`, `pitching_war`,
     `platoon_adjustment`, `recent_health_rest_adjustment`,
     `recent_player_performance`, `park_weather_adjustment`,
     `team_matchup_adjustment`
   - Hitters: `xwoba`, `wrc_plus`, `platoon_wrc_plus`, `lineup_spot`,
     `vs_opponent_wrc_plus`, `vs_opponent_xwoba`
   - Pitchers: `xera`, `fip`, `k_bb_pct`, `rest_days`,
     `pitch_count_workload`, `velocity_change`, `projected_innings`,
     `vs_opponent_fip`

   Surface stats such as `ERA`, `BA`/`AVG`, home runs, RBI, wins, and losses
   are intentionally rejected in absence rows. They can inform the derived
   inputs upstream, but the runtime absence algorithm should only consume
   WAR, advanced rate stats, workload/rest, and explicit context adjustments.

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
