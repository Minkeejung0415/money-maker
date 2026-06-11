"""Tests for the MLB grading script (free StatsAPI finals -> settlements)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from alpha.engines.sports.mlb_prediction_logger import MLBPredictionLogger
from scripts.grade_mlb_predictions import fetch_final_scores, grade


def _prediction(game_id=777001, **overrides):
    rec = {
        "event_id": f"mlb-statsapi-{game_id}",
        "statsapi_game_id": game_id,
        "game_date": "2026-06-11",
        "home_team": "New York Yankees",
        "away_team": "Toronto Blue Jays",
        "market_consensus_home_no_vig_prob": 0.579,
        "market_consensus_away_no_vig_prob": 0.421,
        "paper_bet_decision": "NO_BET",
    }
    rec.update(overrides)
    return rec


def _statsapi_payload(games):
    return {"dates": [{"games": games}]}


def _final_game(game_pk=777001, home=5, away=3, state="Final"):
    return {
        "gamePk": game_pk,
        "status": {"abstractGameState": state},
        "teams": {
            "home": {"score": home, "team": {"name": "New York Yankees"}},
            "away": {"score": away, "team": {"name": "Toronto Blue Jays"}},
        },
    }


def test_fetch_final_scores_skips_non_final():
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = _statsapi_payload([
        _final_game(777001, 5, 3, "Final"),
        _final_game(777002, 1, 1, "Live"),
    ])
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    finals = fetch_final_scores("2026-06-11", session=session)
    assert finals == {777001: {"home_score": 5, "away_score": 3}}
    url = session.get.call_args.args[0]
    assert "statsapi.mlb.com" in url  # free endpoint only


def test_grade_settles_final_games(tmp_path, capsys):
    log = MLBPredictionLogger(tmp_path)
    log.log_prediction(_prediction(777001))
    log.log_prediction(_prediction(777002))  # not final yet
    finals = {777001: {"home_score": 2, "away_score": 6}}
    with patch("scripts.grade_mlb_predictions.fetch_final_scores", return_value=finals):
        grade(tmp_path, date_filter=None, dry_run=False)
    merged = {r["statsapi_game_id"]: r for r in log.merged_records()}
    assert merged[777001]["result"]["winner"] == "away"
    assert merged[777002]["result"] is None  # still visible as ungraded
    assert len(log.ungraded()) == 1
    assert "Settled 1" in capsys.readouterr().out


def test_grade_is_idempotent_across_runs(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    log.log_prediction(_prediction(777001))
    finals = {777001: {"home_score": 4, "away_score": 1}}
    with patch("scripts.grade_mlb_predictions.fetch_final_scores", return_value=finals):
        grade(tmp_path, date_filter=None, dry_run=False)
        grade(tmp_path, date_filter=None, dry_run=False)
    settlements = log.settlements_file.read_text().strip().splitlines()
    assert len(settlements) == 1


def test_dry_run_settles_nothing(tmp_path):
    log = MLBPredictionLogger(tmp_path)
    log.log_prediction(_prediction(777001))
    finals = {777001: {"home_score": 4, "away_score": 1}}
    with patch("scripts.grade_mlb_predictions.fetch_final_scores", return_value=finals):
        grade(tmp_path, date_filter=None, dry_run=True)
    assert not log.settlements_file.exists()
