"""
Mardood — Trade Memory
Stores all signals and trades in a local SQLite database.
"""
import sqlite3
import json
from datetime import datetime
from config import MEMORY_DB

# Ensure the folder exists
MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    return sqlite3.connect(MEMORY_DB)


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                asset_type  TEXT NOT NULL,
                signal      TEXT NOT NULL,
                confidence  REAL,
                reasoning   TEXT,
                risk_level  TEXT,
                full_data   TEXT,
                acted_on    INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TEXT NOT NULL,
                symbol        TEXT NOT NULL,
                side          TEXT NOT NULL,
                quantity      REAL,
                entry_price   REAL,
                exit_price    REAL,
                pnl           REAL,
                status        TEXT DEFAULT 'OPEN',
                notes         TEXT
            )
        """)
        conn.commit()


def log_signal(signal: dict):
    """Save a signal to the database."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO signals
                (timestamp, symbol, asset_type, signal, confidence, reasoning, risk_level, full_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            signal.get("symbol"),
            signal.get("asset_type"),
            signal.get("signal"),
            signal.get("confidence"),
            signal.get("reasoning"),
            signal.get("risk_level"),
            json.dumps(signal)
        ))
        conn.commit()


def log_signals(signals: list):
    """Save multiple signals."""
    for s in signals:
        log_signal(s)


def get_recent_signals(limit: int = 20) -> list:
    """Retrieve recent signals as a list of dicts."""
    with get_conn() as conn:
        cursor = conn.execute(
            "SELECT id, timestamp, symbol, asset_type, signal, confidence, reasoning, risk_level "
            "FROM signals ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def get_stats() -> dict:
    """Return basic signal statistics."""
    with get_conn() as conn:
        total  = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        buys   = conn.execute("SELECT COUNT(*) FROM signals WHERE signal='BUY'").fetchone()[0]
        sells  = conn.execute("SELECT COUNT(*) FROM signals WHERE signal='SELL'").fetchone()[0]
        holds  = conn.execute("SELECT COUNT(*) FROM signals WHERE signal='HOLD'").fetchone()[0]
    return {"total": total, "buy": buys, "sell": sells, "hold": holds}


# Initialize on import
init_db()
