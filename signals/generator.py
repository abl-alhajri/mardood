"""
Mardood — Signal Generator with Full Context
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from data.stocks.fetcher import get_stock_data
from data.crypto.fetcher import get_crypto_ohlcv
from data.news.fetcher import get_full_context
from analysis.technical.indicators import add_all_indicators, get_signal_summary
from analysis.brain import analyze
from config import STOCKS_WATCHLIST, CRYPTO_WATCHLIST, SIGNAL_CONFIDENCE_THRESHOLD
from rich.console import Console

console = Console()


def scan_stock(ticker):
    try:
        df = get_stock_data(ticker, period="3mo", interval="1d")
        df = add_all_indicators(df)
        indicators = get_signal_summary(df)
        news = get_full_context(ticker, "stock")
        signal = analyze(ticker, "stock", indicators, news)
        signal["symbol"] = ticker
        signal["asset_type"] = "stock"
        return signal
    except Exception as e:
        console.print(f"  [red]✗ {ticker}: {e}[/red]")
        return None


def scan_crypto(symbol):
    try:
        df = get_crypto_ohlcv(symbol, interval="1d", limit=90)
        df = add_all_indicators(df)
        indicators = get_signal_summary(df)
        news = get_full_context(symbol, "crypto")
        signal = analyze(symbol, "crypto", indicators, news)
        signal["symbol"] = symbol
        signal["asset_type"] = "crypto"
        return signal
    except Exception as e:
        console.print(f"  [red]✗ {symbol}: {e}[/red]")
        return None


def run_full_scan():
    all_signals = []
    tasks = []

    for ticker in STOCKS_WATCHLIST:
        tasks.append((scan_stock, ticker))
    for symbol in CRYPTO_WATCHLIST:
        tasks.append((scan_crypto, symbol))

    console.print(f"[cyan]⚡ Scanning {len(tasks)} assets in parallel...[/cyan]")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fn, arg): arg for fn, arg in tasks}
        for future in as_completed(futures):
            symbol = futures[future]
            signal = future.result()
            if not signal:
                continue
            confidence = signal.get("confidence", 0)
            sig_type = signal.get("signal", "?")
            if confidence >= SIGNAL_CONFIDENCE_THRESHOLD:
                all_signals.append(signal)
                console.print(f"  [green]★ {symbol}: {sig_type} ({confidence:.0%})[/green]")
            else:
                console.print(f"  [dim]  {symbol}: {sig_type} ({confidence:.0%})[/dim]")

    return all_signals