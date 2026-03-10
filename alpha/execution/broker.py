"""Alpaca paper trading broker integration."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AlpacaBroker:
    """Lightweight Alpaca REST client focused on paper trading.

    Uses dollar-notional orders via the `/v2/orders` endpoint.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str = "https://paper-api.alpaca.markets",
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("ALPACA_API_SECRET", "")
        self.base_url = base_url.rstrip("/")

        if not self.api_key or not self.api_secret:
            logger.warning("AlpacaBroker initialized without API credentials")

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    def submit_order(self, symbol: str, dollar_amount: float, side: str) -> dict[str, Any]:
        """Submit a notional (dollar-based) order.

        Returns a normalized order dict on success or an error dict on failure.
        """
        url = f"{self.base_url}/v2/orders"
        payload = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "notional": float(dollar_amount),
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=self._headers(), json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Alpaca submit_order failed for {symbol}: {e}", exc_info=True)
            return {"status": "error", "reason": str(e)}

        order_id = str(data.get("id", ""))
        status = str(data.get("status", "accepted"))
        return {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "dollar_amount": float(dollar_amount),
            "status": status,
        }

    def get_positions(self) -> list[dict[str, Any]]:
        """Fetch open positions and return a simplified list."""
        url = f"{self.base_url}/v2/positions"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=self._headers())
                resp.raise_for_status()
                raw_positions = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Alpaca get_positions failed: {e}", exc_info=True)
            return []

        positions: list[dict[str, Any]] = []
        for p in raw_positions:
            try:
                positions.append(
                    {
                        "symbol": str(p.get("symbol", "")),
                        "qty": float(p.get("qty", 0) or 0),
                        "market_value": float(p.get("market_value", 0) or 0),
                    }
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to parse position {p}: {e}")
        return positions

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders.

        Returns True on success, False on failure.
        """
        url = f"{self.base_url}/v2/orders"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.delete(url, headers=self._headers())
                # Alpaca returns 207 Multi-Status when some cancels fail; treat any 2xx as success.
                if 200 <= resp.status_code < 300:
                    return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Alpaca cancel_all_orders failed: {e}", exc_info=True)
            return False
        return False

