import pytest
from alpha.data.storage.sqlite import AlphaDB
from alpha.data.storage.schema import CREATE_TABLES_SQL


def test_db_creates_tables(tmp_path):
    db = AlphaDB(db_path=str(tmp_path / "test.db"))
    tables = db.list_tables()
    assert "prices" in tables
    assert "signals" in tables
    assert "trades" in tables
    assert "odds" in tables


def test_db_insert_and_fetch_price(tmp_path):
    db = AlphaDB(db_path=str(tmp_path / "test.db"))
    db.insert_price("AAPL", "2026-01-01", 180.50, 181.00, 179.50, 180.75, 1_000_000, "stock")
    rows = db.fetch_prices("AAPL", limit=1)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["close"] == 180.75
