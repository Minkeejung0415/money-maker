"""
Grade logged MLB moneyline predictions from FREE MLB StatsAPI finals.

Reads data/mlb_predictions/predictions.jsonl, finds ungraded records,
fetches final scores from the StatsAPI schedule endpoint (zero paid
credits), and appends idempotent settlements.  Prediction snapshots are
never rewritten.

Usage:
  python scripts/grade_mlb_predictions.py                 # grade all ungraded
  python scripts/grade_mlb_predictions.py --date 2026-06-11
  python scripts/grade_mlb_predictions.py --list-ungraded
  python scripts/grade_mlb_predictions.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.engines.sports.mlb_prediction_logger import (  # noqa: E402
    DEFAULT_LOG_DIR,
    MLBPredictionLogger,
)
from alpha.engines.sports.mlb_run_model import (  # noqa: E402
    MIN_CALIBRATION_SAMPLES,
    can_fit_calibrator,
)

logger = logging.getLogger("grade_mlb_predictions")

_STATSAPI_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"


def fetch_final_scores(game_date: str, session: requests.Session | None = None) -> dict[int, dict]:
    """
    FREE StatsAPI call: {statsapi_game_id: {home_score, away_score, final}}.
    Only games whose status is Final are returned.
    """
    session = session or requests.Session()
    try:
        resp = session.get(
            _STATSAPI_SCHEDULE_URL,
            params={"sportId": 1, "date": game_date},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("StatsAPI finals fetch failed for %s: %s", game_date, exc)
        return {}

    finals: dict[int, dict] = {}
    for block in data.get("dates", []):
        for game in block.get("games", []):
            status = (game.get("status") or {}).get("abstractGameState", "")
            if status != "Final":
                continue
            game_pk = game.get("gamePk")
            teams = game.get("teams", {})
            home_score = (teams.get("home") or {}).get("score")
            away_score = (teams.get("away") or {}).get("score")
            if game_pk is None or home_score is None or away_score is None:
                continue
            finals[int(game_pk)] = {
                "home_score": int(home_score),
                "away_score": int(away_score),
            }
    return finals


def grade(log_dir: Path, date_filter: str | None, dry_run: bool) -> None:
    plog = MLBPredictionLogger(log_dir)
    ungraded = plog.ungraded()
    if date_filter:
        ungraded = [r for r in ungraded if str(r.get("game_date", "")) == date_filter]
    if not ungraded:
        print("No ungraded predictions to settle.")
        _calibration_status(plog)
        return

    finals_by_date: dict[str, dict[int, dict]] = {}
    settled = skipped = 0
    for rec in ungraded:
        game_date = str(rec.get("game_date", ""))
        game_id = rec.get("statsapi_game_id")
        if not game_date or game_id is None:
            skipped += 1
            continue
        if game_date not in finals_by_date:
            finals_by_date[game_date] = fetch_final_scores(game_date)
        final = finals_by_date[game_date].get(int(game_id))
        if final is None:
            skipped += 1  # game not final yet — stays visible as ungraded
            continue
        winner = "home" if final["home_score"] > final["away_score"] else "away"
        if dry_run:
            print(
                f"[dry-run] would settle {rec['prediction_id'][:8]} "
                f"{rec.get('away_team')} @ {rec.get('home_team')}: "
                f"{final['away_score']}-{final['home_score']} ({winner})"
            )
            continue
        if plog.settle(rec["prediction_id"], winner,
                       final["home_score"], final["away_score"]):
            settled += 1

    print(f"Settled {settled} prediction(s); {skipped} still pending/unmatchable.")
    _calibration_status(plog)


def _calibration_status(plog: MLBPredictionLogger) -> None:
    graded = plog.graded_count()
    allowed = can_fit_calibrator(graded)
    print(
        f"Graded history: {graded} (calibrator fitting "
        f"{'ALLOWED' if allowed else f'blocked — needs {MIN_CALIBRATION_SAMPLES}'})"
    )


def list_ungraded(log_dir: Path) -> None:
    plog = MLBPredictionLogger(log_dir)
    rows = plog.ungraded()
    if not rows:
        print("No ungraded predictions.")
        return
    for rec in rows:
        print(
            f"{rec.get('prediction_id', '')[:8]}  {rec.get('game_date', '?')}  "
            f"{rec.get('away_team', '?')} @ {rec.get('home_team', '?')}  "
            f"decision={rec.get('paper_bet_decision', '?')}"
        )
    print(f"\n{len(rows)} ungraded prediction(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Only grade predictions for YYYY-MM-DD")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-ungraded", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log_dir = Path(args.log_dir)
    if args.list_ungraded:
        list_ungraded(log_dir)
        return
    grade(log_dir, args.date, args.dry_run)


if __name__ == "__main__":
    main()
