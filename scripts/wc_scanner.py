"""
WC Scanner — FIFA World Cup 2026 match parlay generator.

Orchestrates the full WC pipeline:
  [1/4] Fetch WC fixtures (football-data.org via FootballDataClient.fetch_wc_games)
  [2/4] Run Elo-logistic model (WCMatchModel.predict) per fixture
  [3/4] Build classic parlay combinations (WCSGPBuilder)
  [4/4] Print ranked picks with ELO EDGE annotation

Data sources:
  Games : football-data.org (FOOTBALL_API_KEY in .env — free tier covers WC)
  Model : Elo ratings from data/wc_priors.json + StatsBomb stats from data/.wc_cache/

NOTE: Player props (goals, assists) are NOT available for WC in v1.1.
      Use --mode parlay for multi-game match outcome parlays.

Pre-requisites:
  1. FOOTBALL_API_KEY set in .env
  2. data/wc_priors.json built via: ./venv/Scripts/python.exe scripts/build_wc_priors.py

Usage:
  python scripts/wc_scanner.py --mode parlay
  python scripts/wc_scanner.py --mode parlay --date-from 2026-06-26 --date-to 2026-07-02
  python scripts/wc_scanner.py --mode parlay --min-edge 0.02 --top 10
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("wc_scanner")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    today = date.today().isoformat()
    next_week = (date.today() + timedelta(days=7)).isoformat()
    parser = argparse.ArgumentParser(
        description="WC 2026 match parlay generator with Elo-logistic model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  parlay   -- Classic multi-game moneyline parlay (recommended, only mode in v1.1)

Data sources:
  Games : football-data.org (requires FOOTBALL_API_KEY in .env)
  Model : Elo ratings (data/wc_priors.json) + StatsBomb stats (data/.wc_cache/)

Examples:
  python scripts/wc_scanner.py --mode parlay
  python scripts/wc_scanner.py --mode parlay --date-from 2026-06-26 --date-to 2026-07-02
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["parlay"],
        default="parlay",
        help="Parlay mode (default: parlay)",
    )
    parser.add_argument(
        "--date-from",
        default=today,
        help=f"Start date YYYY-MM-DD (default: today = {today})",
    )
    parser.add_argument(
        "--date-to",
        default=next_week,
        help=f"End date YYYY-MM-DD (default: today+7 = {next_week})",
    )
    parser.add_argument(
        "--bankroll", type=float, default=10_000.0,
        help="Bankroll for Kelly sizing (default: 10000)",
    )
    parser.add_argument(
        "--min-edge", type=float, default=0.04,
        help="Minimum edge to include a combo (default: 0.04)",
    )
    parser.add_argument(
        "--max-legs", type=int, default=4,
        help="Maximum legs per parlay combination (default: 4)",
    )
    parser.add_argument(
        "--top", type=int, default=5,
        help="Number of top combinations to display (default: 5)",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Display model info before running",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    from alpha.data.ingestion.football_data_client import FootballDataClient
    from alpha.engines.sports.wc_model import WCMatchModel
    from alpha.engines.sports.wc_sgp_builder import WCSGPBuilder

    # ── Step 1: Fetch WC fixtures ────────────────────────────────────────
    print(f"[1/4] Fetching WC fixtures ({args.date_from} to {args.date_to})...")
    fd_client = FootballDataClient()
    if not fd_client.is_configured():
        print("  FOOTBALL_API_KEY not set. Add it to .env and retry.")
        sys.exit(0)

    try:
        all_games = fd_client.fetch_wc_games(args.date_from, args.date_to)
    except Exception as exc:
        logger.warning("Could not fetch WC games: %s", exc)
        all_games = []

    if not all_games:
        print("  No WC games found in date range. Exiting.")
        sys.exit(0)
    print(f"  Found {len(all_games)} WC fixture(s)")

    # ── Step 2: Run Elo model ────────────────────────────────────────────
    print("[2/4] Running Elo-logistic model (WCMatchModel)...")
    try:
        wc_model = WCMatchModel(min_edge=args.min_edge)
    except FileNotFoundError as exc:
        print(f"  ERROR: {exc}")
        print("  Run: ./venv/Scripts/python.exe scripts/build_wc_priors.py")
        sys.exit(1)

    if args.validate:
        print(f"  Model: wc_elo_logistic | Elo ratings: {len(wc_model._elo_ratings)} | "
              f"Stats: {len(wc_model._wc_stats)} teams")

    enriched: list[dict] = []
    for game in all_games:
        try:
            game = wc_model.predict(game)
            enriched.append(game)
        except ValueError as exc:
            logger.warning("Skipping game: %s", exc)

    print(f"  Enriched {len(enriched)} game(s) with Elo predictions")

    # ── Step 3: Build SGP combinations ──────────────────────────────────
    print("[3/4] Building WC parlay combinations...")
    builder = WCSGPBuilder(
        bankroll=args.bankroll,
        min_edge=args.min_edge,
        max_legs=args.max_legs,
    )
    results = builder.build(enriched, top_n=args.top)

    # ── Step 4: Output ───────────────────────────────────────────────────
    print("[4/4] Ranking complete.")
    print(f"\n{'='*65}")
    print(f"WC SCANNER — Mode: {args.mode.upper()}  |  "
          f"{args.date_from} to {args.date_to}  |  Min edge: {args.min_edge:.1%}")
    print(f"{'='*65}")

    if not results:
        print(f"\nNo combinations found with >={args.min_edge:.1%} edge in this date range.")
        print(f"  ({len(enriched)} games enriched — try --min-edge 0.02 or expand date range)")
        return

    for rank, combo in enumerate(results, 1):
        print(f"\n#{rank}  EV: {combo.ev:.1%}  |  Edge: {combo.edge:.1%}  |  "
              f"Odds: {combo.combined_decimal_odds:.2f}x  |  "
              f"Stake: ${combo.stake:.2f}")
        print(f"    Model Prob: {combo.combined_model_prob:.1%}  vs  "
              f"Market Implied: {combo.combined_market_prob:.1%}")
        print("    Legs:")
        for leg in combo.legs:
            if isinstance(leg, dict):
                team = leg.get("team", "?")
                odds = leg.get("decimal_odds", 0)
                prob = leg.get("model_prob", 0)
                elo = leg.get("home_elo", "?")
                is_knockout = leg.get("knockout", False)
                outcome = "ADVANCE" if is_knockout else "WIN"
                elo_flag = "  *ELO EDGE*" if leg.get("elo_edge") else ""
                print(f"      * {team} {outcome}  ({odds:.2f}x)  "
                      f"model: {prob:.1%}  [Elo: {elo}]{elo_flag}")

    print()


if __name__ == "__main__":
    main()
