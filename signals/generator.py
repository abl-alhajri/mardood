"""
XYZTradingAE — Signal Generator

Production runs the brain for trading decisions. In parallel, the
deterministic heuristic from analysis.heuristic runs on the same
indicators payload, and BOTH decisions are logged to the
shadow_decisions table for offline comparison.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from data.crypto.fetcher import (
    get_crypto_ohlcv, candle_interval_minutes, COINBASE_SYMBOLS, get_coinbase_ohlcv,
)
from data.news.fetcher import get_full_context
from analysis.technical.indicators import add_all_indicators, get_signal_summary
from analysis.brain import analyze
from analysis.heuristic import heuristic_decision
from memory.trade_log import log_shadow_decision
from config import CRYPTO_WATCHLIST, SIGNAL_CONFIDENCE_THRESHOLD
from rich.console import Console

console = Console()


def _compute_btc_regime_now() -> bool:
    """
    True if BTC's latest 1h close is above its 1h EMA200.
    Fetched once per scan cycle, shared across all parallel workers via
    the regime arg on scan_crypto.
    """
    try:
        # 300 1-hour candles = 12.5 days, plenty for EMA200 to converge.
        btc_1h = get_coinbase_ohlcv("BTCUSDT", granularity=3600, limit=300)
        if len(btc_1h) < 50:
            return False
        ema200 = btc_1h["close"].ewm(span=200, adjust=False).mean()
        return bool(btc_1h["close"].iloc[-1] > ema200.iloc[-1])
    except Exception as e:
        console.print(f"[yellow]BTC regime check failed: {e} (defaulting to False)[/yellow]")
        return False


def scan_crypto(symbol: str, btc_regime_bullish: bool = False):
    """
    Run brain + heuristic on the same indicators. Log both for shadow
    comparison. Return the brain's signal (production trading decision).
    """
    try:
        df = get_crypto_ohlcv(symbol, days=1)
        df = add_all_indicators(df)
        indicators = get_signal_summary(df)
        indicators["interval_minutes"] = candle_interval_minutes(symbol)
        indicators["volume_available"] = symbol in COINBASE_SYMBOLS
        indicators["btc_regime_bullish"] = btc_regime_bullish

        news = get_full_context(symbol, "crypto")

        # Brain (production trading path)
        brain_sig: dict
        try:
            brain_sig = analyze(symbol, "crypto", indicators, news)
            brain_sig["symbol"] = symbol
            brain_sig["asset_type"] = "crypto"
            brain_sig["atr_pct"] = indicators.get("atr_pct", 0.0)
        except Exception as e:
            console.print(f"  [red]✗ {symbol} brain failed: {e}[/red]")
            brain_sig = {
                "signal": "ERROR", "confidence": 0.0,
                "reasoning": str(e), "error": str(e),
                "symbol": symbol, "asset_type": "crypto",
            }

        # Heuristic (cheap, deterministic, on the same indicators)
        try:
            heur_sig = heuristic_decision(indicators, btc_regime_bullish=btc_regime_bullish)
        except Exception as e:
            console.print(f"  [yellow]heuristic({symbol}) failed: {e}[/yellow]")
            heur_sig = {"signal": "ERROR", "confidence": 0.0, "reasoning": str(e)}

        # Shadow log: both decisions side-by-side, regardless of SHADOW_MODE flag
        try:
            log_shadow_decision(
                symbol=symbol,
                price=float(indicators.get("price", 0.0)),
                brain_signal=brain_sig,
                heuristic_signal=heur_sig,
                indicators=indicators,
                btc_regime_bullish=btc_regime_bullish,
            )
        except Exception as e:
            console.print(f"  [yellow]shadow log({symbol}) failed: {e}[/yellow]")

        # Return brain signal (existing trading path); ERROR signals aren't actionable
        if brain_sig.get("signal") == "ERROR":
            return None
        return brain_sig

    except Exception as e:
        console.print(f"  [red]✗ {symbol}: {e}[/red]")
        return None


def run_full_scan():
    all_signals = []

    # BTC regime — computed once, shared across parallel workers.
    btc_regime = _compute_btc_regime_now()
    regime_label = "BULLISH (above 1h EMA200)" if btc_regime else "BEARISH (below 1h EMA200)"
    console.print(f"[dim]BTC 1h regime: {regime_label}[/dim]")

    console.print(f"[cyan]⚡ Scanning {len(CRYPTO_WATCHLIST)} assets...[/cyan]")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(scan_crypto, symbol, btc_regime): symbol
            for symbol in CRYPTO_WATCHLIST
        }
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
