# Alpha Terminal — Milestone 3: Crypto Engine

**Goal:** Wire `alpha/engines/crypto/` with ccxt exchange connector,
a whale/volume tracker, a freqtrade strategy runner wrapper, and
a unified crypto engine entry point.

**Depends on:** Milestones 1 & 2 (storage, ingestion, transforms, macro_filter, stock engine done)

---

### Task 1: Exchange Connector
- `alpha/engines/crypto/exchange.py` — ccxt unified OHLCV + order book + ticker
- `tests/unit/engines/test_crypto_exchange.py`

### Task 2: Whale / Volume Tracker
- `alpha/engines/crypto/whale_tracker.py` — volume spike + unusual activity detection
- `tests/unit/engines/test_whale_tracker.py`

### Task 3: Strategy Runner (freqtrade wrapper)
- `alpha/engines/crypto/strategy_runner.py` — thin freqtrade signal adapter
- `tests/unit/engines/test_strategy_runner.py`

### Task 4: Crypto Engine Entry Point
- `alpha/engines/crypto/engine.py` — ties exchange + whale + strategy → allocations
- `tests/unit/engines/test_crypto_engine.py`
