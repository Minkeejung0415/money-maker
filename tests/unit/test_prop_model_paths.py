"""Stage 4 tests: PropModel XGBoost path vs rule-based fallback path."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _dated_rows(pts: float = 25.0, minutes: float = 32.0, n: int = 12) -> list[dict]:
    """nba_api-style rows with real GAME_DATEs (newest first, 2 days apart)."""
    return [
        {
            "PTS": pts, "REB": 6.0, "AST": 4.0, "FG3M": 2.0,
            "MIN": str(int(minutes)), "MIN_float": minutes,
            "GAME_DATE": f"2025-01-{28 - 2 * i:02d}T00:00:00",
        }
        for i in range(n)
    ]


class _StubXGB:
    """Stands in for a trained XGBoostPropModel returning a fixed projection."""
    def __init__(self, projection: float):
        self.projection = projection
        self.seen_features: dict | None = None

    def predict(self, features: dict) -> float:
        self.seen_features = dict(features)
        return self.projection


@pytest.fixture
def model():
    from alpha.engines.sports.prop_model import PropModel
    with patch("alpha.engines.sports.xgb_prop_model.XGBoostPropModel.load",
               side_effect=Exception("no models on disk")):
        m = PropModel(season="2024-25")
    m._xgb_models = {}
    return m


def _patch_logs(rows):
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_game_logs",
        return_value=rows,
    )


def _patch_team_stats(stats: dict | None = None):
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_team_per_game_stats",
        return_value=stats or {},
    )


def _freeze_today(monkeypatch):
    """Pin date.today() inside prop_model/prop_features to 2025-01-30."""
    from datetime import date as real_date

    class _FixedDate(real_date):
        @classmethod
        def today(cls):
            return real_date(2025, 1, 30)

    monkeypatch.setattr("alpha.engines.sports.prop_model.date", _FixedDate)
    return _FixedDate


def test_xgb_projection_not_double_adjusted(model, monkeypatch):
    """
    When XGBoost serves the projection, minutes/rest/pace/opponent multipliers
    must NOT be applied again — proj_stat equals the raw model output.
    """
    _freeze_today(monkeypatch)
    stub = _StubXGB(projection=24.0)
    model._xgb_models = {"player_points": stub}

    # Recent minutes spike + opponent stats present: the OLD code would have
    # multiplied by minutes ratio / rest / opponent def-rtg on top of XGBoost.
    rows = _dated_rows(pts=25.0, minutes=38.0, n=5) + _dated_rows(pts=25.0, minutes=28.0, n=7)
    team_stats = {"Boston Celtics": {"def_rtg": 105.0, "pace": 104.0}}

    with _patch_logs(rows), _patch_team_stats(team_stats):
        result = model.predict_prop(
            "Test Player", "player_points", 22.5, "Boston Celtics", is_home=True,
        )

    assert result is not None
    assert result["projection_source"] == "xgb"
    assert result["proj_stat"] == 24.0  # exactly the stub output — no multipliers
    # Opponent context was passed INTO the model instead of applied after.
    assert stub.seen_features["opp_def_rtg"] == 105.0
    assert stub.seen_features["opp_pace"] == 104.0
    assert stub.seen_features["is_home"] == 1.0
    assert result["missing_features"] == []


def test_xgb_path_requires_explicit_is_home(model, monkeypatch):
    """No explicit is_home → XGBoost path skipped, rule-based fallback used."""
    _freeze_today(monkeypatch)
    stub = _StubXGB(projection=24.0)
    model._xgb_models = {"player_points": stub}

    with _patch_logs(_dated_rows()), _patch_team_stats():
        result = model.predict_prop("Test Player", "player_points", 22.5, "Boston Celtics")

    assert result is not None
    assert result["projection_source"] == "weighted_avg"
    assert stub.seen_features is None  # model never invoked


def test_undated_logs_fall_back_to_rule_path(model):
    """Logs without GAME_DATE can't build pregame features → rule fallback."""
    rows = [
        {"PTS": 25.0, "REB": 6.0, "AST": 4.0, "MIN_float": 32.0}
        for _ in range(12)
    ]
    model._xgb_models = {"player_points": _StubXGB(projection=24.0)}
    with _patch_logs(rows), _patch_team_stats():
        result = model.predict_prop(
            "Test Player", "player_points", 22.5, "Boston Celtics", is_home=True,
        )
    assert result is not None
    assert result["projection_source"] == "weighted_avg"


def test_schema_error_fails_closed_to_rule_path(model, monkeypatch):
    """A model raising PropSchemaError must not crash — explicit fallback."""
    from alpha.engines.sports.xgb_prop_model import PropSchemaError
    _freeze_today(monkeypatch)

    class _BrokenXGB:
        def predict(self, features):
            raise PropSchemaError("missing required feature: projected_minutes")

    model._xgb_models = {"player_points": _BrokenXGB()}
    with _patch_logs(_dated_rows()), _patch_team_stats():
        result = model.predict_prop(
            "Test Player", "player_points", 22.5, "Boston Celtics", is_home=True,
        )
    assert result is not None
    assert result["projection_source"] == "weighted_avg"


def test_rule_path_unchanged_without_xgb(model):
    """No XGBoost models → legacy weighted-average behavior is preserved."""
    rows = _dated_rows(pts=30.0)
    with _patch_logs(rows), _patch_team_stats():
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics")
    assert result is not None
    assert result["projection_source"] == "weighted_avg"
    assert result["model_prob"] > 0.5
    assert result["model_version"] == "rule_based_v1"
    assert result["feature_schema_version"]


def test_player_threes_scored_via_rule_path(model):
    """player_threes maps to FG3M and produces a probability."""
    rows = _dated_rows()  # FG3M=2.0 every game
    with _patch_logs(rows), _patch_team_stats():
        result = model.predict_prop("Test Player", "player_threes", 1.5, "Boston Celtics")
    assert result is not None
    assert result["model_prob"] > 0.4


def test_missing_opponent_context_logged_not_constant(model, monkeypatch):
    """Unknown opponent → NaN features tracked in missing_features."""
    _freeze_today(monkeypatch)
    stub = _StubXGB(projection=20.0)
    model._xgb_models = {"player_points": stub}
    with _patch_logs(_dated_rows()), _patch_team_stats({}):
        result = model.predict_prop(
            "Test Player", "player_points", 22.5, "Unknown Team", is_home=False,
        )
    assert result["projection_source"] == "xgb"
    assert set(result["missing_features"]) == {"opp_def_rtg", "opp_pace"}
    import math
    assert math.isnan(stub.seen_features["opp_def_rtg"])
