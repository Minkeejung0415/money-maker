"""
Immutable audit log backed by SQLite.
Only supports append and fetch — no updates or deletes.
All trades, signals, and risk events are permanently recorded.
"""
import json
import sqlite3
from datetime import datetime, timezone


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    vertical    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    details     TEXT NOT NULL
)
"""


class AuditLog:
    def __init__(self, db_path: str = "data/audit.db"):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(CREATE_TABLE)
        self._conn.commit()

    def append(
        self,
        event_type: str,
        vertical: str,
        symbol: str,
        details: dict,
    ) -> int:
        """Append a new audit record. Returns the new row id."""
        cursor = self._conn.execute(
            "INSERT INTO audit_log (timestamp, event_type, vertical, symbol, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                event_type,
                vertical,
                symbol,
                json.dumps(details),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def fetch_all(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY id"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def fetch_by_vertical(self, vertical: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE vertical = ? ORDER BY id",
            (vertical,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def fetch_by_event_type(self, event_type: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE event_type = ? ORDER BY id",
            (event_type,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["details"] = json.loads(d["details"])
        return d

    def close(self):
        self._conn.close()
