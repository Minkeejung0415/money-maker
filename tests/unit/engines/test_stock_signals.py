from unittest.mock import MagicMock, patch
import polars as pl
from alpha.engines.stocks.signals import StockSignalEngine


def _mock_price_rows(symbol="AAPL", n=30):
    return [
        {
            "symbol": symbol,
            "date": f"2026-01-{i+1:02d}",
            "open": float(150 + i),
            "high": float(152 + i),
            "low": float(149 + i),
            "close": float(151 + i + (i % 3)),
            "volume": 1_000_000.0,
            "asset_type": "stock",
        }
        for i in range(n)
    ]


def test_signal_engine_initializes():
    engine = StockSignalEngine(av_api_key="TEST", fred_api_key="TEST")
    assert engine is not None


def test_build_features_returns_dataframe():
    engine = StockSignalEngine(av_api_key="TEST", fred_api_key="TEST")
    rows = _mock_price_rows()
    df = engine.build_features(rows)
    assert isinstance(df, pl.DataFrame)
    assert "return_1d" in df.columns
    assert "ma_5" in df.columns
    assert "rsi_14" in df.columns


def test_score_returns_float():
    engine = StockSignalEngine(av_api_key="TEST", fred_api_key="TEST")
    rows = _mock_price_rows()
    df = engine.build_features(rows)
    score = engine.score(df)
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0


def test_signal_is_buy_sell_or_hold():
    engine = StockSignalEngine(av_api_key="TEST", fred_api_key="TEST")
    rows = _mock_price_rows()
    signal = engine.get_signal(rows)
    assert signal["action"] in ("buy", "sell", "hold")
    assert "score" in signal
    assert "symbol" in signal
