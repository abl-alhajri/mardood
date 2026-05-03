"""
Strategy adapters for the backtest harness.

Two modes:
  - heuristic: rule-based, free, fast — validates the harness end-to-end
                without paying for inference. Mimics the brain's general
                bias toward technical-confirmation setups.
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

CACHE_DB = pathlib.Path(__file__).parent / "cache" / "brain.db"


# ─── HEURISTIC MODE ─────────────────────────────────────────────────────────

def heuristic_decision(indicators: dict) -> dict:
    """
    Cheap rule-based stand-in for the brain. Mirrors the production
    decision-framework's "two confirming layers" gate:
      - Bullish stack + RSI 50-70 + MACD widening + volume_spike => high-conf BUY
      - Bullish stack + MACD crossed up                         => mid-conf BUY
      - Bearish reversal across 3 indicators                    => SELL
      - Otherwise                                                => HOLD
    """
    rsi = float(indicators.get("rsi", 50))
    macd_hist = float(indicators.get("macd_hist", 0))
    macd_crossed_up = bool(indicators.get("macd_crossed_up", False))
    bb_pos = float(indicators.get("bb_position", 0.5))
    above_ema20 = bool(indicators.get("above_ema20", False))
    above_ema50 = bool(indicators.get("above_ema50", False))
    above_ema200 = bool(indicators.get("above_ema200", False))
    volume_spike = bool(indicators.get("volume_spike", False))

    bullish_stack = above_ema20 and above_ema50 and above_ema200
    bearish_stack = (not above_ema20) and (not above_ema50)

    # Confirmed-breakout long
    if bullish_stack and macd_crossed_up and 50 <= rsi <= 75 and bb_pos > 0.6 and volume_spike:
        return {
            "signal": "BUY", "confidence": 0.82,
            "reasoning": f"bullish stack + macd_crossed_up + RSI {rsi:.0f} + bb {bb_pos:.2f} + volume_spike",
            "key_factors": ["EMA stack", "MACD cross", "volume spike"],
            "risk_level": "MEDIUM", "timeframe": "SHORT",
        }
    # Mid-confidence long: stack + cross, no volume confirmation
    if bullish_stack and macd_crossed_up and rsi > 50:
        return {
            "signal": "BUY", "confidence": 0.65,
            "reasoning": f"bullish stack + macd_crossed_up + RSI {rsi:.0f}, no volume confirm",
            "key_factors": ["EMA stack", "MACD cross"],
            "risk_level": "MEDIUM", "timeframe": "SHORT",
        }
    # Sell: bearish reversal
    if bearish_stack and macd_hist < 0 and rsi < 50:
        return {
            "signal": "SELL", "confidence": 0.70,
            "reasoning": f"bearish stack + MACD hist {macd_hist:.4f} + RSI {rsi:.0f}",
            "key_factors": ["bearish stack", "MACD negative"],
            "risk_level": "MEDIUM", "timeframe": "SHORT",
        }
    return {
        "signal": "HOLD", "confidence": 0.50,
        "reasoning": "no clean setup",
        "key_factors": [],
        "risk_level": "LOW", "timeframe": "SHORT",
    }


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
