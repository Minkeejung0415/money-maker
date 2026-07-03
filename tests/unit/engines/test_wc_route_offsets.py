"""Tests for World Cup projected-XI route xG offsets."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alpha.engines.sports.wc_route_offsets import (
    SCHEMA_VERSION,
    WCRouteOffsetEngine,
    apply_route_offsets,
)


def _snapshot(**overrides):
    roles_home = {
        "GK": {"cross_claiming": 0.2, "shot_stopping": 0.2},
        "CB": {"aerial_defense": 0.2, "box_defense": 0.2, "buildup_security": 0.1},
        "FB": {"defensive_isolation": 0.1, "recovery": 0.1},
        "DM": {"press_resistance": 0.2, "ball_recovery": 0.3},
        "W": {"isolation": 0.9, "crossing": 0.8, "pressing": 0.7, "transition": 0.5},
        "ST": {"aerial": 0.7, "box_presence": 0.8, "pressing": 0.6},
    }
    roles_away = {
        "GK": {"cross_claiming": -0.2, "shot_stopping": -0.1},
        "CB": {"aerial_defense": -0.3, "box_defense": -0.2, "buildup_security": -0.2},
        "FB": {"defensive_isolation": -0.5, "recovery": -0.3},
        "DM": {"press_resistance": -0.2, "ball_recovery": -0.1},
        "W": {"isolation": 0.1, "crossing": 0.1, "pressing": 0.0, "transition": 0.1},
        "ST": {"aerial": 0.0, "box_presence": 0.1, "pressing": 0.0},
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": "unit_fixture",
        "updated_at": "2026-07-03T00:00:00Z",
        "home": {"roles": roles_home},
        "away": {"roles": roles_away},
    }
    payload.update(overrides)
    return payload


def test_missing_snapshot_fails_closed_to_baseline():
    result = WCRouteOffsetEngine({}).evaluate({"event_id": "missing"})

    assert result.status == "fallback"
    assert result.reason == "route_offset_snapshot_missing"
    assert result.pick_eligible is False
    assert result.total_delta == {"home": 0.0, "away": 0.0}


def test_complete_snapshot_emits_duels_and_positive_home_delta():
    engine = WCRouteOffsetEngine({"1001": _snapshot()})
    result = engine.evaluate(
        {"event_id": "1001", "home_team": "Brazil", "away_team": "Germany"},
        as_of=datetime(2026, 7, 3, 1, tzinfo=timezone.utc),
    )

    assert result.status == "shadow_ready"
    assert result.pick_eligible is True
    assert result.role_coverage == {"home": 1.0, "away": 1.0}
    assert {duel["rule_id"] for duel in result.active_duels} >= {
        "wing_isolation",
        "aerial_set_piece_mismatch",
        "press_vs_build",
    }
    assert result.total_delta["home"] > 0


def test_missing_role_shrinks_and_suppresses_pick_eligibility():
    snap = _snapshot()
    del snap["away"]["roles"]["FB"]
    result = WCRouteOffsetEngine({"Brazil|Germany": snap}).evaluate(
        {"home_team": "Brazil", "away_team": "Germany"},
        as_of=datetime(2026, 7, 3, 1, tzinfo=timezone.utc),
    )

    assert result.status == "shadow_suppressed"
    assert result.pick_eligible is False
    assert result.role_coverage["away"] == pytest.approx(5 / 6, abs=1e-4)
    assert result.uncertainty_shrink == pytest.approx(5 / 6, abs=1e-4)
    assert "FB" in result.missing_roles["away"]


def test_schema_mismatch_fails_closed():
    snap = _snapshot(schema_version="future_schema")
    result = WCRouteOffsetEngine({"1001": snap}).evaluate({"event_id": "1001"})

    assert result.status == "fallback"
    assert result.reason == "route_offset_schema_mismatch"
    assert result.pick_eligible is False


def test_apply_route_offsets_bounds_lambdas():
    adjusted = apply_route_offsets(
        3.45,
        0.30,
        {"total_delta": {"home": 1.0, "away": -1.0}},
    )

    assert adjusted == pytest.approx((3.5, 0.25))
