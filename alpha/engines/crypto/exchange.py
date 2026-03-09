"""
Exchange connector — thin wrapper over CryptoFeedClient that adds
market-microstructure helpers: spread calculation, liquidity scoring,
and normalized ticker output.
"""
import logging
from alpha.data.ingestion.crypto_feeds import CryptoFeedClient

logger = logging.getLogger(__name__)


class ExchangeConnector:
    def __init__(
        self,
        exchange_name: str | None = None,
        sandbox: bool = True,
        api_key: str | None = None,
        api_secret: str | None = None,
    ):
        self.exchange_name = exchange_name or "binance"
        self._feed = CryptoFeedClient(
            exchange_name=self.exchange_name,
            sandbox=sandbox,
            api_key=api_key,
            api_secret=api_secret,
        )

    def _parse_ticker(self, raw: dict) -> dict:
        """Normalize a ccxt ticker into a clean dict."""
        bid = raw.get("bid") or 0.0
        ask = raw.get("ask") or 0.0
        mid = (bid + ask) / 2 if (bid + ask) > 0 else 0.0
        spread_pct = (ask - bid) / mid if mid > 0 else 0.0
        return {
            "symbol": raw.get("symbol", ""),
            "price": raw.get("last") or mid,
            "bid": bid,
            "ask": ask,
            "spread_pct": round(spread_pct, 6),
            "volume_24h": raw.get("baseVolume") or 0.0,
            "change_pct": raw.get("percentage") or 0.0,
        }

    def get_ticker(self, symbol: str) -> dict:
        raw = self._feed.fetch_ticker(symbol)
        return self._parse_ticker(raw)

    def get_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 100) -> list[dict]:
        return self._feed.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        return self._feed.fetch_order_book(symbol, limit=limit)

    def liquidity_score(self, ticker: dict) -> float:
        """
        Score in [0, 1] based on volume and spread.
        High volume + tight spread = high liquidity.
        """
        vol = ticker.get("volume_24h", 0) or 0.0
        spread = ticker.get("spread_pct", 1.0) or 1.0
        vol_score = min(1.0, vol / 1_000_000_000)   # normalize vs 1B daily vol
        spread_score = max(0.0, 1.0 - spread * 1000)  # 0.1% spread → 0.0 score
        return round((vol_score + spread_score) / 2, 4)
