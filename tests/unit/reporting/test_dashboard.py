import polars as pl
import pytest
from alpha.reporting.dashboard import DashboardData


def _sample_trades():
    return [
        {"vertical": "stocks", "symbol": "AAPL", "pnl": 200.0, "timestamp": "2026-01-05T10:00:00+00:00"},
        {"vertical": "stocks", "symbol": "MSFT", "pnl": -50.0, "timestamp": "2026-01-06T10:00:00+00:00"},
        {"vertical": "crypto", "symbol": "BTC/USDT", "pnl": 500.0, "timestamp": "2026-01-07T10:00:00+00:00"},
        {"vertical": "sports", "symbol": "Lakers", "pnl": 80.0, "timestamp": "2026-01-08T10:00:00+00:00"},
        {"vertical": "sports", "symbol": "Warriors", "pnl": -30.0, "timestamp": "2026-01-09T10:00:00+00:00"},
    ]


def test_dashboard_data_initializes():
    dd = DashboardData(_sample_trades())
    assert dd is not None


def test_summary_stats():
    dd = DashboardData(_sample_trades())
    stats = dd.summary_stats()
    assert stats["total_pnl"] == pytest.approx(700.0)
    assert stats["trade_count"] == 5
    assert stats["win_rate"] == pytest.approx(0.6)


def test_pnl_by_vertical():
    dd = DashboardData(_sample_trades())
    by_v = dd.pnl_by_vertical()
    assert by_v["stocks"] == pytest.approx(150.0)
    assert by_v["crypto"] == pytest.approx(500.0)
    assert by_v["sports"] == pytest.approx(50.0)


def test_cumulative_pnl_series():
    dd = DashboardData(_sample_trades())
    series = dd.cumulative_pnl_series()
    assert isinstance(series, list)
    assert len(series) == 5
    assert series[-1]["cumulative_pnl"] == pytest.approx(700.0)


def test_build_plotly_figure_returns_dict():
    dd = DashboardData(_sample_trades())
    fig = dd.build_pnl_chart()
    # plotly Figure has a .to_dict() method
    assert hasattr(fig, "to_dict") or isinstance(fig, dict)
