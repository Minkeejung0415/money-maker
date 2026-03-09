import pytest
from alpha.risk.exposure import ExposureLimiter


def test_exposure_limiter_initializes():
    limiter = ExposureLimiter(total_capital=100_000.0)
    assert limiter is not None


def test_single_position_within_limit():
    limiter = ExposureLimiter(total_capital=100_000.0, max_single_pct=0.10)
    assert limiter.check_position("AAPL", 9_000.0) is True


def test_single_position_exceeds_limit():
    limiter = ExposureLimiter(total_capital=100_000.0, max_single_pct=0.10)
    assert limiter.check_position("AAPL", 11_000.0) is False


def test_clip_positions_to_limits():
    limiter = ExposureLimiter(total_capital=100_000.0, max_single_pct=0.10)
    positions = {"AAPL": 15_000.0, "MSFT": 5_000.0, "NVDA": 20_000.0}
    clipped = limiter.clip_positions(positions)
    assert clipped["AAPL"] <= 10_000.0
    assert clipped["MSFT"] == 5_000.0
    assert clipped["NVDA"] <= 10_000.0


def test_total_vertical_exposure():
    limiter = ExposureLimiter(total_capital=100_000.0, max_vertical_pct=0.50)
    positions = {"AAPL": 30_000.0, "MSFT": 25_000.0}
    total = limiter.total_exposure(positions)
    assert total == 55_000.0


def test_vertical_exposure_exceeds_limit():
    limiter = ExposureLimiter(total_capital=100_000.0, max_vertical_pct=0.40)
    positions = {"AAPL": 30_000.0, "MSFT": 25_000.0}
    assert limiter.check_vertical_exposure(positions) is False


def test_vertical_exposure_within_limit():
    limiter = ExposureLimiter(total_capital=100_000.0, max_vertical_pct=0.60)
    positions = {"AAPL": 30_000.0, "MSFT": 25_000.0}
    assert limiter.check_vertical_exposure(positions) is True
