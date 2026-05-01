"""
Mardood — Gemini API Brain
"""
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

SYSTEM_PROMPT = """You are Mardood, an aggressive SHORT-TERM scalp trader specializing in US stocks and crypto.

Your goal is quick profits: enter fast, exit fast.
- Prefer SHORT timeframe trades (hours to 1-2 days maximum)
- Take profit target: 8%
- Stop loss: 2%
- Only give BUY when you see strong momentum RIGHT NOW
- Be aggressive — if momentum is there, say BUY with high confidence
- Use ALL data sources — social + technical + on-chain together

Always respond with ONLY a JSON object (no markdown, no code fences):
{
  "signal": "BUY" or "SELL" or "HOLD",
  "confidence": 0.0 to 1.0,
  "reasoning": "2-3 sentence explanation",
  "key_factors": ["factor 1", "factor 2", "factor 3"],
  "risk_level": "LOW" or "MEDIUM" or "HIGH",
  "suggested_entry": null,
  "suggested_stop_loss": null,
  "suggested_take_profit": null,
  "timeframe": "SHORT"
}"""


def analyze(symbol, asset_type, indicators, news_summary=""):
    prompt = f"""{SYSTEM_PROMPT}

Analyze {symbol} ({asset_type.upper()}).

TECHNICAL INDICATORS:
{json.dumps(indicators, indent=2)}

MARKET CONTEXT:
{news_summary or "No recent news."}

JSON only:"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7}
    }

    response = requests.post(GEMINI_URL, json=payload, timeout=15)
    response.raise_for_status()

    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())
