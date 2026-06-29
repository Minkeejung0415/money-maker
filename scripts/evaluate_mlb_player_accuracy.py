"""Evaluate MLB player-aware reports and write promotion metadata."""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from alpha.engines.sports.mlb_player_modeling import (  # noqa: E402
    build_model_artifact_metadata,
    select_promoted_result,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate MLB player-aware walk-forward report.")
    parser.add_argument("--report", required=True, help="JSON report from walk-forward ablations")
    parser.add_argument("--output", default="data/mlb/model_metadata/mlb_player_candidate.meta.json")
    parser.add_argument("--allow-unpromoted", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = json.loads(_repo_path(args.report).read_text(encoding="utf-8"))
    promoted = select_promoted_result(report)
    if promoted is None and not args.allow_unpromoted:
        raise SystemExit("No candidate beat the baseline promotion gate.")
    candidate = promoted or _best_nonbaseline(report)
    metadata = build_model_artifact_metadata(candidate, report)
    metadata.update({
        "model_id": "mlb_player_v2_3_candidate",
        "league": "MLB",
        "market": "moneyline",
        "promotion_passed": bool(metadata.get("validated")),
        "allowed_runtime": bool(metadata.get("validated")),
    })
    output = _repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote MLB player model metadata: {output}")
    print(f"promotion_passed={metadata['promotion_passed']}")


def _best_nonbaseline(report: dict) -> dict:
    candidates = [a for a in report.get("ablations", []) if not a.get("is_baseline")]
    if not candidates:
        raise SystemExit("Report has no non-baseline candidates.")
    return min(candidates, key=lambda item: float(item["mean_metrics"]["brier_score"]))


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    main()
