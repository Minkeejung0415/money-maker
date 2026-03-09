# Alpha Terminal — Milestone 1: Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Scaffold the `alpha/` terminal package with a unified config system, all data ingestion connectors, a polars-based transform layer, and a sqlite/S3 storage layer — the foundation every engine depends on.

**Architecture:** The `alpha/` package is installed as an editable local pip package. All cloned repos (qlib, ccxt, freqtrade, etc.) are installed as local editable dependencies from their subdirectories. Config is TOML-based with a single `Settings` dataclass. Data flows: ingestion → polars transform → sqlite/S3 storage.

**Tech Stack:** Python 3.11+, uv (package manager), polars, dask, pydantic-settings, tomllib, pytest, sqlite3, boto3, python-dotenv

---

## Prerequisites

Install uv if not present:
```bash
pip install uv
```

All commands run from `C:\Users\justi\Documents\money-maker\` unless noted.

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `alpha/__init__.py`
- Create: `alpha/config/__init__.py`
- Create: `.env.example`
- Create: `.gitignore` (append)

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "alpha-terminal"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "polars>=0.20",
    "dask>=2024.1",
    "pydantic-settings>=2.0",
    "python-dotenv>=1.0",
    "requests>=2.31",
    "boto3>=1.34",
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "ruff>=0.3",
]

[tool.hatch.build.targets.wheel]
packages = ["alpha"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"

[tool.ruff]
line-length = 100
target-version = "py311"
```

**Step 2: Create alpha/__init__.py**

```python
"""Alpha Terminal — unified multi-asset trading engine."""
__version__ = "0.1.0"
```

**Step 3: Create .env.example**

```bash
# Alpha Vantage
ALPHA_VANTAGE_API_KEY=your_key_here

# FRED (Federal Reserve)
FRED_API_KEY=your_key_here

# AWS S3 (optional)
AWS_ACCESS_KEY_ID=your_key_here
AWS_SECRET_ACCESS_KEY=your_key_here
AWS_S3_BUCKET=alpha-terminal-data

# Crypto Exchange (ccxt)
EXCHANGE_NAME=binance
EXCHANGE_API_KEY=your_key_here
EXCHANGE_API_SECRET=your_key_here

# Paper trading mode (true = no real orders)
PAPER_MODE=true
```

**Step 4: Create folder structure**

```bash
mkdir -p alpha/config alpha/engines/stocks alpha/engines/crypto alpha/engines/sports
mkdir -p alpha/data/ingestion alpha/data/storage alpha/data/transforms
mkdir -p alpha/signals alpha/risk alpha/execution alpha/reporting
mkdir -p strategies/stocks strategies/crypto strategies/sports
mkdir -p notebooks/stocks notebooks/crypto notebooks/sports
mkdir -p tests/unit/config tests/unit/data tests/unit/engines
mkdir -p tests/integration tests/backtests
mkdir -p scripts
touch alpha/engines/__init__.py alpha/engines/stocks/__init__.py
touch alpha/engines/crypto/__init__.py alpha/engines/sports/__init__.py
touch alpha/data/__init__.py alpha/data/ingestion/__init__.py
touch alpha/data/storage/__init__.py alpha/data/transforms/__init__.py
touch alpha/signals/__init__.py alpha/risk/__init__.py
touch alpha/execution/__init__.py alpha/reporting/__init__.py
```

**Step 5: Install the package**

```bash
uv pip install -e .
```

Expected: `Successfully installed alpha-terminal-0.1.0`

**Step 6: Commit**

```bash
git add pyproject.toml alpha/ strategies/ notebooks/ tests/ scripts/ .env.example
git commit -m "feat: scaffold alpha terminal package structure"
```

---

### Task 2: Config System

**Files:**
- Create: `alpha/config/settings.py`
- Create: `alpha/config/settings.toml`
- Create: `alpha/config/exchanges.toml`
- Create: `alpha/config/risk.toml`
- Create: `alpha/config/sports.toml`
- Test: `tests/unit/config/test_settings.py`

**Step 1: Write failing test**

```python
# tests/unit/config/test_settings.py
import pytest
from alpha.config.settings import Settings, RiskConfig, SportsConfig


def test_settings_loads_defaults():
    s = Settings()
    assert s.paper_mode is True
    assert s.active_verticals == ["stocks", "crypto", "sports"]


def test_risk_config_has_limits():
    r = RiskConfig()
    assert 0 < r.max_drawdown_pct <= 1.0
    assert 0 < r.kelly_fraction <= 1.0
    assert r.max_cross_asset_exposure_pct <= 1.0


def test_sports_config_has_books():
    sc = SportsConfig()
    assert len(sc.books) > 0
    assert len(sc.sports) > 0
```

