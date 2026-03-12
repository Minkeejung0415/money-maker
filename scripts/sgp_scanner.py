"""
SGP Scanner — NBA Same-Game Parlay generator.

Orchestrates the full pipeline end to end:
  [1/8] Fetch today's NBA games (OddsAPIClient)
  [2/8] Fetch player prop lines (PlayerPropsClient)
  [3/8] Run prop model (PropModel via nba_api)
  [4/8] Apply contextual evaluators (position, paint deterrence, foul trouble, etc.)
  [5/8] Build correlation matrix (CorrelationEngine)
  [6/8] Run backtest validation (PropBacktester) — only with --validate
  [7/8] Build and rank SGP combinations (SGPBuilder)
  [8/8] Betting intelligence: EV analysis, parlay math, Kelly sizing

Usage:
  python scripts/sgp_scanner.py --mode parlay
  python scripts/sgp_scanner.py --mode props --no-corr --min-edge 0.03
  python scripts/sgp_scanner.py --mode props --validate
  python scripts/sgp_scanner.py --mode props --max-legs 3 --bankroll 5000

NOTE: Prop model not validated by default.
Run with --validate to check calibration before trusting results.
"""
from __future__ import annotations

import argparse
import logging
import io
import os
import sys
from pathlib import Path

# Ensure repo root is on the path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Force UTF-8 output on Windows so special characters don't crash
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
logger = logging.getLogger("sgp_scanner")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NBA Same-Game Parlay (SGP) generator with +EV filtering.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  props    -- Pure player prop parlay (2-4 legs, same game)
  ml_sgp   -- Moneyline + player props (same game)
  mixed    -- Any combination of ML and props (same game)
  parlay   -- Classic multi-game moneyline parlay (independent legs)

