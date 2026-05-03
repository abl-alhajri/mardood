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

def heuristic_decision(indicators: dict, btc_regime_bullish: bool = True) -> dict:
    """
    Single high-conviction BUY path. After 90d backtest analysis, the
    prior two-tier emission produced too many low-quality setups. This
    version requires SIX confirming layers in conjunction:

      1. BTC regime: BTC above its 1h EMA200 (broad market trending up)
      2. Bullish EMA stack on the symbol (price > EMA20 > EMA50 > EMA200)
      3. MACD histogram meaningfully positive (> 0.05% of price — filters
         micro-crosses near zero AND captures established momentum without
         requiring a same-bar cross event, which is too rare to combine
         with the other filters)
      4. RSI in 55-70 (bullish without being overbought; the 70-75 zone
         was producing late-entry losers in v2)
      5. bb_position > 0.65 (price actively breaking out, not mid-range)
      6. volume_spike=true (real breakout, not chop)

    No SELL emission — exits via SL/TP only.
    """
    rsi = float(indicators.get("rsi", 50))
    macd_hist = float(indicators.get("macd_hist", 0))
    bb_pos = float(indicators.get("bb_position", 0.5))
    above_ema20 = bool(indicators.get("above_ema20", False))
    above_ema50 = bool(indicators.get("above_ema50", False))
    above_ema200 = bool(indicators.get("above_ema200", False))
    volume_spike = bool(indicators.get("volume_spike", False))
    price = float(indicators.get("price", 0))

    bullish_stack = above_ema20 and above_ema50 and above_ema200

    # MACD histogram normalized to price scale. A literal threshold doesn't
    # work across BTC ($78K, hist in dollars) and SHIB ($0.000006, hist
    # microscopic). 0.0005 = 0.05% of price filters near-zero values.
    macd_hist_pct = (macd_hist / price) if price > 0 else 0.0
    macd_meaningful = macd_hist_pct > 0.0005

    if (
        btc_regime_bullish
        and bullish_stack
        and macd_meaningful
        and 55 <= rsi <= 70
        and bb_pos > 0.65
        and volume_spike
    ):
        return {
            "signal": "BUY", "confidence": 0.82,
            "reasoning": (
                f"BTC trend OK + bullish stack + MACD hist {macd_hist_pct*100:.3f}% "
                f"+ RSI {rsi:.0f} + bb {bb_pos:.2f} + volume_spike"
            ),
            "key_factors": ["BTC regime", "EMA stack", "MACD momentum", "volume spike"],
            "risk_level": "MEDIUM", "timeframe": "SHORT",
        }

    return {
        "signal": "HOLD", "confidence": 0.50,
        "reasoning": "no high-conviction setup",
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
