# alpha/data/storage/schema.py
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL NOT NULL,
    volume      REAL,
    asset_type  TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, date, asset_type)
);

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    vertical    TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    value       REAL NOT NULL,
    confidence  REAL,
    meta        TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    vertical    TEXT NOT NULL,
    side        TEXT NOT NULL,
    qty         REAL NOT NULL,
    price       REAL NOT NULL,
    status      TEXT NOT NULL,
    paper       INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now')),
    closed_at   TEXT
);

CREATE TABLE IF NOT EXISTS odds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sport       TEXT NOT NULL,
    league      TEXT NOT NULL,
    event       TEXT NOT NULL,
    market      TEXT NOT NULL,
    book        TEXT NOT NULL,
    odds_home   REAL,
    odds_away   REAL,
    odds_draw   REAL,
    ev_home     REAL,
    ev_away     REAL,
    scraped_at  TEXT DEFAULT (datetime('now'))
);
"""
