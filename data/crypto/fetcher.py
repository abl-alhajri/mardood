"""
Mardood — Crypto Data Fetcher (CoinGecko)
"""
import time
import random
import requests
import pandas as pd
from config import CRYPTO_WATCHLIST

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

SYMBOL_TO_ID = {
    "BTCUSDT":   "bitcoin",
    "ETHUSDT":   "ethereum",
    "SOLUSDT":   "solana",
    "BNBUSDT":   "binancecoin",
    "XRPUSDT":   "ripple",
    "DOGEUSDT":  "dogecoin",
    "SHIBUSDT":  "shiba-inu",
    "PEPEUSDT":  "pepe",
    "WIFUSDT":   "dogwifcoin",
    "BONKUSDT":  "bonk",
    "FLOKIUSDT": "floki",
}

_CG_MAX_RETRIES = 5
_CG_BASE_DELAY = 1.0
_CG_MAX_DELAY = 30.0


def coingecko_get(path: str, params: dict | None = None, timeout: int = 10) -> dict:
    """
    GET <COINGECKO_BASE><path> with exponential backoff on 429/5xx/network errors.

    The free CoinGecko tier rate-limits aggressively (~10-30 req/min) and
    silently 429s. This wraps every call with up to 5 retries, honoring
    Retry-After when present and otherwise backing off 1/2/4/8/16s + jitter.
    """
    url = f"{COINGECKO_BASE}{path}"
    last_err: Exception | None = None
    for attempt in range(_CG_MAX_RETRIES):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("Retry-After")
                if retry_after:
                    delay = min(float(retry_after), _CG_MAX_DELAY)
                else:
                    delay = min(_CG_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), _CG_MAX_DELAY)
                last_err = requests.HTTPError(f"{r.status_code} from CoinGecko {path}")
                time.sleep(delay)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            time.sleep(min(_CG_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), _CG_MAX_DELAY))
    raise RuntimeError(f"CoinGecko: exhausted {_CG_MAX_RETRIES} retries for {path}: {last_err}")


BINANCE_BASE = "https://api.binance.com"


def get_crypto_ohlcv(symbol: str, interval: str = "5m", limit: int = 500) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Binance public klines API. Binance supports
    intra-hour granularities CoinGecko doesn't (and returns real volume,
    which CoinGecko's OHLC endpoint zeroes out).

    intervals: "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", ...
    limit:     max 1000 (default 500 ~= 41 hours of 5-min data)
    """
    r = requests.get(
        f"{BINANCE_BASE}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def get_crypto_price(symbol: str) -> float:
    coin_id = SYMBOL_TO_ID.get(symbol)
    if not coin_id:
        raise ValueError(f"Unknown symbol: {symbol}")

    data = coingecko_get("/simple/price", {"ids": coin_id, "vs_currencies": "usd"})
    return float(data[coin_id]["usd"])


def get_watchlist_data(interval: str = "5m", limit: int = 500) -> dict:
    return {symbol: get_crypto_ohlcv(symbol, interval=interval, limit=limit) for symbol in CRYPTO_WATCHLIST}
