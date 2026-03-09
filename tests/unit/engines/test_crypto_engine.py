import pytest
from alpha.engines.crypto.engine import CryptoEngine


def _ohlcv_rows(symbol="BTC/USDT", n=60, base_price=42000.0):
    rows = []
    price = base_price
    for i in range(n):
        price *= (1 + (0.001 if i % 3 != 0 else -0.002))
        rows.append({
            "symbol": symbol,
            "date": f"2026-01-{(i % 28) + 1:02d}",
            "open": price * 0.998,
            "high": price * 1.005,
            "low": price * 0.995,
            "close": price,
            "volume": 1_000_000.0 + i * 10_000,
            "asset_type": "crypto",
        })
    return rows


_UNIVERSE = {
    "BTC/USDT": _ohlcv_rows("BTC/USDT", base_price=42000.0),
    "ETH/USDT": _ohlcv_rows("ETH/USDT", base_price=3000.0),
}


def test_engine_initializes():
    engine = CryptoEngine()
    assert engine is not None


def test_analyze_symbol_returns_signal():
    engine = CryptoEngine()
    rows = _ohlcv_rows()
    result = engine.analyze_symbol("BTC/USDT", rows)
    assert result["symbol"] == "BTC/USDT"
    assert result["action"] in ("buy", "sell", "hold")


def test_run_universe_returns_result():
    engine = CryptoEngine()
    result = engine.run_universe(_UNIVERSE, position_scalar=1.0)
    assert "signals" in result
    assert "weights" in result
    assert "regime_scalar" in result


def test_risk_off_reduces_weights():
    engine = CryptoEngine()
    full = engine.run_universe(_UNIVERSE, position_scalar=1.0)
    reduced = engine.run_universe(_UNIVERSE, position_scalar=0.25)
    full_w = sum(full["weights"].values())
    reduced_w = sum(reduced["weights"].values())
    assert reduced_w <= full_w + 1e-9
