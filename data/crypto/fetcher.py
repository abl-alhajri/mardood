"""
Mardood — Crypto Data Fetcher
"""
import requests
import pandas as pd
from config import CRYPTO_WATCHLIST

BINANCE_BASE = "https://api.binance.com/api/v3"


def get_crypto_ohlcv(symbol: str, interval: str = "1d", limit: int = 90) -> pd.DataFrame:
    url = f"{BINANCE_BASE}/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def get_crypto_price(symbol: str) -> float:
    url = f"{BINANCE_BASE}/ticker/price"
    response = requests.get(url, params={"symbol": symbol}, timeout=10)
    response.raise_for_status()
    return float(response.json()["price"])


def get_watchlist_data(interval: str = "1d") -> dict:
    return {symbol: get_crypto_ohlcv(symbol, interval) for symbol in CRYPTO_WATCHLIST}