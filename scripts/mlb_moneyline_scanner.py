"""
MLB MONEYLINE SCANNER — paper mode only.

Pipeline (free feeds first, paid odds budgeted):
  1. FREE StatsAPI schedule + probable pitchers
  2. Cached-or-daily PAID moneyline odds (one fetch/day, baseball_mlb h2h)
  3. Robust schedule<->odds join (team names + commence time, DH-safe)
  4. FREE starter features (pybaseball/Statcast) + team offense baseline
  5. MLBRunModel independent probabilities vs market no-vig consensus
  6. Fail-closed paper-bet gate with explicit refusal reasons
  7. Append-only prediction log (data/mlb_predictions/)

There is NO real-money execution path.  --paper-only is enforced
unconditionally; passing it is allowed but cannot be turned off.
There is NO automatic polling: odds refresh only via the daily budget,
--force-refresh-odds, or --selected-event-id (both manual).

Usage:
  python scripts/mlb_moneyline_scanner.py --date 2026-06-11
  python scripts/mlb_moneyline_scanner.py --team yankees --verbose
  python scripts/mlb_moneyline_scanner.py --force-refresh-odds
  python scripts/mlb_moneyline_scanner.py --selected-event-id <odds_event_id>
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.data.ingestion.mlb_odds_api import MLBOddsClient  # noqa: E402
from alpha.data.ingestion.mlb_schedule import MLBScheduleClient  # noqa: E402
from alpha.data.ingestion.mlb_starter_features import (  # noqa: E402
    get_starter_features,
    to_starter_features,
)
from alpha.data.ingestion.mlb_team_offense import (  # noqa: E402
    get_team_offense,
    to_team_offense_features,
)
from alpha.engines.sports.mlb_features import (  # noqa: E402
    FEATURE_SCHEMA_VERSION,
    GameContext,
    TeamSideFeatures,
)
from alpha.engines.sports.mlb_prediction_logger import MLBPredictionLogger  # noqa: E402
from alpha.engines.sports.mlb_run_model import MODEL_VERSION, MLBRunModel  # noqa: E402

logger = logging.getLogger("mlb_moneyline_scanner")


# ---------------------------------------------------------------------------
# Robust schedule <-> odds join
# ---------------------------------------------------------------------------

def _norm_team(name: str) -> str:
    return " ".join(str(name).lower().replace(".", "").split())


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def join_odds_to_schedule(schedule_games: list[dict], odds_games: list[dict]) -> dict[str, dict]:
    """
    Map schedule event_id -> odds record.  Matches on normalized home+away
    names; among candidates (doubleheaders), picks the closest commence
    time and never reuses one odds event for two schedule games.
    """
    by_matchup: dict[tuple[str, str], list[dict]] = {}
    for odds in odds_games:
        key = (_norm_team(odds.get("home_team", "")), _norm_team(odds.get("away_team", "")))
        by_matchup.setdefault(key, []).append(odds)

    joined: dict[str, dict] = {}
    used_odds_ids: set[str] = set()
    for game in schedule_games:
        key = (_norm_team(game["home_team"]), _norm_team(game["away_team"]))
        candidates = [
            o for o in by_matchup.get(key, [])
            if o.get("event_id") not in used_odds_ids
        ]
        if not candidates:
            continue
        sched_ts = _parse_ts(game.get("commence_time_utc", ""))

        def _time_gap(odds: dict) -> float:
            odds_ts = _parse_ts(odds.get("commence_time_utc", ""))
            if sched_ts is None or odds_ts is None:
                return float("inf")
            return abs((sched_ts - odds_ts).total_seconds())

        best = min(candidates, key=_time_gap)
        used_odds_ids.add(best.get("event_id", ""))
        joined[game["event_id"]] = best
    return joined


# ---------------------------------------------------------------------------
# Per-game analysis
# ---------------------------------------------------------------------------

def analyze_game(
    game: dict,
    odds: dict | None,
    model: MLBRunModel,
    game_date: str,
    starter_source=None,
    offense_source=None,
) -> dict:
    """Build features, run the model, evaluate the gate for one game."""
    def _side(team: str, pitcher_name, pitcher_id) -> TeamSideFeatures:
        starter_rec = get_starter_features(
            pitcher_id, pitcher_name, game_date, source=starter_source
        )
        offense_rec = get_team_offense(team, game_date, source=offense_source)
        return TeamSideFeatures(
            team=team,
            starter=to_starter_features(starter_rec),
            offense=to_team_offense_features(offense_rec),
        )

    home_side = _side(
        game["home_team"], game["probable_pitcher_home"], game["probable_pitcher_home_id"]
    )
    away_side = _side(
        game["away_team"], game["probable_pitcher_away"], game["probable_pitcher_away_id"]
    )
    context = GameContext(
        event_id=game["event_id"],
        game_date=game["game_date"],
        commence_time_utc=game["commence_time_utc"],
        home_team=game["home_team"],
        away_team=game["away_team"],
        venue=game.get("venue"),
        doubleheader_flag=bool(game.get("doubleheader_flag")),
        probable_pitchers_confirmed=bool(game.get("probable_pitchers_confirmed")),
    )

    prediction = model.predict(home_side, away_side, context)
    real_odds_present = bool(odds and odds.get("num_books", 0) > 0)
    gate = model.evaluate_paper_gate(prediction, context, real_odds_present)

    return {
        "game": game,
        "odds": odds,
        "context": context,
        "prediction": prediction,
        "gate": gate,
        "real_odds_present": real_odds_present,
    }


def build_log_record(analysis: dict) -> dict:
    game = analysis["game"]
    odds = analysis["odds"] or {}
    prediction = analysis["prediction"]
    gate = analysis["gate"]
    return {
        "event_id": game["event_id"],
        "statsapi_game_id": game["statsapi_game_id"],
        "odds_event_id": odds.get("event_id"),
        "game_date": game["game_date"],
        "commence_time_utc": game["commence_time_utc"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "probable_pitchers": {
            "home": game.get("probable_pitcher_home"),
            "away": game.get("probable_pitcher_away"),
        },
        "pitcher_confirmed": bool(game.get("probable_pitchers_confirmed")),
        "real_odds_present": analysis["real_odds_present"],
        "independent_home_prob": prediction.home_win_prob,
        "independent_away_prob": prediction.away_win_prob,
        "market_consensus_home_no_vig_prob": odds.get("consensus_home_no_vig_prob"),
        "market_consensus_away_no_vig_prob": odds.get("consensus_away_no_vig_prob"),
        "best_home_odds": odds.get("best_home_odds"),
        "best_away_odds": odds.get("best_away_odds"),
        "missing_features": prediction.missing_features,
        "neutral_factors_used": prediction.neutral_factors_used,
        "calibrator_status": gate.calibrator_status,
        "paper_bet_decision": gate.decision,
        "refusal_reasons": gate.reasons,
        "model_version": MODEL_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        # Placeholders filled by grading / closing-odds capture later.
        "result": None,
        "closing_odds": None,
        "clv": None,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _pct(p: float | None) -> str:
    return f"{p * 100:.1f}%" if p is not None else "n/a"


def print_game_report(analysis: dict, verbose: bool) -> None:
    game = analysis["game"]
    odds = analysis["odds"] or {}
    prediction = analysis["prediction"]
    gate = analysis["gate"]

    home, away = game["home_team"], game["away_team"]
    print(f"\n{away} @ {home}")
    if game.get("doubleheader_flag"):
        print(f"  (doubleheader game {game.get('game_number', '?')})")
    print("Probable pitchers:")
    print(f"  {away}: {game.get('probable_pitcher_away') or 'NOT ANNOUNCED'}")
    print(f"  {home}: {game.get('probable_pitcher_home') or 'NOT ANNOUNCED'}")

    print("\nIndependent model:")
    print(f"  {away}: {_pct(prediction.away_win_prob)}")
    print(f"  {home}: {_pct(prediction.home_win_prob)}")

    print("\nMarket consensus (no-vig):")
    if analysis["real_odds_present"]:
        print(f"  {away}: {_pct(odds.get('consensus_away_no_vig_prob'))}")
        print(f"  {home}: {_pct(odds.get('consensus_home_no_vig_prob'))}")
        print(
            f"  Best prices: {home} {odds.get('best_home_odds')} ({odds.get('best_home_book')})"
            f" / {away} {odds.get('best_away_odds')} ({odds.get('best_away_book')})"
            f" across {odds.get('num_books')} book(s)"
        )
    else:
        print("  NO REAL ODDS (fail closed)")

    print("\nMissing features:")
    if prediction.missing_features:
        shown = prediction.missing_features if verbose else prediction.missing_features[:8]
        for name in shown:
            print(f"  {name}")
        if not verbose and len(prediction.missing_features) > 8:
            print(f"  ... {len(prediction.missing_features) - 8} more (use --verbose)")
    else:
        print("  none")

    print("\nPaper-bet decision:")
    print(f"  {gate.decision.replace('_', ' ')}")
    if gate.reasons:
        print("  Reasons:")
        for reason in gate.reasons:
            print(f"  - {reason}")

    if verbose:
        print("\nExpected runs:")
        print(f"  {home}: {prediction.expected_runs_home}")
        print(f"  {away}: {prediction.expected_runs_away}")
        if prediction.neutral_factors_used:
            print("Neutral factors substituted:")
            for name in prediction.neutral_factors_used:
                print(f"  {name}")


# ---------------------------------------------------------------------------
# Scan driver
# ---------------------------------------------------------------------------

def scan(
    game_date: str,
    team_filter: str | None = None,
    force_refresh_odds: bool = False,
    selected_event_ids: list[str] | None = None,
    verbose: bool = False,
    schedule_client: MLBScheduleClient | None = None,
    odds_client: MLBOddsClient | None = None,
    prediction_logger: MLBPredictionLogger | None = None,
    model: MLBRunModel | None = None,
    starter_source=None,
    offense_source=None,
) -> list[dict]:
    """Run the full paper-mode pipeline.  Returns the logged records."""
    schedule_client = schedule_client or MLBScheduleClient()
    odds_client = odds_client or MLBOddsClient()
    prediction_logger = prediction_logger or MLBPredictionLogger()
    model = model or MLBRunModel()

    print("MLB MONEYLINE SCANNER")
    print(f"Date: {game_date}   Mode: PAPER ONLY (real-money execution disabled)")

    # 1-2. Free schedule + probable pitchers.
    schedule_games = schedule_client.fetch_schedule(game_date)
    if team_filter:
        needle = team_filter.lower()
        schedule_games = [
            g for g in schedule_games
            if needle in g["home_team"].lower() or needle in g["away_team"].lower()
        ]
    if not schedule_games:
        print("No games found for this date/filter.")
        return []
    if schedule_client.last_pitcher_changes:
        print(f"Probable pitcher changes detected: {len(schedule_client.last_pitcher_changes)}")

    # 3. Cached-or-daily paid odds (manual refresh modes only).
    odds_games = odds_client.fetch_moneyline(
        force_refresh=force_refresh_odds,
        selected_event_ids=selected_event_ids,
    )
    if selected_event_ids is not None:
        # Selected refresh returns only the refreshed events; merge with cache.
        odds_games = odds_client.fetch_moneyline()
    joined = join_odds_to_schedule(schedule_games, odds_games)

    logged: list[dict] = []
    for game in schedule_games:
        analysis = analyze_game(
            game, joined.get(game["event_id"]), model, game_date,
            starter_source=starter_source, offense_source=offense_source,
        )
        print_game_report(analysis, verbose)
        record = build_log_record(analysis)
        record["prediction_id"] = prediction_logger.log_prediction(record)
        logged.append(record)

    print(f"\nLogged {len(logged)} prediction(s) to {prediction_logger.predictions_file}")
    quota = odds_client.last_quota
    if quota.get("credits_remaining") is not None:
        print(
            f"Odds API quota: used={quota.get('credits_used')} "
            f"remaining={quota.get('credits_remaining')}"
        )
    return logged


def main() -> None:
    parser = argparse.ArgumentParser(description="MLB moneyline paper scanner")
    parser.add_argument("--date", default=str(date_cls.today()), help="YYYY-MM-DD")
    parser.add_argument("--team", help="Filter games by team substring")
    parser.add_argument(
        "--force-refresh-odds", action="store_true",
        help="Manually spend an extra paid odds credit today",
    )
    parser.add_argument(
        "--selected-event-id", action="append", default=None,
        help="Manually refresh odds for one Odds-API event id (repeatable)",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--paper-only", action="store_true", default=True,
        help="Always on — real-money execution does not exist in this scanner",
    )
    args = parser.parse_args()

    # Paper mode is structural, not optional: there is no execution path,
    # and the flag exists only so operators can state intent explicitly.
    assert args.paper_only is True

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    scan(
        game_date=args.date,
        team_filter=args.team,
        force_refresh_odds=args.force_refresh_odds,
        selected_event_ids=args.selected_event_id,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
