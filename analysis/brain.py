"""
Mardood — Claude API Brain (Enhanced)
"""
import anthropic
import json
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are Mardood, an elite SHORT-TERM scalp trader with access to:
- Technical indicators (RSI, MACD, Bollinger Bands, EMA)
- Real-time news and sentiment
- X/Twitter social sentiment
- Reddit community mood (WallStreetBets, CryptoCurrency)
- Google Trends data
- Bitcoin/Ethereum on-chain metrics
- Insider trading activity
- Fear & Greed Index

Your goal is quick profits: enter fast, exit fast.
- Prefer SHORT timeframe trades (hours to 1-2 days maximum)
- Take profit target: 8%
- Stop loss: 2%
- Only give BUY when you see strong momentum RIGHT NOW
- Use ALL data sources — social + technical + on-chain together
- Be aggressive — if momentum is there, say BUY with high confidence
- If Twitter + Reddit are both bullish AND technicals confirm → very high confidence BUY
- If insider buying + bullish news → strong BUY signal

Always respond with ONLY a JSON object (no markdown, no code fences):
{
  "signal": "BUY" or "SELL" or "HOLD",
  "confidence": 0.0 to 1.0,
  "reasoning": "2-3 sentence explanation mentioning key data sources",
  "key_factors": ["factor 1", "factor 2", "factor 3"],
  "risk_level": "LOW" or "MEDIUM" or "HIGH",
  "suggested_entry": null,
  "suggested_stop_loss": null,
  "suggested_take_profit": null,
  "timeframe": "SHORT"
}"""


def analyze(symbol, asset_type, indicators, news_summary=""):
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"""Analyze {symbol} ({asset_type.upper()}).

TECHNICAL INDICATORS:
{json.dumps(indicators, indent=2)}

MARKET CONTEXT (News + Social + On-chain):
{news_summary or "No data available."}

Based on ALL the above data sources combined, give your trading signal.
JSON only:"""}]
    )
    raw = message.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
