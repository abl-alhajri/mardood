"""
XYZTradingAE — Signal Generator
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from data.crypto.fetcher import get_crypto_ohlcv
from data.news.fetcher import get_full_context
from analysis.technical.indicators import add_all_indicators, get_signal_summary
from analysis.brain import analyze
from config import CRYPTO_WATCHLIST, SIGNAL_CONFIDENCE_THRESHOLD
from rich.console import Console

console = Console()


def scan_crypto(symbol):
    try:
        # 4h candles, 30 days of history (~180 candles — enough for EMA200 to converge)
        df = get_crypto_ohlcv(symbol, days=30)
        df = add_all_indicators(df)
        indicators = get_signal_summary(df)
        news = get_full_context(symbol, "crypto")
        signal = analyze(symbol, "crypto", indicators, news)
        signal["symbol"] = symbol
        signal["asset_type"] = "crypto"
        # Pipe ATR through so the paper trader can size stops by realised vol
        signal["atr_pct"] = indicators.get("atr_pct", 0.0)
        return signal
    except Exception as e:
        console.print(f"  [red]✗ {symbol}: {e}[/red]")
        return None


def run_full_scan():
    all_signals = []
    tasks = [(scan_crypto, symbol) for symbol in CRYPTO_WATCHLIST]

    console.print(f"[cyan]⚡ Scanning {len(tasks)} assets...[/cyan]")

    # Claude's rate limits are well above what 11 concurrent scans need;
    # the SDK auto-retries on 429s and brain.analyze() has its own backoff.
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
