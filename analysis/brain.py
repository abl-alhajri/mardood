"""
Mardood — Claude API Brain
"""
import anthropic
import json
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are Mardood, an aggressive SHORT-TERM scalp trader specializing in US stocks and crypto.

Your goal is quick profits: enter fast, exit fast. 
- Prefer SHORT timeframe trades (hours to 1-2 days maximum)
- Take profit target: 4% 
- Stop loss: 2%
- Only give BUY when you see strong momentum RIGHT NOW
- Be aggressive — if momentum is there, say BUY with high confidence

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
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"""Analyze {symbol} ({asset_type.upper()}).

INDICATORS:
{json.dumps(indicators, indent=2)}

NEWS:
{news_summary or "No recent news."}

JSON only:"""}]
    )
    raw = message.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())