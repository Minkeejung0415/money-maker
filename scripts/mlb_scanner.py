"""
MLB Scanner — Same-Game Parlay / bet generator.

Orchestrates the full pipeline:
  [1/6] Fetch today's MLB games (OddsAPIClient)
  [2/6] Fetch player prop lines (Odds API MLB props)
  [3/6] Run prop model (MLBPropModel)
  [4/6] Apply static correlation table
  [5/6] Run optional validation
  [6/6] Build and rank SGP combinations (MLBSGPBuilder)

Usage:
  python scripts/mlb_scanner.py --mode props
  python scripts/mlb_scanner.py --mode parlay --min-edge 0.04
  python scripts/mlb_scanner.py --mode sgp --no-corr --validate
"""
from __future__ import annotations

import argparse
import io
import logging
import os
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
logger = logging.getLogger("mlb_scanner")

_MLB_SPORT_KEY = "baseball_mlb"

_MLB_PROP_MARKETS = {
    "batter_hits",
    "batter_home_runs",
    "batter_rbis",
    "pitcher_strikeouts",
    "pitcher_outs",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MLB Same-Game Parlay generator with +EV filtering.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  props    -- Pure player prop parlay (2-4 legs, same game)
  sgp      -- Moneyline + player props (same game)
  mixed    -- Any combination of ML and props (same game)
  parlay   -- Classic multi-game moneyline parlay (independent legs)

Examples:
  python scripts/mlb_scanner.py --mode parlay
  python scripts/mlb_scanner.py --mode props --no-corr --min-edge 0.03
  python scripts/mlb_scanner.py --mode sgp --validate
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["props", "sgp", "mixed", "parlay"],
        default="props",
        help="Parlay mode (default: props)",
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
        help="Skip correlation adjustment (faster)",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Display model source info before running",
    )
    parser.add_argument(
        "--confidence",
        choices=["HIGH", "MEDIUM", "ALL"],
        default="MEDIUM",
        help="Minimum confidence level (default: MEDIUM)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    from alpha.data.ingestion.odds_api import OddsAPIClient
    from alpha.engines.sports.mlb_model import MLBModel
    from alpha.engines.sports.mlb_prop_model import MLBPropModel
    from alpha.engines.sports.mlb_sgp_builder import MLBSGPBuilder, SGPMode, PropLeg

    mode_map = {
        "props":  SGPMode.PROPS_ONLY,
        "sgp":    SGPMode.MONEYLINE_SGP,
        "mixed":  SGPMode.MIXED_SGP,
        "parlay": SGPMode.CLASSIC_PARLAY,
    }
    sgp_mode = mode_map[args.mode]

    # ── Step 1: Fetch games ──────────────────────────────────────────────
    print("[1/6] Fetching today's MLB games...")
    odds_client = OddsAPIClient()
    if not odds_client.is_configured():
        print("  ODDS_API_KEY not set. Exiting.")
        sys.exit(0)

    try:
        games = odds_client.fetch_games(sport_key=_MLB_SPORT_KEY)
    except Exception as exc:
        logger.warning("MLB games fetch failed: %s", exc)
        games = []

    if not games:
        print("    No MLB games found today (or API error). Exiting.")
        sys.exit(0)
    print(f"    Found {len(games)} game(s)")

    # Enrich with MLBModel win probabilities
    mlb_model = MLBModel()
    for game in games:
        pred = mlb_model.predict(game)
        game["home_model_prob"] = pred["home_win_prob"]
        game["away_model_prob"] = pred["away_win_prob"]

    if args.validate:
        src = "XGBoost (mlb_outcomes)" if mlb_model._xgb_models_loaded else "market-implied fallback"
        print(f"    Model source: {src}")

    # ── Step 2: Fetch props ──────────────────────────────────────────────
    prop_legs_raw: list[dict] = []
    if sgp_mode != SGPMode.CLASSIC_PARLAY:
        print("[2/6] Fetching MLB player prop lines...")
        prop_legs_raw = _fetch_mlb_props(odds_client, games)
        print(f"    Fetched {len(prop_legs_raw)} prop lines")
    else:
        print("[2/6] Skipping prop lines (classic parlay mode)")

    # ── Step 3: Run prop model ───────────────────────────────────────────
    scored_legs: list[PropLeg] = []
    skipped_insufficient = 0
    skipped_low_conf = 0

    if sgp_mode != SGPMode.CLASSIC_PARLAY and prop_legs_raw:
        print(f"[3/6] Running MLB prop model — {len(prop_legs_raw)} props...")
        prop_model = MLBPropModel()

        pitcher_markets = {"pitcher_strikeouts", "pitcher_outs"}
        for raw in prop_legs_raw:
            if raw.get("market") not in _MLB_PROP_MARKETS:
                continue

            is_pitcher = raw.get("market") in pitcher_markets
            result = prop_model.predict_prop(
                player_name=raw["player"],
                market=raw["market"],
                line=raw["line"],
                is_pitcher=is_pitcher,
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

        print(f"    Scored {len(scored_legs)} legs "
              f"({skipped_insufficient} insufficient, {skipped_low_conf} low confidence)")
    else:
        print("[3/6] Skipping prop model (classic parlay mode)")

    # ── Step 4: Correlation ──────────────────────────────────────────────
    if not args.no_corr and sgp_mode != SGPMode.CLASSIC_PARLAY:
        print("[4/6] Using static MLB correlation table")
    else:
        print("[4/6] Skipping correlation adjustment")

    # ── Step 5: Validation ───────────────────────────────────────────────
    if args.validate:
        print(f"[5/6] Validation: model={mlb_model._xgb_models_loaded and 'xgboost' or 'market_implied'}")
    else:
        print("[5/6] Skipping validation  (run with --validate to check model source)")

    # ── Step 6: Build combinations ───────────────────────────────────────
    print("[6/6] Building MLB SGP combinations...")
    builder = MLBSGPBuilder(
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

    # ── Output ─────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"MLB SCANNER — Mode: {args.mode.upper()}  |  Min edge: {args.min_edge:.1%}")
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
                print(f"      * {leg.get('team', '?')} ML  "
                      f"({leg.get('decimal_odds', 0):.2f}x)  "
                      f"model: {leg.get('model_prob', 0):.1%}")
            else:
                print(f"      * {leg.player}: OVER {leg.line} {_market_label(leg.market)}  "
                      f"({leg.over_odds:+d})  "
                      f"model: {leg.model_prob:.1%}  [{leg.confidence}]")

    print()


def _fetch_mlb_props(
    odds_client,
    games: list[dict],
) -> list[dict]:
    """Fetch MLB player props for all games."""
    all_props: list[dict] = []
    markets_param = ",".join(_MLB_PROP_MARKETS)

    for game in games:
        event_id = game.get("event_id", "")
        if not event_id:
            continue
        try:
            import requests
            api_key = os.environ.get("ODDS_API_KEY", "")
            if not api_key:
                continue
            url = f"https://api.the-odds-api.com/v4/sports/{_MLB_SPORT_KEY}/events/{event_id}/odds/"
            resp = requests.get(url, params={
                "apiKey": api_key,
                "regions": "us",
                "markets": markets_param,
                "oddsFormat": "american",
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            props = _parse_mlb_props(data, event_id, game.get("home_team", ""), game.get("away_team", ""))
            all_props.extend(props)
        except Exception as exc:
            logger.debug("MLB props fetch failed for event %s: %s", event_id, exc)

    return all_props


def _parse_mlb_props(
    data: dict,
    event_id: str,
    home_team: str,
    away_team: str,
) -> list[dict]:
    """Parse Odds API MLB props response."""
    best: dict = {}

    for bookmaker in data.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            market_key = market.get("key", "")
            if market_key not in _MLB_PROP_MARKETS:
                continue

            player_outcomes: dict = {}
            for outcome in market.get("outcomes", []):
                player = outcome.get("description", "")
                if player:
                    player_outcomes.setdefault(player, []).append(outcome)

            for player, player_outs in player_outcomes.items():
                over_out = next((o for o in player_outs if o.get("name", "").lower() == "over"), None)
                under_out = next((o for o in player_outs if o.get("name", "").lower() == "under"), None)
                if not over_out or not under_out:
                    continue

                line = float(over_out.get("point", 0))
                over_odds = int(over_out.get("price", -110))
                under_odds = int(under_out.get("price", -110))

                key = (player, market_key)
                existing = best.get(key)
                if existing is None or over_odds > existing["over_odds"]:
                    best[key] = {
                        "event_id": event_id,
                        "home_team": home_team,
                        "away_team": away_team,
                        "player": player,
                        "market": market_key,
                        "line": line,
                        "over_odds": over_odds,
                        "under_odds": under_odds,
                    }

    return list(best.values())


def _market_label(market: str) -> str:
    return {
        "batter_hits":        "hits",
        "batter_home_runs":   "HR",
        "batter_rbis":        "RBI",
        "pitcher_strikeouts": "Ks",
        "pitcher_outs":       "outs",
    }.get(market, market)


if __name__ == "__main__":
    main()
