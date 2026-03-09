import pytest
from alpha.risk.drawdown import DrawdownMonitor


def test_monitor_initializes():
    mon = DrawdownMonitor(peak_capital=100_000.0, max_drawdown_pct=0.15)
    assert mon.peak_capital == 100_000.0


def test_no_drawdown_at_peak():
    mon = DrawdownMonitor(peak_capital=100_000.0)
    assert mon.current_drawdown_pct(100_000.0) == 0.0


def test_drawdown_calculated_correctly():
    mon = DrawdownMonitor(peak_capital=100_000.0)
    dd = mon.current_drawdown_pct(85_000.0)
    assert abs(dd - 0.15) < 1e-9


def test_circuit_breaker_not_triggered_below_threshold():
    mon = DrawdownMonitor(peak_capital=100_000.0, max_drawdown_pct=0.20)
    assert mon.is_breaker_triggered(90_000.0) is False


def test_circuit_breaker_triggered_above_threshold():
    mon = DrawdownMonitor(peak_capital=100_000.0, max_drawdown_pct=0.15)
    assert mon.is_breaker_triggered(84_000.0) is True


def test_peak_updates_on_new_high():
    mon = DrawdownMonitor(peak_capital=100_000.0)
    mon.update(110_000.0)
    assert mon.peak_capital == 110_000.0


def test_peak_does_not_decrease():
    mon = DrawdownMonitor(peak_capital=100_000.0)
    mon.update(80_000.0)
    assert mon.peak_capital == 100_000.0


def test_get_scalar_zero_when_breaker_triggered():
    mon = DrawdownMonitor(peak_capital=100_000.0, max_drawdown_pct=0.10)
    scalar = mon.get_position_scalar(88_000.0)
    assert scalar == 0.0


def test_get_scalar_one_at_peak():
    mon = DrawdownMonitor(peak_capital=100_000.0, max_drawdown_pct=0.20)
    scalar = mon.get_position_scalar(100_000.0)
    assert scalar == 1.0
