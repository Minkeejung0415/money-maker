"""Leakage-safe retrospective comparison of baseline and tactical WC models."""
from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from alpha.data.ingestion.wc_recent_form import WCRecentFormClient
from alpha.data.ingestion.wc_tactics import WCTacticsClient
from alpha.data.ingestion.wc_tactical_history import TacticalHistoryRow, audit_rows
from alpha.engines.sports.wc_goal_markets import WCScorelineModel
from alpha.engines.sports.wc_model import WCMatchModel
from alpha.engines.sports.wc_tactical_matchup import compare_tactics


def _brier(probabilities: list[float], actual: int) -> float:
    return sum((probability - (1.0 if index == actual else 0.0)) ** 2 for index, probability in enumerate(probabilities))


def _log_loss(probabilities: list[float], actual: int) -> float:
    return -math.log(max(1e-12, probabilities[actual]))


def _binary_metrics(probability: float, actual: int) -> tuple[int, float, float]:
    prediction = int(probability >= 0.5)
    return int(prediction == actual), (probability - actual) ** 2, -math.log(max(1e-12, probability if actual else 1.0 - probability))


def _fetch_finished(date_from: str, date_to: str) -> list[dict]:
    response = requests.get(
        "https://api.football-data.org/v4/competitions/WC/matches",
        headers={"X-Auth-Token": os.environ.get("FOOTBALL_API_KEY", "")},
        params={"dateFrom": date_from, "dateTo": date_to},
        timeout=20,
    )
    response.raise_for_status()
    return [match for match in response.json().get("matches", []) if match.get("status") == "FINISHED"]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def coverage_status(rows: list[TacticalHistoryRow], audit_cutoff: datetime) -> dict:
    """Return the canonical fail-closed historical coverage gate."""
    return audit_rows(rows, audit_cutoff=audit_cutoff).to_dict()


def validate(date_from: str, date_to: str) -> dict:
    matches = _fetch_finished(date_from, date_to)
    recent_client = WCRecentFormClient()
    tactics_client = WCTacticsClient()
    model = WCMatchModel()
    scoreline_model = WCScorelineModel()
    rows = []

    for index, match in enumerate(matches, 1):
        home_team = match.get("homeTeam", {}).get("name", "")
        away_team = match.get("awayTeam", {}).get("name", "")
        score = match.get("score", {}).get("fullTime", {})
        home_goals, away_goals = score.get("home"), score.get("away")
        if not home_team or not away_team or home_goals is None or away_goals is None:
            continue
        kickoff = datetime.fromisoformat(str(match["utcDate"]).replace("Z", "+00:00"))
        print(f"[{index}/{len(matches)}] {home_team} vs {away_team}", flush=True)
        try:
            home_form = recent_client.fetch(home_team, kickoff.date())
            away_form = recent_client.fetch(away_team, kickoff.date())
            team_ids = tactics_client.resolve_team_ids(kickoff.date())
            home_tactics = tactics_client.fetch_profile(home_team, team_ids.get(home_team, ""), kickoff)
            away_tactics = tactics_client.fetch_profile(away_team, team_ids.get(away_team, ""), kickoff)
        except Exception as exc:
            print(f"  skipped: {exc}")
            continue
        if None in (home_form, away_form, home_tactics, away_tactics):
            print("  skipped: incomplete pre-match form or tactical sample")
            continue

        game = {
            "home_team": home_team,
            "away_team": away_team,
            "league": "wc",
            "stage": match.get("stage", "GROUP_STAGE"),
            "home_odds": -110,
            "away_odds": -110,
            "recent_team_stats": {home_team: home_form, away_team: away_form},
            "home_elo_override": home_form["elo_rating"],
            "away_elo_override": away_form["elo_rating"],
        }
        baseline_game = model.predict(dict(game))
        baseline_distribution = scoreline_model.build(baseline_game)
        game["tactical_comparison"] = compare_tactics(home_tactics, away_tactics)
        tactical_game = model.predict(game)
        tactical_distribution = scoreline_model.build(tactical_game)

        actual_outcome = 0 if home_goals > away_goals else 2 if home_goals < away_goals else 1
        actual_over = int(home_goals + away_goals >= 3)
        actual_btts = int(home_goals > 0 and away_goals > 0)
        baseline_probs = [baseline_game["win_prob"], baseline_game["draw_prob"], baseline_game["loss_prob"]]
        tactical_probs = [tactical_game["win_prob"], tactical_game["draw_prob"], tactical_game["loss_prob"]]
        rows.append({
            "baseline_outcome_correct": int(max(range(3), key=baseline_probs.__getitem__) == actual_outcome),
            "tactical_outcome_correct": int(max(range(3), key=tactical_probs.__getitem__) == actual_outcome),
            "baseline_outcome_brier": _brier(baseline_probs, actual_outcome),
            "tactical_outcome_brier": _brier(tactical_probs, actual_outcome),
            "baseline_outcome_logloss": _log_loss(baseline_probs, actual_outcome),
            "tactical_outcome_logloss": _log_loss(tactical_probs, actual_outcome),
        })
        for market, actual, baseline_probability, tactical_probability in (
            ("over", actual_over, baseline_distribution.probability("over_2_5"), tactical_distribution.probability("over_2_5")),
            ("btts", actual_btts, baseline_distribution.probability("btts_yes"), tactical_distribution.probability("btts_yes")),
        ):
            for prefix, probability in (("baseline", baseline_probability), ("tactical", tactical_probability)):
                correct, brier, logloss = _binary_metrics(probability, actual)
                rows[-1][f"{prefix}_{market}_correct"] = correct
                rows[-1][f"{prefix}_{market}_brier"] = brier
                rows[-1][f"{prefix}_{market}_logloss"] = logloss

    result = {"available_matches": len(matches), "evaluated_matches": len(rows)}
    for market in ("outcome", "over", "btts"):
        for metric in ("correct", "brier", "logloss"):
            for prefix in ("baseline", "tactical"):
                key = f"{prefix}_{market}_{metric}"
                result[key] = _mean([float(row[key]) for row in rows])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", default="2026-06-11")
    parser.add_argument("--date-to", default="2026-06-21")
    args = parser.parse_args()
    result = validate(args.date_from, args.date_to)
    print("\nWC TACTICAL BACKTEST")
    print(f"Available: {result['available_matches']} | Evaluated: {result['evaluated_matches']}")
    for market, label in (("outcome", "1X2"), ("over", "Over 2.5"), ("btts", "BTTS")):
        print(f"\n{label}")
        print(f"  Accuracy: {result[f'baseline_{market}_correct']:.1%} -> {result[f'tactical_{market}_correct']:.1%}")
        print(f"  Brier:    {result[f'baseline_{market}_brier']:.4f} -> {result[f'tactical_{market}_brier']:.4f}")
        print(f"  Log loss: {result[f'baseline_{market}_logloss']:.4f} -> {result[f'tactical_{market}_logloss']:.4f}")


if __name__ == "__main__":
    main()