**Step 2: Run to confirm failure**

```bash
pytest tests/unit/config/test_settings.py -v
```

Expected: `ModuleNotFoundError: No module named 'alpha.config.settings'`

**Step 3: Implement settings.py**

```python
# alpha/config/settings.py
from __future__ import annotations
import tomllib
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

CONFIG_DIR = Path(__file__).parent


def _load_toml(name: str) -> dict:
    path = CONFIG_DIR / name
    if path.exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


class RiskConfig:
    def __init__(self):
        data = _load_toml("risk.toml").get("risk", {})
        self.max_drawdown_pct: float = data.get("max_drawdown_pct", 0.15)
        self.kelly_fraction: float = data.get("kelly_fraction", 0.25)
        self.max_cross_asset_exposure_pct: float = data.get("max_cross_asset_exposure_pct", 0.80)
        self.circuit_breaker_daily_loss_pct: float = data.get("circuit_breaker_daily_loss_pct", 0.05)


class SportsConfig:
    def __init__(self):
        data = _load_toml("sports.toml").get("sports", {})
        self.books: list[str] = data.get("books", ["fanduel", "draftkings", "betmgm"])
        self.sports: list[str] = data.get("sports", ["basketball", "football", "tennis"])
        self.leagues: list[str] = data.get("leagues", ["nba", "nfl", "atp"])
        self.min_ev_threshold: float = data.get("min_ev_threshold", 0.05)


class Settings(BaseSettings):
    paper_mode: bool = True
    active_verticals: list[str] = ["stocks", "crypto", "sports"]

    alpha_vantage_api_key: str = ""
    fred_api_key: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_bucket: str = "alpha-terminal-data"

    exchange_name: str = "binance"
    exchange_api_key: str = ""
    exchange_api_secret: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```

**Step 4: Create TOML config files**

```toml
# alpha/config/risk.toml
[risk]
max_drawdown_pct = 0.15
kelly_fraction = 0.25
max_cross_asset_exposure_pct = 0.80
circuit_breaker_daily_loss_pct = 0.05
```

```toml
# alpha/config/sports.toml
[sports]
books = ["fanduel", "draftkings", "betmgm", "caesars"]
sports = ["basketball", "football", "tennis", "baseball"]
leagues = ["nba", "nfl", "atp", "mlb"]
min_ev_threshold = 0.05
```

```toml
# alpha/config/exchanges.toml
[exchanges]
default = "binance"
sandbox = true
```

```toml
# alpha/config/settings.toml
[terminal]
paper_mode = true
active_verticals = ["stocks", "crypto", "sports"]
log_level = "INFO"
```

**Step 5: Run tests**

```bash
pytest tests/unit/config/ -v
```

Expected: 3 PASSED

**Step 6: Commit**

```bash
git add alpha/config/ tests/unit/config/
git commit -m "feat: add TOML config system with pydantic-settings"
```

---

### Task 3: Storage Layer — SQLite Schema

**Files:**
- Create: `alpha/data/storage/schema.py`
- Create: `alpha/data/storage/sqlite.py`
- Test: `tests/unit/data/test_sqlite.py`

**Step 1: Write failing tests**

```python
# tests/unit/data/test_sqlite.py
import tempfile, os, pytest
from alpha.data.storage.sqlite import AlphaDB
from alpha.data.storage.schema import CREATE_TABLES_SQL


def test_db_creates_tables(tmp_path):
    db = AlphaDB(db_path=str(tmp_path / "test.db"))
    tables = db.list_tables()
    assert "prices" in tables
    assert "signals" in tables
    assert "trades" in tables
    assert "odds" in tables


def test_db_insert_and_fetch_price(tmp_path):
    db = AlphaDB(db_path=str(tmp_path / "test.db"))
    db.insert_price("AAPL", "2026-01-01", 180.50, 181.00, 179.50, 180.75, 1_000_000, "stock")
    rows = db.fetch_prices("AAPL", limit=1)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["close"] == 180.75
```

**Step 2: Run to confirm failure**

```bash
pytest tests/unit/data/test_sqlite.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement schema.py**

```python
# alpha/data/storage/schema.py
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL NOT NULL,
    volume      REAL,
    asset_type  TEXT NOT NULL,  -- 'stock', 'crypto', 'index'
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, date, asset_type)
);

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    vertical    TEXT NOT NULL,  -- 'stocks', 'crypto', 'sports'
    signal_type TEXT NOT NULL,
    value       REAL NOT NULL,
    confidence  REAL,
    meta        TEXT,           -- JSON blob for extra data
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    vertical    TEXT NOT NULL,
    side        TEXT NOT NULL,  -- 'buy', 'sell', 'bet'
    qty         REAL NOT NULL,
    price       REAL NOT NULL,
    status      TEXT NOT NULL,  -- 'open', 'closed', 'cancelled'
    paper       INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now')),
    closed_at   TEXT
);

