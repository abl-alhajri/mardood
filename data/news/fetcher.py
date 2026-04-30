"""
Mardood — News & Data Sources (Enhanced)
Finnhub, CoinGecko, Google Trends, On-chain, Insider Trading
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN")


# ─── FINNHUB ────────────────────────────────────────────────────────────────

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
    except:
        return "News unavailable."


def get_finnhub_sentiment(ticker: str) -> str:
    try:
        url = f"https://finnhub.io/api/v1/news-sentiment?symbol={ticker}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=5)
        d = r.json()
        score = d.get("companyNewsScore", 0)
        bullish = d.get("sentiment", {}).get("bullishPercent", 0)
        return f"News sentiment score: {score:.2f}, Bullish: {bullish*100:.1f}%"
    except:
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
    except:
        return "Insider data unavailable."


# ─── CRYPTO ─────────────────────────────────────────────────────────────────

def get_crypto_news(symbol: str) -> str:
    try:
        coin = symbol.replace("USDT", "").lower()
        coin_map = {
            "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
            "bnb": "binancecoin", "xrp": "ripple", "doge": "dogecoin",
            "shib": "shiba-inu", "pepe": "pepe", "wif": "dogwifhat",
            "bonk": "bonk", "floki": "floki"
        }
        coin_id = coin_map.get(coin, coin)
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&market_data=false&community_data=true"
        r = requests.get(url, timeout=5)
        d = r.json()
        up = d.get("sentiment_votes_up_percentage", 0)
        down = d.get("sentiment_votes_down_percentage", 0)
        return f"Community: {up:.1f}% bullish, {down:.1f}% bearish."
    except:
        return "Crypto data unavailable."


# ─── GOOGLE TRENDS ──────────────────────────────────────────────────────────

def get_google_trends(symbol: str) -> str:
    try:
        clean = symbol.replace("USDT", "")
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
        r = requests.get(url, timeout=5)
        if clean.upper() in r.text.upper():
            return f"Google Trends: {clean} is TRENDING in the US right now! 🔥"
        return f"Google Trends: {clean} not in current US trending topics."
    except:
        return ""


# ─── ON-CHAIN DATA ───────────────────────────────────────────────────────────

def get_onchain_data(symbol: str) -> str:
    try:
        clean = symbol.replace("USDT", "").lower()
        if clean not in ["btc", "eth"]:
            return ""

        if clean == "btc":
            r = requests.get("https://mempool.space/api/v1/fees/recommended", timeout=5)
            fees = r.json()
            fast = fees.get("fastestFee", 0)
            r2 = requests.get("https://mempool.space/api/mempool", timeout=5)
            mempool = r2.json()
            pending = mempool.get("count", 0)
            activity = "HIGH" if pending > 50000 else "MEDIUM" if pending > 20000 else "LOW"
            return f"BTC On-chain: {pending:,} pending txs, fees {fast} sat/vB (fast), Network activity: {activity}"

        if clean == "eth":
            r = requests.get("https://beaconcha.in/api/v1/execution/gasnow", timeout=5)
            d = r.json().get("data", {})
            fast = d.get("fast", 0) // 1_000_000_000
            return f"ETH On-chain: Gas {fast} Gwei"
    except:
        return ""


# ─── FEAR & GREED + TRENDING ─────────────────────────────────────────────────

def get_fear_greed_index() -> str:
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        d = r.json()["data"][0]
        return f"Fear & Greed Index: {d['value']}/100 — {d['value_classification']}"
    except:
        return "Fear & Greed unavailable."


def get_coingecko_trending() -> str:
    try:
        r = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=5)
        coins = r.json().get("coins", [])[:5]
        names = [c["item"]["name"] for c in coins]
        return f"CoinGecko Trending: {', '.join(names)}"
    except:
        return "Trending unavailable."


# ─── MAIN AGGREGATOR ─────────────────────────────────────────────────────────

def get_full_context(symbol: str, asset_type: str) -> str:
    lines = [get_fear_greed_index()]

    if asset_type == "stock":
        lines.append(get_stock_news(symbol))
        lines.append(get_finnhub_sentiment(symbol))
        lines.append(get_insider_trading(symbol))
        lines.append(get_google_trends(symbol))
    else:
        lines.append(get_crypto_news(symbol))
        lines.append(get_coingecko_trending())
        lines.append(get_google_trends(symbol))
        onchain = get_onchain_data(symbol)
        if onchain:
            lines.append(onchain)

    return "\n".join(filter(None, lines))


def get_news(query: str) -> str:
    return "News unavailable."
