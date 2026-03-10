"""Crypto execution via ccxt in sandbox/paper mode."""

from __future__ import annotations

import logging
from typing import Any

import ccxt  # type: ignore[import]

logger = logging.getLogger(__name__)


class CryptoExecutor:
    """Execute crypto orders via a ccxt exchange instance."""

    def __init__(self, exchange_id: str = "binance", paper: bool = True) -> None:
        exchange_cls = getattr(ccxt, exchange_id)
        self.exchange = exchange_cls()

        if paper:
            # Not all exchanges implement sandbox; be defensive.
            try:
                setattr(self.exchange, "sandbox", True)
                if hasattr(self.exchange, "set_sandbox_mode"):
                    self.exchange.set_sandbox_mode(True)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to enable sandbox for {exchange_id}: {e}")

        self.markets: dict[str, Any] = {}
        try:
            self.markets = self.exchange.load_markets()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to load markets for {exchange_id}: {e}")

    def _get_last_price(self, symbol: str) -> float:
        ticker = self.exchange.fetch_ticker(symbol)
        last = ticker.get("last")
        if last is None:
            raise ValueError(f"No last price available for {symbol}")
        return float(last)

    def submit_order(self, symbol: str, side: str, amount_usd: float) -> dict[str, Any]:
        """Submit a market order sized by USD notional."""
        try:
            price: float | None = None
            market = self.markets.get(symbol)
            if market and isinstance(market, dict):
                info = market.get("info", {})
                price_val = info.get("lastPrice") or info.get("last") or info.get("price")
                if price_val is not None:
                    price = float(price_val)

            if price is None:
                price = self._get_last_price(symbol)

            qty = amount_usd / price
            order = self.exchange.create_market_order(symbol, side, qty)
            order_id = str(order.get("id", ""))
            status = str(order.get("status", "accepted"))

            return {
                "id": order_id,
                "symbol": symbol,
                "side": side,
                "amount_usd": float(amount_usd),
                "status": status,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"CryptoExecutor submit_order failed for {symbol}: {e}", exc_info=True)
            return {"status": "error", "reason": str(e)}

    def get_balances(self) -> dict[str, float]:
        """Return non-zero balances keyed by currency symbol."""
        try:
            bal = self.exchange.fetch_balance()
        except Exception as e:  # noqa: BLE001
            logger.error(f"CryptoExecutor get_balances failed: {e}", exc_info=True)
            return {}

        result: dict[str, float] = {}
        for currency, info in bal.get("total", {}).items():
            try:
                qty = float(info)
                if qty != 0:
                    result[str(currency)] = qty
            except Exception:
                continue
        return result

