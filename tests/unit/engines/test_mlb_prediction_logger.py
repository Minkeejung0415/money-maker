"""Tests for the append-only MLB prediction logger."""
from __future__ import annotations

import json

import pytest

from alpha.engines.sports.mlb_prediction_logger import MLBPredictionLogger


def _prediction(**overrides):
    rec = {
        "event_id": "mlb-statsapi-777001",
        "commence_time_utc": "2026-06-11T23:05:00Z",
        "home_team": "New York Yankees",
        "away_team": "Toronto Blue Jays",
        "independent_home_prob": 0.558,
        "independent_away_prob": 0.442,
        "market_consensus_home_no_vig_prob": 0.579,
        "market_consensus_away_no_vig_prob": 0.421,
        "paper_bet_decision": "NO_BET",
        "refusal_reasons": ["calibrator_not_fitted"],
        "model_version": "mlb_run_model_v1",
        "feature_schema_version": "mlb_features_v1",
    }
    rec.update(overrides)
    return rec


def test_append_only_log_never_overwrites(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    pid1 = log.log_prediction(_prediction())
    pid2 = log.log_prediction(_prediction())  # same game, later snapshot
    assert pid1 != pid2
    lines = log.predictions_file.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["prediction_id"] == pid1
    assert first["result"] is None  # placeholders present
    assert first["closing_odds"] is None
    assert first["clv"] is None


def test_settlement_merges_without_rewriting_snapshot(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    pid = log.log_prediction(_prediction())
    assert log.settle(pid, winner="home", home_score=5, away_score=3) is True
    merged = log.merged_records()
    assert merged[0]["result"]["winner"] == "home"
    assert merged[0]["result"]["home_score"] == 5
    # The raw snapshot file is untouched.
    raw = json.loads(log.predictions_file.read_text().strip())
    assert raw["result"] is None


def test_duplicate_settlement_is_idempotent(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    pid = log.log_prediction(_prediction())
    assert log.settle(pid, "home", 5, 3) is True
    assert log.settle(pid, "home", 5, 3) is False  # no-op
    assert log.settle(pid, "away", 3, 5) is False  # conflict rejected
    settlements = log.settlements_file.read_text().strip().splitlines()
    assert len(settlements) == 1
    assert log.merged_records()[0]["result"]["winner"] == "home"


def test_ungraded_rows_stay_visible(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    pid1 = log.log_prediction(_prediction())
    log.log_prediction(_prediction(event_id="mlb-statsapi-777002"))
    log.settle(pid1, "away", 2, 7)
    ungraded = log.ungraded()
    assert len(ungraded) == 1
    assert ungraded[0]["event_id"] == "mlb-statsapi-777002"
    assert log.graded_count() == 1


def test_closing_odds_stored_separately(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    pid = log.log_prediction(_prediction())
    assert log.record_closing_odds(pid, 0.60, 0.40, -160, 140) is True
    assert log.record_closing_odds(pid, 0.99, 0.01) is False  # first wins
    merged = log.merged_records()[0]
    assert merged["closing_odds"]["consensus_home_no_vig_prob"] == 0.60
    # Raw prediction snapshot unchanged.
    raw = json.loads(log.predictions_file.read_text().strip())
    assert raw["closing_odds"] is None


def test_clv_computed_only_after_closing_odds(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    pid = log.log_prediction(_prediction())
    assert log.merged_records()[0]["clv"] is None
    log.record_closing_odds(pid, 0.60, 0.40)
    clv = log.merged_records()[0]["clv"]
    assert clv["home_prob_move"] == pytest.approx(0.60 - 0.579, abs=1e-6)
    assert clv["away_prob_move"] == pytest.approx(-(0.60 - 0.579), abs=1e-6)


def test_clv_unavailable_without_logged_consensus(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    pid = log.log_prediction(
        _prediction(market_consensus_home_no_vig_prob=None,
                    market_consensus_away_no_vig_prob=None)
    )
    log.record_closing_odds(pid, 0.60, 0.40)
    assert log.merged_records()[0]["clv"] is None  # never invent a baseline
