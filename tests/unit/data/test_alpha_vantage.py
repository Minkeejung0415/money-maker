from unittest.mock import patch, MagicMock
import pytest
from alpha.data.ingestion.alpha_vantage import AlphaVantageClient


def test_client_builds_url():
    client = AlphaVantageClient(api_key="TEST")
    url = client._build_url("TIME_SERIES_DAILY", symbol="AAPL")
    assert "TIME_SERIES_DAILY" in url
    assert "AAPL" in url
    assert "TEST" in url


def test_parse_daily_prices():
    client = AlphaVantageClient(api_key="TEST")
    raw = {
        "Time Series (Daily)": {
            "2026-01-02": {
                "1. open": "180.00",
                "2. high": "182.00",
                "3. low": "179.00",
                "4. close": "181.50",
                "5. volume": "1000000",
            }
        }
    }
    rows = client._parse_daily(raw, "AAPL")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["close"] == 181.50
    assert rows[0]["asset_type"] == "stock"


@patch("alpha.data.ingestion.alpha_vantage.requests.get")
def test_fetch_returns_rows(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "Time Series (Daily)": {
            "2026-01-02": {
                "1. open": "180.00", "2. high": "182.00",
                "3. low": "179.00", "4. close": "181.50", "5. volume": "1000000"
            }
        }
    }
    mock_get.return_value = mock_response
    client = AlphaVantageClient(api_key="TEST")
    rows = client.fetch_daily("AAPL")
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# get_fundamentals tests
# ---------------------------------------------------------------------------

@patch("alpha.data.ingestion.alpha_vantage.requests.get")
def test_get_fundamentals_pass(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "PERatio": "20.5",
        "EPS": "5.00",
        "ProfitMargin": "0.15",
    }
    mock_get.return_value = mock_resp
    client = AlphaVantageClient(api_key="TEST")
    result = client.get_fundamentals("AAPL")
    assert result is not None
    assert result["pe_ratio"] == pytest.approx(20.5)
    assert result["eps"] == pytest.approx(5.0)
    assert result["profit_margin"] == pytest.approx(0.15)


def test_get_fundamentals_no_api_key():
    """Returns None when no API key is set."""
    client = AlphaVantageClient(api_key=None)
    # Monkeypatch Settings to avoid reading env
    client.api_key = None
    result = client.get_fundamentals("AAPL")
    assert result is None


@patch("alpha.data.ingestion.alpha_vantage.requests.get")
def test_get_fundamentals_missing_key_returns_none(mock_get):
    """Missing/non-numeric field in API response returns None."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"PERatio": "None", "EPS": "N/A", "ProfitMargin": "0.10"}
    mock_get.return_value = mock_resp
    client = AlphaVantageClient(api_key="TEST")
    result = client.get_fundamentals("BAD")
    assert result is None


@patch("alpha.data.ingestion.alpha_vantage.requests.get", side_effect=ConnectionError("offline"))
def test_get_fundamentals_network_error_returns_none(mock_get):
    client = AlphaVantageClient(api_key="TEST")
    result = client.get_fundamentals("AAPL")
    assert result is None
