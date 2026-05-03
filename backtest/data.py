"""
Historical OHLCV fetcher for the backtest harness.

Coinbase Exchange's public /candles endpoint returns at most 300 candles
per request, so we paginate backwards through the requested window. Cached
to disk as pickled DataFrames so re-runs are essentially free.
"""
from __future__ import annotations

import time
import pathlib
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from data.crypto.fetcher import COINBASE_SYMBOLS

CACHE_DIR = pathlib.Path(__file__).parent / "cache" / "ohlcv"
COINBASE_BASE = "https://api.exchange.coinbase.com"
MAX_CANDLES_PER_REQUEST = 300
INTER_REQUEST_PAUSE = 0.15  # be polite to the public endpoint


def _fetch_chunk(product_id: str, start: datetime, end: datetime, granularity: int) -> list:
    """Fetch up to MAX_CANDLES_PER_REQUEST candles in [start, end]."""
    r = requests.get(
        f"{COINBASE_BASE}/products/{product_id}/candles",
        params={
            "granularity": granularity,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _fetch_paginated(product_id: str, start_dt: datetime, end_dt: datetime,
                    granularity: int = 300) -> pd.DataFrame:
    """Walk backwards from end_dt to start_dt, MAX_CANDLES candles per chunk."""
    chunk_seconds = MAX_CANDLES_PER_REQUEST * granularity
    candles: list = []
    cur_end = end_dt

    while cur_end > start_dt:
        cur_start = max(start_dt, cur_end - timedelta(seconds=chunk_seconds))
        try:
            chunk = _fetch_chunk(product_id, cur_start, cur_end, granularity)
        except requests.HTTPError as e:
            print(f"[backtest.data] {product_id} chunk {cur_start.date()} failed: {e}", flush=True)
            break
        if not chunk:
            break

        candles.extend(chunk)
        oldest_ts = min(c[0] for c in chunk)
        cur_end = datetime.fromtimestamp(oldest_ts, tz=timezone.utc) - timedelta(seconds=granularity)
        time.sleep(INTER_REQUEST_PAUSE)

    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    # Coinbase columns: [time_unix, low, high, open, close, volume]
    df = pd.DataFrame(candles, columns=["timestamp", "low", "high", "open", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.drop_duplicates(subset="timestamp").set_index("timestamp").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def get_historical_ohlcv(symbol: str, days: int = 90, granularity: int = 300,
                        force_refresh: bool = False) -> pd.DataFrame:
    """
    Get `days` worth of OHLCV ending now, at `granularity` seconds per candle.
    Cached on disk as a pickle, keyed by (symbol, days, granularity).

    Only Coinbase symbols are supported in the harness — the CoinGecko
    fallback path returns 30-min candles with no volume, which would
    distort backtest signals vs. production behavior on the 6 majors.
    """
    if symbol not in COINBASE_SYMBOLS:
        raise ValueError(
            f"{symbol} is not in COINBASE_SYMBOLS — backtest only supports "
            f"the 6 Coinbase-listed majors for clean 5-min OHLCV with volume."
        )
    product_id = COINBASE_SYMBOLS[symbol]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{symbol}_{days}d_{granularity}s.pkl"

    if cache_path.exists() and not force_refresh:
        return pd.read_pickle(cache_path)

    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)

    print(f"[backtest.data] Fetching {symbol} ({product_id}) {days}d @ {granularity}s "
          f"from {start.date()} to {end.date()}...", flush=True)
    df = _fetch_paginated(product_id, start, end, granularity)
    if df.empty:
        raise RuntimeError(f"No OHLCV returned for {symbol}")

    df.to_pickle(cache_path)
    print(f"[backtest.data] Cached {len(df)} candles -> {cache_path.name}", flush=True)
    return df