CREATE TABLE IF NOT EXISTS odds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sport       TEXT NOT NULL,
    league      TEXT NOT NULL,
    event       TEXT NOT NULL,
    market      TEXT NOT NULL,  -- '1x2', 'moneyline', 'totals'
    book        TEXT NOT NULL,
    odds_home   REAL,
    odds_away   REAL,
    odds_draw   REAL,
    ev_home     REAL,
    ev_away     REAL,
    scraped_at  TEXT DEFAULT (datetime('now'))
);
"""
```

**Step 4: Implement sqlite.py**

```python
# alpha/data/storage/sqlite.py
import sqlite3
import json
from pathlib import Path
from alpha.data.storage.schema import CREATE_TABLES_SQL

DEFAULT_DB = Path(__file__).parent.parent.parent.parent / "data" / "alpha.db"


class AlphaDB:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DEFAULT_DB)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(CREATE_TABLES_SQL)

    def list_tables(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        return [r["name"] for r in rows]

    def insert_price(self, symbol, date, open_, high, low, close, volume, asset_type):
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO prices
                   (symbol, date, open, high, low, close, volume, asset_type)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (symbol, date, open_, high, low, close, volume, asset_type),
            )

    def fetch_prices(self, symbol: str, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM prices WHERE symbol=? ORDER BY date DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_signal(self, symbol, vertical, signal_type, value, confidence=None, meta=None):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO signals (symbol, vertical, signal_type, value, confidence, meta)
                   VALUES (?,?,?,?,?,?)""",
                (symbol, vertical, signal_type, value, confidence, json.dumps(meta) if meta else None),
            )

    def insert_odds(self, sport, league, event, market, book, odds_home, odds_away, odds_draw=None, ev_home=None, ev_away=None):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO odds (sport, league, event, market, book, odds_home, odds_away, odds_draw, ev_home, ev_away)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sport, league, event, market, book, odds_home, odds_away, odds_draw, ev_home, ev_away),
            )
```

**Step 5: Run tests**

```bash
pytest tests/unit/data/test_sqlite.py -v
```

Expected: 2 PASSED

**Step 6: Commit**

```bash
git add alpha/data/storage/ tests/unit/data/test_sqlite.py
git commit -m "feat: add sqlite storage layer with unified schema"
```

---

### Task 4: Data Ingestion — Alpha Vantage (Stocks)

**Files:**
- Create: `alpha/data/ingestion/alpha_vantage.py`
- Test: `tests/unit/data/test_alpha_vantage.py`

**Step 1: Write failing tests**

```python
# tests/unit/data/test_alpha_vantage.py
from unittest.mock import patch, MagicMock
import pytest
from alpha.data.ingestion.alpha_vantage import AlphaVantageClient


def test_client_builds_url():
    client = AlphaVantageClient(api_key="TEST")
    url = client._build_url("TIME_SERIES_DAILY", symbol="AAPL")
    assert "TIME_SERIES_DAILY" in url
    assert "AAPL" in url
    assert "TEST" in url


def test_parse_daily_prices():
    client = AlphaVantageClient(api_key="TEST")
    raw = {
        "Time Series (Daily)": {
            "2026-01-02": {
                "1. open": "180.00",
                "2. high": "182.00",
                "3. low": "179.00",
                "4. close": "181.50",
                "5. volume": "1000000",
            }
        }
    }
    rows = client._parse_daily(raw, "AAPL")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["close"] == 181.50
    assert rows[0]["asset_type"] == "stock"


@patch("alpha.data.ingestion.alpha_vantage.requests.get")
def test_fetch_returns_rows(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "Time Series (Daily)": {
            "2026-01-02": {
                "1. open": "180.00", "2. high": "182.00",
                "3. low": "179.00", "4. close": "181.50", "5. volume": "1000000"
            }
        }
    }
    mock_get.return_value = mock_response
    client = AlphaVantageClient(api_key="TEST")
    rows = client.fetch_daily("AAPL")
    assert len(rows) == 1
```

**Step 2: Run to confirm failure**

```bash
pytest tests/unit/data/test_alpha_vantage.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement alpha_vantage.py**

