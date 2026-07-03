"""Paired validation for WC route-offset shadow predictions.

Input rows may be JSON or JSONL. Each row must contain baseline and route
probabilities for the same fixture plus either actual_goals or actual labels.
The command reports paired Brier/log-loss deltas and promotion gate status.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, Mapping

OUTCOMES = ("home_win", "draw", "away_win")
BINARIES = ("over_2_5", "btts_yes")


def _clip(probability: float) -> float:
    return max(1e-9, min(1.0 - 1e-9, probability))


def _brier(probs: Mapping[str, float], actual: str) -> float:
    return sum((float(probs.get(label, 0.0)) - (1.0 if label == actual else 0.0)) ** 2 for label in OUTCOMES)


def _log_loss(probs: Mapping[str, float], actual: str) -> float:
    return -math.log(_clip(float(probs.get(actual, 0.0))))


def _binary_brier(probability: float, actual: int) -> float:
    return (float(probability) - float(actual)) ** 2


def _binary_log_loss(probability: float, actual: int) -> float:
    p = _clip(float(probability))
    return -(actual * math.log(p) + (1 - actual) * math.log(1.0 - p))


def load_rows(path: str | Path) -> list[dict]:
    p = Path(path)
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            rows = data.get("rows", data) if isinstance(data, dict) else data
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, Mapping)]
            if isinstance(rows, Mapping):
                return [dict(rows)]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _actual_outcome(row: Mapping[str, object]) -> str:
    label = row.get("actual_outcome")
    if label in OUTCOMES:
        return str(label)
    home_goals = int(row.get("home_goals", 0))
    away_goals = int(row.get("away_goals", 0))
    if home_goals > away_goals:
        return "home_win"
    if home_goals < away_goals:
        return "away_win"
    return "draw"


def _actual_binary(row: Mapping[str, object], market: str) -> int:
    label = row.get(f"actual_{market}")
    if label is not None:
        return int(bool(label))
    home_goals = int(row.get("home_goals", 0))
    away_goals = int(row.get("away_goals", 0))
    if market == "over_2_5":
        return int(home_goals + away_goals >= 3)
    if market == "btts_yes":
        return int(home_goals > 0 and away_goals > 0)
    raise ValueError(f"Unknown binary market: {market}")


def validate_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    min_rows: int = 30,
    max_brier_regression: float = 0.0,
    max_logloss_regression: float = 0.0,
) -> dict[str, object]:
    scored = []
    for row in rows:
        baseline = row.get("baseline_probabilities", {})
        route = row.get("route_probabilities", row.get("shadow_probabilities", {}))
        if not isinstance(baseline, Mapping) or not isinstance(route, Mapping):
            continue
        if any(label not in baseline or label not in route for label in OUTCOMES):
            continue
        actual = _actual_outcome(row)
        item = {
            "event_id": row.get("event_id"),
            "actual_outcome": actual,
            "baseline_brier": _brier(baseline, actual),
            "route_brier": _brier(route, actual),
            "baseline_logloss": _log_loss(baseline, actual),
            "route_logloss": _log_loss(route, actual),
        }
        for market in BINARIES:
            if market in baseline and market in route:
                actual_binary = _actual_binary(row, market)
                item[f"baseline_{market}_brier"] = _binary_brier(float(baseline[market]), actual_binary)
                item[f"route_{market}_brier"] = _binary_brier(float(route[market]), actual_binary)
                item[f"baseline_{market}_logloss"] = _binary_log_loss(float(baseline[market]), actual_binary)
                item[f"route_{market}_logloss"] = _binary_log_loss(float(route[market]), actual_binary)
        scored.append(item)

    summary = _summarize(scored)
    gates = {
        "min_rows": len(scored) >= min_rows,
        "brier_no_regression": summary["route_brier"] <= summary["baseline_brier"] + max_brier_regression,
        "logloss_no_regression": summary["route_logloss"] <= summary["baseline_logloss"] + max_logloss_regression,
        "over_2_5_no_brier_regression": _binary_gate(summary, "over_2_5", max_brier_regression),
        "btts_yes_no_brier_regression": _binary_gate(summary, "btts_yes", max_brier_regression),
    }
    return {
        "status": "passed" if all(gates.values()) else "blocked",
        "promotion_passed": all(gates.values()),
        "n": len(scored),
        "min_rows": min_rows,
        "metrics": summary,
        "gates": gates,
        "rows": scored,
    }


def _summarize(rows: list[dict[str, object]]) -> dict[str, float]:
    keys = {
        "baseline_brier",
        "route_brier",
        "baseline_logloss",
        "route_logloss",
        "baseline_over_2_5_brier",
        "route_over_2_5_brier",
        "baseline_btts_yes_brier",
        "route_btts_yes_brier",
        "baseline_over_2_5_logloss",
        "route_over_2_5_logloss",
        "baseline_btts_yes_logloss",
        "route_btts_yes_logloss",
    }
    result = {}
    for key in keys:
        values = [float(row[key]) for row in rows if key in row]
        result[key] = sum(values) / len(values) if values else float("inf")
    result["delta_brier"] = result["route_brier"] - result["baseline_brier"]
    result["delta_logloss"] = result["route_logloss"] - result["baseline_logloss"]
    return result


def _binary_gate(summary: Mapping[str, float], market: str, tolerance: float) -> bool:
    baseline = summary.get(f"baseline_{market}_brier", float("inf"))
    route = summary.get(f"route_{market}_brier", float("inf"))
    if not math.isfinite(baseline) or not math.isfinite(route):
        return True
    return route <= baseline + tolerance


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate WC route-offset shadow predictions.")
    parser.add_argument("--predictions", required=True, help="JSON/JSONL paired prediction rows")
    parser.add_argument("--out", default=None, help="Optional JSON report path")
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--max-brier-regression", type=float, default=0.0)
    parser.add_argument("--max-logloss-regression", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = validate_rows(
        load_rows(args.predictions),
        min_rows=args.min_rows,
        max_brier_regression=args.max_brier_regression,
        max_logloss_regression=args.max_logloss_regression,
    )
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("WC route-offset paired validation")
    print(f"  status={report['status']} promotion_passed={str(report['promotion_passed']).lower()} n={report['n']}")
    metrics = report["metrics"]
    print(f"  Brier:   baseline={metrics['baseline_brier']:.4f} route={metrics['route_brier']:.4f} delta={metrics['delta_brier']:+.4f}")
    print(f"  LogLoss: baseline={metrics['baseline_logloss']:.4f} route={metrics['route_logloss']:.4f} delta={metrics['delta_logloss']:+.4f}")
    print("  Gates:")
    for gate, passed in report["gates"].items():
        print(f"    {gate}={'PASS' if passed else 'BLOCK'}")


if __name__ == "__main__":
    main()
