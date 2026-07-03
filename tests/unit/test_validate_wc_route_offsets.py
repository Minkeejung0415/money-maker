"""Tests for scripts/validate_wc_route_offsets.py."""
from __future__ import annotations

import json

from scripts.validate_wc_route_offsets import load_rows, validate_rows


def _row(event_id: str, actual: str = "home_win") -> dict:
    return {
        "event_id": event_id,
        "actual_outcome": actual,
        "home_goals": 2,
        "away_goals": 1,
        "baseline_probabilities": {
            "home_win": 0.52,
            "draw": 0.25,
            "away_win": 0.23,
            "over_2_5": 0.51,
            "btts_yes": 0.50,
        },
        "route_probabilities": {
            "home_win": 0.60,
            "draw": 0.22,
            "away_win": 0.18,
            "over_2_5": 0.58,
            "btts_yes": 0.56,
        },
    }


def test_validate_rows_passes_when_route_improves_on_same_fixtures():
    report = validate_rows([_row("1"), _row("2")], min_rows=2)

    assert report["status"] == "passed"
    assert report["promotion_passed"] is True
    assert report["metrics"]["delta_brier"] < 0
    assert report["gates"]["min_rows"] is True


def test_validate_rows_blocks_when_sample_too_small():
    report = validate_rows([_row("1")], min_rows=2)

    assert report["status"] == "blocked"
    assert report["promotion_passed"] is False
    assert report["gates"]["min_rows"] is False


def test_validate_rows_blocks_brier_regression():
    bad = _row("1")
    bad["route_probabilities"] = {
        "home_win": 0.20,
        "draw": 0.30,
        "away_win": 0.50,
        "over_2_5": 0.20,
        "btts_yes": 0.20,
    }

    report = validate_rows([bad, _row("2")], min_rows=2)

    assert report["status"] == "blocked"
    assert report["gates"]["brier_no_regression"] is False


def test_load_rows_accepts_jsonl(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(_row("1")) + "\n" + json.dumps(_row("2")) + "\n", encoding="utf-8")

    rows = load_rows(path)

    assert [row["event_id"] for row in rows] == ["1", "2"]