```python
# alpha/data/ingestion/alpha_vantage.py
import requests
from alpha.config.settings import Settings

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Settings().alpha_vantage_api_key

    def _build_url(self, function: str, **params) -> str:
        parts = f"{BASE_URL}?function={function}&apikey={self.api_key}"
        for k, v in params.items():
            parts += f"&{k}={v}"
        return parts

    def _parse_daily(self, raw: dict, symbol: str) -> list[dict]:
        ts = raw.get("Time Series (Daily)", {})
        rows = []
        for date, vals in ts.items():
            rows.append({
                "symbol": symbol,
                "date": date,
                "open": float(vals["1. open"]),
                "high": float(vals["2. high"]),
                "low": float(vals["3. low"]),
                "close": float(vals["4. close"]),
                "volume": float(vals["5. volume"]),
                "asset_type": "stock",
            })
        return rows

    def fetch_daily(self, symbol: str, outputsize: str = "compact") -> list[dict]:
        url = self._build_url("TIME_SERIES_DAILY", symbol=symbol, outputsize=outputsize)
        resp = requests.get(url)
        resp.raise_for_status()
        return self._parse_daily(resp.json(), symbol)

    def fetch_overview(self, symbol: str) -> dict:
        url = self._build_url("OVERVIEW", symbol=symbol)
        resp = requests.get(url)
        resp.raise_for_status()
        return resp.json()
```

**Step 4: Run tests**

```bash
pytest tests/unit/data/test_alpha_vantage.py -v
```

Expected: 3 PASSED

**Step 5: Commit**

```bash
git add alpha/data/ingestion/alpha_vantage.py tests/unit/data/test_alpha_vantage.py
git commit -m "feat: add Alpha Vantage stock data ingestion client"
```

---

### Task 5: Data Ingestion — FRED (Macro)

**Files:**
- Create: `alpha/data/ingestion/fred.py`
- Test: `tests/unit/data/test_fred.py`

**Step 1: Write failing tests**

```python
# tests/unit/data/test_fred.py
from unittest.mock import patch, MagicMock
from alpha.data.ingestion.fred import FREDClient


def test_client_builds_url():
    client = FREDClient(api_key="TEST")
    url = client._build_url("DFF")
    assert "DFF" in url
    assert "TEST" in url


def test_parse_series():
    client = FREDClient(api_key="TEST")
    raw = {
        "observations": [
            {"date": "2026-01-01", "value": "5.33"},
            {"date": "2026-01-02", "value": "."},  # FRED uses "." for missing
        ]
    }
    rows = client._parse_observations(raw, "DFF")
    assert len(rows) == 1  # missing filtered out
    assert rows[0]["value"] == 5.33
    assert rows[0]["series_id"] == "DFF"


@patch("alpha.data.ingestion.fred.requests.get")
def test_fetch_series(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "observations": [{"date": "2026-01-01", "value": "5.33"}]
    }
    mock_get.return_value = mock_response
    client = FREDClient(api_key="TEST")
    rows = client.fetch_series("DFF")
    assert len(rows) == 1
```

**Step 2: Run to confirm failure**

```bash
pytest tests/unit/data/test_fred.py -v
```

**Step 3: Implement fred.py**

```python
# alpha/data/ingestion/fred.py
import requests
from alpha.config.settings import Settings

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Key macro series for risk regime gating
KEY_SERIES = {
    "DFF": "Fed Funds Rate",
    "T10Y2Y": "10Y-2Y Yield Spread (recession signal)",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI (inflation)",
    "VIXCLS": "VIX (fear index)",
    "DXY": "US Dollar Index",
}


class FREDClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Settings().fred_api_key

    def _build_url(self, series_id: str, **params) -> str:
        url = f"{BASE_URL}?series_id={series_id}&api_key={self.api_key}&file_type=json"
        for k, v in params.items():
            url += f"&{k}={v}"
        return url

    def _parse_observations(self, raw: dict, series_id: str) -> list[dict]:
        rows = []
        for obs in raw.get("observations", []):
            if obs["value"] == ".":
                continue
            rows.append({
                "series_id": series_id,
                "date": obs["date"],
                "value": float(obs["value"]),
            })
        return rows

    def fetch_series(self, series_id: str, limit: int = 252) -> list[dict]:
        url = self._build_url(series_id, limit=limit, sort_order="desc")
        resp = requests.get(url)
        resp.raise_for_status()
        return self._parse_observations(resp.json(), series_id)

    def fetch_macro_regime(self) -> dict[str, float | None]:
        """Fetch latest value for all key macro indicators."""
        regime = {}
        for series_id in KEY_SERIES:
            try:
                rows = self.fetch_series(series_id, limit=1)
                regime[series_id] = rows[0]["value"] if rows else None
            except Exception:
                regime[series_id] = None
        return regime
```

