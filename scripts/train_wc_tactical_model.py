"""Train and evaluate regularized World Cup tactical residual candidates."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.data.ingestion.wc_tactical_history import load_rows
from alpha.engines.sports.wc_tactical_calibration import (
    evaluate_candidate,
    fit_goals,
    fit_outcome,
    goal_nll,
    outcome_log_loss,
    select_regularization,
)


def train(dataset_dir: Path) -> dict:
    development = load_rows(dataset_dir / "development.jsonl")
    validation = load_rows(dataset_dir / "validation.jsonl")
    audit = load_rows(dataset_dir / "external_audit.jsonl")
    if len(development) < 200 or len(validation) < 50:
        return {"status": "blocked", "reason": "dataset does not satisfy 200/50 development gates"}
    outcome_l2 = select_regularization(development, fit_outcome, outcome_log_loss)
    goal_l2 = select_regularization(development, fit_goals, goal_nll)
    fit_rows = [*development, *validation]
    outcome = fit_outcome(fit_rows, outcome_l2)
    goals = fit_goals(fit_rows, goal_l2)
    evaluation = evaluate_candidate(outcome, goals, validation, audit) if len(audit) >= 30 else {
        "status": "blocked", "reason": "external audit requires at least 30 rows"
    }
    return {
        "status": "candidate",
        "outcome": asdict(outcome),
        "goals": asdict(goals),
        "development_rows": len(development),
        "validation_rows": len(validation),
        "evaluation": evaluation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = train(args.dataset)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
