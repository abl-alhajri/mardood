"""
Mardood — Claude API Brain
"""
import os
import time
import random
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    max_retries=5,
)

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are Mardood, an elite SHORT-TERM crypto scalp trader.

INPUTS YOU RECEIVE EACH ANALYSIS:
- Technical indicators (RSI, MACD, Bollinger Bands, EMA)
- Fear & Greed Index — current value (0-100), classification, and 1-day + 7-day trend
- BTC mempool & on-chain (block height, pending txs, virtual mempool size, recommended fees, hashrate, last block stats)
- ETH gas (when analyzing ETH)
- CoinGecko community sentiment for the symbol (% bullish vs bearish)
- CoinGecko trending coins (market-wide attention)
- Google Trends presence for the symbol
- FinBERT sentiment (ProsusAI/finbert) on recent headlines — financial-news tone, "net" in [-1, +1]
- CryptoBERT sentiment (ElKulako/cryptobert) on recent headlines — crypto-native tone, "net" in [-1, +1]

OBJECTIVE — fast in, fast out:
- Holding period: hours to 1-2 days
- Take profit target: 8%
- Stop loss: 2%

DECISION FRAMEWORK (apply in order):
1. TECHNICALS DRIVE DIRECTION. RSI extremes, MACD crosses, Bollinger Band breakouts. Without a technical setup, default to HOLD.
2. MARKET MOOD CONFIRMS OR DISCONFIRMS:
   - Fear & Greed < 25 (Extreme Fear): contrarian-bullish, especially if 7-day trend is rising off a low.
   - Fear & Greed > 75 (Extreme Greed): contrarian-bearish, especially if 7-day trend is plateauing.
   - The DIRECTION of F&G matters more than the absolute value — falling F&G during a price uptrend is a divergence warning.
3. ON-CHAIN AS SECONDARY CONFIRMATION (especially for BTC, but also relevant for altcoins riding BTC liquidity):
   - HIGH mempool pressure + rising fees → active demand, supports BUY.
   - LOW mempool activity + falling fees → waning demand, supports HOLD/SELL.
   - Hashrate trending up → miner conviction.
4. SENTIMENT MODELS (FinBERT + CryptoBERT) ON RECENT HEADLINES:
   - Treat the "net" score as the most useful number: net > +0.30 = clearly bullish text, net < -0.30 = clearly bearish text, in-between = noisy.
   - When both models AGREE on direction, weight that confirmation higher than community votes.
   - When they DISAGREE (e.g., FinBERT bullish, CryptoBERT bearish), discount both — the news is ambiguous; rely more on technicals and on-chain.
   - Low n (n<3) means few headlines were available — treat sentiment as a weak signal.
5. COMMUNITY/TRENDS: confirmation only. They calibrate confidence, never set direction. If a coin is on the trending list AND technicals + mood agree, push confidence higher.

CONFIDENCE CALIBRATION:
- All four layers (technical + mood + on-chain + sentiment models) align → BUY/SELL at 0.80-0.95
- Three of four align → 0.65-0.80
- Two of four align → 0.45-0.65, often a HOLD
- Mixed or conflicting signals → HOLD at 0.40-0.55, never force a trade
- No clear technical setup → HOLD regardless of mood/sentiment

Always emit your decision via the `record_signal` tool. Do not respond with prose."""

SIGNAL_TOOL = {
    "name": "record_signal",
    "description": "Record the trading signal for the analyzed symbol. Call this exactly once per analysis.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
            "confidence": {"type": "number", "description": "0.0 to 1.0"},
            "reasoning": {"type": "string", "description": "2-3 sentences mentioning key data sources"},
            "key_factors": {"type": "array", "items": {"type": "string"}},
            "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "timeframe": {"type": "string", "enum": ["SHORT"]},
        },
        "required": ["signal", "confidence", "reasoning", "key_factors", "risk_level", "timeframe"],
        "additionalProperties": False,
    },
}

MAX_ATTEMPTS = 4
BASE_DELAY = 1.0
MAX_DELAY = 30.0


def _request(symbol, asset_type, indicators, news_summary):
    user_text = (
        f"Analyze {symbol} ({asset_type.upper()}).\n\n"
        f"TECHNICAL INDICATORS:\n{json.dumps(indicators, indent=2, sort_keys=True)}\n\n"
        f"MARKET CONTEXT (Fear & Greed + On-chain + Community + FinBERT/CryptoBERT):\n{news_summary or 'No data available.'}\n\n"
        "Apply the decision framework: technicals first, then layer mood, on-chain, and the sentiment models. "
        "Call record_signal with your decision."
    )
    return client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[SIGNAL_TOOL],
        tool_choice={"type": "tool", "name": "record_signal"},
        messages=[{"role": "user", "content": user_text}],
    )


def analyze(symbol, asset_type, indicators, news_summary=""):
    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            message = _request(symbol, asset_type, indicators, news_summary)
            for block in message.content:
                if block.type == "tool_use" and block.name == "record_signal":
                    return block.input
            raise ValueError(f"Claude returned no record_signal call (stop_reason={message.stop_reason})")
        except (anthropic.APIConnectionError, anthropic.RateLimitError, ValueError) as e:
            last_err = e
        except anthropic.APIStatusError as e:
            if e.status_code < 500:
                raise
            last_err = e
        delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
        time.sleep(delay)
    raise last_err