**Step 4: Run tests**

```bash
pytest tests/unit/data/test_fred.py -v
```

Expected: 3 PASSED

**Step 5: Commit**

```bash
git add alpha/data/ingestion/fred.py tests/unit/data/test_fred.py
git commit -m "feat: add FRED macro data ingestion with regime indicators"
```

---

### Task 6: Data Ingestion — Crypto (ccxt wrapper)

**Files:**
- Create: `alpha/data/ingestion/crypto_feeds.py`
- Test: `tests/unit/data/test_crypto_feeds.py`

**Step 1: Install ccxt as local dep**

```bash
uv pip install -e ./ccxt/python
```

**Step 2: Write failing tests**

```python
# tests/unit/data/test_crypto_feeds.py
from unittest.mock import patch, MagicMock
import pytest
from alpha.data.ingestion.crypto_feeds import CryptoFeedClient


def test_client_initializes_exchange():
    client = CryptoFeedClient(exchange_name="binance", sandbox=True)
    assert client.exchange_name == "binance"


def test_parse_ohlcv():
    client = CryptoFeedClient(exchange_name="binance", sandbox=True)
    raw = [[1704067200000, 42000.0, 43000.0, 41500.0, 42500.0, 1500.5]]
    rows = client._parse_ohlcv(raw, "BTC/USDT")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTC/USDT"
    assert rows[0]["close"] == 42500.0
    assert rows[0]["asset_type"] == "crypto"
    assert "date" in rows[0]
```

**Step 3: Run to confirm failure**

```bash
pytest tests/unit/data/test_crypto_feeds.py -v
```

**Step 4: Implement crypto_feeds.py**

```python
# alpha/data/ingestion/crypto_feeds.py
from datetime import datetime, timezone
import ccxt
from alpha.config.settings import Settings


class CryptoFeedClient:
    def __init__(
        self,
        exchange_name: str | None = None,
        sandbox: bool = True,
        api_key: str | None = None,
        api_secret: str | None = None,
    ):
        settings = Settings()
        self.exchange_name = exchange_name or settings.exchange_name
        ExchangeClass = getattr(ccxt, self.exchange_name)
        self.exchange = ExchangeClass({
            "apiKey": api_key or settings.exchange_api_key,
            "secret": api_secret or settings.exchange_api_secret,
            "sandbox": sandbox,
            "enableRateLimit": True,
        })

    def _parse_ohlcv(self, raw: list, symbol: str) -> list[dict]:
        rows = []
        for candle in raw:
            ts_ms, open_, high, low, close, vol = candle
            rows.append({
                "symbol": symbol,
                "date": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
                "asset_type": "crypto",
            })
        return rows

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 100) -> list[dict]:
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return self._parse_ohlcv(raw, symbol)

    def fetch_ticker(self, symbol: str) -> dict:
        return self.exchange.fetch_ticker(symbol)

    def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
        return self.exchange.fetch_order_book(symbol, limit=limit)
```

**Step 5: Run tests**

```bash
pytest tests/unit/data/test_crypto_feeds.py -v
```

Expected: 2 PASSED

**Step 6: Commit**

```bash
git add alpha/data/ingestion/crypto_feeds.py tests/unit/data/test_crypto_feeds.py
git commit -m "feat: add ccxt crypto feed client for OHLCV and order book"
```

---

### Task 7: Data Ingestion — OddsHarvester (Sports)

**Files:**
- Create: `alpha/data/ingestion/odds_feed.py`
- Test: `tests/unit/data/test_odds_feed.py`

**Step 1: Install OddsHarvester as local dep**

```bash
uv pip install -e ./OddsHarvester
```

**Step 2: Write failing tests**

```python
# tests/unit/data/test_odds_feed.py
from unittest.mock import patch, MagicMock
from alpha.data.ingestion.odds_feed import OddsIngester


def test_ingester_builds_scrape_params():
    ingester = OddsIngester()
    params = ingester._build_params(sport="basketball", markets=["1x2"])
    assert params["sport"] == "basketball"
    assert "1x2" in params["markets"]


def test_parse_odds_row():
    ingester = OddsIngester()
    raw = {
        "home_team": "Lakers",
        "away_team": "Celtics",
        "odds_home": 1.85,
        "odds_away": 2.10,
        "book": "fanduel",
        "market": "moneyline",
    }
    row = ingester._parse_row(raw, sport="basketball", league="nba")
    assert row["event"] == "Lakers vs Celtics"
    assert row["sport"] == "basketball"
    assert row["odds_home"] == 1.85
```

**Step 3: Run to confirm failure**

