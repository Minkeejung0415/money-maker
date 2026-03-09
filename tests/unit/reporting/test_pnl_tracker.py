import pytest
from alpha.reporting.pnl_tracker import PnLTracker


def test_tracker_initializes():
    tracker = PnLTracker()
    assert tracker.total_pnl() == 0.0


def test_record_win():
    tracker = PnLTracker()
    tracker.record_trade(
        vertical="stocks", symbol="AAPL",
        entry_price=150.0, exit_price=160.0,
        quantity=10, side="long"
    )
    assert tracker.total_pnl() == pytest.approx(100.0)


def test_record_loss():
    tracker = PnLTracker()
    tracker.record_trade(
        vertical="crypto", symbol="BTC/USDT",
        entry_price=42000.0, exit_price=40000.0,
        quantity=0.1, side="long"
    )
    assert tracker.total_pnl() == pytest.approx(-200.0)


def test_pnl_by_vertical():
    tracker = PnLTracker()
    tracker.record_trade("stocks", "AAPL", 150.0, 160.0, 10, "long")
    tracker.record_trade("crypto", "ETH/USDT", 3000.0, 2800.0, 1.0, "long")
    by_v = tracker.pnl_by_vertical()
    assert by_v["stocks"] == pytest.approx(100.0)
    assert by_v["crypto"] == pytest.approx(-200.0)


def test_win_rate():
    tracker = PnLTracker()
    tracker.record_trade("stocks", "AAPL", 150.0, 160.0, 10, "long")
    tracker.record_trade("stocks", "MSFT", 300.0, 290.0, 5, "long")
    assert tracker.win_rate() == pytest.approx(0.5)


def test_trade_count():
    tracker = PnLTracker()
    tracker.record_trade("sports", "Lakers", 0, 0, 0, "bet", pnl=50.0)
    tracker.record_trade("sports", "Warriors", 0, 0, 0, "bet", pnl=-20.0)
    assert tracker.trade_count() == 2
