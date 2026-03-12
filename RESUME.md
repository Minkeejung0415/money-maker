# RESUME — Alpha Terminal Session Continuity

> Read this at the start of every session before doing anything else.

---

## What This Project Is

Unified multi-asset trading engine: **Stocks + Crypto + Sports Betting**.
All code lives in `alpha/`. Cloned repos are read-only pip dependencies.

**Repo:** `C:\Users\justi\Documents\money-maker\`
**Venv:** `./venv/` — always use `./venv/Scripts/python.exe`
**Package manager:** `uv`

---

## Current State

**482/482 tests passing** as of last session.

| Milestone | Status |
|---|---|
| M1 Foundation | ✅ DONE |
| M2 Stock Engine | ✅ DONE |
| M3 Crypto Engine | ✅ DONE |
| M4 Sports Engine | ✅ DONE |
| M5 Risk Layer | ✅ DONE |
| M6 Reporting | ✅ DONE |
| M7 Execution | ✅ DONE |
| NBA SGP Scanner | ✅ DONE |
| Soccer + MLB Engines | ✅ DONE |
| NBA 10-system upgrade | ✅ DONE |
| NBA bug fixes (foul trouble + recent form) | ✅ DONE |

---

## NBA Scanner — What Was Built

Full pipeline in `scripts/sgp_scanner.py`:
- Fetches 9 games + 352 prop lines from Odds API
- Runs prop model on 106 players (cached after first run)
- Context evaluators: position filter, paint deterrence, foul trouble, pace, def rating
- Correlation engine, SGP builder, parlay constructor with EV/Kelly output
- Modes: `--mode props`, `--mode ml_sgp`, `--mode mixed`, `--mode parlay`

**Known issue with context evaluators:** They work but take 18+ minutes due to nba_api rate limiting with no timeout. Run with `--no-context` for fast results. Fix is queued.

---

## Next Session — Coding Agent Task

The full prompt is in `memory/nba_fix_prompt_v2.md` (write it there if needed).

### Bugs to Fix

**1. "Trae Young vs Trae Young" correlation note**
- File: `alpha/engines/sports/sgp_builder.py` → `_build_corr_note()`
- Same player with two props compares to themselves, returns `r=0.00`
- Fix: skip same-player pairs, label as `"Trae Young (pts + ast): same player — r=0.65"`

**2. "ML+player same team" flag always fires**
- File: `alpha/engines/sports/sgp_builder.py` → `_score_mixed_combo()`
- Checks `home_team == team OR away_team == team` — always true for any prop in the game
- Fix: add `player_team: str = ""` field to `PropLeg`, populate in scanner, check `player_team == team` vs `player_team != team` to distinguish same-team vs opposing-team correlation

**3. Negative-edge ML legs included in parlays**
- File: `alpha/engines/sports/sgp_builder.py` → `_best_ml_leg()`
- Detroit Pistons at 1.10x (model 87.4%, market implies 90.9%) = negative edge, still gets included
- Fix: return `None` from `_best_ml_leg()` if best side EV <= 0

**4. Context evaluators timeout (18 minutes)**
- File: `alpha/data/ingestion/nba_stats_cache.py` + `alpha/engines/sports/nba_context.py`
- No timeout on nba_api calls, no wall-clock limit on `evaluate_props()`
- Fix: add `timeout=10` to all nba_api calls, add 90-second total timeout on context pipeline, fall back to no-context gracefully

### Features to Add

**5. `--mode ml` — list all moneylines**
- New mode in scanner that skips props and just evaluates all 9 games
- Shows both sides of every game: model prob vs market, edge, EV/100, Kelly
- Flags any side with edge > 4% as VALUE
- Prints ranked top-5 value ML bets at the end

**6. Minimum 60% confidence floor**
- Add `--min-prob 0.60` CLI flag (default 0.60)
- Filter out prop legs below threshold after prop model step
- Eliminates weak legs like Isaiah Joe OVER 2.5 ast at 53.4%

**7. Kelly stake display cap at 5%**
- File: `alpha/engines/sports/parlay_constructor.py`
- Current output shows 22-23% Kelly which is unrealistic
- Cap displayed Kelly at 5%, show `[capped from X%]` when triggered
- Keep raw value internally

**8. `--favorites-only` flag for parlay mode**
- Filters out ML legs where `model_prob < 0.45` before building combinations
- Prevents every parlay anchoring around long shots like Nets at 22%
- Builds cleaner parlays from Celtics/Grizzlies/Nuggets tier

**9. Head-to-head history in moneyline model**
- Add `fetch_head_to_head()` to `NBAStatsCache` using `TeamGameLog`
- Wire into `NBAModel._apply_context_adjustments()` at 15% weight, capped ±0.03
- Only apply when ≥ 4 H2H games exist, 24-hour TTL cache

**10. Traded player stats warning**
- If player has fewer than 10 games with current team this season, downgrade confidence HIGH → MEDIUM and add `recent_trade: True` flag
- Catches players like Trae Young (recently traded to Wizards — his stats are mostly Hawks-era)
- Add `fetch_player_team_game_count()` to `NBAStatsCache`

---

## Player Notes (Important)
- **Trae Young** — traded to Washington Wizards. Scanner already picks this up correctly (Wizards ML + Trae props = positively correlated). But his rolling stats are mostly Atlanta Hawks games — treat with caution until 10+ Wizards games.

---

## Live Run Results (2026-03-11)
Best individual picks from today's context-enabled run:

| Pick | Model | Edge |
|------|-------|------|
| Cameron Johnson OVER 8.5 pts | 97.0% | +45.5% |
| Trae Young OVER 5.5 ast | 95.4% | +43.9% |
| Trae Young OVER 12.5 pts | 98.7% | +44.6% |
| Giannis OVER 25.5 pts | 91.3% | +38.5% |
| Davion Mitchell OVER 9.5 pts | 92.7% | +38.1% |
| Josh Giddey OVER 7.5 reb | 88.1% | +36.1% |

Best ML value bets today: Brooklyn Nets (+9.5% edge), Boston Celtics (+15.3%), Memphis Grizzlies (+15.8%)

Picks saved in `picks/` folder.

---

## Quick Commands

```bash
# Run all tests
./venv/Scripts/python.exe -m pytest tests/ -q

