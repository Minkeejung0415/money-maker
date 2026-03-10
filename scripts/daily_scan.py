from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from alpha.data.storage.sqlite import AlphaDB
from alpha.orchestrator import Orchestrator
from alpha.reporting.audit_log import AuditLog

logger = logging.getLogger(__name__)


def _retrain_lgbm(universe_rows: dict) -> None:
    """Retrain LGBMAlphaModel on latest data for each symbol."""
    try:
        from alpha.engines.stocks.lgbm_alpha import LGBMAlphaModel  # noqa: PLC0415
        import polars as pl  # noqa: PLC0415
        lgbm = LGBMAlphaModel()
        for symbol, rows in universe_rows.items():
            try:
                df = pl.DataFrame(rows)
                lgbm.train(df, symbol)
            except Exception as exc:
                logger.debug("LGBM retrain skipped for %s: %s", symbol, exc)
    except Exception as exc:
        logger.debug("LGBM retraining unavailable: %s", exc)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Alpha Terminal daily scan.")
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="Total capital to allocate (default: 100_000)",
    )
    parser.add_argument(
        "--verticals",
        type=str,
        default="stocks,crypto,sports",
        help="Comma-separated list of verticals (default: stocks,crypto,sports)",
    )
    return parser.parse_args()


def _print_summary(results: dict[str, dict[str, Any]]) -> None:
    headers = ["vertical", "positions", "orders", "scalar"]
    row_fmt = "{:<10} {:<20} {:<20} {:<10}"
    print(row_fmt.format(*headers))
    print("-" * 70)
    for vertical, res in results.items():
        scalar = res.get("scalar", 1.0)
        if vertical == "sports":
            positions_repr = f"{len(res.get('bets', []))} bets"
        else:
            positions = res.get("positions", {})
            positions_repr = f"{len(positions)} symbols"
        orders_repr = str(len(res.get("orders", [])))
        print(row_fmt.format(vertical, positions_repr, orders_repr, scalar))


def main() -> int:
    args = _parse_args()

    # Ensure DB exists and schema is created.
    AlphaDB()
    audit = AuditLog()

    # Refresh NBA team stats before running the sports vertical.
    if "sports" in args.verticals:
        try:
            from alpha.engines.sports.nba_model import NBAModel  # noqa: PLC0415
            refreshed = NBAModel().refresh_stats()
            if refreshed:
                logger.info("NBA stats refresh: OK")
            else:
                logger.warning("NBA stats refresh: failed — using cached/market-implied data")
        except Exception as exc:
            logger.warning("NBA stats refresh skipped: %s", exc)

    verticals = [v.strip() for v in args.verticals.split(",") if v.strip()]
    orchestrator = Orchestrator(verticals=verticals, total_capital=args.capital)

    try:
        results = orchestrator.run_cycle(current_capital=args.capital)
    except Exception as exc:  # noqa: BLE001
        logger.error("daily_scan failed", exc_info=True)
        print(f"daily_scan failed: {exc}")
        return 1

    # Retrain LGBM alpha model per stock symbol with latest price data.
    stocks_result = results.get("stocks", {})
    universe_rows = getattr(orchestrator, "_last_universe_rows", {})
    if universe_rows:
        _retrain_lgbm(universe_rows)

    # Persist a summary of each vertical's result to the audit log.
    for vertical, res in results.items():
        symbol = "*"  # aggregate event
        details = {
            "scalar": res.get("scalar"),
            "positions": res.get("positions") or res.get("bets"),
            "orders": res.get("orders", []),
            "event": "daily_scan",
        }
        try:
            audit.append(
                event_type="daily_scan",
                vertical=vertical,
                symbol=symbol,
                details=details,
            )
        except Exception:
            logger.error("Failed to append daily_scan event to audit log", exc_info=True)

    _print_summary(results)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())

