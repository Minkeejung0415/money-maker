import pytest
from alpha.risk.position_sizer import PositionSizer


def test_sizer_initializes():
    sizer = PositionSizer(total_capital=100_000.0)
    assert sizer.total_capital == 100_000.0


def test_vertical_allocation():
    sizer = PositionSizer(
        total_capital=100_000.0,
        stocks_pct=0.50,
        crypto_pct=0.30,
        sports_pct=0.20,
    )
    alloc = sizer.vertical_allocations()
    assert abs(alloc["stocks"] - 50_000.0) < 0.01
    assert abs(alloc["crypto"] - 30_000.0) < 0.01
    assert abs(alloc["sports"] - 20_000.0) < 0.01


def test_allocations_sum_to_capital():
    sizer = PositionSizer(total_capital=100_000.0)
    alloc = sizer.vertical_allocations()
    assert abs(sum(alloc.values()) - 100_000.0) < 0.01


def test_scale_weights_to_capital():
    sizer = PositionSizer(total_capital=100_000.0, stocks_pct=0.50)
    weights = {"AAPL": 0.60, "MSFT": 0.40}
    positions = sizer.scale_weights("stocks", weights)
    assert abs(positions["AAPL"] - 30_000.0) < 0.01
    assert abs(positions["MSFT"] - 20_000.0) < 0.01


def test_scale_respects_position_scalar():
    sizer = PositionSizer(total_capital=100_000.0, stocks_pct=0.50)
    weights = {"AAPL": 1.0}
    full = sizer.scale_weights("stocks", weights, position_scalar=1.0)
    half = sizer.scale_weights("stocks", weights, position_scalar=0.5)
    assert abs(half["AAPL"] - full["AAPL"] / 2) < 0.01
