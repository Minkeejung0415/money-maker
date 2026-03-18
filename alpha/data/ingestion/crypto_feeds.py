from datetime import datetime, timezone
import ccxt
from alpha.config.settings import Settings


def _make_exchange(exchange_id: str, params: dict | None = None):
    """Instantiate a ccxt exchange, compatible with ccxt v4+ submodule layout."""
    import importlib  # noqa: PLC0415
    try:
        # ccxt v4+: exchange classes live in ccxt.<exchange_id>.<exchange_id>
        mod = importlib.import_module(f"ccxt.{exchange_id}")
        ExchangeClass = getattr(mod, exchange_id)
    except (ModuleNotFoundError, AttributeError):
        # Fallback for older ccxt versions
        ExchangeClass = getattr(ccxt, exchange_id)
    return ExchangeClass(params or {"enableRateLimit": True})


def fetch_ohlcv(
    symbol: str,
    exchange_id: str = "binance",
    timeframe: str = "1d",
    limit: int = 100,
) -> list[dict]:
    """
    Convenience function: fetch OHLCV rows for *symbol* from a public exchange
    endpoint (no API key required for market data on most exchanges).

    Returns rows with keys: symbol, date, open, high, low, close, volume, asset_type.
    """
    exchange = _make_exchange(exchange_id, {"enableRateLimit": True})
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    rows = []
    for candle in raw:
        ts_ms, open_, high, low, close, vol = candle
        rows.append({
            "symbol": symbol,
            "date": datetime.fromtimestamp(
                ts_ms / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "asset_type": "crypto",
        })
    return rows


class CryptoFeedClient:
    def __init__(
        self,
        exchange_name: str | None = None,
        sandbox: bool = True,
        api_key: str | None = None,
        api_secret: str | None = None,
    ):
        settings = Settings()
        self.exchange_name = exchange_name or settings.exchange_name
        self.exchange = _make_exchange(self.exchange_name, {
            "apiKey": api_key or settings.exchange_api_key,
            "secret": api_secret or settings.exchange_api_secret,
            "sandbox": sandbox,
            "enableRateLimit": True,
        })

    def _parse_ohlcv(self, raw: list, symbol: str) -> list[dict]:
        rows = []
        for candle in raw:
            ts_ms, open_, high, low, close, vol = candle
            rows.append({
                "symbol": symbol,
                "date": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
                "asset_type": "crypto",
            })
        return rows

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 100) -> list[dict]:
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return self._parse_ohlcv(raw, symbol)

    def fetch_ticker(self, symbol: str) -> dict:
        return self.exchange.fetch_ticker(symbol)

    def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
        return self.exchange.fetch_order_book(symbol, limit=limit)
