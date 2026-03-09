from unittest.mock import MagicMock, patch
import polars as pl
import pytest
from alpha.engines.stocks.engine import StockEngine


_MOCK_ROWS = [
    {
        "symbol": "AAPL",
        "date": f"2026-01-{i+1:02d}",
        "open": float(150 + i),
        "high": float(152 + i),
        "low": float(149 + i),
        "close": float(151 + i + (i % 3)),
        "volume": 80_000_000.0,
        "asset_type": "stock",
    }
    for i in range(60)
]

_UNIVERSE_ROWS = {
    "AAPL": _MOCK_ROWS,
    "MSFT": [{**r, "symbol": "MSFT", "close": 300.0 + i, "volume": 35_000_000.0} for i, r in enumerate(_MOCK_ROWS)],
}


def test_engine_initializes():
    engine = StockEngine()
    assert engine is not None


def test_analyze_symbol_returns_signal():
    engine = StockEngine()
    result = engine.analyze_symbol("AAPL", _MOCK_ROWS)
    assert result["symbol"] == "AAPL"
    assert result["action"] in ("buy", "sell", "hold")
    assert "score" in result


def test_run_universe_returns_allocations():
    engine = StockEngine()
    result = engine.run_universe(_UNIVERSE_ROWS, position_scalar=1.0)
    assert "signals" in result
    assert "weights" in result
    assert "regime_scalar" in result


def test_position_scalar_reduces_weights():
    engine = StockEngine()
    full = engine.run_universe(_UNIVERSE_ROWS, position_scalar=1.0)
    half = engine.run_universe(_UNIVERSE_ROWS, position_scalar=0.5)
    full_total = sum(full["weights"].values())
    half_total = sum(half["weights"].values())
    assert half_total <= full_total + 1e-9
