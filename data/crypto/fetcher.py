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


def get_crypto_ohlcv(symbol: str, days: int = 1) -> pd.DataFrame:
    """
    Fetch OHLC candles from CoinGecko (Binance is geo-blocked from US infra
    like Railway us-west2). Granularity is dictated by `days`:
        days = 1   -> 30-min candles, ~48 of them   (closest to 5-min on free tier)
        days = 2   -> 30-min candles, ~96 of them
        days = 30  -> 4-hour  candles
        days = 90+ -> 4-day   candles

    Volume is unavailable on this endpoint (CoinGecko's /ohlc returns price-only),
    so the volume column is filled with zeros. The downstream volume_ratio /
    volume_spike features degrade gracefully to neutral values.
    """
    coin_id = SYMBOL_TO_ID.get(symbol)
    if not coin_id:
        raise ValueError(f"Unknown symbol: {symbol}")

    data = coingecko_get(f"/coins/{coin_id}/ohlc", {"vs_currency": "usd", "days": days})

    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df["volume"] = 0.0  # CoinGecko OHLC endpoint does not provide volume
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def get_simple_prices(symbols: list[str]) -> dict:
    """
    Fetch live USD prices + 24h change for many symbols in ONE CoinGecko call.
    Used by the dashboard's price grid. Returns {SYMBOL: {price, change_pct}}.
    """
    coin_ids = [SYMBOL_TO_ID[s] for s in symbols if s in SYMBOL_TO_ID]
    if not coin_ids:
        return {}
    data = coingecko_get(
        "/simple/price",
        {
            "ids": ",".join(coin_ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        },
    )
    id_to_sym = {v: k for k, v in SYMBOL_TO_ID.items()}
    out: dict[str, dict] = {}
    for coin_id, info in data.items():
        sym = id_to_sym.get(coin_id)
        if not sym or "usd" not in info:
            continue
        out[sym] = {
            "price": float(info["usd"]),
            "change_pct": round(float(info.get("usd_24h_change", 0) or 0), 2),
        }
    return out


def get_crypto_price(symbol: str) -> float:
    coin_id = SYMBOL_TO_ID.get(symbol)
    if not coin_id:
        raise ValueError(f"Unknown symbol: {symbol}")

    data = coingecko_get("/simple/price", {"ids": coin_id, "vs_currencies": "usd"})
    return float(data[coin_id]["usd"])


def get_watchlist_data(days: int = 1) -> dict:
    return {symbol: get_crypto_ohlcv(symbol, days=days) for symbol in CRYPTO_WATCHLIST}
