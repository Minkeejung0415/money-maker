"""
Soccer Scanner — EPL + UCL Same-Game Parlay / bet generator.

Orchestrates the full pipeline:
  [1/6] Fetch today's soccer games (football-data.org via FootballDataClient)
  [2/6] Fetch player prop lines (no free source — props skipped)
  [3/6] Run prop model (SoccerPropModel)
  [4/6] Apply static correlation table
  [5/6] Run optional validation
  [6/6] Build and rank SGP combinations (SoccerSGPBuilder)

Data sources:
  Games  : football-data.org (FOOTBALL_API_KEY in .env — free tier covers EPL + UCL)
  Stats  : Understat (EPL player xG/shots/assists — free, no key needed)
  Props  : No free odds source available — props mode will return 0 legs.
           Use --mode parlay for moneyline parlays.

NOTE: The Odds API (ODDS_API_KEY) is reserved for NBA only and is NOT used here.

Usage:
  python scripts/soccer_scanner.py --mode parlay --league epl
  python scripts/soccer_scanner.py --mode parlay --league all
  python scripts/soccer_scanner.py --mode props --league epl   # 0 prop lines (no source)
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
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
logger = logging.getLogger("soccer_scanner")

_SOCCER_PROP_MARKETS = {
    "player_shots",
    "player_shots_on_target",
    "player_assists",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Soccer (EPL + UCL) Same-Game Parlay generator with +EV filtering.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  props    -- Player prop parlay (no prop lines currently — 0 legs)
  sgp      -- Moneyline + player props (no prop lines currently)
  mixed    -- Any combination of ML and props
  parlay   -- Classic multi-game moneyline parlay (recommended)

Data sources:
  Games : football-data.org (requires FOOTBALL_API_KEY in .env)
  Stats : Understat (EPL only — free, no key needed)

Examples:
  python scripts/soccer_scanner.py --mode parlay --league epl
  python scripts/soccer_scanner.py --mode parlay --league all
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["props", "sgp", "mixed", "parlay"],
        default="parlay",
        help="Parlay mode (default: parlay)",
    )
    parser.add_argument(
        "--league",
        choices=["epl", "ucl", "all"],
        default="all",
        help="League to scan (default: all)",
    )
    parser.add_argument(
        "--bankroll", type=float, default=10_000.0,
        help="Bankroll for Kelly sizing (default: 10000)",
    )
    parser.add_argument(
        "--min-edge", type=float, default=0.05,
        help="Minimum edge to include a combo (default: 0.05)",
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
        "--no-corr", action="store_true",
        help="Skip correlation adjustment (faster, less accurate)",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Display model source info before running",
    )
    parser.add_argument(
        "--confidence",
        choices=["HIGH", "MEDIUM", "ALL"],
        default="MEDIUM",
        help="Minimum confidence level for prop legs (default: MEDIUM)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    from alpha.data.ingestion.football_data_client import FootballDataClient
    from alpha.engines.sports.soccer_model import SoccerModel
    from alpha.engines.sports.soccer_prop_model import SoccerPropModel
    from alpha.engines.sports.soccer_sgp_builder import SoccerSGPBuilder, SGPMode, PropLeg

    mode_map = {
        "props":  SGPMode.PROPS_ONLY,
        "sgp":    SGPMode.MONEYLINE_SGP,
        "mixed":  SGPMode.MIXED_SGP,
        "parlay": SGPMode.CLASSIC_PARLAY,
    }
    sgp_mode = mode_map[args.mode]

    leagues_to_scan = (
        ["epl", "ucl"] if args.league == "all" else [args.league]
    )

    # ── Step 1: Fetch games ──────────────────────────────────────────────
    print("[1/6] Fetching today's soccer games (football-data.org)...")
    fd_client = FootballDataClient()
    if not fd_client.is_configured():
        print("  FOOTBALL_API_KEY not set. Add it to .env and retry.")
        sys.exit(0)

    all_games: list[dict] = []
    for league_key in leagues_to_scan:
        try:
            games = fd_client.fetch_today_games(league_key)
            all_games.extend(games)
        except Exception as exc:
            logger.warning("Could not fetch games for %s: %s", league_key, exc)

    if not all_games:
        print("    No soccer games found today. Exiting.")
        sys.exit(0)
    print(f"    Found {len(all_games)} game(s) across {leagues_to_scan}")

    # Enrich with model win probabilities (EPL → SoccerModel, UCL → UCLEloModel)
    soccer_model = SoccerModel()
    try:
        from alpha.engines.sports.ucl_model import UCLEloModel
        ucl_model = UCLEloModel()
        ucl_available = True
    except Exception as exc:
        logger.warning("UCLEloModel unavailable: %s", exc)
        ucl_model = None
        ucl_available = False

    for game in all_games:
        league = game.get("league", "epl")
        if league == "ucl" and ucl_available and ucl_model is not None:
            try:
                game = ucl_model.predict(game)  # mutates in place and returns
                game["home_model_prob"] = game["win_prob"]
                game["away_model_prob"] = game["loss_prob"]
                # model_name already set by UCLEloModel.predict ("ucl_elo_logistic")
            except Exception as exc:
                logger.warning(
                    "UCLEloModel prediction failed for %s: %s",
                    game.get("home_team"), exc,
                )
                pred = soccer_model.predict(game)
                game["home_model_prob"] = pred["home_win_prob"]
                game["away_model_prob"] = pred["away_win_prob"]
                game["draw_prob"] = pred.get("draw_prob", 0.25)
                game["model_name"] = pred.get("model_name", "market_implied")
        else:
            pred = soccer_model.predict(game)
            game["home_model_prob"] = pred["home_win_prob"]
            game["away_model_prob"] = pred["away_win_prob"]
            game["draw_prob"] = pred.get("draw_prob", 0.25)
            game["model_name"] = pred.get("model_name", "market_implied")

    # Print game probability table (H/D/A columns)
    print("Game probabilities:")
    for game in all_games:
        print(
            f"  {game.get('home_team', '?')} vs {game.get('away_team', '?')}  "
            f"H: {game.get('home_model_prob', 0):.1%}  "
            f"D: {game.get('draw_prob', 0):.1%}  "
            f"A: {game.get('away_model_prob', 0):.1%}  "
            f"[{game.get('model_name', '?')}]"
        )

    # ── Step 2: Fetch props ──────────────────────────────────────────────
    prop_legs_raw: list[dict] = []
    if sgp_mode != SGPMode.CLASSIC_PARLAY:
        print("[2/6] Soccer prop lines — no free source available.")
        print("      (Props require a dedicated odds API. Use --mode parlay for ML parlays.)")
    else:
        print("[2/6] Skipping prop lines (classic parlay mode)")

    # ── Step 3: Run prop model ───────────────────────────────────────────
    scored_legs: list[PropLeg] = []

    if sgp_mode != SGPMode.CLASSIC_PARLAY and prop_legs_raw:
        print(f"[3/6] Running soccer prop model — {len(prop_legs_raw)} props...")
        prop_model = SoccerPropModel()
        for raw in prop_legs_raw:
            if raw.get("market") not in _SOCCER_PROP_MARKETS:
                continue
            result = prop_model.predict_prop(
                player_name=raw["player"],
                market=raw["market"],
                line=raw["line"],
                over_odds=raw.get("over_odds", -110),
            )
            if result is None:
                continue
            conf = result.get("confidence", "LOW")
            if args.confidence == "HIGH" and conf != "HIGH":
                continue
            if args.confidence == "MEDIUM" and conf == "LOW":
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
        print(f"    Scored {len(scored_legs)} legs")
    else:
        print("[3/6] Skipping prop model (no prop lines or classic parlay mode)")

    # ── Step 4: Correlation (static table) ──────────────────────────────
    if not args.no_corr and sgp_mode != SGPMode.CLASSIC_PARLAY:
        print("[4/6] Using static soccer correlation table")
    else:
        print("[4/6] Skipping correlation adjustment")

    # ── Step 5: Validation ───────────────────────────────────────────────
    if args.validate:
        src = "XGBoost (ProphitBet)" if soccer_model._xgb_models_loaded else "market-implied"
        ucl_src = "UCLEloModel" if ucl_available else "unavailable (fallback to market-implied)"
        print(f"[5/6] Model info: EPL={src} | UCL={ucl_src}")
    else:
        print("[5/6] Skipping validation  (run with --validate to check model source)")

    # ── Step 6: Build combinations ───────────────────────────────────────
    print("[6/6] Building soccer SGP combinations...")
    builder = SoccerSGPBuilder(
        bankroll=args.bankroll,
        min_edge=args.min_edge,
        max_legs=args.max_legs,
    )
    results = builder.build(
        prop_legs=scored_legs,
        ml_games=all_games,
        mode=sgp_mode,
        top_n=args.top,
    )

    # ── Output ─────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"SOCCER SCANNER — Mode: {args.mode.upper()}  |  "
          f"League: {args.league.upper()}  |  Min edge: {args.min_edge:.1%}")
    print(f"{'='*65}")

    if not results:
        print(f"\nNo combinations found with >={args.min_edge:.1%} edge today.")
        if scored_legs:
            print(f"  (Scored {len(scored_legs)} legs — try --min-edge 0.02)")
        return

    for rank, combo in enumerate(results, 1):
        print(f"\n#{rank}  EV: {combo.ev:.1%}  |  Edge: {combo.edge:.1%}  |  "
              f"Odds: {combo.combined_decimal_odds:.2f}x  |  "
              f"Stake: ${combo.stake:.2f}")
        print(f"    Model Prob: {combo.combined_model_prob:.1%}  vs  "
              f"Market Implied: {combo.combined_market_prob:.1%}")
        if combo.confidence_summary:
            print(f"    Confidence: {combo.confidence_summary}")
        if combo.correlation_note:
            print(f"    Correlation: {combo.correlation_note}")
        print("    Legs:")
        for leg in combo.legs:
            if isinstance(leg, dict):
                is_draw = leg.get("is_draw") or leg.get("type") == "draw"
                draw_flag = "  *DRAW RISK*" if is_draw else ""
                leg_label = "DRAW" if is_draw else "ML"
                print(f"      * {leg.get('team', '?')} {leg_label}  "
                      f"({leg.get('decimal_odds', 0):.2f}x)  "
                      f"model: {leg.get('model_prob', 0):.1%}{draw_flag}")
            else:
                print(f"      * {leg.player}: OVER {leg.line} {_market_label(leg.market)}  "
                      f"({leg.over_odds:+d})  "
                      f"model: {leg.model_prob:.1%}  [{leg.confidence}]")

    print()


def _market_label(market: str) -> str:
    return {
        "player_shots":             "shots",
        "player_shots_on_target":   "shots_on_target",
        "player_assists":           "assists",
    }.get(market, market)


if __name__ == "__main__":
    main()
