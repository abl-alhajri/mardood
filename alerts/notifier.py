"""
Mardood — Alert System
Sends trading signals to Telegram.
"""
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def format_signal_message(signal: dict) -> str:
    """Format a signal dict into a clean Telegram message."""
    s_emoji  = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(signal.get("signal"), "⚪")
    r_emoji  = {"LOW": "🔵", "MEDIUM": "🟠", "HIGH": "🔴"}.get(signal.get("risk_level"), "⚪")
    tf_label = {"SHORT": "Short-term", "MEDIUM": "Swing", "LONG": "Long-term"}.get(signal.get("timeframe"), "—")

    lines = [
        f"{s_emoji} *MARDOOD SIGNAL*",
        "",
        f"*{signal.get('symbol')}* ({signal.get('asset_type', '').upper()})",
        f"Signal: *{signal.get('signal')}*",
        f"Confidence: *{signal.get('confidence', 0):.0%}*",
        f"Risk: {r_emoji} {signal.get('risk_level', '—')}",
        f"Timeframe: {tf_label}",
        "",
        f"_{signal.get('reasoning', '')}_",
        "",
    ]

    factors = signal.get("key_factors", [])
    if factors:
        lines.append("*Key factors:*")
        for f in factors:
            lines.append(f"• {f}")
        lines.append("")

    entry = signal.get("suggested_entry")
    sl    = signal.get("suggested_stop_loss")
    tp    = signal.get("suggested_take_profit")

    if entry: lines.append(f"📍 Entry: `{entry}`")
    if sl:    lines.append(f"🛑 Stop-loss: `{sl}`")
    if tp:    lines.append(f"🎯 Take-profit: `{tp}`")

    lines.append("")
    lines.append("_⚠ Not financial advice. Always DYOR._")

    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    """Send a message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠  Telegram not configured — skipping alert")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def send_signal_alert(signal: dict) -> bool:
    """Format and send one signal alert."""
    message = format_signal_message(signal)
    return send_telegram(message)


def send_signals(signals: list) -> None:
    """Send all high-confidence signals, or a no-signal message."""
    if not signals:
        send_telegram("🤖 *Mardood scan complete*\nNo high\\-confidence signals right now\\.")
        return

    send_telegram(f"🤖 *Mardood found {len(signals)} signal(s)*")
    for signal in signals:
        send_signal_alert(signal)
