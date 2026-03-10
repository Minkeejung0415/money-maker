from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from alpha.execution.broker import AlpacaBroker


def _make_response(status_code: int, json_data: Any) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None if 200 <= status_code < 300 else Exception("error")
    return resp


@patch("alpha.execution.broker.httpx.Client")
def test_submit_order_success(mock_client_cls: MagicMock) -> None:
    broker = AlpacaBroker(api_key="k", api_secret="s")

    mock_client = MagicMock()
    mock_resp = _make_response(
        200,
        {
            "id": "order-123",
            "symbol": "AAPL",
            "status": "accepted",
        },
    )
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    result = broker.submit_order("AAPL", 1000.0, "buy")

    assert result["id"] == "order-123"
    assert result["symbol"] == "AAPL"
    assert result["side"] == "buy"
    assert result["dollar_amount"] == 1000.0
    assert result["status"] == "accepted"


@patch("alpha.execution.broker.httpx.Client")
def test_submit_order_http_failure_returns_error(mock_client_cls: MagicMock) -> None:
    broker = AlpacaBroker(api_key="k", api_secret="s")

    mock_client = MagicMock()
    mock_client.post.side_effect = Exception("network down")
    mock_client_cls.return_value.__enter__.return_value = mock_client

    result = broker.submit_order("AAPL", 500.0, "sell")

    assert result["status"] == "error"
    assert "reason" in result


@patch("alpha.execution.broker.httpx.Client")
def test_get_positions_parses_response(mock_client_cls: MagicMock) -> None:
    broker = AlpacaBroker(api_key="k", api_secret="s")

    mock_client = MagicMock()
    mock_resp = _make_response(
        200,
        [
            {"symbol": "AAPL", "qty": "10", "market_value": "2000"},
            {"symbol": "MSFT", "qty": "5", "market_value": "1500"},
        ],
    )
    mock_client.get.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    positions = broker.get_positions()

    assert len(positions) == 2
    assert positions[0] == {"symbol": "AAPL", "qty": 10.0, "market_value": 2000.0}


@patch("alpha.execution.broker.httpx.Client")
def test_get_positions_failure_returns_empty_list(mock_client_cls: MagicMock) -> None:
    broker = AlpacaBroker(api_key="k", api_secret="s")

    mock_client = MagicMock()
    mock_client.get.side_effect = Exception("timeout")
    mock_client_cls.return_value.__enter__.return_value = mock_client

    positions = broker.get_positions()
    assert positions == []


@patch("alpha.execution.broker.httpx.Client")
def test_cancel_all_orders_success_on_207(mock_client_cls: MagicMock) -> None:
    broker = AlpacaBroker(api_key="k", api_secret="s")

    mock_client = MagicMock()
    mock_resp = _make_response(207, [])
    mock_client.delete.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    assert broker.cancel_all_orders() is True


@patch("alpha.execution.broker.httpx.Client")
def test_cancel_all_orders_failure_on_exception(mock_client_cls: MagicMock) -> None:
    broker = AlpacaBroker(api_key="k", api_secret="s")

    mock_client = MagicMock()
    mock_client.delete.side_effect = Exception("boom")
    mock_client_cls.return_value.__enter__.return_value = mock_client

    assert broker.cancel_all_orders() is False

