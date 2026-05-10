"""
XYZTradingAE — Telegram transport.

Low-level send-message helper used by bot.telegram_bot's outbound formatters.
Kept separate from bot.telegram_bot so the trading bot can post messages
without depending on python-telegram-bot — a single requests.post is faster
and never touches asyncio.
"""
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_telegram(message: str) -> bool:
    """Send a Markdown-formatted message to TELEGRAM_CHAT_ID. Returns False
    silently on missing config or any network failure — never raises, so a
    Telegram outage cannot crash the scanner."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠  Telegram not configured — skipping alert")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False
