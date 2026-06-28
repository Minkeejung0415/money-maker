"""
MLB Scanner — Same-Game Parlay / bet generator.

Orchestrates the full pipeline:
  [1/6] Fetch today's MLB games (MLB Stats API — free, no key needed)
  [2/6] Fetch player prop lines (no free source — props skipped)
  [3/6] Run prop model (MLBPropModel)
  [4/6] Apply static correlation table
  [5/6] Run optional validation
  [6/6] Build and rank SGP combinations (MLBSGPBuilder)

Data sources:
  Games  : MLB Stats API via mlb-statsapi (free, no key needed)
  Stats  : pybaseball (free, no key needed)
  Props  : No free odds source available — props mode will return 0 legs.
           Use --mode parlay for moneyline parlays.

NOTE: The Odds API (ODDS_API_KEY) is reserved for NBA only and is NOT used here.

Usage:
  python scripts/mlb_scanner.py --mode parlay
  python scripts/mlb_scanner.py --mode parlay --min-edge 0.04
  python scripts/mlb_scanner.py --mode parlay --validate
  python scripts/mlb_scanner.py --mode parlay --date 2026-06-28
  python scripts/mlb_scanner.py --date 2026-06-28 --individual-only
"""
from __future__ import annotations

import argparse
import io
import json
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
logger = logging.getLogger("mlb_scanner")

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
  props    -- Player prop parlay (no prop lines currently — 0 legs)
  sgp      -- Moneyline + player props (no prop lines currently)
  mixed    -- Any combination of ML and props
  parlay   -- Classic multi-game moneyline parlay (recommended)

Data sources:
  Games  : MLB Stats API (free, no key needed)
  Stats  : pybaseball (free, no key needed)

