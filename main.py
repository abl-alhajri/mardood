"""
XYZTRADINGAE — AI Trading Agent
"""
import argparse
import schedule
import time
from rich.console import Console
from rich.panel import Panel

from config import SCAN_INTERVAL_MINUTES, TIMEZONE, XYZTRADINGAE_PHASE, SHADOW_MODE
from signals.generator import run_full_scan
from alerts.notifier import send_signals, send_telegram
from memory.trade_log import log_signals
from execution.paper_trader import (
    execute_paper_trade,
    get_performance_summary,
    check_stop_loss_take_profit,
    get_portfolio,
)
from data.crypto.fetcher import get_live_price

console = Console()


def print_banner():
    console.print(Panel.fit(
        "[bold cyan]🤖  X Y Z T R A D I N G A E[/bold cyan]\n"
        "[dim]AI Trading Agent — Crypto[/dim]\n"
        f"[dim]Phase {XYZTRADINGAE_PHASE} · {TIMEZONE}[/dim]",
        border_style="cyan"
    ))


def get_current_price(symbol: str, asset_type: str = "crypto"):
    """Live price for a single symbol. Routes through the same source as OHLCV."""
    try:
        return get_live_price(symbol)
    except Exception as e:
        console.print(f"  [red]✗ Price fetch failed for {symbol}: {e}[/red]")
        return None


def run_scan():
    console.rule("[cyan]Market Scan[/cyan]")

    # Run SL/TP exits on currently open positions before scanning for new entries
    if XYZTRADINGAE_PHASE >= 2:
        open_syms = {p["symbol"]: p["asset_type"] for p in get_portfolio()["positions"]}
        if open_syms:
            current_prices = {}
            for sym, atype in open_syms.items():
                p = get_current_price(sym, atype)
                if p:
                    current_prices[sym] = p
            exits = check_stop_loss_take_profit(current_prices)
            for ex in exits:
                emoji = "✅" if ex["pnl"] > 0 else "❌"
                console.print(f"  [{('green' if ex['pnl'] > 0 else 'red')}]{emoji} EXIT {ex['symbol']} | PnL: ${ex['pnl']} ({ex['reason']})[/]")
                send_telegram(f"📝 *Auto-Exit*\n{emoji} {ex['symbol']} | PnL: *${ex['pnl']}* ({ex['pnl_pct']}%)\nReason: {ex['reason']}")

    signals = run_full_scan()

    if signals:
        # Strongest signals win the slots when MAX_CONCURRENT_POSITIONS is hit.
        # Without this, ThreadPoolExecutor.as_completed() arrival order decided
        # which 5 signals filled — last live scan filled with 67% sigs while
        # 72%/68% sigs got "skipped: max concurrent".
        signals.sort(key=lambda s: s.get("confidence", 0), reverse=True)
        console.print(f"\n[green]✓ {len(signals)} signal(s) above threshold[/green]")
        log_signals(signals)
        send_signals(signals)

        # Paper trading — skipped in SHADOW_MODE
        if XYZTRADINGAE_PHASE >= 2 and not SHADOW_MODE:
            console.print("\n[cyan]📝 Executing paper trades...[/cyan]")
            for signal in signals:
                price = get_current_price(signal["symbol"], signal["asset_type"])
                if not price:
                    continue
                result = execute_paper_trade(signal, price)
                if not result:
                    continue
                action = result["action"]
                sym = result["symbol"]
                if action == "OPENED":
                    console.print(f"  [green]+ BOUGHT {sym} @ ${price:.6f}[/green]")
                    send_telegram(f"📝 *Paper Trade*\n🟢 BOUGHT {sym} @ ${price}\nStop: ${result['stop_loss']} | Target: ${result['take_profit']}")
                elif action == "CLOSED":
                    pnl = result["pnl"]
                    emoji = "✅" if pnl > 0 else "❌"
                    console.print(f"  [{('green' if pnl > 0 else 'red')}]{emoji} CLOSED {sym} | PnL: ${pnl}[/]")
                    send_telegram(f"📝 *Paper Trade Closed*\n{emoji} {sym} | PnL: *${pnl}* ({result['pnl_pct']}%)\nReason: {result['reason']}")
                elif action == "SKIPPED":
                    console.print(f"  [dim]· skipped {sym}: {result['reason']}[/dim]")

            # Always print the per-scan portfolio summary, even if every
            # signal was SKIPPED (a previous scan was reported missing the
            # line; wrap defensively so the next missing line carries
            # diagnostic info instead of going silent).
            try:
                perf = get_performance_summary()
                console.print(f"\n[dim]Portfolio: ${perf['portfolio_value']} | Trades: {perf['total_trades']} | Win rate: {perf['win_rate']}%[/dim]")
            except Exception as e:
                console.print(f"\n[red]Portfolio summary unavailable: {e}[/red]")
        elif SHADOW_MODE:
            console.print("\n[yellow]🔭 SHADOW_MODE active — decisions logged to shadow_decisions, no new trades opened[/yellow]")
    else:
        console.print("\n[yellow]No high-confidence signals this scan.[/yellow]")

    console.rule()


def show_stats():
    perf = get_performance_summary()

    console.print(Panel.fit(
        f"[bold]💰 Portfolio Value:[/bold] ${perf['portfolio_value']}\n"
        f"[bold]💵 Cash:[/bold] ${perf['cash']}\n"
        f"[bold]📊 Total Trades:[/bold] {perf['total_trades']}\n"
        f"[bold]✅ Wins:[/bold] {perf['wins']} | [bold]❌ Losses:[/bold] {perf['losses']}\n"
        f"[bold]🎯 Win Rate:[/bold] {perf['win_rate']}%\n"
        f"[bold]💹 Total P&L:[/bold] ${perf['total_pnl']}",
        title="XYZTradingAE Performance",
        border_style="cyan"
    ))


def main():
    parser = argparse.ArgumentParser(description="XYZTradingAE AI Trading Agent")
    parser.add_argument("--once",  action="store_true", help="Run one scan and exit")
    parser.add_argument("--stats", action="store_true", help="Show performance stats")
    args = parser.parse_args()

    print_banner()

    if args.stats:
        show_stats()
        return

    if args.once:
        run_scan()
        return

    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scan)
    console.print(f"[green]✓ XYZTradingAE is live[/green] — scanning every {SCAN_INTERVAL_MINUTES} min")
    console.print(f"[dim]Press Ctrl+C to stop[/dim]\n")
    run_scan()

    while True:
        schedule.run_pending()
        time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]XYZTradingAE stopped.[/yellow]")
