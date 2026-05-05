"""
Computes pairwise return correlation across CRYPTO_WATCHLIST from
4h Coinbase OHLC. Cached on disk (alongside the SQLite DB on the
volume) so we don't recompute every scan. Refreshed once per day.

Used by the position-selection layer to penalize signals that are
just same-trade-different-wrapper of an already-picked symbol.
"""
import json
import time
import pathlib
import pandas as pd

from data.crypto.fetcher import get_crypto_ohlcv
from config import CRYPTO_WATCHLIST, DATA_DIR

CORR_CACHE_PATH = DATA_DIR / "correlations.json"
CORR_TTL_HOURS = 24


def _is_fresh(ts: float) -> bool:
    return (time.time() - ts) < CORR_TTL_HOURS * 3600


def _load_cache() -> dict | None:
    if not CORR_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CORR_CACHE_PATH.read_text())
        if not _is_fresh(data.get("ts", 0)):
            return None
        return data
    except Exception:
        return None


def _compute_fresh() -> dict:
    """Fetch 4h OHLC for all watchlist symbols, compute return correlations."""
    closes: dict[str, pd.Series] = {}
    for sym in CRYPTO_WATCHLIST:
        try:
            df = get_crypto_ohlcv(sym)  # 4h candles
            # ~75 4h candles ≈ 12.5 days. We'd prefer 30 days but Coinbase
            # 1h->4h resampling caps history at this length. 75 observations
            # is statistically valid for a correlation estimate, and recent
            # correlations matter more than long ones for portfolio risk.
            closes[sym] = df["close"].pct_change().dropna()
        except Exception as e:
            print(f"[correlation] skipped {sym}: {e}", flush=True)
    if len(closes) < 2:
        return {"ts": time.time(), "matrix": {}, "symbols": list(closes.keys())}
    df_returns = pd.DataFrame(closes).dropna()
    corr = df_returns.corr().round(3)
    matrix: dict[str, float] = {}
    for s1 in corr.index:
        for s2 in corr.columns:
            if s1 != s2:
                matrix[f"{s1}|{s2}"] = float(corr.loc[s1, s2])
    return {"ts": time.time(), "matrix": matrix, "symbols": list(corr.index)}


def get_correlation_matrix() -> dict:
    """Cached accessor. Returns {"ts", "matrix", "symbols"} dict."""
    cached = _load_cache()
    if cached is not None:
        return cached
    fresh = _compute_fresh()
    try:
        CORR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CORR_CACHE_PATH.write_text(json.dumps(fresh))
    except Exception as e:
        print(f"[correlation] cache write failed: {e}", flush=True)
    return fresh


def correlation(sym1: str, sym2: str, matrix: dict) -> float:
    """Look up correlation between two symbols. Defaults to 0.5 if unknown."""
    if sym1 == sym2:
        return 1.0
    key1 = f"{sym1}|{sym2}"
    key2 = f"{sym2}|{sym1}"
    return matrix.get(key1, matrix.get(key2, 0.5))
