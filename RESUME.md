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

**125/125 tests passing** as of last session.

| Milestone | Status | Key Files |
|---|---|---|
| M1 Foundation | ✅ DONE | config, sqlite, ingestion (AV/FRED/ccxt/odds), transforms, macro filter, orchestrator |
| M2 Stock Engine | ✅ DONE | `alpha/engines/stocks/` — signals, screener, portfolio, alpha_factory, engine |
| M3 Crypto Engine | ✅ DONE | `alpha/engines/crypto/` — exchange, whale_tracker, strategy_runner, engine |
| M4 Sports Engine | ✅ DONE | `alpha/engines/sports/` — ev_calculator, kelly, nba_model, engine |
| M5 Risk Layer | ✅ DONE | `alpha/risk/` — position_sizer, drawdown, exposure (wired into orchestrator) |
| M6 Reporting | ✅ DONE | `alpha/reporting/` — pnl_tracker, audit_log, dashboard (plotly) |
| M7 Execution | ⏳ NEXT | `alpha/execution/` — broker, exchange, sportsbook |

---

## Next Task: Milestone 7 — Execution Layer

**Files to create:**
1. `alpha/execution/broker.py` — stock broker (Alpaca paper trading API)
   - `tests/unit/execution/test_broker.py`
2. `alpha/execution/exchange.py` — crypto execution via ccxt (paper/sandbox mode)
   - `tests/unit/execution/test_exchange_execution.py`
3. `alpha/execution/sportsbook.py` — sportsbook API stub (paper mode)
   - `tests/unit/execution/test_sportsbook.py`

**After M7:**
- `scripts/daily_scan.py` — morning cron: refresh all signals, write to SQLite
- `scripts/backtest_runner.py` — run backtests, output P&L report

---

## How to Resume

```bash
# 1. Verify tests still pass
./venv/Scripts/python.exe -m pytest tests/ -q

# 2. Check where we are
git log --oneline -8

# 3. Start M7 Task 1
# Create tests/unit/execution/__init__.py + test_broker.py
# Create alpha/execution/broker.py
# Run tests, commit, move to next task
```

---

## Known Issues (do not forget)

| Issue | Fix |
|---|---|
| `ccxt/` and `freqtrade/` dirs shadow installed packages | Fixed in `conftest.py` — adds their python paths first |
| qlib requires MSVC C++ on Windows | Using polars-native `AlphaFactory` instead |
| `pyarrow` needed for polars→pandas (PyPortfolioOpt) | Already installed |
| freqtrade complex imports | `CryptoStrategyRunner` is pure Python, no freqtrade import needed |

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
execution (broker/exchange/sportsbook)  ← M7
    ↓
reporting (P&L + audit log + dashboard)
```

**The macro filter gates ALL verticals.** If VIX > 30 or yield curve inverted → position scalar drops → all engines deploy less.

---

## Quick Commands

```bash
# Run all tests
./venv/Scripts/python.exe -m pytest tests/ -q

# Run specific milestone tests
./venv/Scripts/python.exe -m pytest tests/unit/engines/ -q
./venv/Scripts/python.exe -m pytest tests/unit/risk/ -q
./venv/Scripts/python.exe -m pytest tests/unit/reporting/ -q

# Install a new local dep
VIRTUAL_ENV=./venv ./venv/Scripts/python.exe -m pip install -e ./REPO_NAME

# Verify orchestrator
./venv/Scripts/python.exe -c "from alpha.orchestrator import Orchestrator; o = Orchestrator(); print('OK')"
```
