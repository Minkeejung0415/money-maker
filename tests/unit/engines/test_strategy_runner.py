import polars as pl
import pytest
from alpha.engines.crypto.strategy_runner import CryptoStrategyRunner


def _ohlcv_rows(symbol="BTC/USDT", n=60):
    rows = []
    price = 42000.0
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


def test_strategy_runner_initializes():
    runner = CryptoStrategyRunner()
    assert runner is not None


def test_run_returns_signal_dict():
    runner = CryptoStrategyRunner()
    rows = _ohlcv_rows()
    signal = runner.run(rows)
    assert "symbol" in signal
    assert "action" in signal
    assert signal["action"] in ("buy", "sell", "hold")
    assert "score" in signal


def test_ema_crossover_strategy():
    runner = CryptoStrategyRunner(strategy="ema_crossover")
    rows = _ohlcv_rows()
    signal = runner.run(rows)
    assert signal["strategy"] == "ema_crossover"


def test_rsi_mean_reversion_strategy():
    runner = CryptoStrategyRunner(strategy="rsi_mean_reversion")
    rows = _ohlcv_rows()
    signal = runner.run(rows)
    assert signal["strategy"] == "rsi_mean_reversion"