```bash
pytest tests/unit/data/test_odds_feed.py -v
```

**Step 4: Implement odds_feed.py**

```python
# alpha/data/ingestion/odds_feed.py
from alpha.config.settings import Settings


class OddsIngester:
    """
    Wrapper around OddsHarvester to standardize odds data
    into the Alpha Terminal's storage schema.
    """

    def __init__(self):
        self.settings = Settings()

    def _build_params(self, sport: str, markets: list[str]) -> dict:
        return {"sport": sport, "markets": markets}

    def _parse_row(self, raw: dict, sport: str, league: str) -> dict:
        home = raw.get("home_team", "")
        away = raw.get("away_team", "")
        return {
            "sport": sport,
            "league": league,
            "event": f"{home} vs {away}",
            "market": raw.get("market", ""),
            "book": raw.get("book", ""),
            "odds_home": raw.get("odds_home"),
            "odds_away": raw.get("odds_away"),
            "odds_draw": raw.get("odds_draw"),
        }

    def scrape_upcoming(self, sport: str, league: str, markets: list[str]) -> list[dict]:
        """
        Calls OddsHarvester CLI programmatically.
        Returns parsed odds rows ready for AlphaDB.insert_odds().
        """
        try:
            from oddsharvester.core.scraper import scrape_upcoming
            raw_rows = scrape_upcoming(sport=sport, markets=markets)
            return [self._parse_row(r, sport, league) for r in raw_rows]
        except ImportError:
            # OddsHarvester not available; return empty (for tests)
            return []
```

**Step 5: Run tests**

```bash
pytest tests/unit/data/test_odds_feed.py -v
```

Expected: 2 PASSED

**Step 6: Commit**

```bash
git add alpha/data/ingestion/odds_feed.py tests/unit/data/test_odds_feed.py
git commit -m "feat: add OddsHarvester sports odds ingestion wrapper"
```

---

### Task 8: Polars Transform Layer

**Files:**
- Create: `alpha/data/transforms/features.py`
- Create: `alpha/data/transforms/normalizers.py`
- Test: `tests/unit/data/test_transforms.py`

**Step 1: Write failing tests**

```python
# tests/unit/data/test_transforms.py
import polars as pl
import pytest
from alpha.data.transforms.features import add_returns, add_moving_averages, add_rsi
from alpha.data.transforms.normalizers import zscore_normalize


def _sample_df():
    return pl.DataFrame({
        "symbol": ["AAPL"] * 30,
        "date": [f"2026-01-{i+1:02d}" for i in range(30)],
        "close": [float(100 + i + (i % 3)) for i in range(30)],
    })


def test_add_returns():
    df = add_returns(_sample_df())
    assert "return_1d" in df.columns
    assert df["return_1d"][0] is None  # first row has no prior


def test_add_moving_averages():
    df = add_moving_averages(_sample_df(), windows=[5, 10])
    assert "ma_5" in df.columns
    assert "ma_10" in df.columns


def test_add_rsi():
    df = add_rsi(_sample_df(), period=14)
    assert "rsi_14" in df.columns
    # RSI must be between 0 and 100 for valid rows
    valid = df.filter(pl.col("rsi_14").is_not_null())["rsi_14"]
    assert (valid >= 0).all() and (valid <= 100).all()


def test_zscore_normalize():
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
    norm = zscore_normalize(df, "close")
    assert "close_z" in norm.columns
    # mean of z-scores should be ~0
    assert abs(norm["close_z"].mean()) < 1e-10
```

**Step 2: Run to confirm failure**

```bash
pytest tests/unit/data/test_transforms.py -v
```

**Step 3: Implement features.py**

```python
# alpha/data/transforms/features.py
import polars as pl


def add_returns(df: pl.DataFrame, price_col: str = "close") -> pl.DataFrame:
    return df.with_columns(
        pl.col(price_col).pct_change().alias("return_1d")
    )


def add_moving_averages(df: pl.DataFrame, windows: list[int], price_col: str = "close") -> pl.DataFrame:
    exprs = [
        pl.col(price_col).rolling_mean(window_size=w).alias(f"ma_{w}")
        for w in windows
    ]
    return df.with_columns(exprs)


def add_rsi(df: pl.DataFrame, period: int = 14, price_col: str = "close") -> pl.DataFrame:
    delta = df[price_col].diff()
    gain = delta.map_elements(lambda x: x if x > 0 else 0.0, return_dtype=pl.Float64)
    loss = delta.map_elements(lambda x: -x if x < 0 else 0.0, return_dtype=pl.Float64)
    avg_gain = gain.rolling_mean(window_size=period)
    avg_loss = loss.rolling_mean(window_size=period)
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return df.with_columns(rsi.alias(f"rsi_{period}"))


def build_feature_set(df: pl.DataFrame) -> pl.DataFrame:
    """Standard feature set used across all verticals."""
    df = add_returns(df)
    df = add_moving_averages(df, windows=[5, 10, 20, 50])
    df = add_rsi(df, period=14)
    return df
```

