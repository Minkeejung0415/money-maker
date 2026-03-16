"""Tests for prediction logger."""
from __future__ import annotations

import json


def test_log_appends_jsonl_record(tmp_path):
    """Logging a prediction appends one JSONL line to the output file."""
    from scripts.log_predictions import log_prediction

    log_file = tmp_path / "picks.jsonl"
    log_prediction(
        player="Jayson Tatum",
        market="player_points",
        line=28.5,
        model_prob=0.72,
        market_implied=0.50,
        confidence="HIGH",
        game_date="2026-03-15",
        log_file=log_file,
    )

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["player"] == "Jayson Tatum"
    assert record["model_prob"] == 0.72
    assert record["market_implied"] == 0.50
    assert record["direction"] == "over"
    assert record["outcome"] is None  # not yet graded


def test_log_appends_multiple(tmp_path):
    """Multiple calls append multiple lines."""
    from scripts.log_predictions import log_prediction

    log_file = tmp_path / "picks.jsonl"
    for i in range(3):
        log_prediction(
            player=f"Player {i}",
            market="player_points",
            line=20.0,
            model_prob=0.6,
            market_implied=0.5,
            confidence="MEDIUM",
            game_date="2026-03-15",
            log_file=log_file,
        )

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 3


def test_log_creates_parent_dir(tmp_path):
    """Logger creates parent directory if it doesn't exist."""
    from scripts.log_predictions import log_prediction

    log_file = tmp_path / "nested" / "deep" / "picks.jsonl"
    log_prediction(
        player="Test", market="player_points", line=20.0,
        model_prob=0.6, market_implied=0.5, confidence="LOW",
        game_date="2026-03-15", log_file=log_file,
    )
    assert log_file.exists()


def test_log_under_direction(tmp_path):
    """Under legs are logged with direction='under'."""
    from scripts.log_predictions import log_prediction

    log_file = tmp_path / "picks.jsonl"
    log_prediction(
        player="Test", market="player_rebounds", line=6.5,
        model_prob=0.68, market_implied=0.50, confidence="HIGH",
        game_date="2026-03-15", direction="under", log_file=log_file,
    )
    record = json.loads(log_file.read_text().strip())
    assert record["direction"] == "under"
