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
  python scripts/wc_scanner.py --fixtures-file data/wc_round32_remaining_2026-06-28.json --individual-only
  python scripts/wc_scanner.py --fixtures-file data/wc_round32_remaining_2026-06-28.json --props-only
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import date, datetime, timedelta
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
        description="WC 2026 match parlay generator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  parlay   -- Classic multi-game moneyline parlay
  sgp      -- Same-match 1X2, total-goals, and BTTS combinations

Data sources:
  Games : football-data.org (requires FOOTBALL_API_KEY in .env)
  Model : Elo ratings (data/wc_priors.json) + StatsBomb stats (data/.wc_cache/)

Examples:
  python scripts/wc_scanner.py --mode parlay
  python scripts/wc_scanner.py --mode parlay --date-from 2026-06-26 --date-to 2026-07-02
  python scripts/wc_scanner.py --fixtures-file data/wc_round32_remaining_2026-06-28.json --individual-only
  python scripts/wc_scanner.py --fixtures-file data/wc_round32_remaining_2026-06-28.json --props-only
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["parlay", "sgp"],
        default="parlay",
        help="Combination mode (default: parlay)",
    )
    parser.add_argument(
        "--model",
        choices=["elo", "hybrid", "player", "auto"],
        default="elo",
        help="Match model: elo baseline, hybrid challenger, player/auto require promoted artifact",
    )
    parser.add_argument(
        "--shadow-model",
        choices=["none", "elo", "hybrid"],
        default="none",
        help="Log a challenger model beside active picks without affecting rankings",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Allow auto/player artifact failures to fall back to Elo with explicit labels",
    )
    parser.add_argument(
        "--artifact-meta",
        default=str(ROOT / "alpha" / "models" / "wc_runtime_model.meta.json"),
        help="Runtime artifact metadata JSON for --model auto/player",
    )
    parser.add_argument(
        "--individual-only",
        action="store_true",
        help="Print individual fixture probabilities only; skip SGP/parlay building",
    )
    parser.add_argument(
        "--props-only",
        action="store_true",
        help="Print per-game model prop probabilities only; skip SGP/parlay building",
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
        "--fixtures-file",
        default=None,
        help="Optional JSON fixture file to use instead of football-data.org",
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
        help="Top classic parlays to display; SGP mode always shows all (default: 5)",
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
    from alpha.data.ingestion.wc_market_odds import load_wc_market_odds
    from alpha.data.ingestion.wc_recent_form import WCRecentFormClient
    from alpha.data.ingestion.wc_tactics import WCTacticsClient
    from alpha.engines.model_registry import validate_runtime_artifact
    from alpha.engines.sports.wc_hybrid_model import WCHybridModel
    from alpha.engines.sports.wc_model import WCMatchModel
    from alpha.engines.sports.wc_goal_markets import WCScorelineModel
    from alpha.engines.sports.wc_sgp_builder import WCSGPBuilder
    from alpha.engines.sports.wc_tactical_matchup import compare_tactics
    from alpha.engines.sports.wc_tactical_calibration import load_artifact

    # ── Step 1: Fetch WC fixtures ────────────────────────────────────────
    print(f"[1/4] Fetching WC fixtures ({args.date_from} to {args.date_to})...")
    if args.fixtures_file:
        try:
            all_games = _load_fixture_file(args.fixtures_file)
        except Exception as exc:
            print(f"  ERROR: could not load fixtures file: {exc}")
            sys.exit(1)
        print(f"  Loaded fixtures from {args.fixtures_file}")
    else:
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

    # ── Odds override: patch real decimal odds from data/wc_odds_override.json ──
    _odds_path = ROOT / "data" / "wc_odds_override.json"
    market_odds = {}
    if _odds_path.exists():
        market_odds = load_wc_market_odds(_odds_path)
        patched = 0
        for game in all_games:
            key = f"{game['home_team']}|{game['away_team']}"
            prices = market_odds.get(key)
            if prices and "home_win" in prices.prices and "away_win" in prices.prices:
                h = prices.prices["home_win"]
                a = prices.prices["away_win"]
                game["home_odds"] = round(-100 / (h - 1)) if h < 2 else round((h - 1) * 100)
                game["away_odds"] = round(-100 / (a - 1)) if a < 2 else round((a - 1) * 100)
                game["has_market_odds"] = True
                patched += 1
        print(f"  Odds override applied to {patched}/{len(all_games)} game(s) from {_odds_path.name}")

    # ── Step 2: Run selected match model ─────────────────────────────────
    requested_model = args.model
    fallback_used = False
    fallback_reason = None
    artifact_metadata: dict = {}
    try:
        model_choice, artifact_check = _resolve_runtime_model(args, validate_runtime_artifact)
    except RuntimeError as exc:
        print(f"  ERROR: {exc}")
        sys.exit(1)

    if artifact_check is not None:
        artifact_metadata = artifact_check.metadata
        if not artifact_check.ok:
            fallback_used = True
            fallback_reason = artifact_check.reason
            print(f"  fallback_used=true fallback_reason={fallback_reason} "
                  f"active_model=elo requested_model={requested_model}")

    model_label = (
        "WCMatchModel / wc_elo_logistic"
        if model_choice == "elo"
        else "WCHybridModel / wc_hybrid_baseline"
    )
    print(f"[2/4] Running {model_label}...")
    try:
        wc_model = (
            WCMatchModel(min_edge=args.min_edge)
            if model_choice == "elo"
            else WCHybridModel(min_edge=args.min_edge)
        )
        shadow_model = None
        if args.shadow_model != "none":
            shadow_model = (
                WCMatchModel(min_edge=args.min_edge)
                if args.shadow_model == "elo"
                else WCHybridModel(min_edge=args.min_edge)
            )
    except FileNotFoundError as exc:
        print(f"  ERROR: {exc}")
        print("  Run: ./venv/Scripts/python.exe scripts/build_wc_priors.py")
        sys.exit(1)

    if args.validate:
        if model_choice == "elo":
            print(f"  Model: wc_elo_logistic | Elo ratings: {len(wc_model._elo_ratings)} | "
                  f"Stats: {len(wc_model._wc_stats)} teams")
        else:
            base_model = wc_model._base
            ratings = wc_model._ratings
            print(f"  Model: wc_hybrid_baseline | Base Elo ratings: "
                  f"{len(base_model._elo_ratings)} | Hybrid teams: {len(ratings._elo)}")
        print(f"  requested_model={requested_model} active_model={model_choice} "
              f"fallback_used={str(fallback_used).lower()} "
              f"fallback_reason={fallback_reason or 'none'}")
        if artifact_metadata:
            print(f"  artifact_id={artifact_metadata.get('model_id')} "
                  f"artifact_path={args.artifact_meta}")
        if args.shadow_model != "none":
            print(f"  shadow_model={args.shadow_model} shadow_affects_picks=false")

    recent_client = WCRecentFormClient() if args.mode == "sgp" else None
    tactics_client = WCTacticsClient() if args.mode == "sgp" else None
    tactical_artifact, artifact_status = load_artifact(
        ROOT / "data" / ".wc_cache" / "tactical_calibration.json"
    ) if args.mode == "sgp" else (None, {"status": "fallback", "reason": "not used"})
    if recent_client:
        print("  Loading recent last-10 international form and Elo for every team...")
        print(f"  Tactical calibration: {artifact_status['status']} ({artifact_status['reason']})")

    enriched: list[dict] = []
    shadow_rows: list[dict] = []
    for game in all_games:
        try:
            if recent_client:
                commence = str(game.get("commence_time", ""))[:10]
                as_of = date.fromisoformat(commence) if commence else date.fromisoformat(args.date_from)
                home = recent_client.fetch(game["home_team"], as_of)
                away = recent_client.fetch(game["away_team"], as_of)
                if home is None or away is None:
                    print(f"  Skipping {game.get('home_team')} vs {game.get('away_team')}: "
                          "fewer than 5 recent pre-match results available")
                    continue
                game["recent_team_stats"] = {
                    game["home_team"]: home,
                    game["away_team"]: away,
                }
                if home.get("elo_rating") is not None:
                    game["home_elo_override"] = home["elo_rating"]
                if away.get("elo_rating") is not None:
                    game["away_elo_override"] = away["elo_rating"]
                kickoff = datetime.fromisoformat(
                    str(game.get("commence_time", "")).replace("Z", "+00:00")
                )
                team_ids = tactics_client.resolve_team_ids(kickoff.date())
                home_profile = tactics_client.fetch_profile(
                    game["home_team"], team_ids.get(game["home_team"], ""), kickoff
                )
                away_profile = tactics_client.fetch_profile(
                    game["away_team"], team_ids.get(game["away_team"], ""), kickoff
                )
                if home_profile is None or away_profile is None:
                    print(f"  Skipping {game.get('home_team')} vs {game.get('away_team')}: "
                          "fewer than 3 stat-complete tactical matches available")
                    continue
                baseline_game = wc_model.predict(dict(game))
                comparison = compare_tactics(home_profile, away_profile)
                game["tactical_profiles"] = {
                    game["home_team"]: home_profile,
                    game["away_team"]: away_profile,
                }
                game["tactical_explanation"] = comparison
                game["tactical_baseline_game"] = baseline_game
                gates = {market: False for market in ("1x2", "totals", "btts")}
                if tactical_artifact is not None:
                    try:
                        tactical_artifact.validate(target_kickoff=kickoff)
                    except ValueError as exc:
                        game["tactical_artifact_status"] = {"status": "fallback", "reason": str(exc)}
                    else:
                        gates = {market: tactical_artifact.gates[market].passed for market in gates}
                        game["tactical_artifact_status"] = {
                            "status": "loaded",
                            "reason": "validated artifact",
                            "schema_version": tactical_artifact.schema_version,
                            "trained_through": tactical_artifact.trained_through,
                        }
                        if gates["1x2"]:
                            game["tactical_elo_adjustment_override"] = tactical_artifact.outcome.elo_adjustment(
                                comparison.home_components, comparison.away_components
                            )
                        if gates["totals"] or gates["btts"]:
                            home_multiplier, away_multiplier = tactical_artifact.goals.multipliers(
                                comparison.home_components, comparison.away_components
                            )
                            from dataclasses import replace
                            game["tactical_comparison"] = replace(
                                comparison,
                                home_attack_multiplier=home_multiplier,
                                away_attack_multiplier=away_multiplier,
                            )
                            game["tactical_applied_comparison"] = game["tactical_comparison"]
                            game["tactical_goal_authorized"] = True
                        game["tactical_joint_approved"] = tactical_artifact.joint_approved
                else:
                    game["tactical_artifact_status"] = artifact_status
                game["tactical_market_gates"] = gates
            if shadow_model is not None:
                shadow_pred = shadow_model.predict(dict(game))
                shadow_rows.append(
                    _shadow_row(game, shadow_pred, requested_model, model_choice, args.shadow_model)
                )
            game = wc_model.predict(game)
            game["requested_model"] = requested_model
            game["active_model"] = model_choice
            game["fallback_used"] = fallback_used
            game["fallback_reason"] = fallback_reason
            if recent_client:
                baseline_distribution = WCScorelineModel().build(baseline_game)
                adjusted_distribution = WCScorelineModel().build(game)
                game["tactical_baseline"] = {
                    "win_prob": baseline_game["win_prob"],
                    "draw_prob": baseline_game["draw_prob"],
                    "loss_prob": baseline_game["loss_prob"],
                    "over_2_5": baseline_distribution.probability("over_2_5"),
                    "btts_yes": baseline_distribution.probability("btts_yes"),
                }
                game["tactical_adjusted"] = {
                    "over_2_5": adjusted_distribution.probability("over_2_5") if gates["totals"] else baseline_distribution.probability("over_2_5"),
                    "btts_yes": adjusted_distribution.probability("btts_yes") if gates["btts"] else baseline_distribution.probability("btts_yes"),
                }
            enriched.append(game)
        except Exception as exc:
            logger.warning(
                "Skipping %s vs %s: %s",
                game.get("home_team"), game.get("away_team"), exc,
            )

    if shadow_rows:
        shadow_path = _write_shadow_predictions(shadow_rows, args.date_from)
        print(f"  Shadow predictions logged: {len(shadow_rows)} -> {shadow_path}")

    print(f"  Enriched {len(enriched)} game(s) with {model_choice} predictions")
    if recent_client:
        print(f"  Recent form ready for {len(enriched)} game(s)")

    if args.individual_only:
        print(f"\nWC individual probabilities ({args.date_from} to {args.date_to})")
        print(f"requested_model={requested_model} active_model={model_choice} "
              f"fallback_used={str(fallback_used).lower()} "
              f"fallback_reason={fallback_reason or 'none'}")
        if args.shadow_model != "none":
            print(f"shadow_model={args.shadow_model} shadow_affects_picks=false")
        for game in enriched:
            print(
                f"  {game['home_team']} vs {game['away_team']} | "
                f"H/D/A {game['win_prob']:.1%}/{game['draw_prob']:.1%}/{game['loss_prob']:.1%} | "
                f"model={game.get('model_name', model_choice)}"
            )
        print("\nIndividual-only mode: skipped SGP/parlay building, edge, EV, and staking output.")
        return

    if args.props_only:
        _print_game_props(enriched, wc_model, args, requested_model, model_choice, fallback_used, fallback_reason)
        return

    # ── Step 3: Build SGP combinations ──────────────────────────────────
    print(f"[3/4] Building WC {args.mode} combinations...")
    builder = WCSGPBuilder(
        bankroll=args.bankroll,
        min_edge=args.min_edge,
        max_legs=args.max_legs,
        team_stats=getattr(wc_model, "_wc_stats", {}),
    )
    if args.mode == "sgp":
        results = builder.build_probability_same_game(enriched)
    else:
        # Edge/EV math requires real market prices. Games whose odds are the
        # ingestion placeholder (-110/-110, has_market_odds=False) would show
        # a fabricated edge, so they are excluded from parlay building.
        parlay_games = [g for g in enriched if g.get("has_market_odds", True)]
        skipped_no_odds = len(enriched) - len(parlay_games)
        if skipped_no_odds:
            print(f"  {skipped_no_odds} game(s) excluded from parlays: no real market odds "
                  f"(add prices to data/wc_odds_override.json)")
        results = builder.build(parlay_games, top_n=args.top)

    # ── Step 4: Output ───────────────────────────────────────────────────
    print("[4/4] Ranking complete.")
    print(f"\n{'='*65}")
    header = (f"WC SCANNER — Mode: {args.mode.upper()}  |  "
              f"Model: {model_choice.upper()}  |  {args.date_from} to {args.date_to}")
    if args.mode != "sgp":
        header += f"  |  Min edge: {args.min_edge:.1%}"
    print(header)
    print(f"requested_model={requested_model} active_model={model_choice} "
          f"fallback_used={str(fallback_used).lower()} "
          f"fallback_reason={fallback_reason or 'none'}")
    if args.shadow_model != "none":
        print(f"shadow_model={args.shadow_model} shadow_affects_picks=false")
    print(f"{'='*65}")

    if args.mode == "sgp" and results:
        print(f"\nFull probability set: {len(results)} nonzero compatible combinations.")
        print("\nTACTICAL MATCHUPS")
        for game in enriched:
            comparison = game["tactical_explanation"]
            profiles = game["tactical_profiles"]
            home_profile = profiles[game["home_team"]]
            away_profile = profiles[game["away_team"]]
            baseline = game["tactical_baseline"]
            adjusted = game["tactical_adjusted"]
            statuses = game["tactical_market_gates"]
            artifact = game["tactical_artifact_status"]
            print(f"  {game['home_team']} [{home_profile.formation}] vs "
                  f"{game['away_team']} [{away_profile.formation}]")
            print(f"    Artifact: {artifact['status']} - {artifact['reason']}")
            print("    Gates: " + " | ".join(
                f"{market}={'PASS' if statuses[market] else 'FALLBACK'}"
                for market in ("1x2", "totals", "btts")
            ))
            applied = game.get("tactical_applied_comparison")
            if applied is not None:
                print(f"    Learned goal multipliers: {game['home_team']} "
                      f"{applied.home_attack_multiplier:.3f}x | {game['away_team']} "
                      f"{applied.away_attack_multiplier:.3f}x | tactical Elo "
                      f"{game.get('tactical_elo_adjustment', 0.0):+.1f}")
            else:
                print("    Tactical weights inactive; matchup components are descriptive only.")
            print(f"    1X2 H/D/A: {baseline['win_prob']:.1%}/{baseline['draw_prob']:.1%}/"
                  f"{baseline['loss_prob']:.1%} -> {game['win_prob']:.1%}/"
                  f"{game['draw_prob']:.1%}/{game['loss_prob']:.1%}")
            print(f"    Over 2.5: {baseline['over_2_5']:.1%} -> "
                  f"{adjusted['over_2_5']:.1%} | BTTS Yes: "
                  f"{baseline['btts_yes']:.1%} -> {adjusted['btts_yes']:.1%}")
            for explanation in comparison.home_explanations:
                print(f"    {game['home_team']}: {explanation}")
            for explanation in comparison.away_explanations:
                print(f"    {game['away_team']}: {explanation}")

    if not results:
        print(f"\nNo combinations found with >={args.min_edge:.1%} edge in this date range.")
        if args.mode == "sgp":
            print("  No nonzero compatible scoreline combinations were produced.")
        print(f"  ({len(enriched)} games enriched — try --min-edge 0.02 or expand date range)")
        return

    for rank, combo in enumerate(results, 1):
        if args.mode == "sgp":
            warning = "  |  REDUNDANT LEG" if combo.redundant else ""
            print(f"\n#{rank}  {combo.home_team} vs {combo.away_team}")
            print(f"    Joint win probability: {combo.combined_model_prob:.1%}  |  "
                  f"Model fair odds: {combo.fair_decimal_odds:.2f}x{warning}")
            print("    Legs:")
            for leg in combo.legs:
                print(f"      * {leg['label']}  |  individual model: "
                      f"{leg['model_prob']:.1%}")
            print("    Probability only - no sportsbook odds, edge, EV, or stake assumed.")
            continue
        print(f"\n#{rank}  EV: {combo.ev:.1%}  |  Edge: {combo.edge:.1%}  |  "
              f"Odds: {combo.combined_decimal_odds:.2f}x  |  "
              f"Stake: ${combo.stake:.2f}")
        print(f"    Model Prob: {combo.combined_model_prob:.1%}  vs  "
              f"Market Implied: {combo.combined_market_prob:.1%}")
        print("    Legs:")
        for leg in combo.legs:
            if isinstance(leg, dict):
                if leg.get("type") == "wc_sgp":
                    print(f"      * {leg['label']}  ({leg['decimal_odds']:.2f}x)  "
                          f"model: {leg['model_prob']:.1%}")
                    continue
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


def _resolve_runtime_model(args: argparse.Namespace, validator) -> tuple[str, object | None]:
    """Resolve requested model to an active model with no silent fallback."""
    if args.model in ("elo", "hybrid"):
        return args.model, None

    check = validator(
        args.artifact_meta,
        league="WC",
        market="moneyline",
        supported_model_ids={"wc_hybrid_baseline", "wc_player_v1"},
    )
    if not check.ok:
        if args.allow_fallback:
            return "elo", check
        raise RuntimeError(f"promoted model unavailable ({check.reason}); no silent fallback")

    model_id = check.metadata.get("model_id")
    if args.model == "player" and model_id != "wc_player_v1":
        if args.allow_fallback:
            return "elo", check
        raise RuntimeError(f"promoted player model unavailable (artifact model_id={model_id!r})")
    if model_id == "wc_hybrid_baseline":
        return "hybrid", check
    if model_id == "wc_player_v1":
        raise RuntimeError("promoted player artifact is valid but player runtime is not implemented")
    raise RuntimeError(f"unsupported promoted model_id={model_id!r}")


def _load_fixture_file(path_str: str) -> list[dict]:
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    data = json.loads(path.read_text(encoding="utf-8"))
    games = data.get("games", data) if isinstance(data, dict) else data
    if not isinstance(games, list):
        raise ValueError("fixture file must contain a list or {'games': [...]}")
    return games


def _print_game_props(
    games: list[dict],
    wc_model,
    args: argparse.Namespace,
    requested_model: str,
    model_choice: str,
    fallback_used: bool,
    fallback_reason: str | None,
) -> None:
    from alpha.engines.sports.wc_goal_markets import WCScorelineModel

    scoreline_model = WCScorelineModel(getattr(wc_model, "_wc_stats", {}))
    print(f"\nWC game prop probabilities ({args.date_from} to {args.date_to})")
    print("Player props unavailable: no WC player-prop lines/source configured.")
    print(f"requested_model={requested_model} active_model={model_choice} "
          f"fallback_used={str(fallback_used).lower()} "
          f"fallback_reason={fallback_reason or 'none'}")
    if args.shadow_model != "none":
        print(f"shadow_model={args.shadow_model} shadow_affects_picks=false")

    for game in games:
        distribution = scoreline_model.build(game)
        print(f"\n{game['home_team']} vs {game['away_team']} | stage={game.get('stage', '')}")
        print(f"  {game['home_team']} advance: {game['win_prob']:.1%}")
        print(f"  {game['away_team']} advance: {game['loss_prob']:.1%}")
        print(f"  Over 2.5 goals: {distribution.probability('over_2_5'):.1%}")
        print(f"  Under 2.5 goals: {distribution.probability('under_2_5'):.1%}")
        print(f"  BTTS Yes: {distribution.probability('btts_yes'):.1%}")
        print(f"  BTTS No: {distribution.probability('btts_no'):.1%}")
        print(f"  xG mean: {game['home_team']} {distribution.home_lambda:.2f} | "
              f"{game['away_team']} {distribution.away_lambda:.2f}")

    print("\nProps-only mode: skipped SGP/parlay building, edge, EV, and staking output.")


def _shadow_row(
    game: dict,
    shadow_pred: dict,
    requested_model: str,
    active_model: str,
    shadow_model: str,
) -> dict:
    return {
        "event_id": game.get("event_id"),
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
        "commence_time": game.get("commence_time"),
        "requested_model": requested_model,
        "active_model": active_model,
        "shadow_model": shadow_model,
        "shadow_model_name": shadow_pred.get("model_name"),
        "shadow_win_prob": shadow_pred.get("win_prob"),
        "shadow_draw_prob": shadow_pred.get("draw_prob"),
        "shadow_loss_prob": shadow_pred.get("loss_prob"),
    }


def _write_shadow_predictions(rows: list[dict], date_from: str) -> str:
    out_dir = ROOT / "reports" / "shadow_predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"wc_{date_from}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return str(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