**Step 4: Implement normalizers.py**

```python
# alpha/data/transforms/normalizers.py
import polars as pl


def zscore_normalize(df: pl.DataFrame, col: str) -> pl.DataFrame:
    mean = df[col].mean()
    std = df[col].std()
    return df.with_columns(
        ((pl.col(col) - mean) / std).alias(f"{col}_z")
    )


def minmax_normalize(df: pl.DataFrame, col: str) -> pl.DataFrame:
    min_val = df[col].min()
    max_val = df[col].max()
    return df.with_columns(
        ((pl.col(col) - min_val) / (max_val - min_val)).alias(f"{col}_norm")
    )
```

**Step 5: Run tests**

```bash
pytest tests/unit/data/test_transforms.py -v
```

Expected: 4 PASSED

**Step 6: Commit**

```bash
git add alpha/data/transforms/ tests/unit/data/test_transforms.py
git commit -m "feat: add polars feature engineering and normalization transforms"
```

---

### Task 9: Macro Filter (Risk-Off Gating)

**Files:**
- Create: `alpha/signals/macro_filter.py`
- Test: `tests/unit/test_macro_filter.py`

**Step 1: Write failing tests**

```python
# tests/unit/test_macro_filter.py
from alpha.signals.macro_filter import MacroFilter


def test_risk_on_when_conditions_normal():
    f = MacroFilter()
    regime = {"DFF": 5.0, "T10Y2Y": 0.5, "VIXCLS": 18.0, "UNRATE": 4.2}
    assert f.is_risk_on(regime) is True


def test_risk_off_when_vix_spikes():
    f = MacroFilter()
    regime = {"DFF": 5.0, "T10Y2Y": 0.5, "VIXCLS": 40.0, "UNRATE": 4.2}
    assert f.is_risk_on(regime) is False


def test_risk_off_when_yield_curve_inverted():
    f = MacroFilter()
    regime = {"DFF": 5.0, "T10Y2Y": -0.5, "VIXCLS": 18.0, "UNRATE": 4.2}
    assert f.is_risk_on(regime) is False


def test_get_regime_label():
    f = MacroFilter()
    assert f.get_label({"VIXCLS": 40.0, "T10Y2Y": -0.3}) == "risk_off"
    assert f.get_label({"VIXCLS": 15.0, "T10Y2Y": 0.5}) == "risk_on"
```

**Step 2: Run to confirm failure**

```bash
pytest tests/unit/test_macro_filter.py -v
```

**Step 3: Implement macro_filter.py**

```python
# alpha/signals/macro_filter.py

VIX_RISK_OFF_THRESHOLD = 30.0
YIELD_CURVE_INVERSION_THRESHOLD = 0.0


class MacroFilter:
    """
    Gates capital deployment across all verticals based on macro regime.
    When risk_off: all engines reduce position size or pause entirely.
    """

    def __init__(
        self,
        vix_threshold: float = VIX_RISK_OFF_THRESHOLD,
        yield_curve_threshold: float = YIELD_CURVE_INVERSION_THRESHOLD,
    ):
        self.vix_threshold = vix_threshold
        self.yield_curve_threshold = yield_curve_threshold

    def is_risk_on(self, regime: dict[str, float | None]) -> bool:
        vix = regime.get("VIXCLS")
        spread = regime.get("T10Y2Y")
        if vix is not None and vix >= self.vix_threshold:
            return False
        if spread is not None and spread <= self.yield_curve_threshold:
            return False
        return True

    def get_label(self, regime: dict[str, float | None]) -> str:
        return "risk_on" if self.is_risk_on(regime) else "risk_off"

    def get_position_scalar(self, regime: dict[str, float | None]) -> float:
        """Returns a multiplier [0.0, 1.0] to scale position sizes."""
        if not self.is_risk_on(regime):
            return 0.25  # deploy only 25% of normal size in risk-off
        vix = regime.get("VIXCLS", 15.0) or 15.0
        # Linearly reduce from 1.0 at VIX=15 to 0.5 at VIX=30
        scalar = max(0.5, 1.0 - ((vix - 15.0) / 30.0))
        return round(scalar, 2)
```

**Step 4: Run tests**

```bash
pytest tests/unit/test_macro_filter.py -v
```

Expected: 4 PASSED