Examples:
  python scripts/sgp_scanner.py --mode parlay
  python scripts/sgp_scanner.py --mode props --no-corr --min-edge 0.03
  python scripts/sgp_scanner.py --mode props --validate
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["props", "ml_sgp", "mixed", "parlay"],
        default="props",
        help="Parlay mode (default: props)",
    )
    parser.add_argument(
        "--bankroll", type=float, default=10_000.0,
        help="Bankroll in dollars for Kelly sizing (default: 10000)",
    )
    parser.add_argument(
        "--min-edge", type=float, default=0.05,
        help="Minimum edge (model - market) to include a combo (default: 0.05)",
    )
    parser.add_argument(
        "--max-legs", type=int, default=4,
        help="Maximum legs per parlay combination (default: 4)",
    )
    parser.add_argument(
        "--markets",
        default="player_points,player_rebounds,player_assists",
        help="Comma-separated prop markets (default: player_points,player_rebounds,player_assists)",
    )
    parser.add_argument(
        "--top", type=int, default=5,
        help="Number of top combinations to display (default: 5)",
    )
    parser.add_argument(
        "--no-corr", action="store_true",
        help="Skip correlation matrix build (faster, less accurate)",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Run PropBacktester first and display calibration report",
    )
    parser.add_argument(
        "--confidence",
        choices=["HIGH", "MEDIUM", "ALL"],
        default="MEDIUM",
        help="Minimum confidence level for prop legs (default: MEDIUM — includes HIGH and MEDIUM)",
    )
    parser.add_argument(
        "--no-context", action="store_true",
        help="Skip contextual evaluators (position filter, paint deterrence, etc.)",
    )
    parser.add_argument(
        "--show-ev", action="store_true",
        help="Show detailed EV analysis and bet type recommendations per game",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    markets = [m.strip() for m in args.markets.split(",") if m.strip()]

    from alpha.data.ingestion.odds_api import OddsAPIClient
    from alpha.data.ingestion.player_props import PlayerPropsClient
    from alpha.engines.sports.prop_model import PropModel
    from alpha.engines.sports.prop_backtester import PropBacktester
    from alpha.engines.sports.correlation import CorrelationEngine
    from alpha.engines.sports.sgp_builder import SGPBuilder, SGPMode, PropLeg

    mode_map = {
        "props":  SGPMode.PROPS_ONLY,
        "ml_sgp": SGPMode.MONEYLINE_SGP,
        "mixed":  SGPMode.MIXED_SGP,
        "parlay": SGPMode.CLASSIC_PARLAY,
    }
    sgp_mode = mode_map[args.mode]

    # ── Step 1: Fetch games ──────────────────────────────────────────────
    print("[1/6] Fetching today's NBA games...")
    odds_client = OddsAPIClient()
    if not odds_client.is_configured():
        print("⚠  ODDS_API_KEY not set — set it in .env or as an environment variable.")
        print("   Classic parlay mode requires live odds. Exiting.")
        sys.exit(0)

    games = odds_client.fetch_nba_games()
    if not games:
        print("    No NBA games found today (or API error). Exiting.")
        sys.exit(0)
    print(f"    Found {len(games)} game(s)")

    # Enrich games with NBAModel win probabilities so SGPBuilder has real model_prob
    from alpha.engines.sports.nba_model import NBAModel
    nba_model = NBAModel()
    for game in games:
        pred = nba_model.predict(game)
        game["home_model_prob"] = pred["home_win_prob"]
        game["away_model_prob"] = pred["away_win_prob"]

    # ── Step 2: Fetch props (skip for classic parlay) ────────────────────
    prop_legs_raw: list[dict] = []
    if sgp_mode != SGPMode.CLASSIC_PARLAY:
        print("[2/6] Fetching player prop lines...")
        props_client = PlayerPropsClient()
        prop_legs_raw = props_client.fetch_all_game_props(games)
        print(f"    Fetched {len(prop_legs_raw)} prop lines across {len(games)} game(s)")
    else:
        print("[2/6] Skipping prop lines (classic parlay mode)")

    # ── Step 3: Run prop model ───────────────────────────────────────────
    scored_legs: list[PropLeg] = []
    skipped_insufficient = 0
    skipped_low_conf = 0

    if sgp_mode != SGPMode.CLASSIC_PARLAY and prop_legs_raw:
        unique_players = len({r["player"] for r in prop_legs_raw if r.get("market") in markets})
        print(f"[3/6] Running prop model — {unique_players} players to fetch (cached players are instant)...")
        model = PropModel()
        seen_players: set[str] = set()
        done = 0
        for raw in prop_legs_raw:
            if raw.get("market") not in markets:
                continue
            player = raw["player"]
            if player not in seen_players:
                seen_players.add(player)
                done += 1
                print(f"\r    Fetching: {done}/{unique_players} players ({player[:30]})    ", end="", flush=True)
            # Determine opponent team
            opponent = raw.get("away_team", "")
            result = model.predict_prop(
                player_name=raw["player"],
                market=raw["market"],
                line=raw["line"],
                opponent_team=opponent,
                over_odds=raw.get("over_odds", -110),
            )
            if result is None:
                skipped_insufficient += 1
                continue

            conf = result.get("confidence", "LOW")
            if args.confidence == "HIGH" and conf != "HIGH":
                skipped_low_conf += 1
                continue
            if args.confidence == "MEDIUM" and conf == "LOW":
                skipped_low_conf += 1
                continue

            scored_legs.append(PropLeg(
                player=raw["player"],
                market=raw["market"],
                line=raw["line"],
                model_prob=result["model_prob"],
                over_odds=raw["over_odds"],
                event_id=raw["event_id"],
                home_team=raw["home_team"],
                away_team=raw["away_team"],
                confidence=conf,
            ))

        print()  # newline after progress
        print(f"    Scored {len(scored_legs)} legs  "
              f"({skipped_insufficient} skipped: insufficient data, "
              f"{skipped_low_conf} skipped: low confidence)")
    else:
        print("[3/6] Skipping prop model (classic parlay mode)")

    # ── Step 4: Contextual evaluators ────────────────────────────────────
    context_evaluator = None
    context_scored = []
    if not args.no_context and sgp_mode != SGPMode.CLASSIC_PARLAY and scored_legs:
        print("[4/8] Running contextual evaluators (position, paint, foul trouble, pace)...")
        try:
            from alpha.data.ingestion.nba_stats_cache import NBAStatsCache
            from alpha.engines.sports.nba_context import PropContextEvaluator

            stats_cache = NBAStatsCache()
            context_evaluator = PropContextEvaluator(cache=stats_cache)

            pre_count = len(scored_legs)
            prop_dicts = []
            for leg in scored_legs:
                prop_dicts.append({
                    "player": leg.player,
                    "market": leg.market,
                    "line": leg.line,
                    "model_prob": leg.model_prob,
                    "over_odds": leg.over_odds,
                    "opponent_team": leg.away_team,
                    "event_id": leg.event_id,
                    "home_team": leg.home_team,
                    "away_team": leg.away_team,
                    "confidence": leg.confidence,
                })

            context_scored = context_evaluator.evaluate_props(prop_dicts)

            # Update scored_legs with adjusted probabilities
            adjusted_legs = []
            for cs in context_scored:
                if cs.get("edge", 0) >= args.min_edge:
                    adjusted_legs.append(PropLeg(
                        player=cs["player"],
                        market=cs["market"],
                        line=cs["line"],
                        model_prob=cs.get("adjusted_prob", cs["model_prob"]),
                        over_odds=cs["over_odds"],
                        event_id=cs["event_id"],
                        home_team=cs["home_team"],
                        away_team=cs["away_team"],
                        confidence=cs["confidence"],
                    ))

            filtered_count = pre_count - len(adjusted_legs)
            scored_legs = adjusted_legs if adjusted_legs else scored_legs
            print(f"    Context adjustments applied — {len(scored_legs)} legs remain "
                  f"({filtered_count} filtered/below edge)")
        except Exception as exc:
            print(f"    Context evaluators skipped: {exc}")
    else:
        reason = "classic parlay" if sgp_mode == SGPMode.CLASSIC_PARLAY else "--no-context"
        print(f"[4/8] Skipping contextual evaluators ({reason})")

    # ── Step 5: Correlation matrix ───────────────────────────────────────
    corr_engine = None
    if not args.no_corr and sgp_mode != SGPMode.CLASSIC_PARLAY and scored_legs:
        print("[5/8] Building correlation matrix...")
        player_names = list({leg.player for leg in scored_legs})
        corr_engine = CorrelationEngine()
        corr_engine.build(player_names)
        print(f"    Correlation matrix ready ({len(player_names)} player(s))")
    else:
        reason = "classic parlay mode" if sgp_mode == SGPMode.CLASSIC_PARLAY else "--no-corr flag"
        print(f"[5/8] Skipping correlation matrix ({reason})")

    # ── Step 6: Backtest validation (optional) ───────────────────────────
    unreliable_players: set[str] = set()
    if args.validate and scored_legs:
        print("[6/8] Running backtest validation...")
        backtester = PropBacktester()
        player_names = list({leg.player for leg in scored_legs})
        bt_results = backtester.backtest(player_names, markets)
        backtester.print_report(bt_results)

        for r in bt_results:
            if r["recommendation"] == "UNRELIABLE":
                unreliable_players.add(r["player"])

        if unreliable_players:
            print(f"\n  UNRELIABLE players excluded from SGP: {sorted(unreliable_players)}")
            scored_legs = [leg for leg in scored_legs if leg.player not in unreliable_players]
        print()
    elif not args.validate:
        print("[6/8] Skipping validation  "
              "-- Prop model not validated -- run with --validate to check calibration.")

    # ── Step 7: Build combinations ───────────────────────────────────────
    print("[7/8] Building SGP combinations...")
    builder = SGPBuilder(
        correlation_engine=corr_engine,
        bankroll=args.bankroll,
        min_edge=args.min_edge,
        max_legs=args.max_legs,
    )
    results = builder.build(
        prop_legs=scored_legs,
        ml_games=games,
        mode=sgp_mode,
        top_n=args.top,
    )

    # ── Step 8: Betting intelligence ─────────────────────────────────────
    parlay_ctor = None
    if args.show_ev or context_scored:
        print("[8/8] Running betting intelligence analysis...")
        from alpha.engines.sports.parlay_constructor import ParlayConstructor
        parlay_ctor = ParlayConstructor(
            bankroll=args.bankroll,
            kelly_fraction=0.25,
            max_legs=args.max_legs,
            min_edge=args.min_edge,
        )
    else:
        print("[8/8] Skipping detailed EV analysis (use --show-ev to enable)")

    # ── Output ────────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"SGP SCANNER — Mode: {args.mode.upper()}  |  Min edge: {args.min_edge:.1%}")
    print(f"{'='*65}")

    if not results:
        print(f"\nNo combinations found with >= {args.min_edge:.1%} edge today.")
        if scored_legs and sgp_mode != SGPMode.CLASSIC_PARLAY:
            print(f"  (Scored {len(scored_legs)} legs -- try --min-edge 0.02 or --no-corr)")
        return

    for rank, combo in enumerate(results, 1):
        print(f"\n#{rank}  EV: {combo.ev:.1%}  |  Edge: {combo.edge:.1%}  |  "
              f"Odds: {combo.combined_decimal_odds:.2f}x  |  "
              f"Stake: ${combo.stake:.2f}")
        print(f"    Model Prob: {combo.combined_model_prob:.1%}  vs  "
              f"Market Implied: {combo.combined_market_prob:.1%}")

        if combo.combined_model_prob < 0.15:
            print("    WARNING: Combined win probability below 15% -- "
                  "unlikely to hit regardless of individual leg quality")

        if combo.confidence_summary:
            print(f"    Confidence: {combo.confidence_summary}")
        if combo.correlation_note:
            print(f"    Correlation: {combo.correlation_note}")
        print("    Legs:")
        for leg in combo.legs:
            if isinstance(leg, dict):
                print(f"      * {leg.get('team', '?')} ML  "
                      f"({leg.get('decimal_odds', 0):.2f}x)  "
                      f"model: {leg.get('model_prob', 0):.1%}")
            else:
                print(f"      * {leg.player}: OVER {leg.line} {_market_label(leg.market)}  "
                      f"({leg.over_odds:+d})  "
                      f"model: {leg.model_prob:.1%}  [{leg.confidence}]")

    # Detailed pick output with EV analysis
    if parlay_ctor and context_scored:
        print(f"\n{'='*65}")
        print("DETAILED PICK ANALYSIS")
        print(f"{'='*65}")

        edge_picks = [p for p in context_scored if p.get("edge", 0) >= args.min_edge]
        edge_picks.sort(key=lambda p: p.get("ev", 0), reverse=True)

        for pick in edge_picks[:10]:
            print(parlay_ctor.format_pick(pick, args.bankroll))
            print()

        # Bet type recommendations
        if edge_picks:
            print(f"\n{'='*65}")
            print("BET TYPE RECOMMENDATIONS")
            print(f"{'='*65}")
            recs = parlay_ctor.recommend_bet_types(edge_picks, corr_engine)
            for rec in recs:
                print(parlay_ctor.format_recommendation(rec))
                print()

            # Leg count table
            avg_prob = sum(p.get("adjusted_prob", 0.6) for p in edge_picks) / len(edge_picks)
            print(parlay_ctor.format_leg_count_table(avg_prob))

    print()


def _market_label(market: str) -> str:
    labels = {
        "player_points":   "pts",
        "player_rebounds": "reb",
        "player_assists":  "ast",
        "player_threes":   "3pm",
    }
    return labels.get(market, market)


if __name__ == "__main__":
    main()
