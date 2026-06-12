"""
Regression tests for the standalone detailed-pick (--show-ev) safety gates.

A fallback-derived standalone prop must never appear eligible for
real-money staking: no Kelly stake, no VALUE BET label, diagnostic edge
only, explicit refusal reasons — while research visibility and paper
logging of diagnostic rows are preserved.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from alpha.engines.sports.parlay_constructor import (
    DIAGNOSTIC_EDGE_LABEL,
    MAX_LOW_MINUTES_RISK,
    RESEARCH_ONLY_FALLBACK_MSG,
    RESEARCH_ONLY_UNVALIDATED_MSG,
    ParlayConstructor,
    assess_pick_eligibility,
)


def _pick(**overrides) -> dict:
    """A fully-eligible XGB-backed pick; tests override what they probe."""
    base = {
        "player": "Test Player",
        "market": "player_points",
        "line": 22.5,
        "model_prob": 0.66,
        "adjusted_prob": 0.66,
        "over_odds": -110,
        "edge": 0.13,
        "ev": 0.25,
        "source": "xgb",
        "recommendation_eligible": True,
        "refusal_reasons": [],
        "projected_minutes": 33.5,
        "low_minutes_risk": 0.0,
    }
    base.update(overrides)
    return base


def _fallback_pick(**overrides) -> dict:
    return _pick(
        source="rule_fallback",
        recommendation_eligible=False,
        refusal_reasons=["fallback_model"],
        **overrides,
    )


@pytest.fixture
def ctor() -> ParlayConstructor:
    return ParlayConstructor(bankroll=10_000.0)


# ---------------------------------------------------------------------------
# format_pick gating
# ---------------------------------------------------------------------------

def test_fallback_pick_displays_no_kelly_stake(ctor):
    out = ctor.format_pick(_fallback_pick())
    assert "Kelly" not in out
    assert "$" not in out.split("Implied")[0] or "stake" not in out.lower() \
        or "Kelly" not in out
    assert RESEARCH_ONLY_FALLBACK_MSG in out
    assert DIAGNOSTIC_EDGE_LABEL in out
    assert "fallback_model" in out
    # Research visibility retained: projection/confidence still shown.
    assert "Model confidence" in out


def test_fallback_pick_never_prints_value_bet(ctor):
    out = ctor.format_pick(_fallback_pick())
    assert "VALUE BET" not in out.upper()
    # No actionable bet labeling of any kind.
    assert "BET" not in out.upper().replace("RESEARCH", "")


def test_validated_xgb_pick_may_show_stake(ctor):
    out = ctor.format_pick(_pick())
    assert "Kelly stake" in out
    assert RESEARCH_ONLY_FALLBACK_MSG not in out
    assert RESEARCH_ONLY_UNVALIDATED_MSG not in out
    assert DIAGNOSTIC_EDGE_LABEL not in out


def test_unvalidated_xgb_pick_shows_no_stake(ctor):
    pick = _pick(recommendation_eligible=False,
                 refusal_reasons=["calibration_missing"])
    out = ctor.format_pick(pick)
    assert "Kelly" not in out
    assert RESEARCH_ONLY_UNVALIDATED_MSG in out
    assert "calibration_missing" in out


def test_xgb_pick_without_eligibility_info_fails_safe(ctor):
    """An xgb pick with no model-side verdict cannot be verified — refuse."""
    pick = _pick()
    del pick["recommendation_eligible"]
    del pick["refusal_reasons"]
    eligible, reasons = assess_pick_eligibility(pick)
    assert eligible is False
    assert "model_metadata_missing" in reasons
    assert "Kelly" not in ctor.format_pick(pick)


def test_pick_without_source_treated_as_fallback(ctor):
    pick = _pick()
    del pick["source"]
    eligible, reasons = assess_pick_eligibility(pick)
    assert eligible is False
    assert "fallback_model" in reasons


# ---------------------------------------------------------------------------
# Minutes-based eligibility
# ---------------------------------------------------------------------------

def test_missing_projected_minutes_blocks_low_alt_line_eligibility():
    pick = _pick(line=1.5, projected_minutes=None)
    eligible, reasons = assess_pick_eligibility(pick)
    assert eligible is False
    assert "projected_minutes_unreliable" in reasons


def test_high_low_minutes_risk_blocks_eligibility():
    pick = _pick(low_minutes_risk=MAX_LOW_MINUTES_RISK + 0.1)
    eligible, reasons = assess_pick_eligibility(pick)
    assert eligible is False
    assert "low_minutes_risk_too_high" in reasons


# ---------------------------------------------------------------------------
# recommend_bet_types gating
# ---------------------------------------------------------------------------

def test_recommendations_exclude_ineligible_picks(ctor):
    picks = [
        _fallback_pick(player="Fallback Guy", edge=0.30, ev=0.50),  # juicy but ineligible
        _pick(player="Eligible Guy", edge=0.08, ev=0.10),
    ]
    recs = ctor.recommend_bet_types(picks)
    assert recs, "eligible pick should still produce recommendations"
    for rec in recs:
        for leg in rec.legs:
            assert leg["player"] == "Eligible Guy"


def test_no_recommendations_when_nothing_eligible(ctor):
    picks = [_fallback_pick(player=f"P{i}", edge=0.2) for i in range(4)]
    assert ctor.recommend_bet_types(picks) == []


# ---------------------------------------------------------------------------
# PropModel emits the eligibility verdict
# ---------------------------------------------------------------------------

def _rows(pts: float, minutes: float, n: int) -> list[dict]:
    return [
        {"PTS": pts, "REB": 5.0, "AST": 3.0, "FG3M": 1.0,
         "MIN": str(int(minutes)), "MIN_float": minutes}
        for _ in range(n)
    ]


@pytest.fixture
def model():
    from alpha.engines.sports.prop_model import PropModel
    with patch("alpha.engines.sports.xgb_prop_model.XGBoostPropModel.load",
               side_effect=Exception("no models on disk")):
        m = PropModel(season="2024-25")
    m._xgb_models = {}
    return m


def _patch_logs(rows):
    return patch("alpha.engines.sports.prop_model.PropModel._fetch_game_logs",
                 return_value=rows)


def _patch_team_stats():
    return patch("alpha.engines.sports.prop_model.PropModel._fetch_team_per_game_stats",
                 return_value={})


def test_fallback_result_carries_refusal_verdict(model):
    with _patch_logs(_rows(25.0, 32.0, 15)), _patch_team_stats():
        result = model.predict_prop("Test Player", "player_points", 20.5, "Boston Celtics")
    assert result["recommendation_eligible"] is False
    assert result["research_only"] is True
    assert "fallback_model" in result["refusal_reasons"]


def test_bench_player_gets_low_minutes_refusal(model):
    logs = _rows(2.0, 6.0, 8) + _rows(8.0, 30.0, 8)  # demoted to the bench
    with _patch_logs(logs), _patch_team_stats():
        result = model.predict_prop("Bench Guy", "player_points", 1.5, "Boston Celtics")
    assert result["recommendation_eligible"] is False
    assert "low_minutes_risk_too_high" in result["refusal_reasons"]


def test_validated_xgb_result_is_eligible(model, monkeypatch):
    from datetime import date as real_date

    class _FixedDate(real_date):
        @classmethod
        def today(cls):
            return real_date(2025, 1, 30)

    monkeypatch.setattr("alpha.engines.sports.prop_model.date", _FixedDate)

    class _ValidatedXGB:
        feature_names = ["roll5_stat_per_min"]
        feature_schema_version = "2.0.0"
        validation_metrics = {"val_mae": 3.0}
        def predict(self, features):
            return 26.0

    rows = [
        {"PTS": 25.0, "REB": 5.0, "AST": 3.0, "FG3M": 1.0,
         "MIN": "33", "MIN_float": 33.0,
         "GAME_DATE": f"2025-01-{28 - 2 * i:02d}"}
        for i in range(12)
    ]
    model._xgb_models = {"player_points": _ValidatedXGB()}
    team_stats = {"Boston Celtics": {"def_rtg": 110.0, "pace": 100.0}}
    with _patch_logs(rows), patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_team_per_game_stats",
        return_value=team_stats,
    ):
        result = model.predict_prop(
            "Test Player", "player_points", 22.5, "Boston Celtics", is_home=True)
    assert result["source"] == "xgb"
    assert result["refusal_reasons"] == []
    assert result["recommendation_eligible"] is True


def test_unvalidated_xgb_result_refused_calibration(model, monkeypatch):
    from datetime import date as real_date

    class _FixedDate(real_date):
        @classmethod
        def today(cls):
            return real_date(2025, 1, 30)

    monkeypatch.setattr("alpha.engines.sports.prop_model.date", _FixedDate)

    class _UnvalidatedXGB:
        feature_names = ["roll5_stat_per_min"]
        feature_schema_version = "2.0.0"
        validation_metrics = {}
        def predict(self, features):
            return 26.0

    rows = [
        {"PTS": 25.0, "REB": 5.0, "AST": 3.0, "FG3M": 1.0,
         "MIN": "33", "MIN_float": 33.0,
         "GAME_DATE": f"2025-01-{28 - 2 * i:02d}"}
        for i in range(12)
    ]
    model._xgb_models = {"player_points": _UnvalidatedXGB()}
    team_stats = {"Boston Celtics": {"def_rtg": 110.0, "pace": 100.0}}
    with _patch_logs(rows), patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_team_per_game_stats",
        return_value=team_stats,
    ):
        result = model.predict_prop(
            "Test Player", "player_points", 22.5, "Boston Celtics", is_home=True)
    assert result["recommendation_eligible"] is False
    assert "calibration_missing" in result["refusal_reasons"]


# ---------------------------------------------------------------------------
# Paper logging keeps diagnostic rows with the distinction
# ---------------------------------------------------------------------------

def test_prediction_log_preserves_research_rows_with_reasons(tmp_path):
    import importlib.util
    import sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "log_predictions",
        Path(__file__).resolve().parents[2] / "scripts" / "log_predictions.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["log_predictions"] = mod
    spec.loader.exec_module(mod)

    log_file = tmp_path / "log.jsonl"
    mod.log_prediction(
        player="Bench Guy", market="player_points", line=1.5,
        model_prob=0.71, market_implied=0.52, confidence="MEDIUM",
        game_date="2026-06-12", log_file=log_file,
        source="rule_fallback", recommendation_eligible=False,
        refusal_reasons=["fallback_model", "low_minutes_risk_too_high"],
    )
    rec = json.loads(log_file.read_text().strip())
    assert rec["research_only"] is True
    assert rec["recommendation_eligible"] is False
    assert rec["refusal_reasons"] == ["fallback_model", "low_minutes_risk_too_high"]
    assert rec["source"] == "rule_fallback"
    assert rec["model_prob"] == 0.71  # diagnostic row fully retained


def test_paper_betting_logger_distinguishes_research_rows(tmp_path):
    from alpha.engines.sports.paper_betting_logger import PaperBettingLogger

    log = PaperBettingLogger(tmp_path / "bets.jsonl")
    log.log_prediction(
        event_id="e1", sport="nba", market="player_points", side="over",
        offered_odds=-110, final_calibrated_prob=0.66,
        model_version="rule_based_v1", feature_schema_version="2.0.0",
        player="Bench Guy", line=1.5,
        recommendation_eligible=False,
        refusal_reasons=["fallback_model"],
    )
    log.log_prediction(
        event_id="e1", sport="nba", market="player_rebounds", side="over",
        offered_odds=-110, final_calibrated_prob=0.61,
        model_version="2.0.0", feature_schema_version="2.0.0",
        player="Starter Guy", line=8.5,
        recommendation_eligible=True,
    )
    rows = log.load()
    research = [r for r in rows if r["research_only"]]
    actionable = [r for r in rows if r["recommendation_eligible"]]
    assert len(research) == 1 and research[0]["player"] == "Bench Guy"
    assert research[0]["refusal_reasons"] == ["fallback_model"]
    assert len(actionable) == 1 and actionable[0]["player"] == "Starter Guy"
