# Alpha Terminal — Milestone 2: Stock Engine

**Goal:** Wire `alpha/engines/stocks/` with qlib factor mining, PyPortfolioOpt allocation, alpha-vantage + FRED signal generation, and a multi-factor screener.

**Depends on:** Milestone 1 (storage, ingestion, transforms, macro_filter all exist)

---

### Task 1: Stock Signals Engine

**Files:**
- `alpha/engines/stocks/signals.py` — combine Alpha Vantage + FRED into tradeable signals
- `tests/unit/engines/test_stock_signals.py`

### Task 2: Multi-Factor Screener

**Files:**
- `alpha/engines/stocks/screener.py` — rank stocks by momentum + value + quality
- `tests/unit/engines/test_screener.py`

### Task 3: Portfolio Optimizer (PyPortfolioOpt)

**Files:**
- `alpha/engines/stocks/portfolio.py` — Efficient frontier + max Sharpe allocation
- `tests/unit/engines/test_portfolio.py`

### Task 4: qlib Alpha Factory Wrapper

**Files:**
- `alpha/engines/stocks/alpha_factory.py` — thin qlib wrapper for factor generation
- `tests/unit/engines/test_alpha_factory.py`

### Task 5: Stock Engine Orchestrator

**Files:**
- `alpha/engines/stocks/__init__.py` updates
- `alpha/engines/stocks/engine.py` — ties signals → screen → allocate
- `tests/unit/engines/test_stock_engine.py`
