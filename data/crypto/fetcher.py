"""
XYZTradingAE — Crypto Data Fetcher (Coinbase + CoinGecko)
"""
import time
import random
import requests
import pandas as pd
from config import CRYPTO_WATCHLIST

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

SYMBOL_TO_ID = {
    # CoinGecko slugs for the watchlist — used by news/sentiment helpers
    # (community votes, trending list) even though OHLCV and live prices
    # all flow through Coinbase. Every entry below also has a Coinbase
    # listing in COINBASE_SYMBOLS, so the CoinGecko OHLC/price fallback
    # in get_crypto_ohlcv / get_crypto_price is dead code today — kept
    # for emergency use if a symbol is delisted from Coinbase.
    "BTCUSDT":   "bitcoin",
    "SOLUSDT":   "solana",
    "XRPUSDT":   "ripple",
    "AVAXUSDT":  "avalanche-2",
    "LINKUSDT":  "chainlink",
    "DOTUSDT":   "polkadot",
    "ADAUSDT":   "cardano",
    "ARBUSDT":   "arbitrum",
    "OPUSDT":    "optimism",
    "UNIUSDT":   "uniswap",
    "SUIUSDT":   "sui",
    "TONUSDT":   "the-open-network",
    # POL = rebranded MATIC. CoinGecko slug "matic-network" is deprecated
    # (returns empty); the live slug is "polygon-ecosystem-token".
    "POLUSDT":   "polygon-ecosystem-token",
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


# Coinbase Exchange public market data — no auth, no geo-block, real volume,
# 5-minute candles. Used for symbols listed on Coinbase. Falls through to
# CoinGecko (30-min, no volume) for symbols Coinbase doesn't carry.
COINBASE_BASE = "https://api.exchange.coinbase.com"

COINBASE_SYMBOLS = {
    "BTCUSDT":  "BTC-USD",
    "SOLUSDT":  "SOL-USD",
    "XRPUSDT":  "XRP-USD",
    # Layer-1s and layer-2s added 2026-05 (probed live against
    # api.exchange.coinbase.com/products/<X>/stats and confirmed listed)
    "AVAXUSDT": "AVAX-USD",
    "LINKUSDT": "LINK-USD",
    "DOTUSDT":  "DOT-USD",
    "ADAUSDT":  "ADA-USD",
    "ARBUSDT":  "ARB-USD",
    "OPUSDT":   "OP-USD",
    "UNIUSDT":  "UNI-USD",
    "SUIUSDT":  "SUI-USD",
    "TONUSDT":  "TON-USD",
    "POLUSDT":  "POL-USD",   # rebranded from MATIC
    # All current CRYPTO_WATCHLIST symbols are on Coinbase. The CoinGecko
    # OHLC/price fallback in get_crypto_ohlcv / get_crypto_price is now
    # dead code on the production path — retained as an emergency
    # fallback if a symbol is delisted, not exercised on any scan.
    # Excluded from the watchlist (see config.py): BNB/TRX (CoinGecko
    # rate-limit pressure on Railway), ETH/DOGE/SHIB, all memes.
}


def coinbase_get(path: str, params: dict | None = None, timeout: int = 10):
    """GET <COINBASE_BASE><path>. Public, unauthenticated."""
    r = requests.get(f"{COINBASE_BASE}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_coinbase_ohlcv(symbol: str, granularity: int = 300, limit: int = 300) -> pd.DataFrame:
    """
    Fetch real OHLCV candles from Coinbase Exchange.
    granularity: seconds per candle. Valid: 60, 300, 900, 3600, 21600, 86400.
                 Default 300 = 5-minute candles.
    limit:       max 300 (Coinbase API caps at ~300 candles per request).
                 At 5-min granularity that's ~25 hours of history.
    """
    product_id = COINBASE_SYMBOLS[symbol]
    data = coinbase_get(
        f"/products/{product_id}/candles",
        params={"granularity": granularity},
    )
    # Coinbase response: [[time_unix_seconds, low, high, open, close, volume], ...]
    # newest-first; we sort to oldest-first for rolling/EWM windows.
    df = pd.DataFrame(data, columns=["timestamp", "low", "high", "open", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    df = df.tail(limit)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def _resample_ohlcv(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample finer-granularity OHLCV to a coarser frequency (e.g. 1h -> 4h)."""
    return df.resample(freq).agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()


def get_crypto_ohlcv(symbol: str, days: int = 30, granularity_seconds: int = 14400) -> pd.DataFrame:
    """
    OHLCV fetcher producing 4-HOUR candles by default. Coinbase is the
    only path exercised on production scans today — every CRYPTO_WATCHLIST
    symbol is in COINBASE_SYMBOLS. Coinbase does NOT support 4h natively
    (valid: 1m/5m/15m/1h/6h/1d), so we fetch 300 1-hour candles and
    resample to 4h, yielding ~75 4h candles (~12.5 days of history,
    real volume).

    The CoinGecko branch is retained as an emergency fallback for any
    symbol absent from COINBASE_SYMBOLS — it resolves to native 4-hour
    candles with zero volume. Not used by the live watchlist.
    """
    if symbol in COINBASE_SYMBOLS:
        if granularity_seconds == 14400:
            # 4h not natively supported by Coinbase — fetch 1h then resample.
            df_1h = get_coinbase_ohlcv(symbol, granularity=3600, limit=300)
            return _resample_ohlcv(df_1h, "4h")
        return get_coinbase_ohlcv(symbol, granularity=granularity_seconds, limit=300)

    # CoinGecko fallback — emergency only; no live watchlist symbol routes here.
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


def candle_interval_minutes(symbol: str) -> int:
    """All routes (Coinbase + CoinGecko) now produce 4h candles. Returns 240."""
    return 240


def get_coinbase_prices(symbols: list[str]) -> dict:
    """
    Live USD price + 24h change for symbols listed on Coinbase Exchange.
    One /products/{X-USD}/stats call per symbol, fanned out in parallel.
    Returns {SYMBOL: {price, change_pct}}; symbols not on Coinbase are skipped.
    """
    from concurrent.futures import ThreadPoolExecutor

    pairs = [(s, COINBASE_SYMBOLS[s]) for s in symbols if s in COINBASE_SYMBOLS]
    if not pairs:
        return {}

    def _one(sym_and_product):
        sym, product_id = sym_and_product
        try:
            d = coinbase_get(f"/products/{product_id}/stats", timeout=5)
            last = float(d["last"])
            opn = float(d["open"])
            chg = ((last - opn) / opn * 100) if opn > 0 else 0.0
            return sym, {"price": last, "change_pct": round(chg, 2)}
        except Exception as e:
            print(f"[coinbase] {sym} stats failed: {e}", flush=True)
            return sym, None

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(len(pairs), 6)) as ex:
        for sym, info in ex.map(_one, pairs):
            if info:
                out[sym] = info
    return out


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
    """CoinGecko fallback for symbols Coinbase doesn't carry."""
    coin_id = SYMBOL_TO_ID.get(symbol)
    if not coin_id:
        raise ValueError(f"Unknown symbol: {symbol}")

    data = coingecko_get("/simple/price", {"ids": coin_id, "vs_currencies": "usd"})
    return float(data[coin_id]["usd"])


def get_recent_high_low(symbol: str, lookback_minutes: int = 5) -> tuple[float, float] | None:
    """
    Returns (high, low) over the last `lookback_minutes` for a Coinbase
    symbol using 1-minute candles. Used to detect SL/TP wicks the spot
    sample missed between scans. Returns None for non-Coinbase symbols
    or on fetch failure (caller should fall back to spot).
    """
    if symbol not in COINBASE_SYMBOLS:
        return None
    product_id = COINBASE_SYMBOLS[symbol]
    try:
        data = coinbase_get(
            f"/products/{product_id}/candles",
            params={"granularity": 60},  # 1-minute candles
            timeout=5,
        )
    except Exception as e:
        print(f"[wick-check] {symbol} 1m candles failed: {e}", flush=True)
        return None
    if not data:
        return None
    # Coinbase returns newest-first: [time, low, high, open, close, volume]
    recent = data[:lookback_minutes]
    highs = [float(c[2]) for c in recent]
    lows = [float(c[1]) for c in recent]
    if not highs or not lows:
        return None
    return max(highs), min(lows)


def get_live_price(symbol: str) -> float:
    """
    Live USD price for a single symbol. Routes through the SAME source
    as get_crypto_ohlcv: Coinbase ticker for any symbol in COINBASE_SYMBOLS
    (every current watchlist entry), CoinGecko fallback otherwise.
    Keeps the brain, paper trader, and dashboard reasoning on prices from
    the same exchange so SL/TP triggers don't fire on cross-source drift.
    """
    if symbol in COINBASE_SYMBOLS:
        product_id = COINBASE_SYMBOLS[symbol]
        d = coinbase_get(f"/products/{product_id}/ticker", timeout=5)
        return float(d["price"])
    return get_crypto_price(symbol)


def get_watchlist_data(days: int = 1) -> dict:
    return {symbol: get_crypto_ohlcv(symbol, days=days) for symbol in CRYPTO_WATCHLIST}
