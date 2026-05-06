"""
XYZTRADINGAE — AI Trading Agent
"""
import argparse
import schedule
import time
from rich.console import Console
from rich.panel import Panel

from config import (
    SCAN_INTERVAL_MINUTES, TIMEZONE, XYZTRADINGAE_PHASE, SHADOW_MODE,
    MAX_CONCURRENT_POSITIONS,
)
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
from analysis.correlation import get_correlation_matrix, correlation

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

        # Greedy diversification: each subsequent slot picks the signal that
        # maximizes confidence x (1 - max correlation with already-picked
        # positions). Without this, a scan that sees BTC/SOL/AVAX/XRP/LINK
        # all signal BUY produces 5x effective BTC exposure.
        portfolio = get_portfolio()
        already_open = {p["symbol"] for p in portfolio["positions"]}
        free_slots = max(0, MAX_CONCURRENT_POSITIONS - len(already_open))

        if free_slots > 0 and len(signals) > free_slots:
            corr_data = get_correlation_matrix()
            matrix = corr_data["matrix"]

            picked_syms = set(already_open)  # existing positions are anchors
            remaining = list(signals)
            ordered: list = []

            # First pick: highest confidence (already at index 0 after sort).
            first = max(remaining, key=lambda s: s.get("confidence", 0))
            ordered.append(first)
            picked_syms.add(first["symbol"])
            remaining.remove(first)

            # Subsequent picks: maximize confidence x diversification. The
            # 60/40 split (diversification/confidence) gives diversification
            # more discrimination at the typical 65-68% confidence cluster
            # the brain produces. Tunable.
            def score(sig):
                conf = sig.get("confidence", 0)
                if not picked_syms:
                    return conf
                max_corr = max(correlation(sig["symbol"], s, matrix) for s in picked_syms)
                div_bonus = 1.0 - max(0.0, max_corr)
                return conf * (0.4 + 0.6 * div_bonus)

            # +5 buffer so the loop sorts ALL plausibly-fillable signals
            # into priority order, not just the slot count.
            while remaining and len(ordered) < free_slots + 5:
                best = max(remaining, key=score)
                ordered.append(best)
                picked_syms.add(best["symbol"])
                remaining.remove(best)

            # Anything left (shouldn't happen with the +5 buffer) goes at the
            # end in arrival order — defensive.
            ordered.extend(remaining)
            signals = ordered

            # Audit log: show each slot's max-correlation against the prior
            # set (already-open + earlier picks in this scan).
            for i, s in enumerate(signals[:free_slots], 1):
                prior = (already_open | {x["symbol"] for x in signals[:i - 1]}) - {s["symbol"]}
                if prior:
                    max_corr_anchor = f"{max(correlation(s['symbol'], p, matrix) for p in prior):.2f}"
                else:
                    max_corr_anchor = "—"
                console.print(
                    f"  [dim]slot {i}: {s['symbol']} "
                    f"conf {s.get('confidence', 0):.0%} "
                    f"max-corr-with-portfolio {max_corr_anchor}[/dim]"
                )

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
                pnl_emoji = "📈" if perf['total_pnl'] > 0 else ("📉" if perf['total_pnl'] < 0 else "➡️")
                pnl_color = "green" if perf['total_pnl'] > 0 else ("red" if perf['total_pnl'] < 0 else "dim")
                console.print(
                    f"\n[{pnl_color}]{pnl_emoji} Portfolio: ${perf['portfolio_value']} "
                    f"({perf['total_return_pct']:+.2f}%) | "
                    f"Cash: ${perf['cash']} + Open: ${perf['open_position_value']} | "
                    f"Realized: ${perf['realized_pnl']} | Unrealized: ${perf['unrealized_pnl']} | "
                    f"Trades: {perf['total_trades']} | Win rate: {perf['win_rate']}%[/{pnl_color}]"
                )
                if perf.get('open_positions_failed', 0) > 0:
                    console.print(f"[yellow]  ⚠ {perf['open_positions_failed']} position(s) using entry-price fallback (live price fetch failed)[/yellow]")
            except Exception as e:
                console.print(f"\n[red]Portfolio summary unavailable: {e}[/red]")

            # Effective BTC exposure: sum of positive BTC correlations across
            # currently-open positions. >3.5x on a 5-position portfolio is
            # concentration risk worth flagging.
            try:
                open_now = {p["symbol"]: p for p in get_portfolio()["positions"]}
                if open_now:
                    corr_data = get_correlation_matrix()
                    matrix = corr_data["matrix"]
                    btc_corrs = [correlation(s, "BTCUSDT", matrix) for s in open_now]
                    effective_btc_beta = sum(max(0.0, c) for c in btc_corrs)
                    avg_corr = sum(btc_corrs) / len(btc_corrs)
                    console.print(
                        f"[dim]Effective BTC exposure: {effective_btc_beta:.1f}x "
                        f"({len(open_now)} positions, avg correlation {avg_corr:.2f})[/dim]"
                    )
            except Exception as e:
                console.print(f"[red]BTC exposure metric unavailable: {e}[/red]")
        elif SHADOW_MODE:
            console.print("\n[yellow]🔭 SHADOW_MODE active — decisions logged to shadow_decisions, no new trades opened[/yellow]")
    else:
        console.print("\n[yellow]No high-confidence signals this scan.[/yellow]")

    console.rule()


def show_stats():
    perf = get_performance_summary()

    return_color = "green" if perf['total_return_pct'] > 0 else ("red" if perf['total_return_pct'] < 0 else "white")
    pnl_color = "green" if perf['total_pnl'] > 0 else ("red" if perf['total_pnl'] < 0 else "white")
    unreal_color = "green" if perf['unrealized_pnl'] > 0 else ("red" if perf['unrealized_pnl'] < 0 else "white")

    lines = [
        f"[bold]💰 Portfolio Value:[/bold] ${perf['portfolio_value']} "
        f"[{return_color}]({perf['total_return_pct']:+.2f}%)[/{return_color}]",
        f"[bold]💵 Cash:[/bold] ${perf['cash']}",
        f"[bold]📦 Open Position Value:[/bold] ${perf['open_position_value']}",
        f"[bold]📊 Total Trades:[/bold] {perf['total_trades']}",
        f"[bold]✅ Wins:[/bold] {perf['wins']} | [bold]❌ Losses:[/bold] {perf['losses']}",
        f"[bold]🎯 Win Rate:[/bold] {perf['win_rate']}%",
        f"[bold]💵 Realized P&L:[/bold] ${perf['realized_pnl']}",
        f"[bold]🟡 Unrealized P&L:[/bold] [{unreal_color}]${perf['unrealized_pnl']}[/{unreal_color}]",
        f"[bold]💹 Total P&L:[/bold] [{pnl_color}]${perf['total_pnl']}[/{pnl_color}]",
    ]
    if perf.get('open_positions_failed', 0) > 0:
        lines.append(f"[yellow]⚠ {perf['open_positions_failed']} position(s) using entry-price fallback[/yellow]")

    console.print(Panel.fit(
        "\n".join(lines),
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
