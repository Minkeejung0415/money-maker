# Architecture: World Cup 2026 Soccer Mode Integration

**Project:** Alpha Terminal — v1.1 World Cup Soccer Mode
**Researched:** 2026-06-18
**Scope:** How WC components integrate with the existing `alpha/` architecture

---

## Component Map

### New Files (must create)

| File | Type | Purpose |
|------|------|---------|
| `alpha/data/ingestion/wc_stats.py` | New ingestion module | WC team + player stats from StatsBomb open data (WC 2018/2022) with market-implied fallback |
| `alpha/engines/sports/wc_model.py` | New engine | WC match outcome model (Win/Draw/Loss), national-team-specific features |
| `alpha/engines/sports/wc_prop_model.py` | New engine | WC player prop model (goals, shots, assists) wrapping market-implied priors from The Odds API |
| `alpha/engines/sports/wc_sgp_builder.py` | New engine | WC SGP builder with WC-specific correlation table, reuses `PropLeg`/`ParlayCombination`/`SGPMode` from `soccer_sgp_builder.py` |
| `scripts/wc_scanner.py` | New entry point | Full 6-step pipeline, `--mode [props|sgp|mixed|parlay]` + `--stage [group|knockout|all]` |
| `tests/unit/test_wc_stats.py` | New test | Unit tests for WC stats ingestion (all HTTP mocked) |
| `tests/unit/engines/test_wc_model.py` | New test | Unit tests for WC match model |
| `tests/unit/engines/test_wc_prop_model.py` | New test | Unit tests for WC prop model |
| `tests/unit/engines/test_wc_sgp_builder.py` | New test | Unit tests for WC SGP builder |

### Modified Files (extend existing, never rewrite)

| File | Change | Why Here, Not a New File |
|------|--------|--------------------------|
| `alpha/data/ingestion/football_data_client.py` | Add `"wc": "WC"` to `_COMP_MAP` + new `fetch_wc_games(date_from, date_to, stage)` method | Same API key, same v4 base URL, same HTTP client — competition code `WC` is confirmed available on the free tier. Creating a separate file would duplicate HTTP client setup and error handling. |
| `alpha/data/ingestion/odds_api.py` | Add `"soccer_fifa_world_cup"` sport key constant + `fetch_wc_odds()` / `fetch_wc_prop_lines()` methods | Existing `OddsAPIClient` already handles all HTTP wiring and API key injection. The WC sport key (`soccer_fifa_world_cup`) is confirmed active on The Odds API with player prop markets (anytime goal scorer, shots). Quota consumption pattern matches NBA — guard with same per-run limits. |

### Files Left Untouched

| File | Why Not Modified |
|------|-----------------|
| `alpha/engines/sports/soccer_model.py` | EPL/UCL club football model. WC has different feature requirements — national team FIFA ranking, confederation, knockout vs. group stage pressure. A `tournament_mode=True` flag would force a branching `_build_game_features()` with two incompatible data shapes. |
| `alpha/engines/sports/soccer_prop_model.py` | Hard-wired to Understat via `soccer_stats.py`. WC has no Understat coverage — different data pipeline entirely. |
| `alpha/engines/sports/soccer_sgp_builder.py` | EPL/UCL-calibrated static correlation table. WC has different market correlations (see Q4 below). However, `PropLeg`, `ParlayCombination`, and `SGPMode` from this file ARE imported by `wc_sgp_builder.py` — no duplication. |
| `alpha/data/ingestion/soccer_stats.py` | Understat-only, EPL/UCL scope. WC stats are a completely different source (StatsBomb). |
| `alpha/config/settings.py` | `football_api_key` and `odds_api_key` already present — WC uses both with no new keys. |
| `scripts/soccer_scanner.py` | EPL/UCL-specific orchestrator with Understat assumptions baked in. WC gets its own entry point to keep both scanners readable and independently runnable. |

---

## Q1: Extend `soccer_model.py` with `tournament_mode=True` or create `wc_model.py`?

**Decision: Create `wc_model.py` as a new file.**

The codebase precedent is one class per sport/context: `nba_model.py`, `soccer_model.py`, `mlb_model.py`. Follow it.

Two concrete problems with the `tournament_mode` flag approach:

