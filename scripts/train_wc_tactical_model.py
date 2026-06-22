"""Train and evaluate regularized World Cup tactical residual candidates."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.data.ingestion.wc_tactical_history import TACTICAL_COMPONENTS, load_rows
from alpha.engines.sports.wc_tactical_calibration import (
    evaluate_candidate,
    ARTIFACT_SCHEMA_VERSION,
    MarketGate,
    TacticalCalibrationArtifact,
    dataset_fingerprint,
    fit_goals,
    fit_outcome,
    goal_nll,
    outcome_log_loss,
    select_regularization,
    save_artifact,
)


def train(dataset_dir: Path) -> tuple[dict, TacticalCalibrationArtifact | None]:
    development = load_rows(dataset_dir / "development.jsonl")
    validation = load_rows(dataset_dir / "validation.jsonl")
    audit = load_rows(dataset_dir / "external_audit.jsonl")
    if len(development) < 200 or len(validation) < 50:
        return {"status": "blocked", "reason": "dataset does not satisfy 200/50 development gates"}, None
    outcome_l2 = select_regularization(development, fit_outcome, outcome_log_loss)
    goal_l2 = select_regularization(development, fit_goals, goal_nll)
    fit_rows = [*development, *validation]
    outcome = fit_outcome(fit_rows, outcome_l2)
    goals = fit_goals(fit_rows, goal_l2)
    evaluation = evaluate_candidate(outcome, goals, validation, audit) if len(audit) >= 30 else {
        "status": "blocked", "reason": "external audit requires at least 30 rows"
    }
    result = {
        "status": "candidate",
        "outcome": asdict(outcome),
        "goals": asdict(goals),
        "development_rows": len(development),
        "validation_rows": len(validation),
        "evaluation": evaluation,
    }
    if evaluation.get("status") != "evaluated":
        return result, None
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    gates = {name: MarketGate(**values) for name, values in evaluation["gates"].items()}
    latest = max(row.kickoff for row in [*development, *validation])
    artifact = TacticalCalibrationArtifact(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        feature_order=TACTICAL_COMPONENTS,
        trained_through=latest,
        dataset_fingerprint=dataset_fingerprint(manifest),
        development_rows=len(development), validation_rows=len(validation), audit_rows=len(audit),
        outcome=outcome, goals=goals, gates=gates,
    )
    return result, artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result, artifact = train(args.dataset)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        if artifact is not None:
            save_artifact(artifact, args.output.with_suffix(".artifact.json"))
    print(text, end="")


if __name__ == "__main__":
    main()
