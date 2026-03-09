import pytest
from alpha.engines.sports.ev_calculator import EVCalculator


def test_ev_positive_edge():
    calc = EVCalculator()
    # Our model says 60% win prob, book offers +100 (implied 50%)
    ev = calc.expected_value(model_prob=0.60, decimal_odds=2.0)
    assert ev > 0


def test_ev_negative_edge():
    calc = EVCalculator()
    # Our model says 40% win prob, book offers +100 (implied 50%)
    ev = calc.expected_value(model_prob=0.40, decimal_odds=2.0)
    assert ev < 0


def test_ev_formula():
    calc = EVCalculator()
    # EV = model_prob * (odds - 1) - (1 - model_prob)
    # = 0.55 * 1.0 - 0.45 = 0.10
    ev = calc.expected_value(model_prob=0.55, decimal_odds=2.0)
    assert abs(ev - 0.10) < 1e-9


def test_american_to_decimal_positive():
    calc = EVCalculator()
    # +150 → 2.5
    assert abs(calc.american_to_decimal(150) - 2.5) < 1e-9


def test_american_to_decimal_negative():
    calc = EVCalculator()
    # -150 → 1.667
    assert abs(calc.american_to_decimal(-150) - (1 + 100/150)) < 1e-9


def test_implied_probability():
    calc = EVCalculator()
    # decimal odds 2.0 → implied prob 0.5
    assert abs(calc.implied_prob(2.0) - 0.5) < 1e-9


def test_has_edge_threshold():
    calc = EVCalculator(min_edge=0.05)
    assert calc.has_edge(model_prob=0.60, decimal_odds=2.0) is True
    assert calc.has_edge(model_prob=0.51, decimal_odds=2.0) is False