**Problem 1 — Incompatible data shapes in `_build_game_features()`:**

`soccer_model.py._build_game_features()` calls `get_team_rolling_stats_all()` from `soccer_stats.py`, which is Understat-backed and EPL/UCL-scoped. WC data comes from `wc_stats.py` (StatsBomb). The feature dict shapes differ: club football has `xG_for`, `xG_against` from a domestic season; WC needs `fifa_ranking_diff`, `confederation`, `tournament_games_played`, `wc_qualifying_goals_for`. Adding a `tournament_mode` branch produces a god-method that is hard to test and silently returns empty features when WC data is missing.

**Problem 2 — XGBoost model incompatibility:**

`soccer_model.py` loads ProphitBet pkl files trained on club football features (league rank, head-to-head form, odds history). Those features are meaningless for national teams. A WC-specific XGBoost model (if ever trained) needs entirely different feature columns. Sharing the load logic with a flag leads to pkl format mismatches at runtime.

`wc_model.py` mirrors `soccer_model.py` structurally — same `predict()`, `evaluate_bet()`, `evaluate_batch()` interface, same market-implied fallback when no pkl is present — but pulls from `wc_stats.py` and has its own `MAX_XGB_CONF = 0.68` (national team soccer is the least predictable domain in the codebase).

---

## Q2: WC Fixtures — New Method in `football_data_client.py` or New File?

**Decision: New method `fetch_wc_games()` in the existing `football_data_client.py`.**

The football-data.org `WC` competition code is confirmed available on the free tier (same tier as `PL` and `CL`). Adding it to `_COMP_MAP` and writing one new public method is the minimum change.

`fetch_wc_games()` differs from `fetch_today_games()` in one important way: WC group-stage scheduling has gaps of 1-3 days between match days, so hardcoding `today` misses games scheduled tomorrow. The method takes explicit `date_from` / `date_to` parameters:

```python
# football_data_client.py — additions only

_COMP_MAP: dict[str, str] = {
    "epl": "PL",
    "ucl": "CL",
    "wc":  "WC",   # FIFA World Cup 2026
}

def fetch_wc_games(
    self,
    date_from: str | None = None,   # ISO date string; defaults to today
    date_to: str | None = None,     # ISO date string; defaults to today + 1 day
    stage: str | None = None,       # optional filter: "GROUP_STAGE", "ROUND_OF_16" etc.
) -> list[dict]:
    """
    Fetch upcoming WC fixtures.

    Returns same dict shape as fetch_today_games() plus:
        "stage": str   # "GROUP_STAGE", "ROUND_OF_16", etc.
        "group": str   # "Group A" ... "Group L" (empty in knockout rounds)
    """
```

The return dict is backward-compatible with `SoccerModel.predict()` and `SoccerSGPBuilder.build()` — same field names. `wc_model.py` and `wc_sgp_builder.py` additionally consume `stage` and `group` for correlation adjustments.

---

## Q3: WC Player Stats — Separate `wc_stats.py` or Extend `soccer_stats.py`?

**Decision: Create `alpha/data/ingestion/wc_stats.py` as a new file.**

`soccer_stats.py` is structurally incompatible with WC data:

- **Source:** Understat async library vs. StatsBomb GitHub raw JSON (synchronous requests, no aiohttp)
- **Granularity:** Understat gives season totals aggregated to per-90; StatsBomb gives per-match event rows that can be rolled up per-match
- **Team namespace:** EPL club names vs. national team names — separate lookup tables required
- **Cache directory:** `data/.wc_cache/` not `data/.soccer_cache/` — national team name "Brazil" vs. EPL player "Brazil" (common name conflict risk)

`wc_stats.py` public API intentionally mirrors `soccer_stats.py` for drop-in compatibility with the model layer:

```python
def get_wc_team_stats() -> list[dict]:
    """
    Rolling stats for WC teams using their last 5 tournament/qualifying matches
    from StatsBomb open data.

    Returns same shape as get_team_rolling_stats():
        {"team": str, "goals_for": float, "goals_against": float,
         "xG_for": float, "xG_against": float, "games_used": int}

    Falls back to {} on any failure — wc_model.py uses market-implied fallback.
    """

def get_wc_player_stats(player_name: str) -> dict | None:
    """
    Per-90 stats from StatsBomb WC 2022 data (most recent free dataset).

    Returns same shape as get_player_per90_stats() rows:
        {"player": str, "goals_per90": float, "assists_per90": float,
         "shots_per90": float, "xG_per90": float, "minutes_90s": float}

    Returns None if player not found — wc_prop_model.py falls back to
    market-implied prior from The Odds API.
    """
```

