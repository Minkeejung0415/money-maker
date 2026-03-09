# alpha/data/storage/sqlite.py
import sqlite3
import json
from pathlib import Path
from alpha.data.storage.schema import CREATE_TABLES_SQL

DEFAULT_DB = Path(__file__).parent.parent.parent.parent / "data" / "alpha.db"


class AlphaDB:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DEFAULT_DB)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(CREATE_TABLES_SQL)

    def list_tables(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        return [r["name"] for r in rows]

    def insert_price(self, symbol, date, open_, high, low, close, volume, asset_type):
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO prices
                   (symbol, date, open, high, low, close, volume, asset_type)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (symbol, date, open_, high, low, close, volume, asset_type),
            )

    def fetch_prices(self, symbol: str, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM prices WHERE symbol=? ORDER BY date DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_signal(self, symbol, vertical, signal_type, value, confidence=None, meta=None):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO signals (symbol, vertical, signal_type, value, confidence, meta)
                   VALUES (?,?,?,?,?,?)""",
                (symbol, vertical, signal_type, value, confidence,
                 json.dumps(meta) if meta else None),
            )

    def insert_odds(self, sport, league, event, market, book,
                    odds_home, odds_away, odds_draw=None, ev_home=None, ev_away=None):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO odds
                   (sport, league, event, market, book,
                    odds_home, odds_away, odds_draw, ev_home, ev_away)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sport, league, event, market, book,
                 odds_home, odds_away, odds_draw, ev_home, ev_away),
            )
