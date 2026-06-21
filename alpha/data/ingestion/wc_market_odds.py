"""Normalized local market prices for World Cup match and goal markets."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Mapping

_FIELD_TO_MARKET = {
    "home_decimal": "home_win",
    "draw_decimal": "draw",
    "away_decimal": "away_win",
    "over_2_5_decimal": "over_2_5",
    "under_2_5_decimal": "under_2_5",
    "btts_yes_decimal": "btts_yes",
    "btts_no_decimal": "btts_no",
}


@dataclass(frozen=True)
class WCMarketOdds:
    event_key: str
    prices: Mapping[str, float]
    source: str = "local_override"


def _decimal_price(value: object, field: str, event_key: str) -> float:
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{event_key} {field} must be a decimal number") from exc
    if not math.isfinite(price) or price <= 1.0:
        raise ValueError(f"{event_key} {field} must be greater than 1.0")
    return price


def load_wc_market_odds(path: str | Path) -> dict[str, WCMarketOdds]:
    """Load available decimal prices without filling absent markets."""
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("World Cup odds override must be a JSON object")

    result: dict[str, WCMarketOdds] = {}
    for event_key, entry in raw.items():
        if str(event_key).startswith("_"):
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"{event_key} odds entry must be an object")
        prices = {
            market: _decimal_price(entry[field], field, event_key)
            for field, market in _FIELD_TO_MARKET.items()
            if field in entry
        }
        result[event_key] = WCMarketOdds(event_key=event_key, prices=prices)
    return result