**StatsBomb data availability note (IMPORTANT):**

StatsBomb has confirmed free open data for WC 2018 (64 matches) and WC 2022 (64 matches). The WC 2026 tournament is currently underway (research date: June 18, 2026). StatsBomb historically releases open data after tournament completion, so live 2026 per-match event data is NOT expected through the free tier during the tournament.

`wc_stats.py` must implement a two-tier fallback:
1. **Primary:** StatsBomb WC 2022 per-90 stats for the player (most relevant historical baseline)
2. **Fallback:** Market-implied prior from The Odds API (anytime goal scorer odds → implied goals/90 estimate)

This mirrors how `soccer_stats.py` already handles UCL (Understat has no UCL data — falls back to `[]`, which triggers market-implied in `soccer_model.py`).

**Cache location:** `data/.wc_cache/` and `data/.wc_cache/props/`

---

## Q4: Can `soccer_sgp_builder.py` Handle WC Legs?

**Decision: Create `wc_sgp_builder.py` that imports shared types from `soccer_sgp_builder.py` and overrides the correlation table.**

`soccer_sgp_builder.py` is mechanically data-agnostic — it operates on `PropLeg` dataclasses with no league-specific fields. The SGP math would produce numbers for WC legs. However, the static `_STATIC_CORR` table is wrong for WC:

| Market pair | EPL/UCL correlation | WC correlation | Why different |
|-------------|--------------------|--------------------|---------------|
| `("player_goals", "team_win")` | 0.40 | 0.50 | Knockout elimination pressure — goal scorers are more decisive |
| `("player_goals", "player_shots")` | 0.65 | 0.65 | Same physics, keep |
| `("player_goals", "player_goals")` | -0.10 | -0.10 | Keep |
| `("player_assists", "player_goals")` | 0.30 | 0.30 | Keep |

Additionally, `wc_sgp_builder.py` needs to accept the `stage` field from `fetch_wc_games()` and adjust `("player_goals", "team_win")` correlation dynamically:

```python
_CORR_BY_STAGE: dict[str, dict] = {
    "GROUP_STAGE":  {("player_goals", "team_win"): 0.42},
    "KNOCKOUT":     {("player_goals", "team_win"): 0.55},
}
```

Implementation: `wc_sgp_builder.py` imports `PropLeg`, `ParlayCombination`, `SGPMode` from `soccer_sgp_builder.py` (no duplication), then subclasses or composes `SoccerSGPBuilder` with overridden `_STATIC_CORR`.

**DBTSA stats note:** `soccer_sgp_builder.py` already says "Empirical correlation from FBRef will be added in a later milestone." WC has no FBRef coverage — static table is the only option. This is fine; market is thin enough that static conservative correlations are appropriate.

---

## Q5: Suggested Build Order

Build order driven by dependency chains — each step unblocks the next.

### Phase 1: Data Foundation (no model logic yet)

**Step 1 — Extend `football_data_client.py`** (add `"wc": "WC"` + `fetch_wc_games()`)
- Zero new dependencies
- Immediately testable with mocked HTTP
- Unblocks: everything that consumes WC fixtures

**Step 2 — Create `wc_stats.py`** (StatsBomb fetch + cache + fallback)
- Only dependency: `requests` (already installed)
- StatsBomb is synchronous JSON — no async complexity like Understat
- Unblocks: `wc_model.py`, `wc_prop_model.py`

**Step 3 — Extend `odds_api.py`** (add `soccer_fifa_world_cup` sport key + `fetch_wc_odds()`)
- Zero new dependencies
- Provides: match odds (for model fallback) + player prop lines (anytime goal scorer, shots)
- Unblocks: `wc_prop_model.py` (needs lines for market-implied comparison), `wc_model.py` (needs 3-way odds)

### Phase 2: Models (depend on data layer)

