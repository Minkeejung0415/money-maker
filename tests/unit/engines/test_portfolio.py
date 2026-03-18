import pytest
import polars as pl
from alpha.engines.stocks.portfolio import PortfolioOptimizer


def _returns_df():
    """3 assets × 60 daily returns."""
    import random
    random.seed(42)
    data = {
        "AAPL": [random.gauss(0.001, 0.015) for _ in range(60)],
        "MSFT": [random.gauss(0.0008, 0.012) for _ in range(60)],
        "NVDA": [random.gauss(0.002, 0.025) for _ in range(60)],
    }
    return pl.DataFrame(data)


def test_optimizer_initializes():
    opt = PortfolioOptimizer()
    assert opt is not None


def test_max_sharpe_returns_weights():
    opt = PortfolioOptimizer()
    df = _returns_df()
    weights = opt.max_sharpe(df)
    assert isinstance(weights, dict)
    assert set(weights.keys()) == {"AAPL", "MSFT", "NVDA"}
    # Weights sum to ~1.0
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_min_volatility_returns_weights():
    opt = PortfolioOptimizer()
    df = _returns_df()
    weights = opt.min_volatility(df)
    assert isinstance(weights, dict)
    assert abs(sum(weights.values()) - 1.0) < 1e-4


def test_equal_weight_fallback():
    opt = PortfolioOptimizer()
    symbols = ["AAPL", "MSFT", "NVDA"]
    weights = opt.equal_weight(symbols)
    for w in weights.values():
        assert abs(w - 1 / 3) < 1e-9


def test_signal_weighted_strong_signals():
    opt = PortfolioOptimizer()
    df = _returns_df()
    signals = {"AAPL": 0.6, "MSFT": 0.3, "NVDA": 0.8}
    weights = opt.signal_weighted(df, signals)
    assert isinstance(weights, dict)
    assert set(weights.keys()) == {"AAPL", "MSFT", "NVDA"}
    assert abs(sum(weights.values()) - 1.0) < 1e-4


def test_signal_weighted_weak_signals_falls_back_to_equal():
    opt = PortfolioOptimizer()
    df = _returns_df()
    signals = {"AAPL": 0.05, "MSFT": 0.05, "NVDA": 0.05}
    weights = opt.signal_weighted(df, signals, min_signal_strength=0.2)
    # Below threshold → equal weight
    for w in weights.values():
        assert abs(w - 1 / 3) < 1e-9


def test_allocate_uses_signals_when_provided():
    opt = PortfolioOptimizer()
    df = _returns_df()
    signals = {"AAPL": 0.7, "MSFT": 0.4, "NVDA": 0.9}
    weights = opt.allocate(df, signals=signals)
    assert isinstance(weights, dict)
    assert abs(sum(weights.values()) - 1.0) < 1e-4
