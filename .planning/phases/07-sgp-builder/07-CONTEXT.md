# Phase 7: SGP Builder + Scanner Integration - Context

**Gathered:** 2026-06-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 7 delivers:
1. `alpha/engines/sports/wc_sgp_builder.py` — WC-specific parlay builder consuming predict() output from Phase 6 WCMatchModel
2. `scripts/wc_scanner.py` — standalone WC scanner CLI

Together they satisfy SGP-01, SGP-02, SCAN-01, SCAN-02, TEST-01.
WC games are fetched over a date range (not just today) — a new script is cleaner than extending soccer_scanner.py.

</domain>

<decisions>
## Implementation Decisions

### File structure
- New file: `alpha/engines/sports/wc_sgp_builder.py` — imports nothing from soccer_sgp_builder.py
- New file: `scripts/wc_scanner.py` — standalone CLI for WC picks
- New test files: `tests/unit/engines/test_wc_sgp_builder.py` and `tests/unit/test_wc_scanner.py`
- `soccer_scanner.py` is NOT modified — WC scanner is separate (different fetch API, date-range vs today)

### WCSGPBuilder Class Design (SGP-01, SGP-02)
- `WCSGPBuilder(bankroll=10_000.0, min_edge=0.05, max_legs=4)`
- Reuses `ParlayCombination` and `SGPMode` from `soccer_sgp_builder` via import (no duplication)
- `build(ml_games: list[dict], top_n: int = 5) -> list[ParlayCombination]`
  - Only mode supported in v1.1: CLASSIC_PARLAY (no player prop legs)
  - Calls `_build_classic_parlay(ml_games)` internally
  - Applies min_edge filter; sorts by EV; returns top_n
- `_best_wc_leg(game: dict) -> dict | None`
  - WCMatchModel.predict() has already enriched game dict with `win_prob`, `draw_prob`, `knockout`, `elo_edge`
  - If `game["knockout"] is True`: only Win leg is valid — return Win leg (home = win_prob at home_odds)
  - If group stage: pick Win leg (home moneyline). Draw legs NOT included in parlay combos (illiquid, too wide spread)
  - Returns leg dict: `{"type": "wc_ml", "team": home_team, "model_prob": win_prob, "decimal_odds": home_dec, "event_id": ..., "elo_edge": ...}`
- `_build_classic_parlay(ml_games: list[dict]) -> list[ParlayCombination]`
  - Mirrors `SoccerSGPBuilder._build_classic_parlay()` exactly
  - Uses `_best_wc_leg()` per game (already enriched)
  - Leg dict key: `"model_prob"` (from `win_prob`), `"decimal_odds"` (from home_odds)
  - SGP-02 enforced: `_best_wc_leg()` never returns a Draw leg for any round

### WC Correlation Model
- WC match outcomes across different games are treated as independent (r=0.0)
- No intra-game prop legs in v1.1 → no correlation adjustment needed
- Correlation note: empty string for all WC combos

### wc_scanner.py CLI Design (SCAN-01, SCAN-02)
- Entry point: `scripts/wc_scanner.py`
- Args:
  - `--mode`: choices `["parlay"]`, default `"parlay"` (only mode in v1.1)
  - `--date-from`: str, default = today's date (ISO format YYYY-MM-DD)
  - `--date-to`: str, default = today's date + 7 days (one week lookahead)
  - `--bankroll`: float, default 10_000.0
  - `--min-edge`: float, default 0.04 (matches WCMatchModel default)
  - `--max-legs`: int, default 4
  - `--top`: int, default 5
  - `--validate`: bool flag, prints model info if set
- Pipeline steps:
  1. Fetch WC games: `FootballDataClient().fetch_wc_games(date_from, date_to)`
  2. Run WCMatchModel: `WCMatchModel().predict(game)` for each game (mutates game dict)
  3. Build combos: `WCSGPBuilder().build(games, top_n)`
  4. Print output (see SCAN-02 output format)
- Error handling: if FOOTBALL_API_KEY not set, print message and exit; if FileNotFoundError from WCMatchModel (missing wc_priors.json), print instruction and exit