**Step 4 — Create `wc_model.py`** (WC match outcome model)
- Depends on: `wc_stats.py` (team stats), `football_data_client.fetch_wc_games()` (odds), `odds_api.fetch_wc_odds()` (3-way odds)
- Algorithm: same pattern as `soccer_model.py` — XGBoost if pkl present, market-implied fallback otherwise
- WC pkl not expected for v1.1 (only 128 historical matches across 2 tournaments — insufficient training data); model ships as market-implied only
- Unblocks: `wc_scanner.py` parlay mode, `wc_sgp_builder.py` ML legs

**Step 5 — Create `wc_prop_model.py`** (WC player prop model)
- Depends on: `wc_stats.py` (player per-90), `odds_api.fetch_wc_prop_lines()` (player prop lines)
- Algorithm: same weighted rolling avg + normal CDF as `soccer_prop_model.py`
- Key difference: market-implied fires as primary path when StatsBomb 2026 data is absent
- Confidence thresholds: same as soccer (HIGH = gap > 0.10, MEDIUM = 0.08-0.10)
- Unblocks: `wc_scanner.py` props mode, `wc_sgp_builder.py` prop legs

### Phase 3: SGP Builder (depends on models, imports shared types)

**Step 6 — Create `wc_sgp_builder.py`** (WC SGP construction)
- Depends on: `soccer_sgp_builder.py` (shared types import), `wc_model.py`, `wc_prop_model.py`
- Imports `PropLeg`, `ParlayCombination`, `SGPMode` from `soccer_sgp_builder.py` directly
- Provides: WC-calibrated correlation table, stage-aware correlation adjustment

### Phase 4: Entry Point (depends on all prior steps)

**Step 7 — Create `scripts/wc_scanner.py`** (full pipeline orchestrator)
- Depends on: Steps 1-6
- Mirrors `soccer_scanner.py` structure 6-step pipeline
- CLI: `--mode [props|sgp|mixed|parlay]` + `--stage [group|knockout|all]` + `--bankroll` + `--min-edge`

### Build Order Summary

```
football_data_client.py (add fetch_wc_games)
          |
          |
wc_stats.py ─────────────────── odds_api.py (add soccer_fifa_world_cup)
          |                              |
          +──────────┬───────────────────+
                     |
               wc_model.py        wc_prop_model.py
                     |                   |
                     +─────────┬─────────+
                               |
                         wc_sgp_builder.py
                               |
                        scripts/wc_scanner.py
```

The two parallel tracks in Phase 1 (wc_stats.py and odds_api.py extension) can be built concurrently — they have no mutual dependency.

---

## Q6: WC Model Artifact and Cache Locations

### Pkl Files (model artifacts)

| Artifact | Location | Notes |
|----------|----------|-------|
| WC match model (future only) | `data/wc_match_model.pkl` | Not for v1.1 — insufficient training data |
| WC prop XGBoost (future only) | `data/wc_xgb_goals_model.pkl` | Same naming pattern as NBA pkl files |

For v1.1, no pkl files are created. `wc_model.py` and `wc_prop_model.py` both ship with market-implied as the primary path and gracefully skip pkl loading if files are absent (same pattern as `soccer_model.py` when ProphitBet directory is missing).

### Cache Files

| Cache | Location | TTL | Rationale |
|-------|----------|-----|-----------|
| WC team stats (StatsBomb) | `data/.wc_cache/` | 24h | Separate from `data/.soccer_cache/` to prevent name collisions between national team "Brazil" and any EPL player context |
| WC player stats | `data/.wc_cache/props/` | 24h | Mirrors `data/.soccer_cache/props/` structure |
| WC fixture list | `data/.wc_cache/` | 6h | More frequent; WC group-stage schedule can be updated closer to kickoff |
| WC prop lines (Odds API) | `data/.wc_cache/props/` | 2h | Odds move more during WC; shorter TTL than club soccer |

Cache key naming convention (consistent with existing patterns):

```python
f"wc_team_stats_{date.today()}.pkl"
f"wc_player_{player_name.replace(' ', '_')}_{stat_col}_{date.today()}.pkl"
f"wc_fixtures_{date_from}_{date_to}.pkl"
f"wc_props_{event_id}_{date.today()}.pkl"
```

