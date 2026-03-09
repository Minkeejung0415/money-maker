import pytest
from alpha.engines.sports.kelly import KellySizer


def test_kelly_fraction_even_money():
    sizer = KellySizer()
    # p=0.55, odds=2.0 (even money) → Kelly = 2*0.55 - 1 = 0.10
    f = sizer.kelly_fraction(win_prob=0.55, decimal_odds=2.0)
    assert abs(f - 0.10) < 1e-9


def test_kelly_fraction_negative_edge():
    sizer = KellySizer()
    # p=0.45, even money → Kelly = 2*0.45 - 1 = -0.10 → clamped to 0
    f = sizer.kelly_fraction(win_prob=0.45, decimal_odds=2.0)
    assert f == 0.0


def test_fractional_kelly():
    sizer = KellySizer(kelly_fraction=0.25)
    full = sizer.kelly_fraction(win_prob=0.60, decimal_odds=2.0)
    stake = sizer.bet_size(win_prob=0.60, decimal_odds=2.0, bankroll=1000.0)
    assert stake == pytest.approx(full * 0.25 * 1000.0, abs=0.01)


def test_bet_size_respects_max_stake():
    sizer = KellySizer(kelly_fraction=1.0, max_stake_pct=0.05)
    # Even with large Kelly, stake capped at 5% of bankroll
    stake = sizer.bet_size(win_prob=0.90, decimal_odds=10.0, bankroll=1000.0)
    assert stake <= 50.0


def test_bet_size_zero_for_no_edge():
    sizer = KellySizer()
    stake = sizer.bet_size(win_prob=0.40, decimal_odds=2.0, bankroll=1000.0)
    assert stake == 0.0
