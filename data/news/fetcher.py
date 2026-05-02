"""
Mardood — News & Data Sources
Finnhub, CoinGecko (with retry), mempool.space, alternative.me, Google Trends
"""
import os
import requests
from dotenv import load_dotenv
from data.crypto.fetcher import coingecko_get

load_dotenv()

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN")


# ─── FINNHUB (stocks) ───────────────────────────────────────────────────────

def get_stock_news(ticker: str) -> str:
    try:
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={week_ago}&to={today}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=5)
        articles = r.json()[:5]
        if not articles:
            return "No recent news."
        return "\n".join([f"- {a.get('headline','')}" for a in articles])
    except Exception:
        return "News unavailable."


def get_finnhub_sentiment(ticker: str) -> str:
    try:
        url = f"https://finnhub.io/api/v1/news-sentiment?symbol={ticker}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=5)
        d = r.json()
        score = d.get("companyNewsScore", 0)
        bullish = d.get("sentiment", {}).get("bullishPercent", 0)
        return f"News sentiment score: {score:.2f}, Bullish: {bullish*100:.1f}%"
    except Exception:
        return "Sentiment unavailable."


def get_insider_trading(ticker: str) -> str:
    try:
        url = f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=5)
        data = r.json().get("data", [])[:5]
        if not data:
            return "No recent insider transactions."
        lines = []
        for t in data:
            name = t.get("name", "Unknown")
            change = t.get("change", 0)
            action = "BUY" if change > 0 else "SELL"
            shares = abs(change)
            lines.append(f"- {name}: {action} {shares:,} shares")
        return "Insider transactions:\n" + "\n".join(lines)
    except Exception:
        return "Insider data unavailable."


# ─── CRYPTO COMMUNITY (CoinGecko, retry-wrapped) ────────────────────────────

_COIN_NAME_MAP = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
    "bnb": "binancecoin", "xrp": "ripple", "doge": "dogecoin",
    "shib": "shiba-inu", "pepe": "pepe", "wif": "dogwifcoin",
    "bonk": "bonk", "floki": "floki",
}


def get_crypto_news(symbol: str) -> str:
    try:
        coin = symbol.replace("USDT", "").lower()
        coin_id = _COIN_NAME_MAP.get(coin, coin)
        d = coingecko_get(
            f"/coins/{coin_id}",
            {"localization": "false", "tickers": "false", "market_data": "false", "community_data": "true"},
        )
        up = d.get("sentiment_votes_up_percentage") or 0
        down = d.get("sentiment_votes_down_percentage") or 0
        return f"Community sentiment: {up:.1f}% bullish, {down:.1f}% bearish."
    except Exception:
        return "Community sentiment unavailable."


def get_coingecko_trending() -> str:
    try:
        d = coingecko_get("/search/trending")
        coins = d.get("coins", [])[:5]
        names = [c["item"]["name"] for c in coins]
        return f"CoinGecko Trending: {', '.join(names)}"
    except Exception:
        return "Trending unavailable."


# ─── GOOGLE TRENDS ──────────────────────────────────────────────────────────

def get_google_trends(symbol: str) -> str:
    try:
        clean = symbol.replace("USDT", "")
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
        r = requests.get(url, timeout=5)
        if clean.upper() in r.text.upper():
            return f"Google Trends: {clean} is TRENDING in the US right now."
        return f"Google Trends: {clean} not in current US trending topics."
    except Exception:
        return ""


# ─── BITCOIN ON-CHAIN (mempool.space) ───────────────────────────────────────

def _mempool_get(path: str, *, json_resp: bool = True, timeout: int = 5):
    r = requests.get(f"https://mempool.space{path}", timeout=timeout)
    r.raise_for_status()
    return r.json() if json_resp else r.text.strip()


