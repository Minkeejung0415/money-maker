import os
import tempfile
import pytest
from alpha.reporting.audit_log import AuditLog


@pytest.fixture
def tmp_log(tmp_path):
    db_path = str(tmp_path / "audit_test.db")
    log = AuditLog(db_path=db_path)
    yield log
    log.close()


def test_audit_log_initializes(tmp_log):
    assert tmp_log is not None


def test_append_creates_record(tmp_log):
    tmp_log.append(
        event_type="trade_open",
        vertical="stocks",
        symbol="AAPL",
        details={"price": 150.0, "qty": 10},
    )
    records = tmp_log.fetch_all()
    assert len(records) == 1
    assert records[0]["event_type"] == "trade_open"


def test_append_multiple_records(tmp_log):
    for i in range(5):
        tmp_log.append("signal", "crypto", f"BTC_{i}", {"score": i * 0.1})
    records = tmp_log.fetch_all()
    assert len(records) == 5


def test_fetch_by_vertical(tmp_log):
    tmp_log.append("trade_open", "stocks", "AAPL", {})
    tmp_log.append("trade_open", "crypto", "ETH", {})
    tmp_log.append("trade_close", "stocks", "MSFT", {})
    stocks = tmp_log.fetch_by_vertical("stocks")
    assert len(stocks) == 2


def test_records_are_immutable(tmp_log):
    """Audit log should not allow updates — only appends."""
    tmp_log.append("trade_open", "sports", "Lakers", {"stake": 100})
    records = tmp_log.fetch_all()
    assert len(records) == 1
    # No update method exists
    assert not hasattr(tmp_log, "update")
    assert not hasattr(tmp_log, "delete")
