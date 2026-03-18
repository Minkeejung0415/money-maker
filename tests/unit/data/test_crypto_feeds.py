from unittest.mock import patch, MagicMock
import pytest
from alpha.data.ingestion.crypto_feeds import CryptoFeedClient, fetch_ohlcv


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


# ---------------------------------------------------------------------------
# Fix 3: module-level fetch_ohlcv tests
# ---------------------------------------------------------------------------

def _mock_raw_candles():
    return [
        [1704067200000, 42000.0, 43000.0, 41500.0, 42500.0, 1500.5],
        [1704153600000, 42500.0, 44000.0, 42000.0, 43800.0, 1200.0],
    ]


def test_fetch_ohlcv_returns_correct_row_format():
    """fetch_ohlcv returns rows with required keys and correct asset_type."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv.return_value = _mock_raw_candles()

    with patch("alpha.data.ingestion.crypto_feeds._make_exchange", return_value=mock_exchange):
        rows = fetch_ohlcv("BTC/USDT", exchange_id="binance", timeframe="1d", limit=100)

    assert len(rows) == 2
    required_keys = {"symbol", "date", "open", "high", "low", "close", "volume", "asset_type"}
    assert required_keys.issubset(set(rows[0].keys()))
    assert rows[0]["symbol"] == "BTC/USDT"
    assert rows[0]["close"] == 42500.0
    assert rows[0]["asset_type"] == "crypto"


def test_fetch_ohlcv_passes_timeframe_and_limit():
    """fetch_ohlcv forwards timeframe and limit to the ccxt exchange."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv.return_value = _mock_raw_candles()

    with patch("alpha.data.ingestion.crypto_feeds._make_exchange", return_value=mock_exchange):
        fetch_ohlcv("ETH/USDT", exchange_id="binance", timeframe="1d", limit=50)

    mock_exchange.fetch_ohlcv.assert_called_once_with("ETH/USDT", timeframe="1d", limit=50)