**Step 5: Commit**

```bash
git add alpha/signals/macro_filter.py tests/unit/test_macro_filter.py
git commit -m "feat: add FRED macro regime filter for cross-vertical risk gating"
```

---

### Task 10: Orchestrator Skeleton

**Files:**
- Create: `alpha/orchestrator.py`
- Test: `tests/unit/test_orchestrator.py`

**Step 1: Write failing tests**

```python
# tests/unit/test_orchestrator.py
from unittest.mock import MagicMock, patch
from alpha.orchestrator import Orchestrator


def test_orchestrator_initializes_with_verticals():
    orch = Orchestrator(verticals=["stocks", "crypto", "sports"])
    assert "stocks" in orch.verticals
    assert "crypto" in orch.verticals
    assert "sports" in orch.verticals


def test_orchestrator_skips_disabled_verticals():
    orch = Orchestrator(verticals=["stocks"])
    assert "crypto" not in orch.verticals
    assert "sports" not in orch.verticals


def test_orchestrator_respects_risk_off(monkeypatch):
    orch = Orchestrator(verticals=["stocks", "crypto", "sports"])
    monkeypatch.setattr(orch.macro_filter, "is_risk_on", lambda r: False)
    scalar = orch.macro_filter.get_position_scalar({"VIXCLS": 45.0})
    assert scalar == 0.25
```

**Step 2: Run to confirm failure**

```bash
pytest tests/unit/test_orchestrator.py -v
```

**Step 3: Implement orchestrator.py**

```python
# alpha/orchestrator.py
"""
Main orchestrator — schedules all engines, routes signals,
applies macro filter, and coordinates execution.
"""
import logging
from alpha.config.settings import Settings
from alpha.signals.macro_filter import MacroFilter

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, verticals: list[str] | None = None):
        self.settings = Settings()
        self.verticals = verticals or self.settings.active_verticals
        self.macro_filter = MacroFilter()
        logger.info(f"Orchestrator initialized with verticals: {self.verticals}")

    def run_cycle(self):
        """
        One full cycle: fetch macro regime → gate → run active engines.
        Called by scheduler (modal cron or scripts/daily_scan.py).
        """
        from alpha.data.ingestion.fred import FREDClient

        logger.info("Starting orchestration cycle")
        regime = {}
        try:
            regime = FREDClient().fetch_macro_regime()
            label = self.macro_filter.get_label(regime)
            scalar = self.macro_filter.get_position_scalar(regime)
            logger.info(f"Macro regime: {label} | position scalar: {scalar}")
        except Exception as e:
            logger.warning(f"Macro fetch failed, assuming risk_on: {e}")
            scalar = 1.0

        for vertical in self.verticals:
            try:
                self._run_vertical(vertical, position_scalar=scalar)
            except Exception as e:
                logger.error(f"Vertical {vertical} failed: {e}", exc_info=True)

    def _run_vertical(self, vertical: str, position_scalar: float = 1.0):
        """Dispatch to individual engine. Engines added in Milestone 2."""
        logger.info(f"Running vertical: {vertical} (scalar={position_scalar})")
        # TODO: wire engines in Milestone 2
```

**Step 4: Run tests**

```bash
pytest tests/unit/test_orchestrator.py -v
```

Expected: 3 PASSED

**Step 5: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All passing

**Step 6: Final commit**

```bash
git add alpha/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat: add orchestrator skeleton with macro gating and vertical dispatch"
```

---

## Milestone 1 Complete — Verification

```bash
# Run full suite
pytest tests/ -v --cov=alpha --cov-report=term-missing

# Verify package installs cleanly
uv pip install -e . --quiet && python -c "import alpha; print(alpha.__version__)"

# Verify orchestrator runs without error
python -c "from alpha.orchestrator import Orchestrator; o = Orchestrator(); print('OK')"
```

Expected output:
```
0.1.0
OK
```

---

## Next Milestones

| Milestone | Focus |
|---|---|
| **2** | Stock Engine: qlib alpha factory + PyPortfolioOpt + scikit-learn signals |
| **3** | Crypto Engine: whale tracker (networkx) + freqtrade strategy runner + hummingbot |
| **4** | Sports Engine: NBA-ML wrapper + Kelly sizing + EV calculator |
| **5** | Risk Layer: cross-asset position sizer + drawdown circuit breaker |
| **6** | Execution: broker + exchange + sportsbook routing |
| **7** | Reporting: plotly dashboard + P&L tracker + audit log |
| **8** | Retraining Loop: modal cron + pytorch-lightning + timesfm fine-tuning |
| **9** | GTM: startup-canvas → pricing-strategy → programmatic-seo |
