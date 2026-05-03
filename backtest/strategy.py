"""
Strategy adapters for the backtest harness.

Two modes:
  - heuristic: rule-based, free, fast — validates the harness end-to-end
                without paying for inference. Implementation lives in
                analysis/heuristic.py and is shared with production
                shadow mode.
  - brain:     calls Claude with the production system prompt + tool
                schema. Cached on disk by (symbol, candle_ts,
                indicators_hash) so re-runs are free after the first.

Both return the same dict shape: {signal, confidence, reasoning, ...}
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
import threading
from typing import Optional

# Re-exported so existing backtest imports keep working.
from analysis.heuristic import heuristic_decision  # noqa: F401

CACHE_DB = pathlib.Path(__file__).parent / "cache" / "brain.db"


# ─── BRAIN MODE (cached) ────────────────────────────────────────────────────

class BrainCache:
    """Thread-safe SQLite-backed cache for brain responses."""

    def __init__(self, path: pathlib.Path = CACHE_DB):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            "key TEXT PRIMARY KEY, response TEXT, created_at TEXT)"
        )
        self._conn.commit()

    @staticmethod
    def make_key(symbol: str, candle_ts: str, indicators: dict) -> str:
        # Round indicators to stabilize keys against float jitter
        stable = {
            k: (round(v, 6) if isinstance(v, float) else v)
            for k, v in sorted(indicators.items())
        }
        payload = json.dumps({"sym": symbol, "ts": candle_ts, "ind": stable},
                             sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(payload.encode()).hexdigest()

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM responses WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, response: dict):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, datetime('now'))",
                (key, json.dumps(response)),
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        return {"entries": n, "path": str(self.path)}


def brain_decision(symbol: str, candle_ts: str, indicators: dict,
                   cache: BrainCache) -> dict:
    """
    Cached brain call. On cache hit, free. On cache miss, calls Claude
    with the production system prompt + tool schema. News context is
    omitted (historical news isn't easily retrievable); brain reasons
    on technicals only.
    """
    key = cache.make_key(symbol, candle_ts, indicators)
    cached = cache.get(key)
    if cached:
        return cached

    # Lazy-import so heuristic mode doesn't even touch the anthropic SDK
    from analysis.brain import analyze
    response = analyze(symbol, "crypto", indicators, news_summary="")
    cache.put(key, response)
    return response
