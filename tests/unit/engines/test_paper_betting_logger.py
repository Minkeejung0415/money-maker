"""Stage 6 tests: paper-betting logger (log -> settle -> CLV/PnL)."""
from __future__ import annotations

import json

import pytest

from alpha.engines.sports.paper_betting_logger import (
    RECORD_FIELDS,
    PaperBettingLogger,
    american_to_decimal,
    american_to_implied,
)


@pytest.fixture
def logger(tmp_path):
    return PaperBettingLogger(tmp_path / "paper_bets.jsonl")


def _log_sample(logger: PaperBettingLogger, **overrides) -> str:
    kwargs = dict(
        event_id="evt1",
        sport="nba",
        market="player_points",
        side="over",
        offered_odds=-110,
        final_calibrated_prob=0.62,
        model_version="2.0.0",
        feature_schema_version="2.0.0",
        commence_time_utc="2026-06-10T23:00:00Z",
        player="LeBron James",
        line=25.5,
        bookmaker="fanduel",
        consensus_no_vig_prob=0.55,
        independent_model_prob=0.64,
        projected_stat=27.1,
        projected_minutes=34.0,
        bankroll_before=1000.0,
        suggested_stake=20.0,
    )
    kwargs.update(overrides)
    return logger.log_prediction(**kwargs)


def test_log_prediction_contains_all_required_fields(logger):
    pid = _log_sample(logger)
    records = logger.load()
    assert len(records) == 1
    rec = records[0]
    for field in RECORD_FIELDS:
        assert field in rec, f"missing field {field}"
    assert rec["prediction_id"] == pid
    assert rec["created_at_utc"]
    assert rec["result"] is None  # unsettled
    assert rec["model_version"] == "2.0.0"


def test_settle_win_computes_pnl_and_clv(logger):
    pid = _log_sample(logger, offered_odds=110, suggested_stake=10.0)
    rec = logger.settle(pid, "win", closing_line=25.5, closing_odds=-105)
    assert rec["pnl"] == pytest.approx(11.0)  # +110 win on 10
    expected_clv = american_to_implied(-105) - american_to_implied(110)
    assert rec["clv"] == pytest.approx(expected_clv, abs=1e-6)
    assert logger.open_bets() == []
    assert len(logger.settled()) == 1


def test_settle_loss_and_push(logger):
    p1 = _log_sample(logger, suggested_stake=15.0)
    p2 = _log_sample(logger, suggested_stake=15.0)
    assert logger.settle(p1, "loss")["pnl"] == pytest.approx(-15.0)
    assert logger.settle(p2, "push")["pnl"] == 0.0


def test_settle_prefers_closing_consensus_prob(logger):
    pid = _log_sample(logger, offered_odds=-110)
    rec = logger.settle(pid, "win", closing_odds=-120, closing_consensus_prob=0.58)
    expected = 0.58 - american_to_implied(-110)
    assert rec["clv"] == pytest.approx(expected, abs=1e-6)


def test_settle_unknown_id_returns_none(logger):
    _log_sample(logger)
    assert logger.settle("nonexistent", "win") is None


def test_settle_invalid_result_raises(logger):
    pid = _log_sample(logger)
    with pytest.raises(ValueError):
        logger.settle(pid, "kinda_won")


def test_log_is_jsonl_on_disk(logger):
    _log_sample(logger)
    _log_sample(logger, market="h2h", player=None, line=None, side="home")
    lines = logger.log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["market"] == "h2h"


def test_settlement_preserves_other_records(logger):
    p1 = _log_sample(logger)
    p2 = _log_sample(logger, player="Anthony Davis")
    logger.settle(p1, "win", closing_odds=-115)
    records = {r["prediction_id"]: r for r in logger.load()}
    assert records[p2]["result"] is None
    assert records[p1]["result"] == "win"


def test_odds_conversions():
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(-200) == pytest.approx(1.5)
    assert american_to_implied(-200) == pytest.approx(2 / 3)
