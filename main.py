"""
MARDOOD — AI Trading Agent
"""
import argparse
import schedule
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import SCAN_INTERVAL_MINUTES, TIMEZONE, MARDOOD_PHASE
from signals.generator import run_full_scan
from alerts.notifier import send_signals, send_telegram
from memory.trade_log import log_signals, get_recent_signals, get_stats
from execution.paper_trader import execute_paper_trade, get_performance_summary, check_stop_loss_take_profit
from data.stocks.fetcher import get_stock_data
from data.crypto.fetcher import get_crypto_price

console = Console()


def print_banner():
    console.print(Panel.fit(
        "[bold cyan]🤖  M A R D O O D[/bold cyan]\n"
        "[dim]AI Trading Agent — US Stocks & Crypto[/dim]\n"
        f"[dim]Phase {MARDOOD_PHASE} · {TIMEZONE}[/dim]",
        border_style="cyan"
    ))


def get_current_price(symbol, asset_type):
    try:
        if asset_type == "stock":
            df = get_stock_data(symbol, period="1d", interval="1m")
            return float(df["close"].iloc[-1])
        else:
            return get_crypto_price(symbol)
    except:
        return None


def run_scan():
    console.rule("[cyan]Market Scan[/cyan]")
    signals = run_full_scan()

    if signals:
        console.print(f"\n[green]✓ {len(signals)} signal(s) above threshold[/green]")
        log_signals(signals)
        send_signals(signals)

        # Paper trading
        if MARDOOD_PHASE >= 2:
            console.print("\n[cyan]📝 Executing paper trades...[/cyan]")
            for signal in signals:
                price = get_current_price(signal["symbol"], signal["asset_type"])
                if price:
                    result = execute_paper_trade(signal, price)
                    if result:
                        action = result["action"]
                        sym = result["symbol"]
                        if action == "OPENED":
                            console.print(f"  [green]+ BOUGHT {sym} @ ${price:.2f}[/green]")
                            send_telegram(f"📝 *Paper Trade*\n🟢 BOUGHT {sym} @ ${price:.2f}\nStop: ${result['stop_loss']} | Target: ${result['take_profit']}")
                        elif action == "CLOSED":
                            pnl = result["pnl"]
                            emoji = "✅" if pnl > 0 else "❌"
                            console.print(f"  [{('green' if pnl > 0 else 'red')}]{emoji} CLOSED {sym} | PnL: ${pnl}[/]")
                            send_telegram(f"📝 *Paper Trade Closed*\n{emoji} {sym} | PnL: *${pnl}* ({result['pnl_pct']}%)\nReason: {result['reason']}")

            perf = get_performance_summary()
            console.print(f"\n[dim]Portfolio: ${perf['portfolio_value']} | Trades: {perf['total_trades']} | Win rate: {perf['win_rate']}%[/dim]")
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
        title="Mardood Performance",
        border_style="cyan"
    ))


def main():
    parser = argparse.ArgumentParser(description="Mardood AI Trading Agent")
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
    console.print(f"[green]✓ Mardood is live[/green] — scanning every {SCAN_INTERVAL_MINUTES} min")
    console.print(f"[dim]Press Ctrl+C to stop[/dim]\n")
    run_scan()

    while True:
        schedule.run_pending()
        time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Mardood stopped.[/yellow]")