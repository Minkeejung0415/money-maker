from unittest.mock import MagicMock, patch
import pytest
from alpha.engines.crypto.exchange import ExchangeConnector


def test_connector_initializes():
    conn = ExchangeConnector(exchange_name="binance", sandbox=True)
    assert conn.exchange_name == "binance"


def test_parse_ticker_extracts_fields():
    conn = ExchangeConnector(exchange_name="binance", sandbox=True)
    raw = {
        "symbol": "BTC/USDT",
        "last": 42500.0,
        "bid": 42490.0,
        "ask": 42510.0,
        "baseVolume": 15000.0,
        "percentage": 1.5,
    }
    parsed = conn._parse_ticker(raw)
    assert parsed["symbol"] == "BTC/USDT"
    assert parsed["price"] == 42500.0
    assert parsed["spread_pct"] == pytest.approx(0.000471, abs=1e-4)
    assert parsed["change_pct"] == 1.5


def test_spread_is_zero_for_same_bid_ask():
    conn = ExchangeConnector(exchange_name="binance", sandbox=True)
    raw = {"symbol": "ETH/USDT", "last": 3000.0, "bid": 3000.0, "ask": 3000.0,
           "baseVolume": 5000.0, "percentage": 0.0}
    parsed = conn._parse_ticker(raw)
    assert parsed["spread_pct"] == 0.0
