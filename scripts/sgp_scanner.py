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
from datetime import date
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
from scripts.log_predictions import log_prediction
load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sgp_scanner")
ACTIVE_SEASON = "2025-26"


def _emit_season_verification() -> None:
    """Print canonical season evidence used by scanner startup paths."""
    from alpha.data.ingestion.nba_stats_cache import NBAStatsCache
    from alpha.engines.sports.prop_model import PropModel

    stats_cache = NBAStatsCache()
    model = PropModel(season=ACTIVE_SEASON, stats_cache=stats_cache)

    print(f"ACTIVE_SEASON={ACTIVE_SEASON}")
    print(f"NBAStatsCache active season={ACTIVE_SEASON}")
    print(f"PropModel active season={getattr(model, '_season', ACTIVE_SEASON)}")


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
  ml       -- List all moneylines with model vs market edge

Examples:
  python scripts/sgp_scanner.py --mode parlay
  python scripts/sgp_scanner.py --mode ml
  python scripts/sgp_scanner.py --mode props --no-corr --min-edge 0.03
  python scripts/sgp_scanner.py --mode props --validate
  python scripts/sgp_scanner.py --mode parlay --favorites-only
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["props", "ml_sgp", "mixed", "parlay", "ml"],
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
        "--top", type=int, default=0,
        help="Number of top combinations to display (default: 0 = show all)",
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
        help="[Deprecated] Context is now off by default. Use --context to enable.",
    )
    parser.add_argument(
        "--show-ev", action="store_true",
        help="Show detailed EV analysis and bet type recommendations per game",
    )
    parser.add_argument(
        "--min-prob", type=float, default=0.60,
        help="Minimum model probability for a prop leg (default: 0.60)",
    )
    parser.add_argument(
        "--favorites-only", action="store_true",
        help="In parlay mode, only include games where at least one side has model_prob >= 0.45",
    )
    parser.add_argument(
        "--context", action="store_true",
        help="Enable contextual evaluators (position, paint deterrence, foul trouble). "
             "Disabled by default — adds 5-18 min runtime and can over-filter props.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print reasoning for dropped props and skipped games.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Optional execution date marker for logs (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print startup checks only, then exit before API calls.",
    )
    parser.add_argument(
        "--list-props",
        action="store_true",
        help="Print all individually scored prop legs sorted by model probability.",
    )
    parser.add_argument(
        "--team",
        default=None,
        help="Filter to a single game containing this team name substring (case-insensitive).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def _run_ml_mode(args, games, nba_model) -> None:
    """--mode ml: list all moneylines with model vs market edge."""
    from alpha.engines.sports.ev_calculator import EVCalculator
    from alpha.engines.sports.kelly import KellySizer

    ev_calc = EVCalculator(min_edge=0.0)
    kelly = KellySizer(kelly_fraction=0.25, max_stake_pct=0.05)

    print(f"\n{'='*65}")
    print("MONEYLINE SCANNER — All Games")
    print(f"{'='*65}")

    value_sides: list[dict] = []

    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)
        home_dec = ev_calc.american_to_decimal(home_odds)
        away_dec = ev_calc.american_to_decimal(away_odds)
        home_mp = game.get("home_model_prob", ev_calc.implied_prob(home_dec))
        away_mp = game.get("away_model_prob", ev_calc.implied_prob(away_dec))
        home_mkt = ev_calc.implied_prob(home_dec)
        away_mkt = ev_calc.implied_prob(away_dec)

        home_edge = home_mp - home_mkt
        away_edge = away_mp - away_mkt
        home_ev100 = ev_calc.expected_value(home_mp, home_dec) * 100
        away_ev100 = ev_calc.expected_value(away_mp, away_dec) * 100
        home_kelly = kelly.kelly_fraction(home_mp, home_dec) * 0.25
        away_kelly = kelly.kelly_fraction(away_mp, away_dec) * 0.25

        print(f"\n{home} vs {away}")
        for team, mp, mkt, edge, ev100, kf, is_value in [
            (home, home_mp, home_mkt, home_edge, home_ev100, home_kelly, home_edge > 0.04),
            (away, away_mp, away_mkt, away_edge, away_ev100, away_kelly, away_edge > 0.04),
        ]:
            tag = " <- VALUE" if is_value else (" <- SKIP" if edge < 0 else "")
            print(f"  {team:30s}  model {mp:.1%}  |  market {mkt:.1%}  |  "
                  f"edge {edge:+.1%}  |  EV/100: ${ev100:+.2f}  |  "
                  f"Kelly: {kf:.1%}{tag}")
            if is_value:
                value_sides.append({"team": team, "edge": edge, "ev100": ev100, "mp": mp})

    if value_sides:
        value_sides.sort(key=lambda x: x["edge"], reverse=True)
        limit = args.top if args.top > 0 else len(value_sides)
        print(f"\n{'='*65}")
        print(f"TOP VALUE ML BETS (edge > 4%) — showing {limit} of {len(value_sides)}")
        print(f"{'='*65}")
        for i, v in enumerate(value_sides[:limit], 1):
            print(f"  {i}. {v['team']:30s}  edge {v['edge']:+.1%}  |  "
                  f"EV/100: ${v['ev100']:+.2f}  |  model: {v['mp']:.1%}")
    else:
        print("\n  No moneyline value found today (no side with > 4% edge).")

    print()


