import pytest
from alpha.engines.stocks.screener import StockScreener


_UNIVERSE = [
    {"symbol": "AAPL", "close": 180.0, "ma_20": 170.0, "rsi_14": 55.0, "return_1d": 0.01, "volume": 80_000_000.0},
    {"symbol": "MSFT", "close": 300.0, "ma_20": 310.0, "rsi_14": 45.0, "return_1d": -0.005, "volume": 30_000_000.0},
    {"symbol": "NVDA", "close": 500.0, "ma_20": 450.0, "rsi_14": 68.0, "return_1d": 0.03, "volume": 50_000_000.0},
    {"symbol": "TSLA", "close": 200.0, "ma_20": 220.0, "rsi_14": 35.0, "return_1d": -0.02, "volume": 20_000_000.0},
]


def test_screener_returns_ranked_list():
    screener = StockScreener()
    results = screener.rank(_UNIVERSE)
    assert len(results) == len(_UNIVERSE)
    assert all("score" in r for r in results)
    # Results should be sorted descending by score
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_screener_top_n():
    screener = StockScreener()
    results = screener.top(n=2, universe=_UNIVERSE)
    assert len(results) == 2


def test_screener_filters_by_min_volume():
    screener = StockScreener(min_volume=40_000_000)
    results = screener.rank(_UNIVERSE)
    for r in results:
        assert r["volume"] >= 40_000_000


def test_screener_filters_overbought():
    screener = StockScreener(max_rsi=65.0)
    results = screener.rank(_UNIVERSE)
    for r in results:
        assert r["rsi_14"] <= 65.0
