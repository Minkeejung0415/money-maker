import requests
from alpha.config.settings import Settings

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Key macro series for risk regime gating
KEY_SERIES = {
    "DFF": "Fed Funds Rate",
    "T10Y2Y": "10Y-2Y Yield Spread (recession signal)",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI (inflation)",
    "VIXCLS": "VIX (fear index)",
    "DXY": "US Dollar Index",
}


class FREDClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Settings().fred_api_key

    def _build_url(self, series_id: str, **params) -> str:
        url = f"{BASE_URL}?series_id={series_id}&api_key={self.api_key}&file_type=json"
        for k, v in params.items():
            url += f"&{k}={v}"
        return url

    def _parse_observations(self, raw: dict, series_id: str) -> list[dict]:
        rows = []
        for obs in raw.get("observations", []):
            if obs["value"] == ".":
                continue
            rows.append({
                "series_id": series_id,
                "date": obs["date"],
                "value": float(obs["value"]),
            })
        return rows

    def fetch_series(self, series_id: str, limit: int = 252) -> list[dict]:
        url = self._build_url(series_id, limit=limit, sort_order="desc")
        resp = requests.get(url)
        resp.raise_for_status()
        return self._parse_observations(resp.json(), series_id)

    def fetch_macro_regime(self) -> dict[str, float | None]:
        """Fetch latest value for all key macro indicators."""
        regime = {}
        for series_id in KEY_SERIES:
            try:
                rows = self.fetch_series(series_id, limit=1)
                regime[series_id] = rows[0]["value"] if rows else None
            except Exception:
                regime[series_id] = None
        return regime
