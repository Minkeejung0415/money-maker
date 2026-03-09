import requests
from alpha.config.settings import Settings

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Settings().alpha_vantage_api_key

    def _build_url(self, function: str, **params) -> str:
        parts = f"{BASE_URL}?function={function}&apikey={self.api_key}"
        for k, v in params.items():
            parts += f"&{k}={v}"
        return parts

    def _parse_daily(self, raw: dict, symbol: str) -> list[dict]:
        ts = raw.get("Time Series (Daily)", {})
        rows = []
        for date, vals in ts.items():
            rows.append({
                "symbol": symbol,
                "date": date,
                "open": float(vals["1. open"]),
                "high": float(vals["2. high"]),
                "low": float(vals["3. low"]),
                "close": float(vals["4. close"]),
                "volume": float(vals["5. volume"]),
                "asset_type": "stock",
            })
        return rows

    def fetch_daily(self, symbol: str, outputsize: str = "compact") -> list[dict]:
        url = self._build_url("TIME_SERIES_DAILY", symbol=symbol, outputsize=outputsize)
        resp = requests.get(url)
        resp.raise_for_status()
        return self._parse_daily(resp.json(), symbol)

    def fetch_overview(self, symbol: str) -> dict:
        url = self._build_url("OVERVIEW", symbol=symbol)
        resp = requests.get(url)
        resp.raise_for_status()
        return resp.json()