Examples:
  python scripts/mlb_scanner.py --mode parlay
  python scripts/mlb_scanner.py --mode parlay --min-edge 0.03
  python scripts/mlb_scanner.py --mode parlay --validate
  python scripts/mlb_scanner.py --mode parlay --date 2026-06-28
  python scripts/mlb_scanner.py --date 2026-06-28 --individual-only
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["props", "sgp", "mixed", "parlay"],
        default="parlay",
        help="Parlay mode (default: parlay)",
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
        "--date", default=None,
        help="MLB schedule date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--individual-only", action="store_true",
        help="Print individual game probabilities only; skip props, parlays, edge, and staking output",
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

    from alpha.data.ingestion.mlb_stats import fetch_today_games
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
    schedule_label = args.date or "today"
    print(f"[1/6] Fetching MLB games for {schedule_label} (MLB Stats API)...")
    try:
        games = fetch_today_games(args.date)
    except Exception as exc:
        logger.warning("MLB games fetch failed: %s", exc)
        games = []

    if not games:
        print(f"    No MLB games found for {schedule_label}. Exiting.")
        sys.exit(0)
    print(f"    Found {len(games)} game(s)")

    # Optional manually supplied market odds.
    odds_path = ROOT / "data" / "mlb_odds_override.json"
    if odds_path.exists():
        odds_map = {k: v for k, v in json.loads(odds_path.read_text(encoding="utf-8")).items() if not k.startswith("_")}
        for game in games:
            odds = odds_map.get(f"{game['home_team']}|{game['away_team']}")
            if odds:
                game["home_odds"] = odds["home_american"]
                game["away_odds"] = odds["away_american"]
                game["has_market_odds"] = True

    # Load the model first so we can use its team_state as quality fallback
    mlb_model = MLBModel()

    # Enrich games with live player features so v1.8 bundle activates when present.
    # Pass team_state-derived quality as fallback when pybaseball is unavailable.
    try:
        from alpha.data.ingestion.mlb_live_player_features import (
            build_live_player_features,
            build_quality_from_team_state,
        )
        _team_quality_override = None
        if mlb_model._player_bundle and mlb_model._player_bundle.get("team_state"):
            _team_quality_override = build_quality_from_team_state(
                mlb_model._player_bundle["team_state"]
            )
        player_features_map = build_live_player_features(
            games,
            team_quality_override=_team_quality_override,
        )
        for game in games:
            eid = str(game.get("event_id", ""))
            if eid in player_features_map:
                game["player_features"] = player_features_map[eid]
    except Exception as _pf_exc:
        logger.debug("Live player features unavailable: %s", _pf_exc)

    # Enrich with MLBModel win probabilities (mlb_model already loaded above)
    for game in games:
        pred = mlb_model.predict(game)
        game["home_model_prob"] = pred["home_win_prob"]
        game["away_model_prob"] = pred["away_win_prob"]
        game["mlb_model_label"] = pred.get("model_label", pred.get("source", "unknown"))
        game["mlb_fallback_reason"] = pred.get("fallback_reason")
        game["mlb_uncertainty_flags"] = pred.get("uncertainty_flags", [])
        game["mlb_confidence"] = pred.get("confidence", "LOW")
        game["mlb_pick_eligible"] = pred.get("pick_eligible", False)
        game["mlb_feature_context"] = pred.get("feature_context", {})

    src = "validated trained model" if mlb_model._model_bundle else ("legacy model" if mlb_model._xgb_models_loaded else "UNAVAILABLE — train with scripts/train_mlb_moneyline.py")
    report = mlb_model.runtime_report()
    src = report["source"]
    if args.validate:
        print(f"    Model source: {src}")
        selective = report.get("selective_report", {})
        if any(value is not None for value in selective.values()):
            print(
                "    Validation: "
                f"coverage={selective.get('coverage', 'n/a')} "
                f"selective_win_rate={selective.get('selective_win_rate', 'n/a')} "
                f"accuracy={selective.get('all_games_accuracy', 'n/a')} "
                f"brier={selective.get('brier_score', 'n/a')} "
                f"log_loss={selective.get('log_loss', 'n/a')}"
            )

    print(f"\n    Individual win probabilities ({schedule_label}):")
    for game in games:
        hp, ap = game["home_model_prob"], game["away_model_prob"]
        label = game["mlb_model_label"]
        flags = game["mlb_uncertainty_flags"]
        if game["mlb_pick_eligible"]:
            print(f"      {game['away_team']} {ap:.1%} at {game['home_team']} {hp:.1%} | {label} | fair odds {1/ap:.2f} / {1/hp:.2f}")
        else:
            reason = ", ".join(flags) or game.get("mlb_fallback_reason") or "not pick eligible"
            print(f"      {game['away_team']} {ap:.1%} at {game['home_team']} {hp:.1%} | {label} | suppressed: {reason}")
        context = game.get("mlb_feature_context") or {}
        if game.get("mlb_confidence") == "HIGH" and context:
            pieces = ", ".join(f"{key}={value}" for key, value in context.items())
            print(f"        context: {pieces}")

    if args.individual_only:
        print("\n    Individual-only mode: skipped props, parlays, edge, EV, and staking output.")
        return

    # ── Step 2: Fetch props ──────────────────────────────────────────────
    prop_legs_raw: list[dict] = []
    if sgp_mode != SGPMode.CLASSIC_PARLAY:
        print("[2/6] MLB prop lines — no free source available.")
        print("      (Props require a dedicated odds API. Use --mode parlay for ML parlays.)")
    else:
        print("[2/6] Skipping prop lines (classic parlay mode)")

    # ── Step 3: Run prop model ───────────────────────────────────────────
    scored_legs: list[PropLeg] = []

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

    # ── Step 4: Correlation ──────────────────────────────────────────────
    if not args.no_corr and sgp_mode != SGPMode.CLASSIC_PARLAY:
        print("[4/6] Using static MLB correlation table")
    else:
        print("[4/6] Skipping correlation adjustment")

    # ── Step 5: Validation ───────────────────────────────────────────────
    if args.validate:
        print(f"[5/6] Model info: {src}")
    else:
        print("[5/6] Skipping validation  (run with --validate to check model source)")

    # ── Step 6: Build combinations ───────────────────────────────────────
    print("[6/6] Building MLB SGP combinations...")
    builder = MLBSGPBuilder(
        bankroll=args.bankroll,
        min_edge=args.min_edge,
        max_legs=args.max_legs,
    )
    market_games = [g for g in games if g.get("has_market_odds") and g.get("mlb_pick_eligible", False)]
    results = builder.build(
        prop_legs=scored_legs,
        ml_games=market_games,
        mode=sgp_mode,
        top_n=args.top,
    )

    # ── Output ─────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"MLB SCANNER — Mode: {args.mode.upper()}  |  Min edge: {args.min_edge:.1%}")
    print(f"{'='*65}")

    if not results:
        print(f"\nNo combinations found with >={args.min_edge:.1%} edge today.")
        if not market_games:
            print("  No real market odds supplied; edge/parlay output intentionally disabled.")
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
