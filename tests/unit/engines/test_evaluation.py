"""Stage 6 tests: evaluation metrics + walk-forward splits."""
from __future__ import annotations

import pytest

from alpha.engines.sports.evaluation import (
    betting_metrics,
    brier_score,
    grouped_betting_report,
    log_loss,
    mae,
    moneyline_ablation_configs,
    probability_metrics,
    reliability_table,
    rmse,
    walkforward_splits,
)


def test_mae_rmse():
    assert mae([10, 20], [12, 18]) == pytest.approx(2.0)
    assert rmse([10, 20], [12, 18]) == pytest.approx(2.0)
    assert rmse([0, 0], [0, 4]) == pytest.approx(2 ** 1.5)


def test_brier_perfect_and_worst():
    assert brier_score([1, 0], [1.0, 0.0]) == pytest.approx(0.0)
    assert brier_score([1, 0], [0.0, 1.0]) == pytest.approx(1.0)
    assert brier_score([1, 0], [0.5, 0.5]) == pytest.approx(0.25)


def test_log_loss_clipped():
    # Exact 0/1 probs are clipped — finite loss.
    assert log_loss([1], [0.0]) < 30


def test_reliability_table_bins():
    outcomes = [1, 1, 0, 0, 1, 0]
    probs = [0.75, 0.72, 0.71, 0.15, 0.12, 0.18]
    table = reliability_table(outcomes, probs, n_bins=10)
    assert len(table) == 2
    hi = next(b for b in table if b["bin_low"] == 0.7)
    assert hi["count"] == 3
    assert hi["observed_rate"] == pytest.approx(2 / 3)


def test_probability_metrics_shape():
    out = probability_metrics([1, 0, 1], [0.8, 0.3, 0.6])
    assert {"brier_score", "log_loss", "reliability_table", "n"} <= out.keys()


def _bet(result, pnl, stake=10.0, clv=None, **extra):
    return {"result": result, "pnl": pnl, "suggested_stake": stake, "clv": clv, **extra}


def test_betting_metrics():
    bets = [
        _bet("win", 9.0, clv=0.02),
        _bet("loss", -10.0, clv=-0.01),
        _bet("loss", -10.0, clv=0.03),
        _bet("win", 12.0, clv=0.0),
        _bet("push", 0.0),
        {"result": None, "pnl": None, "suggested_stake": 10.0},  # unsettled — ignored
    ]
    m = betting_metrics(bets)
    assert m["num_bets"] == 5
    assert m["total_pnl"] == pytest.approx(1.0)
    assert m["roi"] == pytest.approx(1.0 / 50.0)
    assert m["win_rate"] == pytest.approx(0.5)
    assert m["longest_losing_streak"] == 2
    assert m["max_drawdown"] == pytest.approx(20.0)  # peak +9 → trough -11
    assert m["avg_clv"] == pytest.approx(0.01)
    assert m["median_clv"] == pytest.approx(0.01)


def test_grouped_report():
    bets = [
        _bet("win", 9.0, market="player_points", bookmaker="fanduel",
             offered_odds=-110, final_calibrated_prob=0.65,
             created_at_utc="2026-01-05T00:00:00+00:00", model_version="2.0.0"),
        _bet("loss", -10.0, market="player_assists", bookmaker="draftkings",
             offered_odds=250, final_calibrated_prob=0.52,
             created_at_utc="2026-02-05T00:00:00+00:00", model_version="2.0.0"),
    ]
    rep = grouped_betting_report(bets)
    assert rep["market"]["player_points"]["num_bets"] == 1
    assert rep["bookmaker"]["draftkings"]["total_pnl"] == pytest.approx(-10.0)
    assert "underdog(+120..+250)" in rep["odds_bucket"]
    assert rep["month"]["2026-01"]["num_bets"] == 1
    assert "0.60-0.70" in rep["confidence_bucket"]


def test_walkforward_never_trains_on_future():
    dates = list(range(100))
    splits = walkforward_splits(dates, n_folds=5)
    assert len(splits) == 5
    for train_idx, test_idx in splits:
        assert train_idx, "every fold must have training data"
        assert max(dates[i] for i in train_idx) < min(dates[i] for i in test_idx)
    # Folds cover the post-burn-in period exactly once.
    all_test = [i for _, t in splits for i in t]
    assert len(all_test) == len(set(all_test)) == 60


def test_walkforward_unsorted_input_is_time_ordered():
    dates = [5, 1, 9, 3, 7, 2, 8, 4, 6, 0]
    for train_idx, test_idx in walkforward_splits(dates, n_folds=3):
        assert max(dates[i] for i in train_idx) < min(dates[i] for i in test_idx)


def test_ablation_configs_cover_components():
    configs = moneyline_ablation_configs()
    assert "base" in configs and "full_default" in configs
    assert configs["base"]["enable_h2h"] is False
    assert configs["base+injury_adjustment"]["enable_injury_adjustment"] is True
    assert configs["base+injury_adjustment"]["enable_recent_form"] is False
    assert configs["base+rest_features"]["enable_rest_features"] is True
    # Every config must be valid NBAModel kwargs.
    from alpha.engines.sports.nba_model import NBAModel
    import inspect
    params = set(inspect.signature(NBAModel.__init__).parameters)
    for cfg in configs.values():
        assert set(cfg) <= params