---

## Integration Point Summary

### `wc_scanner.py` Pipeline (mirrors `soccer_scanner.py` exactly)

```
[1/6] fetch_wc_games(date_from, date_to) — football_data_client.py (extended)
[2/6] fetch_wc_prop_lines()              — odds_api.py (extended, soccer_fifa_world_cup)
[3/6] WCPropModel.predict_prop()         — wc_prop_model.py (new)
[4/6] Static WC correlation table        — wc_sgp_builder.py (new)
[5/6] WCModel.predict()                  — wc_model.py (new)
[6/6] WCSGPBuilder.build()               — wc_sgp_builder.py (new)
```

### Settings: No Changes

`alpha/config/settings.py` is unchanged. Existing fields cover WC:
- `football_api_key` → `fetch_wc_games()` in `football_data_client.py`
- `odds_api_key` → `fetch_wc_odds()` and `fetch_wc_prop_lines()` in `odds_api.py`
- StatsBomb open data → no API key (GitHub raw JSON via `requests`)

### Test Integration

All new test files follow the pattern established by `soccer_model.py` tests (in `__pycache__` from prior session — the source was deleted but the compiled artifact confirms they existed and mocked external HTTP). Each new test file:
- Mocks all external HTTP at the module level
- Verifies the graceful fallback path (empty StatsBomb data → market-implied result)
- Keeps test count growing: 535+ current → 535 + ~20 new WC tests

---

## Data Source Summary

| Need | Source | Free? | Key | Confidence |
|------|--------|-------|-----|------------|
| WC fixture schedule + stage | football-data.org v4 `/competitions/WC/matches` | Yes | `FOOTBALL_API_KEY` (existing) | HIGH — `WC` competition code confirmed free tier |
| WC match 3-way odds | The Odds API `soccer_fifa_world_cup` | Yes (quota) | `ODDS_API_KEY` (existing) | HIGH — sport key confirmed active |
| WC player prop lines | The Odds API `soccer_fifa_world_cup` event odds (anytime goal scorer, shots) | Yes (quota) | `ODDS_API_KEY` (existing) | HIGH — player markets confirmed |
| WC 2022 team/player historical stats | StatsBomb open data GitHub JSON | Yes | None | HIGH — WC 2018 + 2022 confirmed free |
| WC 2026 live player stats | StatsBomb open data (2026 not released mid-tournament) | Unknown | None | LOW — fallback to 2022 stats + market-implied |
| WC group/squad metadata | openfootball/worldcup.json (raw GitHub) | Yes | None | HIGH — 2026 data confirmed present |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| football-data.org WC integration | HIGH | `WC` competition code confirmed, same client and key |
| The Odds API WC sport key and markets | HIGH | `soccer_fifa_world_cup` confirmed, anytime goal scorer + shots markets confirmed |
| StatsBomb 2018/2022 historical data | HIGH | Widely used free open data, Python package `statsbombpy` available |
| StatsBomb 2026 live data | LOW | Tournament underway; free open data historically released post-tournament |
| WC XGBoost match model | LOW | Only 128 training games across 2 tournaments — unreliable; ship market-implied only |
| Market-implied fallback viability | HIGH | The Odds API provides WC 3-way odds; this is the reliable production path for v1.1 |

---

## Sources

- football-data.org WC competition code (`WC` confirmed free): [football-data.org/documentation/quickstart](https://www.football-data.org/documentation/quickstart)
- The Odds API FIFA World Cup sport key and player markets: [the-odds-api.com/sports/fifa-world-cup-odds.html](https://the-odds-api.com/sports/fifa-world-cup-odds.html)
- StatsBomb open data (WC 2018 + 2022 confirmed): [github.com/statsbomb/open-data](https://github.com/statsbomb/open-data)
- statsbombpy Python package: [github.com/statsbomb/statsbombpy](https://github.com/statsbomb/statsbombpy)
- openfootball World Cup 2026 JSON fixtures (no key required): [github.com/openfootball/worldcup.json](https://github.com/openfootball/worldcup.json)
- Best WC 2026 API options comparison: [thestatsapi.com/blog/best-world-cup-2026-apis](https://www.thestatsapi.com/blog/best-world-cup-2026-apis)