### Scanner Output Format (SCAN-02)
```
=================================================================
WC SCANNER — Mode: PARLAY  |  2026-06-20 to 2026-06-27  |  Min edge: 4.0%
=================================================================

#1  EV: 12.3%  |  Edge: 8.1%  |  Odds: 3.45x  |  Stake: $23.50
    Model Prob: 34.2%  vs  Market Implied: 26.1%
    Legs:
      * Brazil WIN  (1.82x)  model: 68.4%  [Elo: 2100]  *ELO EDGE*
      * France WIN  (1.90x)  model: 50.0%  [Elo: 2050]
```
- `*ELO EDGE*` annotation when `game["elo_edge"] is True`
- Elo rating shown in brackets after model probability
- KNOCKOUT games: show `[ADVANCE]` label instead of `WIN` to signal Win-to-Advance

### Test Strategy (TEST-01)
- `test_wc_sgp_builder.py`: monkeypatch-free (no file I/O) — pass enriched game dicts directly
  - At minimum: knockout gate (no Draw legs), classic parlay builds, min_edge filter
- `test_wc_scanner.py`: monkeypatch FootballDataClient + WCMatchModel
  - At minimum: main() runs, no-games-found path, output contains *ELO EDGE* when elo_edge=True

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/engines/sports/soccer_sgp_builder.py` — `ParlayCombination`, `SGPMode` dataclasses to import
- `alpha/engines/sports/kelly.py` — `KellySizer.bet_size()` for stake sizing
- `alpha/engines/sports/ev_calculator.py` — `EVCalculator` for EV/implied_prob
- `alpha/engines/sports/wc_model.py` — `WCMatchModel` (Phase 6 deliverable)
- `alpha/data/ingestion/football_data_client.py` — `FootballDataClient.fetch_wc_games()`
- `scripts/soccer_scanner.py` — full pipeline pattern to mirror

### WCMatchModel predict() output fields consumed in Phase 7
```python
game["win_prob"]   # float — home team W prob (or Win-to-Advance in knockout)
game["draw_prob"]  # float — 0.0 in knockout rounds
game["elo_edge"]   # bool  — |win_prob - market_implied| > 0.05
game["knockout"]   # bool  — True if stage in KNOCKOUT_STAGES
game["model_name"] # str   — "wc_elo_logistic"
game["elo_diff"]   # float — adjusted Elo diff
game["home_elo"]   # int   — home team Elo rating
game["away_elo"]   # int   — away team Elo rating
```

### Established Patterns
- `_best_ml_leg(game)` pattern from SoccerSGPBuilder — directly analogous
- `_build_classic_parlay(ml_games)` pattern — identical logic
- Scanner `[1/N] ... [N/N]` step print pattern from soccer_scanner.py
- Kelly sizing: `_KELLY.bet_size(win_prob, decimal_odds, bankroll)`
- No pytest asyncio — pure sync throughout

</code_context>

<specifics>
## Specific Ideas

- `ParlayCombination` and `SGPMode` are already defined in soccer_sgp_builder.py — import them directly to avoid duplication. No need to redefine.
- `KellySizer` from `alpha/engines/sports/kelly.py` — same import pattern as SoccerSGPBuilder
- Default date range for wc_scanner.py: today to today+7. Makes the scanner useful pre-tournament (see upcoming WC fixtures).
- `*ELO EDGE*` annotation goes inline on the leg line (not combo header) since it's a per-game signal
- Draw legs: NOT used in WC parlays at all (even group stage). Sportsbooks price WC Draw at ~+240 with massive vig. For parlay purposes, Win leg dominates. SGP-02 simply enforces the intuition.

</specifics>

<deferred>
## Deferred Ideas

- WC player prop legs in SGP combos — v1.2 (blocked on Odds API Business tier)
- wc_scanner.py `--stage group` / `--stage knockout` filter — v1.2
- Intra-game correlation for WC (e.g., same tournament group) — v1.2
- Integration with soccer_scanner.py `--league wc` as alternative entry point — v1.2

</deferred>
