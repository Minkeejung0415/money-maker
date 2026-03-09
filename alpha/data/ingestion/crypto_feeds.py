from datetime import datetime, timezone
import ccxt
from alpha.config.settings import Settings


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
        ExchangeClass = getattr(ccxt, self.exchange_name)
        self.exchange = ExchangeClass({
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