def get_btc_onchain_summary() -> str:
    """Market-wide BTC on-chain snapshot — useful context for any crypto signal."""
    try:
        fees = _mempool_get("/api/v1/fees/recommended")
        mempool = _mempool_get("/api/mempool")
        height = _mempool_get("/api/blocks/tip/height", json_resp=False)
    except Exception:
        return ""

    pending = mempool.get("count", 0)
    vsize_mb = mempool.get("vsize", 0) / 1_000_000
    fast = fees.get("fastestFee", 0)
    half_hour = fees.get("halfHourFee", 0)
    activity = "HIGH" if pending > 50_000 else "MEDIUM" if pending > 20_000 else "LOW"

    lines = [
        "BTC On-chain (mempool.space):",
        f"- Block height: {height}",
        f"- Mempool: {pending:,} pending txs ({vsize_mb:.1f} MB virtual size) — activity: {activity}",
        f"- Recommended fees: {fast} sat/vB (fast), {half_hour} sat/vB (30-min)",
    ]

    # Last block details — gives a sense of settlement velocity
    try:
        recent = _mempool_get("/api/v1/blocks")
        if recent:
            lb = recent[0]
            lines.append(
                f"- Last block #{lb.get('height')}: {lb.get('tx_count', 0):,} txs, "
                f"{lb.get('size', 0) / 1_000_000:.2f} MB"
            )
    except Exception:
        pass

    # Hashrate trend — proxy for miner conviction
    try:
        hr = _mempool_get("/api/v1/mining/hashrate/3d")
        cur = hr.get("currentHashrate")
        if cur:
            lines.append(f"- Hashrate: {cur / 1e18:.2f} EH/s (3d avg)")
    except Exception:
        pass

    return "\n".join(lines)


def get_eth_onchain_summary() -> str:
    try:
        r = requests.get("https://beaconcha.in/api/v1/execution/gasnow", timeout=5)
        d = r.json().get("data", {})
        fast = d.get("fast", 0) // 1_000_000_000
        return f"ETH On-chain: Gas {fast} Gwei (fast)"
    except Exception:
        return ""


def get_onchain_data(symbol: str) -> str:
    clean = symbol.replace("USDT", "").lower()
    if clean == "btc":
        return get_btc_onchain_summary()
    if clean == "eth":
        return get_eth_onchain_summary()
    return ""


# ─── FEAR & GREED (alternative.me, with trend) ──────────────────────────────

def get_fear_greed_index() -> str:
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=8", timeout=5)
        data = r.json().get("data", [])
        if not data:
            return "Fear & Greed unavailable."
    except Exception:
        return "Fear & Greed unavailable."

    today = data[0]
    today_val = int(today["value"])
    classification = today["value_classification"]
    line = f"Fear & Greed Index: {today_val}/100 — {classification}"

    def _fmt_delta(d: int) -> str:
        if d > 0:
            return f"+{d}"
        if d < 0:
            return str(d)
        return "+0"

    if len(data) >= 2:
        d1 = int(data[1]["value"])
        trend_parts = [f"{_fmt_delta(today_val - d1)} vs yesterday"]
        if len(data) >= 8:
            d7 = int(data[7]["value"])
            trend_parts.append(f"{_fmt_delta(today_val - d7)} vs 7d ago ({data[7]['value_classification']})")
        line += " (" + ", ".join(trend_parts) + ")"
    return line


# ─── MAIN AGGREGATOR ────────────────────────────────────────────────────────

def get_full_context(symbol: str, asset_type: str) -> str:
    lines = [get_fear_greed_index()]

    if asset_type == "stock":
        lines.append(get_stock_news(symbol))
        lines.append(get_finnhub_sentiment(symbol))
        lines.append(get_insider_trading(symbol))
        lines.append(get_google_trends(symbol))
    else:
        # BTC mempool is a market-wide signal — include for every crypto, not
        # just BTC itself. Altcoins ride BTC's liquidity tide.
        btc_chain = get_btc_onchain_summary()
        if btc_chain:
            lines.append(btc_chain)

        clean = symbol.replace("USDT", "").lower()
        if clean == "eth":
            eth_chain = get_eth_onchain_summary()
            if eth_chain:
                lines.append(eth_chain)

        lines.append(get_crypto_news(symbol))
        lines.append(get_coingecko_trending())
        lines.append(get_google_trends(symbol))

    return "\n".join(filter(None, lines))


def get_news(query: str) -> str:
    return "News unavailable."
