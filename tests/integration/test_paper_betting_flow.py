"""Integration: log paper bets -> settle -> evaluate (Stage 6 end-to-end)."""
from __future__ import annotations

import pytest

from alpha.engines.sports.evaluation import (
    betting_metrics,
    grouped_betting_report,
    probability_metrics,
)
from alpha.engines.sports.paper_betting_logger import PaperBettingLogger


def test_full_paper_betting_cycle(tmp_path):
    log = PaperBettingLogger(tmp_path / "bets.jsonl")

    # Night 1: two props and a moneyline are logged pregame.
    p1 = log.log_prediction(
        event_id="e1", sport="nba", market="player_points", side="over",
        offered_odds=-110, final_calibrated_prob=0.62,
        model_version="2.0.0", feature_schema_version="2.0.0",
        player="LeBron James", line=25.5, bookmaker="fanduel",
        consensus_no_vig_prob=0.55, independent_model_prob=0.64,
        projected_stat=27.3, projected_minutes=35.0,
        bankroll_before=1000.0, suggested_stake=20.0,
        commence_time_utc="2026-01-05T00:00:00+00:00",
    )
    p2 = log.log_prediction(
        event_id="e1", sport="nba", market="player_rebounds", side="under",
        offered_odds=105, final_calibrated_prob=0.58,
        model_version="2.0.0", feature_schema_version="2.0.0",
        player="Anthony Davis", line=11.5, bookmaker="draftkings",
        bankroll_before=1000.0, suggested_stake=10.0,
        commence_time_utc="2026-01-05T00:00:00+00:00",
    )
    p3 = log.log_prediction(
        event_id="e2", sport="nba", market="h2h", side="home",
        offered_odds=-140, final_calibrated_prob=0.61,
        model_version="ml-1.0", feature_schema_version="1.0",
        bookmaker="betmgm", consensus_no_vig_prob=0.57,
        bankroll_before=1000.0, suggested_stake=15.0,
        commence_time_utc="2026-01-06T00:00:00+00:00",
    )

    assert len(log.open_bets()) == 3

    # Morning after: settle with closing context.
    log.settle(p1, "win", closing_line=25.5, closing_odds=-120)
    log.settle(p2, "loss", closing_line=11.5, closing_odds=110)
    log.settle(p3, "win", closing_odds=-150, closing_consensus_prob=0.60)

    settled = log.settled()
    assert len(settled) == 3
    by_id = {r["prediction_id"]: r for r in settled}
    assert by_id[p1]["clv"] > 0          # -110 beat the -120 close
    assert by_id[p3]["clv"] == pytest.approx(0.60 - (140 / 240), abs=1e-6)

    # Evaluation over the settled log.
    metrics = betting_metrics(settled)
    assert metrics["num_bets"] == 3
    expected_pnl = 20.0 * (100 / 110) - 10.0 + 15.0 * (100 / 140)
    assert metrics["total_pnl"] == pytest.approx(expected_pnl, abs=0.01)

    decided = [b for b in settled if b["result"] in ("win", "loss")]
    probs = probability_metrics(
        [1 if b["result"] == "win" else 0 for b in decided],
        [b["final_calibrated_prob"] for b in decided],
    )
    assert 0.0 <= probs["brier_score"] <= 1.0

    grouped = grouped_betting_report(settled)
    assert grouped["market"]["h2h"]["num_bets"] == 1
    assert grouped["bookmaker"]["fanduel"]["win_rate"] == 1.0
    assert grouped["month"]["2026-01"]["num_bets"] == 3
