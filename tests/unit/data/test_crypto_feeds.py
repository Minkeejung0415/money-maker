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