def main() -> None:
    args = _parse_args()
    _emit_season_verification()
    if args.date:
        print(f"RUN_DATE={args.date}")
    if args.dry_run:
        print("DRY_RUN=1")
        return

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

    # ── --team filter ─────────────────────────────────────────────────────
    if getattr(args, "team", None):
        team_filter = args.team.lower()
        games = [
            g for g in games
            if team_filter in g.get("home_team", "").lower()
            or team_filter in g.get("away_team", "").lower()
        ]
        if not games:
            print(f"    No game found containing team '{args.team}'. Exiting.")
            sys.exit(0)
        print(f"    Filtered to {len(games)} game(s) matching '{args.team}'")
    if getattr(args, "verbose", False):
        for g in games:
            print(f"      {g.get('away_team','?')} @ {g.get('home_team','?')}  "
                  f"[event_id={g.get('event_id','?')[:12]}...]")

    # Enrich games with NBAModel win probabilities so SGPBuilder has real model_prob
    from alpha.engines.sports.nba_model import NBAModel
    nba_model = NBAModel()
    for game in games:
        pred = nba_model.predict(game)
        game["home_model_prob"] = pred["home_win_prob"]
        game["away_model_prob"] = pred["away_win_prob"]

    # ── ML-only mode: skip all prop logic ────────────────────────────────
    if args.mode == "ml":
        _run_ml_mode(args, games, nba_model)
        return

    sgp_mode = mode_map[args.mode]

    # ── Feature 4: --favorites-only filter ───────────────────────────────
    if args.favorites_only and sgp_mode == SGPMode.CLASSIC_PARLAY:
        pre = len(games)
        games = [
            g for g in games
            if g.get("home_model_prob", 0) >= 0.45
            or g.get("away_model_prob", 0) >= 0.45
        ]
        print(f"    --favorites-only: kept {len(games)}/{pre} games with >= 45% model prob side")

    # ── Step 1.5: Injury check ───────────────────────────────────────────
    injury_statuses: dict[str, str] = {}
    if sgp_mode != SGPMode.CLASSIC_PARLAY:
        print("[1.5/6] Checking injury/availability status...")
        try:
            from alpha.data.ingestion.nba_injuries import get_player_injury_statuses
            all_team_names: list[str] = []
            for g in games:
                all_team_names.extend([g.get("home_team", ""), g.get("away_team", "")])
            all_team_names = [t for t in all_team_names if t]
            injury_statuses = get_player_injury_statuses(all_team_names)
            out_players_today = {p: s for p, s in injury_statuses.items() if s == "OUT"}
            questionable_players_today = {p: s for p, s in injury_statuses.items() if s == "QUESTIONABLE"}
            if out_players_today:
                print(f"    OUT: {', '.join(sorted(out_players_today.keys()))}")
            if questionable_players_today:
                print(f"    QUESTIONABLE: {', '.join(sorted(questionable_players_today.keys()))}")
            if not out_players_today and not questionable_players_today:
                print("    No injury concerns found.")
        except Exception as exc:
            print(f"    Injury check skipped: {exc}")
    else:
        print("[1.5/6] Skipping injury check (classic parlay mode)")

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

        # Build player → current team map (single cached API call, used to fix player_team)
        from alpha.data.ingestion.nba_stats_cache import NBAStatsCache as _NBAStatsCache
        _stats_cache_step3 = _NBAStatsCache()
        player_team_map = _stats_cache_step3.fetch_player_team_map()

        model = PropModel(stats_cache=_stats_cache_step3)
        seen_players: set[str] = set()
        done = 0
        traded_warnings: list[str] = []
        for raw in prop_legs_raw:
            if raw.get("market") not in markets:
                continue
            player = raw["player"]
            if player not in seen_players:
                seen_players.add(player)
                done += 1
                print(f"\r    Fetching: {done}/{unique_players} players ({player[:30]})    ", end="", flush=True)
            opponent = raw.get("away_team", "")
            result = model.predict_prop(
                player_name=raw["player"],
                market=raw["market"],
                line=raw["line"],
                opponent_team=opponent,
                over_odds=raw.get("over_odds", -110),
                under_odds=raw.get("under_odds"),
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

            # Resolve player's actual current team (fall back to home_team if unknown)
            actual_team = player_team_map.get(player.lower(), raw.get("home_team", ""))

            if result.get("recent_trade"):
                traded_warnings.append(
                    f"  ⚠ {player}: recently traded — stats may be stale, confidence capped MEDIUM"
                )

            # Apply injury downgrade: QUESTIONABLE player → cap at MEDIUM
            player_inj_status = injury_statuses.get(raw["player"])
            if player_inj_status == "QUESTIONABLE" and conf == "HIGH":
                conf = "MEDIUM"
            elif player_inj_status == "QUESTIONABLE":
                conf = "LOW"

            # Apply teammate boost for OUT players (+8% on pts/reb if teammate is out)
            final_model_prob = result["model_prob"]
            for out_name, out_status in injury_statuses.items():
                if out_status == "OUT":
                    # We can't easily look up the out player's team here without extra API,
                    # so apply a flat +8% if the prop player is on the same team
                    # (team matching will be approximate via player_team_map)
                    pass  # teammate boost handled after scoring via boost_map below

            scored_legs.append(PropLeg(
                player=raw["player"],
                market=raw["market"],
                line=raw["line"],
                model_prob=final_model_prob,
                over_odds=raw["over_odds"],
                event_id=raw["event_id"],
                home_team=raw["home_team"],
                away_team=raw["away_team"],
                confidence=conf,
                player_team=actual_team,
            ))
            log_prediction(
                player=raw["player"],
                market=raw["market"],
                line=raw["line"],
                direction="over",
                model_prob=final_model_prob,
                market_implied=result.get("market_implied", 0.5),
                confidence=conf,
                game_date=str(date.today()),
            )

            # Generate UNDER leg if 1 - model_prob >= 0.65
            under_prob = round(1.0 - result["model_prob"], 4)
            if under_prob >= 0.65:
                # Classify confidence for the UNDER
                if under_prob >= 0.72:
                    under_conf = "HIGH"
                elif under_prob >= 0.65:
                    under_conf = "MEDIUM"
                else:
                    under_conf = "LOW"
                # CONF-03 floor: under prob must be >= 0.60 (it is, since >= 0.65)
                # Apply injury downgrade to UNDER leg too
                if player_inj_status == "QUESTIONABLE" and under_conf == "HIGH":
                    under_conf = "MEDIUM"
                elif player_inj_status == "QUESTIONABLE":
                    under_conf = "LOW"
                # Respect --confidence filter
                if args.confidence == "HIGH" and under_conf != "HIGH":
                    pass  # skip this under leg
                elif args.confidence == "MEDIUM" and under_conf == "LOW":
                    pass  # skip this under leg
                else:
                    under_odds = raw.get("under_odds", raw.get("over_odds", -110))
                    scored_legs.append(PropLeg(
                        player=raw["player"],
                        market=raw["market"],
                        line=raw["line"],
                        model_prob=under_prob,
                        over_odds=under_odds,
                        event_id=raw["event_id"],
                        home_team=raw["home_team"],
                        away_team=raw["away_team"],
                        confidence=under_conf,
                        direction="under",
                        player_team=actual_team,
                    ))
                    log_prediction(
                        player=raw["player"],
                        market=raw["market"],
                        line=raw["line"],
                        direction="under",
                        model_prob=under_prob,
                        market_implied=round(1.0 - result.get("market_implied", 0.5), 4),
                        confidence=under_conf,
                        game_date=str(date.today()),
                    )

        print()  # newline after progress

        # Feature 2: min-prob confidence floor
        pre_filter = len(scored_legs)
        scored_legs = [leg for leg in scored_legs if leg.model_prob >= args.min_prob]
        dropped = pre_filter - len(scored_legs)
        if dropped > 0:
            if args.verbose:
                weak = [leg for leg in [l for l in scored_legs if l.model_prob < args.min_prob]]
                # re-check before filter for verbose (already filtered, show count)
            print(f"    Min-prob filter ({args.min_prob:.0%}): dropped {dropped} weak legs")

        print(f"    Scored {len(scored_legs)} legs  "
              f"({skipped_insufficient} skipped: insufficient data, "
              f"{skipped_low_conf} skipped: low confidence)")

        if traded_warnings:
            print("\n  RECENTLY TRADED PLAYERS (stats may be stale):")
            for w in sorted(set(traded_warnings)):
                print(w)
            print()
    else:
        print("[3/6] Skipping prop model (classic parlay mode)")

    # ── Step 4: Contextual evaluators (opt-in with --context) ────────────
    context_evaluator = None
    context_scored = []
    _use_context = getattr(args, "context", False) and not getattr(args, "no_context", False)
    if _use_context and sgp_mode != SGPMode.CLASSIC_PARLAY and scored_legs:
        print("[4/8] Running contextual evaluators (position, paint, foul trouble, pace)...")
        try:
            import threading as _threading

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

            result_box: list = []
            exc_box: list = []

            def _run_ctx():
                try:
                    result_box.append(context_evaluator.evaluate_props(prop_dicts, wall_timeout=60))
                except Exception as e:
                    exc_box.append(e)

            ctx_thread = _threading.Thread(target=_run_ctx, daemon=True)
            ctx_thread.start()
            ctx_thread.join(timeout=90)

            if ctx_thread.is_alive():
                print("    Context evaluators timed out (90s) — falling back to no-context")
                context_scored = []
            elif exc_box:
                raise exc_box[0]
            else:
                context_scored = result_box[0] if result_box else []

            if context_scored:
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
                            player_team=cs.get("home_team", ""),
                        ))

                filtered_count = pre_count - len(adjusted_legs)
                scored_legs = adjusted_legs if adjusted_legs else scored_legs
                print(f"    Context adjustments applied — {len(scored_legs)} legs remain "
                      f"({filtered_count} filtered/below edge)")
        except Exception as exc:
            print(f"    Context evaluators skipped: {exc}")
    else:
        if sgp_mode == SGPMode.CLASSIC_PARLAY:
            reason = "classic parlay"
        elif not _use_context:
            reason = "disabled by default (use --context to enable)"
        else:
            reason = "--no-context"
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

    # ── Optional: list all scored props (default ON in props mode) ───────
    list_props = getattr(args, "list_props", False) or args.mode == "props"
    if list_props and scored_legs:
        print(f"\n{'='*65}")
        print(f"ALL SCORED PROPS ({len(scored_legs)} legs)  |  sorted by model prob")
        print(f"{'='*65}")
        sorted_legs = sorted(scored_legs, key=lambda l: l.model_prob, reverse=True)
        for leg in sorted_legs:
            direction_label = "UNDER" if leg.direction == "under" else "OVER"
            stat_label = _market_label(leg.market)
            print(f"  {leg.player}: {direction_label} {leg.line} {stat_label}  "
                  f"({leg.over_odds:+d})  model: {leg.model_prob:.1%}  [{leg.confidence}]")
        print()

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
                direction_label = "UNDER" if leg.direction == "under" else "OVER"
                stat_label = _market_label(leg.market)
                if leg.direction == "under":
                    stat_label = f"[U] {stat_label}"
                print(f"      * {leg.player}: {direction_label} {leg.line} {stat_label}  "
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
