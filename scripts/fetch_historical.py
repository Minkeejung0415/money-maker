"""
Fetch 5-year historical OHLCV data for stocks and crypto and save to SQLite.
Run this once before running backtest_runner.py.

Usage:
    ./venv/Scripts/python.exe scripts/fetch_historical.py
    ./venv/Scripts/python.exe scripts/fetch_historical.py --vertical stocks
    ./venv/Scripts/python.exe scripts/fetch_historical.py --vertical crypto
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from alpha.config.settings import Settings, StocksConfig, CryptoConfig
from alpha.data.ingestion.alpha_vantage import AlphaVantageClient
from alpha.data.ingestion.crypto_feeds import fetch_ohlcv
from alpha.data.storage.sqlite import AlphaDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# 5 years of daily bars
_CRYPTO_LIMIT = 1826
_AV_RATE_LIMIT_SLEEP = 12  # seconds between Alpha Vantage calls (free tier: 5/min)


def _save_rows(db: AlphaDB, rows: list[dict], label: str) -> None:
    for r in rows:
        db.insert_price(
            symbol=r["symbol"],
            date=r["date"],
            open_=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            asset_type=r["asset_type"],
        )
    logger.info("  saved %d rows for %s", len(rows), label)


def fetch_stocks(db: AlphaDB) -> None:
    settings = Settings()
    if not settings.alpha_vantage_api_key:
        logger.error("ALPHA_VANTAGE_API_KEY not set in .env — cannot fetch stocks")
        return

    cfg = StocksConfig()
    client = AlphaVantageClient(api_key=settings.alpha_vantage_api_key)

    logger.info("Fetching full history for %d stocks (outputsize=full)...", len(cfg.watchlist))
    logger.info("This will take ~%d seconds due to Alpha Vantage rate limits.", len(cfg.watchlist) * _AV_RATE_LIMIT_SLEEP)

    for i, symbol in enumerate(cfg.watchlist):
        try:
            logger.info("[%d/%d] Fetching %s ...", i + 1, len(cfg.watchlist), symbol)
            rows = client.fetch_daily(symbol, outputsize="full")
            if rows:
                _save_rows(db, rows, symbol)
            else:
                logger.warning("  no data returned for %s", symbol)
        except Exception as exc:
            logger.warning("  failed to fetch %s: %s", symbol, exc)

        # Alpha Vantage free tier: 5 calls/min — sleep between calls
        if i < len(cfg.watchlist) - 1:
            time.sleep(_AV_RATE_LIMIT_SLEEP)

    logger.info("Stocks fetch complete.")


def fetch_crypto(db: AlphaDB) -> None:
    cfg = CryptoConfig()
    logger.info("Fetching %d days of history for %d crypto pairs...", _CRYPTO_LIMIT, len(cfg.pairs))

    for pair in cfg.pairs:
        try:
            logger.info("  Fetching %s ...", pair)
            rows = fetch_ohlcv(pair, exchange_id="binance", timeframe="1d", limit=_CRYPTO_LIMIT)
            if rows:
                _save_rows(db, rows, pair)
            else:
                logger.warning("  no data returned for %s", pair)
        except Exception as exc:
            logger.warning("  failed to fetch %s: %s", pair, exc)

    logger.info("Crypto fetch complete.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV data into SQLite.")
    parser.add_argument(
        "--vertical",
        choices=["stocks", "crypto", "both"],
        default="both",
        help="Which vertical to fetch (default: both)",
    )
    args = parser.parse_args()

    db = AlphaDB()
    logger.info("Database ready at %s", db.db_path)

    if args.vertical in ("stocks", "both"):
        fetch_stocks(db)

    if args.vertical in ("crypto", "both"):
        fetch_crypto(db)

    logger.info("Done. Run backtest_runner.py to see results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
