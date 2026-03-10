from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


@patch("alpha.execution.exchange.ccxt")
def test_submit_order_success(mock_ccxt: MagicMock) -> None:
    # Arrange mocked exchange
    exchange_cls = MagicMock()
    exchange = MagicMock()
    exchange.load_markets.return_value = {
        "BTC/USDT": {"info": {"lastPrice": "50000"}},
    }
    exchange.create_market_order.return_value = {"id": "abc", "status": "filled"}
    exchange.fetch_ticker.return_value = {"last": 50000}
    exchange_cls.return_value = exchange
    mock_ccxt.binance = exchange_cls

    from alpha.execution.exchange import CryptoExecutor

    executor = CryptoExecutor(exchange_id="binance", paper=True)

    result = executor.submit_order("BTC/USDT", "buy", 1000.0)

    assert result["id"] == "abc"
    assert result["symbol"] == "BTC/USDT"
    assert result["side"] == "buy"
    assert result["amount_usd"] == 1000.0
    assert result["status"] == "filled"


@patch("alpha.execution.exchange.ccxt")
def test_submit_order_returns_error_on_exception(mock_ccxt: MagicMock) -> None:
    exchange_cls = MagicMock()
    exchange = MagicMock()
    exchange.load_markets.return_value = {}
    exchange.fetch_ticker.side_effect = Exception("ticker error")
    exchange_cls.return_value = exchange
    mock_ccxt.binance = exchange_cls

    from alpha.execution.exchange import CryptoExecutor

    executor = CryptoExecutor(exchange_id="binance", paper=True)

    result = executor.submit_order("BTC/USDT", "buy", 100.0)
    assert result["status"] == "error"
    assert "reason" in result


@patch("alpha.execution.exchange.ccxt")
def test_get_balances_filters_non_zero(mock_ccxt: MagicMock) -> None:
    exchange_cls = MagicMock()
    exchange = MagicMock()
    exchange.load_markets.return_value = {}
    exchange.fetch_balance.return_value = {
        "total": {
            "BTC": 0.5,
            "USDT": 0.0,
            "ETH": 1.2,
        }
    }
    exchange_cls.return_value = exchange
    mock_ccxt.binance = exchange_cls

    from alpha.execution.exchange import CryptoExecutor

    executor = CryptoExecutor(exchange_id="binance", paper=True)
    balances = executor.get_balances()

    assert balances == {"BTC": 0.5, "ETH": 1.2}


@patch("alpha.execution.exchange.ccxt")
def test_get_balances_returns_empty_on_exception(mock_ccxt: MagicMock) -> None:
    exchange_cls = MagicMock()
    exchange = MagicMock()
    exchange.load_markets.return_value = {}
    exchange.fetch_balance.side_effect = Exception("boom")
    exchange_cls.return_value = exchange
    mock_ccxt.binance = exchange_cls

    from alpha.execution.exchange import CryptoExecutor

    executor = CryptoExecutor(exchange_id="binance", paper=True)
    balances = executor.get_balances()

    assert balances == {}

