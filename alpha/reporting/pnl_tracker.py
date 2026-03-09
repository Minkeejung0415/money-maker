"""
Cross-vertical P&L tracker.
Records individual trade outcomes and provides aggregate metrics.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TradeRecord:
    vertical: str
    symbol: str
    entry_price: float
    exit_price: float
    quantity: float
    side: str  # "long", "short", "bet"
    pnl: float
    timestamp: str


class PnLTracker:
    def __init__(self):
        self._trades: list[TradeRecord] = []

    def record_trade(
        self,
        vertical: str,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        side: str,
        pnl: float | None = None,
    ) -> TradeRecord:
        """
        Record a completed trade.
        If pnl is not provided, it is computed from entry/exit/quantity.
        """
        if pnl is None:
            if side == "long":
                pnl = (exit_price - entry_price) * quantity
            elif side == "short":
                pnl = (entry_price - exit_price) * quantity
            else:
                pnl = 0.0

        record = TradeRecord(
            vertical=vertical,
            symbol=symbol,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            side=side,
            pnl=round(pnl, 4),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._trades.append(record)
        return record

    def total_pnl(self) -> float:
        return round(sum(t.pnl for t in self._trades), 4)

    def pnl_by_vertical(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for t in self._trades:
            result[t.vertical] = result.get(t.vertical, 0.0) + t.pnl
        return {k: round(v, 4) for k, v in result.items()}

    def win_rate(self) -> float:
        if not self._trades:
            return 0.0
        wins = sum(1 for t in self._trades if t.pnl > 0)
        return wins / len(self._trades)

    def trade_count(self) -> int:
        return len(self._trades)

    def to_dicts(self) -> list[dict]:
        return [t.__dict__ for t in self._trades]
