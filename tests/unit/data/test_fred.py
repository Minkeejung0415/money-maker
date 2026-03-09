from unittest.mock import patch, MagicMock
from alpha.data.ingestion.fred import FREDClient


def test_client_builds_url():
    client = FREDClient(api_key="TEST")
    url = client._build_url("DFF")
    assert "DFF" in url
    assert "TEST" in url


def test_parse_series():
    client = FREDClient(api_key="TEST")
    raw = {
        "observations": [
            {"date": "2026-01-01", "value": "5.33"},
            {"date": "2026-01-02", "value": "."},  # FRED uses "." for missing
        ]
    }
    rows = client._parse_observations(raw, "DFF")
    assert len(rows) == 1  # missing filtered out
    assert rows[0]["value"] == 5.33
    assert rows[0]["series_id"] == "DFF"


@patch("alpha.data.ingestion.fred.requests.get")
def test_fetch_series(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "observations": [{"date": "2026-01-01", "value": "5.33"}]
    }
    mock_get.return_value = mock_response
    client = FREDClient(api_key="TEST")
    rows = client.fetch_series("DFF")
    assert len(rows) == 1
