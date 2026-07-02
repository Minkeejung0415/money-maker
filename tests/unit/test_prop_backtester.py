"""Unit tests for PropBacktester."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from alpha.engines.sports.prop_backtester import PropBacktester, _CALIBRATION_BUCKETS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_logs(pts_values: list[float]) -> list[dict]:
    return [{"PTS": v, "REB": 5.0, "AST": 5.0, "FG3M": 2.0} for v in pts_values]


def _patch_logs(log_rows: list[dict] | None):
    return patch(
        "alpha.engines.sports.prop_backtester.PropBacktester._fetch_logs",
        return_value=log_rows,
    )


@pytest.fixture
def bt():
    return PropBacktester(season="2024-25")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_brier_score_perfect_predictions(bt):
    """All predictions = 1.0 and all actual hits = 1 → Brier score = 0.0."""
    preds = [1.0] * 20
    hits = [1] * 20
    assert bt._brier_score(preds, hits) == pytest.approx(0.0, abs=1e-9)


def test_brier_score_random_predictions(bt):
    """All predictions = 0.5 → Brier score = 0.25 regardless of outcomes."""
    preds = [0.5] * 40
    hits = [1, 0] * 20
    assert bt._brier_score(preds, hits) == pytest.approx(0.25, abs=1e-9)


def test_calibration_buckets_correct_keys(bt):
    """Result dict must have the expected decile bucket keys."""
    preds = [0.15, 0.35, 0.55, 0.75, 0.95]
    hits  = [0, 1, 1, 1, 0]
    table = bt._calibration_table(preds, hits)
    expected_keys = [f"{lo:.2f}-{hi:.2f}" for lo, hi in _CALIBRATION_BUCKETS]
    for key in expected_keys:
        assert key in table, f"Missing bucket key: {key}"


def test_recommendation_reliable_when_low_brier(bt):
    """brier=0.18, hc_hit_rate=0.65 → RELIABLE."""
    assert bt._recommend(0.18, 0.65) == "RELIABLE"


def test_recommendation_unreliable_when_high_brier(bt):
    """brier=0.28 → UNRELIABLE regardless of hc hit rate."""
    assert bt._recommend(0.28, 0.70) == "UNRELIABLE"


def test_skips_players_with_insufficient_data(bt):
    """Players with < 25 game logs are excluded from results."""
    # Only 10 games → should be skipped
    short_logs = _make_logs([20.0] * 10)
    with _patch_logs(short_logs):
        results = bt.backtest(["LeBron James"], ["player_points"])
    assert results == []


def test_backtest_returns_results_with_sufficient_data(bt):
    """Players with ≥ 25 game logs should produce a result entry."""
    # 40 games → enough for backtest
    logs = _make_logs([25.0, 30.0, 20.0, 35.0, 22.0] * 8)
    with _patch_logs(logs):
        results = bt.backtest(["LeBron James"], ["player_points"])
    assert len(results) == 1
    r = results[0]
    assert r["player"] == "LeBron James"
    assert r["market"] == "player_points"
    assert "brier_score" in r
    assert "recommendation" in r
    assert r["recommendation"] in {"RELIABLE", "MARGINAL", "UNRELIABLE"}


def test_recommendation_marginal_boundary(bt):
    """brier=0.23 (< 0.25 but >= 0.22) with low hc hit rate → MARGINAL."""
    assert bt._recommend(0.23, 0.50) == "MARGINAL"


def test_predictions_are_not_constant_half(bt):
    """Regression: pred_prob once used loc == the synthetic line, so every
    prediction was exactly 0.50 and the validation was inert.  With a real
    decay-weighted projection, varying game logs must produce varying
    probabilities."""
    # Strong upward recent trend (logs are newest-first): recent games well
    # above the older ones the flat line is computed from.
    trending = [40.0, 38.0, 36.0, 34.0, 32.0] * 4 + [15.0, 14.0, 16.0, 15.0, 14.0] * 4
    logs = _make_logs(trending)
    with _patch_logs(logs):
        results = bt.backtest(["LeBron James"], ["player_points"])
    assert len(results) == 1
    preds = []
    for bucket in results[0]["calibration"].values():
        if bucket["n"] > 0:
            preds.append(bucket["predicted"])
    assert any(abs(p - 0.5) > 0.02 for p in preds), (
        f"all predictions ~0.5 — backtester projection is inert: {preds}"
    )
