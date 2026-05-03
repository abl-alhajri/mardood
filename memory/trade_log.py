"""
XYZTradingAE — Trade Memory
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
        # WAL: concurrent reader + writer (dashboard + scanner) without locking.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
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
        # Shadow comparison: brain vs heuristic on every scan.
        # Outcome columns are NULL on insert; backfilled later by an
        # outcome-resolution pass that walks forward N candles to see
        # which side's recommendation would have been profitable.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_decisions (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp             TEXT NOT NULL,
                symbol                TEXT NOT NULL,
                price                 REAL,
                brain_signal          TEXT,
                brain_confidence      REAL,
                brain_reasoning       TEXT,
                brain_risk_level      TEXT,
                brain_error           TEXT,
                heuristic_signal      TEXT,
                heuristic_confidence  REAL,
                heuristic_reasoning   TEXT,
                agree                 INTEGER,
                indicators_json       TEXT,
                btc_regime_bullish    INTEGER,
                outcome_pnl_pct       REAL,
                outcome_resolved_at   TEXT,
                outcome_kind          TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_ts ON shadow_decisions(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_symbol ON shadow_decisions(symbol)")
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


def log_shadow_decision(
    symbol: str,
    price: float,
    brain_signal: dict,
    heuristic_signal: dict,
    indicators: dict,
    btc_regime_bullish: bool,
):
    """
    Log brain's vs heuristic's decision on identical inputs. Captures the
    indicators snapshot so a later outcome-resolution job can backfill
    'would this BUY have been profitable'.
    """
    brain_sig = (brain_signal or {}).get("signal")
    heur_sig = (heuristic_signal or {}).get("signal")
    agree = 1 if (brain_sig == heur_sig and brain_sig is not None) else 0

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO shadow_decisions
                (timestamp, symbol, price,
                 brain_signal, brain_confidence, brain_reasoning, brain_risk_level, brain_error,
                 heuristic_signal, heuristic_confidence, heuristic_reasoning,
                 agree, indicators_json, btc_regime_bullish)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(), symbol, price,
            brain_sig, (brain_signal or {}).get("confidence"),
            (brain_signal or {}).get("reasoning", ""),
            (brain_signal or {}).get("risk_level"),
            (brain_signal or {}).get("error"),
            heur_sig, (heuristic_signal or {}).get("confidence"),
            (heuristic_signal or {}).get("reasoning", ""),
            agree, json.dumps(indicators, default=str),
            int(bool(btc_regime_bullish)),
        ))
        conn.commit()


def get_shadow_summary(limit: int = 1000) -> dict:
    """Quick stats on the shadow_decisions table for the dashboard or CLI."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM shadow_decisions").fetchone()[0]
        if total == 0:
            return {"total": 0}
        recent = conn.execute(
            "SELECT brain_signal, heuristic_signal, agree FROM shadow_decisions "
            "ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        agreement = sum(1 for r in recent if r[2] == 1) / len(recent) * 100
        brain_buys = sum(1 for r in recent if r[0] == "BUY")
        heur_buys = sum(1 for r in recent if r[1] == "BUY")
    return {
        "total": total,
        "sampled": len(recent),
        "agreement_pct": round(agreement, 1),
        "brain_buy_rate_pct": round(brain_buys / len(recent) * 100, 1),
        "heuristic_buy_rate_pct": round(heur_buys / len(recent) * 100, 1),
    }


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
