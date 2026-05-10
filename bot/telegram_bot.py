"""
XYZTradingAE — Telegram bot.

Two responsibilities:

1. Outbound alerts — sync helpers (send_signal_alert / send_trade_alert /
   send_exit_alert / send_portfolio_summary) called from the scanner. They
   delegate to alerts.notifier.send_telegram (raw HTTP, ~200ms per call),
   so call sites stay sync and never touch asyncio.

2. Command bot — python-telegram-bot Application (/start /status /positions
   /signals /portfolio /help) running in a daemon thread. Commands are
   gated to TELEGRAM_CHAT_ID; messages from any other chat are silently
   ignored. The thread uses run_polling(stop_signals=None) so PTB doesn't
   try to install signal handlers off the main thread (which raises
   ValueError: signal only works in main thread — the trap that broke the
   previous attempt).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from alerts.notifier import send_telegram
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)


# --- Outbound helpers (sync) -------------------------------------------------

_SIGNAL_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}


def send_signal_alert(symbol: str, confidence: float, signal_type: str,
                      risk_level: Optional[str] = None) -> bool:
    """★ signal alert (≥SIGNAL_CONFIDENCE_THRESHOLD). One per symbol per scan."""
    pct = f"{confidence * 100:.0f}%" if confidence <= 1 else f"{confidence:.0f}%"
    risk = f" | Risk: {risk_level}" if risk_level else ""
    msg = (
        "🔥 *STRONG SIGNAL*\n"
        f"`{symbol}` {signal_type} *{pct}*{risk}"
    )
    return send_telegram(msg)


def send_trade_alert(action: str, symbol: str, price: float,
                     reason: Optional[str] = None) -> bool:
    """Paper-trade open/close. action == 'BUY' or 'SELL'."""
    if action.upper() == "BUY":
        emoji, verb = "🟢", "BOUGHT"
    else:
        emoji, verb = "🔴", "SOLD"
    lines = [f"{emoji} *{verb}* `{symbol}`", f"Price: ${price:,.4f}"]
    if reason:
        lines.append(f"_{reason}_")
    return send_telegram("\n".join(lines))


def send_exit_alert(symbol: str, pnl: float, exit_reason: str,
                    pnl_pct: Optional[float] = None) -> bool:
    """SL/TP exit."""
    won = pnl > 0
    emoji = "✅" if won else "❌"
    sign = "+" if pnl >= 0 else ""
    pnl_str = f"*{sign}${pnl:,.2f}*"
    if pnl_pct is not None:
        pnl_str += f" ({sign}{pnl_pct:.2f}%)"
    msg = (
        f"{emoji} *EXIT {symbol}*\n"
        f"PnL: {pnl_str}\n"
        f"Reason: {exit_reason}"
    )
    return send_telegram(msg)


def send_portfolio_summary() -> bool:
    """Snapshot of portfolio value, P&L, win rate."""
    msg = _format_portfolio_summary()
    return send_telegram(msg)


def _format_portfolio_summary() -> str:
    from execution.paper_trader import get_performance_summary

    perf = get_performance_summary()
    pnl_emoji = "📈" if perf["total_pnl"] > 0 else ("📉" if perf["total_pnl"] < 0 else "➡️")
    sign = "+" if perf["total_return_pct"] >= 0 else ""
    return (
        "📊 *Portfolio Status*\n"
        f"Value: *${perf['portfolio_value']:,.2f}* "
        f"{pnl_emoji} {sign}{perf['total_return_pct']:.2f}%\n"
        f"Cash: ${perf['cash']:,.2f}\n"
        f"Open: ${perf['open_position_value']:,.2f}\n"
        f"Realized P&L: ${perf['realized_pnl']:,.2f}\n"
        f"Unrealized P&L: ${perf['unrealized_pnl']:,.2f}\n"
        f"Trades: {perf['total_trades']} | Win rate: {perf['win_rate']}%"
    )


# --- Command handlers --------------------------------------------------------

HELP_TEXT = (
    "🤖 *XYZTradingAE Bot*\n\n"
    "/status — portfolio value, P&L, win rate\n"
    "/positions — open positions with live P&L\n"
    "/signals — last 10 ★ signals\n"
    "/portfolio — detailed breakdown\n"
    "/help — this message"
)


def _is_authorized(update: Update) -> bool:
    """Only the configured chat may issue commands."""
    if not TELEGRAM_CHAT_ID:
        return False
    chat = update.effective_chat
    if chat is None:
        return False
    try:
        return str(chat.id) == str(TELEGRAM_CHAT_ID)
    except Exception:
        return False


async def _reject(update: Update) -> None:
    log.warning("Rejected command from unauthorized chat: %s", update.effective_chat)


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _reject(update)
    await update.message.reply_text(
        "👋 *XYZTradingAE online.*\n\n" + HELP_TEXT,
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _reject(update)
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _reject(update)
    try:
        msg = _format_portfolio_summary()
    except Exception as e:
        log.exception("status command failed")
        msg = f"⚠ Status unavailable: {e}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_positions(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _reject(update)
    try:
        from data.crypto.fetcher import get_live_price
        from execution.paper_trader import get_portfolio

        positions = get_portfolio()["positions"]
        if not positions:
            await update.message.reply_text(
                "📭 No open positions.", parse_mode=ParseMode.MARKDOWN
            )
            return

        lines = [f"📦 *Open Positions ({len(positions)})*", ""]
        for p in positions:
            sym = p["symbol"]
            entry = p["entry_price"]
            qty = p["quantity"]
            try:
                live = get_live_price(sym)
                pnl = (live - entry) * qty
                pnl_pct = (live - entry) / entry * 100 if entry else 0.0
                emoji = "🟢" if pnl >= 0 else "🔴"
                sign = "+" if pnl >= 0 else ""
                lines.append(
                    f"{emoji} `{sym}` @ ${entry:,.4f} → ${live:,.4f}\n"
                    f"   PnL: {sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%)"
                )
            except Exception as e:
                log.warning("live price fetch failed for %s: %s", sym, e)
                lines.append(f"⚪ `{sym}` @ ${entry:,.4f} (live price unavailable)")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        log.exception("positions command failed")
        await update.message.reply_text(f"⚠ Positions unavailable: {e}")


async def cmd_signals(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _reject(update)
    try:
        from config import SIGNAL_CONFIDENCE_THRESHOLD
        from memory.trade_log import get_recent_signals

        # Fetch a wider window then filter to ★ (above threshold) so we can
        # always show 10 strong signals even if the most recent scans included
        # sub-threshold rows in the log.
        rows = get_recent_signals(limit=200)
        strong = [
            r for r in rows
            if (r.get("confidence") or 0) >= SIGNAL_CONFIDENCE_THRESHOLD
        ][:10]

        if not strong:
            await update.message.reply_text(
                "📭 No ★ signals yet.", parse_mode=ParseMode.MARKDOWN
            )
            return

        lines = [f"⭐ *Last {len(strong)} ★ signals*", ""]
        for r in strong:
            sym = r.get("symbol", "?")
            sig = r.get("signal", "?")
            conf = (r.get("confidence") or 0) * 100
            ts = (r.get("timestamp") or "")[:16].replace("T", " ")
            emoji = _SIGNAL_EMOJI.get(sig, "⚪")
            lines.append(f"{emoji} `{sym}` {sig} *{conf:.0f}%* — {ts}")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        log.exception("signals command failed")
        await update.message.reply_text(f"⚠ Signals unavailable: {e}")


async def cmd_portfolio(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _reject(update)
    try:
        msg = _format_portfolio_summary()
    except Exception as e:
        log.exception("portfolio command failed")
        msg = f"⚠ Portfolio unavailable: {e}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# --- Application + polling thread --------------------------------------------

def build_application() -> Application:
    """Build the PTB Application with command handlers attached. Pure
    construction — does not start polling. Useful for tests."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("signals", cmd_signals))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    return app


def _run_polling_in_thread() -> None:
    try:
        app = build_application()
        # stop_signals=None: PTB tries to install SIGINT/SIGTERM handlers by
        # default, which only works on the main thread. Disabling it lets us
        # poll from a daemon thread; the daemon flag handles shutdown when
        # main.py exits.
        app.run_polling(stop_signals=None, close_loop=False)
    except Exception as e:
        log.exception("Telegram polling thread crashed: %s", e)


def start_polling_thread() -> Optional[threading.Thread]:
    """Spin up command polling in a daemon thread. No-op (with a warning) if
    TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing — the trading bot must
    not depend on Telegram being configured."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning(
            "Telegram disabled — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"
        )
        return None
    t = threading.Thread(
        target=_run_polling_in_thread,
        name="telegram-polling",
        daemon=True,
    )
    t.start()
    return t
