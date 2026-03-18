from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlite3

from alpha.data.storage.sqlite import DEFAULT_DB, AlphaDB
from alpha.engines.crypto.engine import CryptoEngine
from alpha.engines.stocks.engine import StockEngine
from alpha.execution.sportsbook import SportsbookExecutor
from alpha.reporting.pnl_tracker import PnLTracker


logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run simple historical backtest.")
    parser.add_argument(
        "--vertical",
        type=str,
        default="stocks",
        choices=["stocks", "crypto", "sports"],
        help="Vertical to backtest (default: stocks)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to backtest (default: 30)",
    )
    return parser.parse_args()


def _fetch_price_history(asset_type: str, days: int) -> dict[str, list[dict[str, Any]]]:
    """Fetch OHLCV history from SQLite grouped by symbol."""
    AlphaDB()  # ensure DB and schema exist
    if not Path(DEFAULT_DB).exists():
        return {}

    conn = sqlite3.connect(DEFAULT_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT symbol, date, open, high, low, close, volume
            FROM prices
            WHERE asset_type = ?
            ORDER BY date ASC
            """,
            (asset_type,),
        ).fetchall()
    finally:
        conn.close()

    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_symbol[r["symbol"]].append(dict(r))

    # Trim to last N days by date for each symbol
    for sym, sym_rows in by_symbol.items():
        if len(sym_rows) > days:
            by_symbol[sym] = sym_rows[-days:]
    return by_symbol


def _simulate_stocks(days: int) -> tuple[list[tuple[str, float]], PnLTracker]:
    history = _fetch_price_history("stock", days + 1)
    tracker = PnLTracker()
    if not history:
        return [], tracker

    engine = StockEngine()
    # Build unified date index
    all_dates = sorted({row["date"] for rows in history.values() for row in rows})
    if len(all_dates) < 2:
        return [], tracker

    daily_results: list[tuple[str, float]] = []
    capital = 100_000.0
    for i in range(len(all_dates) - 1):
        day = all_dates[i]
        next_day = all_dates[i + 1]

        # Build universe up to current day
        universe: dict[str, list[dict]] = {}
        for sym, rows in history.items():
            upto = [r for r in rows if r["date"] <= day]
            if len(upto) >= 2:
                universe[sym] = upto

        if not universe:
            continue

        res = engine.run_universe(universe_rows=universe, position_scalar=1.0)
        weights = res.get("weights", {})
        if not weights:
            daily_results.append((day, 0.0))
            continue

        # Compute portfolio daily return from day -> next_day
        daily_ret = 0.0
        for sym, w in weights.items():
            sym_rows = history.get(sym, [])
            closes_by_date = {r["date"]: r["close"] for r in sym_rows}
            if day in closes_by_date and next_day in closes_by_date:
                c0 = closes_by_date[day]
                c1 = closes_by_date[next_day]
                if c0:
                    ret = (c1 - c0) / c0
                    daily_ret += w * ret

        daily_pnl = capital * daily_ret
        capital += daily_pnl
        tracker.record_trade(
            vertical="stocks",
            symbol="PORTFOLIO",
            entry_price=1.0,
            exit_price=1.0,
            quantity=1.0,
            side="long",
            pnl=daily_pnl,
        )
        daily_results.append((day, capital))

    return daily_results, tracker


def _simulate_crypto(days: int) -> tuple[list[tuple[str, float]], PnLTracker]:
    history = _fetch_price_history("crypto", days + 1)
    tracker = PnLTracker()
    if not history:
        return [], tracker

    engine = CryptoEngine()
    all_dates = sorted({row["date"] for rows in history.values() for row in rows})
    if len(all_dates) < 2:
        return [], tracker

    daily_results: list[tuple[str, float]] = []
    capital = 100_000.0
    for i in range(len(all_dates) - 1):
        day = all_dates[i]
        next_day = all_dates[i + 1]

        universe: dict[str, list[dict]] = {}
        for sym, rows in history.items():
            upto = [r for r in rows if r["date"] <= day]
            if len(upto) >= 2:
                universe[sym] = upto

        if not universe:
            continue

        res = engine.run_universe(universe_rows=universe, position_scalar=1.0)
        weights = res.get("weights", {})
        if not weights:
            daily_results.append((day, 0.0))
            continue

        daily_ret = 0.0
        for sym, w in weights.items():
            sym_rows = history.get(sym, [])
            closes_by_date = {r["date"]: r["close"] for r in sym_rows}
            if day in closes_by_date and next_day in closes_by_date:
                c0 = closes_by_date[day]
                c1 = closes_by_date[next_day]
                if c0:
                    ret = (c1 - c0) / c0
                    daily_ret += w * ret

        daily_pnl = capital * daily_ret
        capital += daily_pnl
        tracker.record_trade(
            vertical="crypto",
            symbol="PORTFOLIO",
            entry_price=1.0,
            exit_price=1.0,
            quantity=1.0,
            side="long",
            pnl=daily_pnl,
        )
        daily_results.append((day, capital))

    return daily_results, tracker


def _simulate_sports(days: int) -> tuple[list[tuple[str, float]], PnLTracker]:
    # Ledger is in-memory only for now; this is a stub simulation.
    tracker = PnLTracker()
    sb = SportsbookExecutor()
    ledger = sb.get_ledger()
    capital = 100_000.0
    daily_results: list[tuple[str, float]] = []
    if not ledger:
        return daily_results, tracker
    # If bets existed, we could aggregate by settlement date; left as future work.
    return daily_results, tracker


def _compute_max_drawdown(equity_curve: list[float]) -> float:
    max_draw = 0.0
    peak = equity_curve[0] if equity_curve else 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            draw = (peak - value) / peak
            max_draw = max(max_draw, draw)
    return max_draw


def main() -> int:
    args = _parse_args()
    vertical = args.vertical
    days = args.days

    if vertical == "stocks":
        daily_results, tracker = _simulate_stocks(days)
    elif vertical == "crypto":
        daily_results, tracker = _simulate_crypto(days)
    else:
        daily_results, tracker = _simulate_sports(days)

    # Build equity curve — exclude 0.0 placeholder entries (days with no signals)
    equity = [v for _, v in daily_results if v > 0.0] if daily_results else []
    if not equity:
        equity = [100_000.0]
    max_dd = _compute_max_drawdown(equity)

    total_return_pct = 0.0
    if len(equity) >= 2:
        total_return_pct = (equity[-1] / equity[0] - 1.0) * 100

    win_rate = tracker.win_rate()

    out_dir = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.utcnow().strftime("%Y%m%d")
    out_path = out_dir / f"backtest_{vertical}_{date_str}.txt"

    lines: list[str] = []
    lines.append(f"Backtest vertical: {vertical}")
    lines.append(f"Days: {days}")
    lines.append("")
    lines.append("Day\tEquity")
    for day, value in daily_results:
        lines.append(f"{day}\t{value:.2f}")
    lines.append("")
    lines.append(f"Total return: {total_return_pct:.2f}%")
    lines.append(f"Win rate: {win_rate:.2%}")
    lines.append(f"Max drawdown: {max_dd:.2%}")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())

