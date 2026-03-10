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


def _fmt_dollar(amount: float | None) -> str:
    """Format a dollar amount as $1,234 or — when None/zero."""
    if amount is None or amount == 0:
        return "—"
    return f"${amount:,.0f}"


def _fmt_pct(prob: float) -> str:
    return f"{prob * 100:.1f}%"


def _print_summary(results: dict[str, dict[str, Any]]) -> None:
    from datetime import date  # noqa: PLC0415

    today = date.today().strftime("%Y-%m-%d")

    # Derive macro info from any vertical that has a scalar stored
    scalar = 1.0
    for res in results.values():
        if "scalar" in res:
            scalar = res["scalar"]
            break

    # Determine macro label from scalar
    if scalar >= 0.9:
        macro_label = "risk_on"
    elif scalar >= 0.5:
        macro_label = "neutral"
    else:
        macro_label = "risk_off"

    border = "═" * 42
    print(border)
    print(f" ALPHA TERMINAL — {today}")
    print(f" Macro: {macro_label} | scalar: {scalar:.2f}")
    print(border)

    # ── STOCKS ──────────────────────────────────────────────────────
    stocks = results.get("stocks", {})
    signals: dict[str, dict] = stocks.get("signals", {})
    positions: dict[str, float] = stocks.get("positions", {})

    buy_sell = [
        (sym, sig)
        for sym, sig in signals.items()
        if sig.get("action") in ("buy", "sell")
    ]
    buy_sell.sort(key=lambda x: x[1].get("score", 0), reverse=True)

    print(f"\nSTOCKS ({len(buy_sell)} signals)")
    if buy_sell:
        hdr = f"{'symbol':<8} {'action':<7} {'score':<8} {'position':<10} {'filter'}"
        print(hdr)
        for sym, sig in buy_sell:
            score = sig.get("score", 0)
            score_str = f"{score:+.2f}"
            action = sig.get("action", "")
            pos_usd = positions.get(sym)
            pos_str = _fmt_dollar(pos_usd) if pos_usd else "—"
            fund = sig.get("fundamental_filter", "—")
            print(f"{sym:<8} {action:<7} {score_str:<8} {pos_str:<10} {fund}")
    else:
        print("  (no buy/sell signals)")

    # ── CRYPTO ──────────────────────────────────────────────────────
    crypto = results.get("crypto", {})
    crypto_signals: dict[str, dict] = crypto.get("signals", {})
    crypto_positions: dict[str, float] = crypto.get("positions", {})

    crypto_signals_filtered = [
        (sym, sig)
        for sym, sig in crypto_signals.items()
        if sig.get("action") in ("buy", "sell")
    ]
    crypto_signals_filtered.sort(key=lambda x: x[1].get("score", 0), reverse=True)

    print(f"\nCRYPTO ({len(crypto_signals_filtered)} signals)")
    if crypto_signals_filtered:
        hdr = f"{'pair':<14} {'action':<7} {'score':<8} {'whale':<7} {'position'}"
        print(hdr)
        for sym, sig in crypto_signals_filtered:
            score = sig.get("score", 0)
            score_str = f"{score:+.2f}"
            action = sig.get("action", "")
            whale = "yes" if sig.get("whale_detected") else "no"
            pos_usd = crypto_positions.get(sym)
            pos_str = _fmt_dollar(pos_usd) if pos_usd else "—"
            print(f"{sym:<14} {action:<7} {score_str:<8} {whale:<7} {pos_str}")
    else:
        print("  (no buy/sell signals)")

    # ── SPORTS ──────────────────────────────────────────────────────
    sports = results.get("sports", {})
    bets: list[dict] = sports.get("bets", [])
    bets_sorted = sorted(bets, key=lambda b: b.get("ev", 0), reverse=True)

    print(f"\nSPORTS — NBA ({len(bets_sorted)} bets)")
    if bets_sorted:
        hdr = (
            f"{'game':<34} {'side':<6} {'model%':<8} {'book%':<8}"
            f" {'EV':<8} {'stake'}"
        )
        print(hdr)
        total_stake = 0.0
        for bet in bets_sorted:
            home = bet.get("home_team", "")
            away = bet.get("away_team", "")
            game_str = f"{away} @ {home}"
            side = bet.get("bet_side", "")
            model_prob = bet.get("model_prob", 0.0)
            decimal_odds = bet.get("decimal_odds", 0.0)
            ev = bet.get("ev", 0.0)
            stake = bet.get("stake", 0.0)
            total_stake += stake
            # Derive book-implied probability from decimal odds
            book_pct = (1 / decimal_odds) if decimal_odds > 0 else 0.0
            print(
                f"{game_str:<34} {side:<6} {_fmt_pct(model_prob):<8}"
                f" {_fmt_pct(book_pct):<8} {ev:+.3f}   ${stake:,.2f}"
            )
        print(f"Total stake: ${total_stake:,.2f}")
    else:
        print("  (no qualifying bets)")

    print(f"\n{border}")


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

