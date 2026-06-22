from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math

import pytest

from alpha.engines.sports.wc_tactical_calibration import (
    BootstrapDelta,
    expanding_folds,
    evaluate_candidate,
    fit_goals,
    fit_outcome,
    holm_rejections,
    paired_bootstrap_delta,
    promotion_gate,
)
from tests.unit.data.test_wc_tactical_history import _row


def _rows(count: int = 80):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        row = _row(str(index), start + timedelta(days=index))
        edge = 0.8 if index % 2 == 0 else -0.8
        components = dict(row.home_components)
        away = dict(row.away_components)
        components["chance creation"] = edge
        away["chance creation"] = -edge
        rows.append(replace(
            row,
            home_goals=2 if edge > 0 else 0,
            away_goals=0 if edge > 0 else 2,
            home_components=components,
            away_components=away,
        ))
    return rows


def test_outcome_model_recovers_signal_and_preserves_probability_sum():
    rows = _rows()
    model = fit_outcome(rows, regularization=1.0)
    positive = model.probabilities(rows[0])
    negative = model.probabilities(rows[1])
    assert positive[0] > negative[0]
    assert sum(positive) == pytest.approx(1.0)


def test_regularization_shrinks_noise_and_goal_adjustments_are_capped():
    rows = _rows()
    weak = fit_outcome(rows, regularization=1000.0)
    strong = fit_outcome(rows, regularization=0.01)
    assert sum(abs(value) for value in weak.weights) < sum(abs(value) for value in strong.weights)
    goal_model = fit_goals(rows, regularization=1.0)
    home, away = goal_model.rates(rows[0])
    assert 0.9 <= home / rows[0].baseline_home_lambda <= 1.1
    assert 0.9 <= away / rows[0].baseline_away_lambda <= 1.1


def test_expanding_folds_are_strictly_chronological():
    rows = list(reversed(_rows(30)))
    for train, validation in expanding_folds(rows):
        assert max(rows[index].kickoff for index in train) < min(rows[index].kickoff for index in validation)


def test_paired_bootstrap_is_deterministic_and_holm_corrects():
    first = paired_bootstrap_delta([0.1] * 30, [0.2] * 30, repetitions=1000)
    second = paired_bootstrap_delta([0.1] * 30, [0.2] * 30, repetitions=1000)
    assert first == second
    assert first.upper < 0
    assert holm_rejections([0.001, 0.02, 0.2]) == (True, True, False)


def test_promotion_gate_requires_material_and_significant_improvement():
    good = BootstrapDelta(-0.01, -0.02, -0.003, 0.001)
    gate = promotion_gate("1x2", [("baseline", good), ("recalibrated", good)])
    assert gate.passed
    tiny = BootstrapDelta(-0.001, -0.002, -0.0001, 0.001)
    assert not promotion_gate("1x2", [("baseline", tiny), ("recalibrated", tiny)]).passed


def test_evaluation_blocks_undersized_audit_without_retuning():
    rows = _rows(80)
    outcome = fit_outcome(rows, 1.0)
    goals = fit_goals(rows, 1.0)
    result = evaluate_candidate(outcome, goals, rows[:50], rows[50:79], repetitions=100)
    assert result["status"] == "blocked"


def test_evaluation_returns_independent_market_gates():
    rows = _rows(100)
    outcome = fit_outcome(rows[:70], 1.0)
    goals = fit_goals(rows[:70], 1.0)
    result = evaluate_candidate(outcome, goals, rows[:50], rows[70:100], repetitions=200)
    assert result["status"] == "evaluated"
    assert set(result["gates"]) == {"1x2", "totals", "btts"}
