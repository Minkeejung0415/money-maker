"""Unit tests for PropModel."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_log_rows(pts_values: list[float], min_val: float = 30.0) -> list[dict]:
    """Build a list of fake game-log dicts."""
    return [
        {"PTS": v, "REB": 5.0, "AST": 5.0, "FG3M": 2.0, "MIN": str(int(min_val)), "MIN_float": min_val}
        for v in pts_values
    ]


@pytest.fixture
def model():
    from alpha.engines.sports.prop_model import PropModel
    return PropModel(season="2024-25")


def _patch_logs(log_rows: list[dict]):
    """Patch _fetch_game_logs to return the given rows."""
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_game_logs",
        return_value=log_rows,
    )


def _patch_def_ratings(ratings: dict | None = None):
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_def_ratings",
        return_value=ratings or {},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_high_avg_beats_low_line(model):
    """30-point average player against a 25-point line → model_prob > 0.70."""
    rows = _make_log_rows([30.0] * 20)
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics")
    assert result is not None
    assert result["model_prob"] > 0.70


def test_low_avg_misses_high_line(model):
    """20-point average player against a 25-point line → model_prob < 0.30."""
    rows = _make_log_rows([20.0] * 20)
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics")
    assert result is not None
    assert result["model_prob"] < 0.30


def test_returns_none_on_empty_logs(model):
    """Empty game log → None returned."""
    with _patch_logs([]):
        result = model.predict_prop("Ghost Player", "player_points", 20.0, "Boston Celtics")
    assert result is None


def test_filters_low_minute_games(model):
    """Games with < 20 minutes are excluded; only high-minute games count."""
    # 3 low-minute games that would be filtered out, 5 legit 35-point games
    low_min_rows = _make_log_rows([50.0] * 3, min_val=15.0)   # should be excluded
    high_min_rows = _make_log_rows([35.0] * 15, min_val=35.0)  # should count
    rows = low_min_rows + high_min_rows
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 30.0, "Boston Celtics")
    assert result is not None
    # proj_stat should reflect the high-minute rows (~35), not the inflated 50-pt rows
    assert result["proj_stat"] < 45.0


def test_weighted_avg_favors_recent(model):
    """Last 5 games averaging 35 pts should pull projection above simple 20-game avg."""
    # last 5 = 35 pts, next 15 = 15 pts → simple avg ≈ 20; weighted should be > 20
    recent = _make_log_rows([35.0] * 5)
    older  = _make_log_rows([15.0] * 15)
    rows = recent + older
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 20.0, "Boston Celtics")
    assert result is not None
    # proj_stat = 0.5*35 + 0.3*avg(first10) + 0.2*avg(first20)
    # avg(first10) = (5*35 + 5*15)/10 = 25
    # avg(first20) = (5*35 + 15*15)/20 = 20
    # weighted = (0.5*35 + 0.3*25 + 0.2*20) / 1.0 = 17.5+7.5+4.0 = 29.0
    assert result["proj_stat"] > 20.0


def test_market_col_mapping(model):
    assert model._market_col("player_points")   == "PTS"
    assert model._market_col("player_rebounds") == "REB"
    assert model._market_col("player_assists")  == "AST"
    assert model._market_col("player_threes")   is None
    assert model._market_col("player_steals")   is None


def test_confidence_high_when_large_gap(model):
    """Model ~84%, market 52% → gap=32% → HIGH confidence."""
    rows = _make_log_rows([26.0] * 20)
    with _patch_logs(rows), _patch_def_ratings():
        # over_odds=-110 → market_implied ≈ 52.4%
        # With avg=26 and line=25 and std≈1.0, p_over ≈ 0.84 → gap large
        # (line=25 avoids CONF-02 low-line skepticism gate)
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics",
                                    over_odds=-110)
    assert result is not None
    assert result["confidence"] == "HIGH"


def test_confidence_low_when_small_gap(model):
    """Model ≈ market probability → LOW confidence."""
    # Use line right at mean so model_prob ≈ 0.50, same as -110 market_implied (~0.524)
    # gap = |0.50 - 0.524| ≈ 0.024 < 0.04 → LOW
    rows = _make_log_rows([25.0] * 20)
    with _patch_logs(rows), _patch_def_ratings():
        # line = 25 = proj_stat → p_over ≈ 0.50
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics",
                                    over_odds=-110)
    assert result is not None
    assert result["confidence"] == "LOW"
