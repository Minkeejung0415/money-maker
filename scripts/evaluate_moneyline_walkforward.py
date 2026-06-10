"""
Walk-forward evaluation for the NBA moneyline model.  PAPER ONLY.

Grades SETTLED moneyline paper bets from the paper-betting log in time
order: probability metrics (Brier, log loss, reliability) for the model's
final calibrated probabilities AND for the market consensus benchmark —
the model only matters if it beats the benchmark out of sample — plus
betting metrics (ROI, CLV, drawdown) grouped by bookmaker / confidence /
odds bucket / month / model version.

A full retrain-per-fold walk-forward for the moneyline XGBoost model
requires a historical odds + results dataset, which this repository does
not yet contain; collect it via the paper log (closing odds at settle
time) and re-run this script as the sample grows.

Ablation: --list-ablations prints the NBAModel constructor configs for
base / base+component runs (see evaluation.moneyline_ablation_configs).

Usage:
    python scripts/evaluate_moneyline_walkforward.py [--paper-log PATH]
    python scripts/evaluate_moneyline_walkforward.py --list-ablations
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.engines.sports.evaluation import (
    betting_metrics,
    grouped_betting_report,
    moneyline_ablation_configs,
    probability_metrics,
)
from alpha.engines.sports.paper_betting_logger import PaperBettingLogger

REPORT_DIR = Path("reports")
DEFAULT_LOG = Path("data/paper_bets/paper_bets.jsonl")

MONEYLINE_MARKETS = {"h2h", "moneyline"}


def run_report(paper_log: Path) -> dict:
    logger = PaperBettingLogger(paper_log)
    bets = [b for b in logger.settled() if b.get("market") in MONEYLINE_MARKETS]
    if not bets:
        print("No settled moneyline paper bets found.")
        return {"num_bets": 0}

    report: dict = {"overall": betting_metrics(bets)}

    decided = [b for b in bets if b["result"] in ("win", "loss")]
    if decided:
        outcomes = [1 if b["result"] == "win" else 0 for b in decided]
        model_probs = [float(b["final_calibrated_prob"]) for b in decided]
        report["probability_model"] = probability_metrics(outcomes, model_probs)

        # Benchmark comparison: the consensus no-vig probability of the
        # SAME side.  The model must beat this to claim any skill.
        bench = [b for b in decided if b.get("consensus_no_vig_prob") is not None]
        if bench:
            outcomes_b = [1 if b["result"] == "win" else 0 for b in bench]
            probs_b = [float(b["consensus_no_vig_prob"]) for b in bench]
            report["probability_market_benchmark"] = probability_metrics(outcomes_b, probs_b)

    report["grouped"] = grouped_betting_report(
        bets, dimensions=["bookmaker", "confidence_bucket", "odds_bucket",
                          "month", "model_version"],
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--list-ablations", action="store_true")
    args = parser.parse_args()

    if args.list_ablations:
        print(json.dumps(moneyline_ablation_configs(), indent=2))
        raise SystemExit(0)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = run_report(args.paper_log)
    out = REPORT_DIR / "moneyline_walkforward.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report written to {out}")