# Run scanner fast (no context evaluators)
./venv/Scripts/python.exe scripts/sgp_scanner.py --mode props --no-context --min-edge 0.02

# Run scanner with full context (slow — 15-20 min first run, cached after)
./venv/Scripts/python.exe scripts/sgp_scanner.py --mode props --show-ev --min-edge 0.02

# All modes fast
./venv/Scripts/python.exe scripts/sgp_scanner.py --mode parlay --no-context
./venv/Scripts/python.exe scripts/sgp_scanner.py --mode ml_sgp --no-context --min-edge 0.02
./venv/Scripts/python.exe scripts/sgp_scanner.py --mode mixed --no-context --min-edge 0.02
```

---

## Architecture Reminder

```
ingestion (AV/FRED/ccxt/odds)
    ↓
transforms (polars features)
    ↓
engines (stocks/crypto/sports) → signals + weights
    ↓
risk layer (macro filter + drawdown + exposure)
    ↓
execution (broker/exchange/sportsbook)
    ↓
reporting (P&L + audit log + dashboard)
```

**The macro filter gates ALL verticals.** VIX > 30 or yield curve inverted → all engines deploy less.

---

## Known Issues

| Issue | Fix |
|---|---|
| Context evaluators take 18+ min | Use `--no-context` until timeout fix is shipped |
| `ccxt/` and `freqtrade/` dirs shadow installed packages | Fixed in `conftest.py` |
| qlib requires MSVC C++ on Windows | Using polars-native `AlphaFactory` instead |
| Trae Young stats are Hawks-era | Treat his props with lower confidence until 10+ Wizards games |
