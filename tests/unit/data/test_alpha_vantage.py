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
