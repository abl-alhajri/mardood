"""
Backtest harness CLI / orchestrator.

Usage:
    python -m backtest.runner                          # 90d, 6 majors, heuristic
    python -m backtest.runner --days 30                # shorter window
    python -m backtest.runner --symbols BTCUSDT,ETHUSDT
    python -m backtest.runner --mode brain             # call Claude (cached)
    python -m backtest.runner --sample-every 6         # every 30 min instead of 1h

Outputs an HTML report to backtest/reports/.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
from datetime import datetime, timezone

import pandas as pd

from analysis.technical.indicators import add_all_indicators, get_signal_summary

from .data import get_historical_ohlcv
from .strategy import BrainCache, brain_decision, heuristic_decision
from .simulator import Simulator
from .metrics import compute_metrics, equity_for_report, trades_for_report
from .report import render_report

DEFAULT_SYMBOLS = ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
REPORTS_DIR = pathlib.Path(__file__).parent / "reports"


def _load_data(symbols: list[str], days: int, force_refresh: bool) -> dict[str, pd.DataFrame]:
    """Fetch + cache OHLCV per symbol, attach indicators."""
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = get_historical_ohlcv(sym, days=days, force_refresh=force_refresh)
        df_ind = add_all_indicators(df)
        # add_all_indicators drops rows missing ema_20/rsi (the warm-up window).
        # That's exactly what we want — no decisions on partially-warm indicators.
        out[sym] = df_ind
        print(f"[backtest] {sym}: {len(df_ind):,} usable candles "
              f"({df_ind.index[0]} -> {df_ind.index[-1]})", flush=True)
    return out


def _unified_timeline(per_symbol: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    """Union of all symbols' timestamps, sorted."""
    union = pd.DatetimeIndex([])
    for df in per_symbol.values():
        union = union.union(df.index)
    return union.sort_values()


def _decide(mode: str, symbol: str, candle_ts, indicators: dict,
           cache: BrainCache | None, btc_regime_bullish: bool) -> dict:
    if mode == "brain":
        # For brain mode, surface the regime as an extra indicator key so
        # the prompt can read it; brain doesn't otherwise have access.
        ind_with_regime = dict(indicators)
        ind_with_regime["btc_regime_bullish"] = btc_regime_bullish
        return brain_decision(symbol, candle_ts.isoformat(), ind_with_regime, cache)
    return heuristic_decision(indicators, btc_regime_bullish=btc_regime_bullish)


def _compute_btc_regime(btc_5m_df: pd.DataFrame) -> pd.Series:
    """
    Returns a bool Series indexed by 5m timestamps: True when BTC is
    above its 1h EMA200 at the time of decision.

    No look-ahead: the 1h regime is shifted forward by 1 hour before
    reindexing back to 5m, so the regime at 5m timestamp T uses BTC
    1h EMA200 computed from data strictly before T.
    """
    btc_1h = btc_5m_df["close"].resample("1h").last().dropna()
    ema200_1h = btc_1h.ewm(span=200, adjust=False).mean()
    regime_1h = (btc_1h > ema200_1h).astype(bool)
    # Shift forward 1 hour: the regime AT hour H is computed from data UP TO H-1
    regime_1h_shifted = regime_1h.shift(1).fillna(False)
    regime_5m = regime_1h_shifted.reindex(btc_5m_df.index, method="ffill").fillna(False)
    return regime_5m.astype(bool)


def run_backtest(
    symbols: list[str],
    days: int,
    mode: str,
    sample_every: int,
    starting_cash: float,
    confidence_threshold: float,
    force_refresh: bool,
    fee_override: float | None = None,
) -> tuple[Simulator, dict, list[dict], list[dict]]:
    print(f"[backtest] Mode: {mode}  |  Symbols: {symbols}  |  Days: {days}  "
          f"|  Sample every: {sample_every} candles", flush=True)

    per_symbol = _load_data(symbols, days, force_refresh)
    if not per_symbol:
        raise RuntimeError("No OHLCV loaded — aborting.")

    timeline = _unified_timeline(per_symbol)
    if timeline.empty:
        raise RuntimeError("Empty timeline after indicator warm-up.")

    # BTC regime filter: any alt entry requires BTC above its 1h EMA200.
    btc_df = per_symbol.get("BTCUSDT")
    if btc_df is None:
        raise RuntimeError("BTCUSDT data is required for the BTC regime filter.")
    btc_regime = _compute_btc_regime(btc_df)
    print(f"[backtest] BTC regime bullish: {btc_regime.sum():,}/{len(btc_regime):,} "
          f"5m candles ({btc_regime.mean()*100:.1f}% of timeline)", flush=True)

    sim = Simulator(starting_cash=starting_cash, fee_pct_per_side=fee_override)
    if fee_override is not None:
        print(f"[backtest] FEE override active: {fee_override*100:.3f}% per side "
              f"(default is {0.001*100:.3f}%)", flush=True)
    brain_cache = BrainCache() if mode == "brain" else None

    # Per-symbol cursor index for fast row lookup
    cursors = {sym: 0 for sym in per_symbol}

    # Per-symbol candle-index sequence for sampling
    candle_indices = {sym: 0 for sym in per_symbol}

    t_start = time.time()
    last_log = t_start
    decisions = 0

    for tick_idx, ts in enumerate(timeline):
        # Build a {symbol: ohlcv_row} for symbols whose candle closed at this ts
        ohlcv_at_ts: dict[str, dict] = {}
        mark_at_ts: dict[str, float] = {}
        for sym, df in per_symbol.items():
            if cursors[sym] < len(df) and df.index[cursors[sym]] == ts:
                row = df.iloc[cursors[sym]]
                ohlcv_at_ts[sym] = {
                    "open": row["open"], "high": row["high"], "low": row["low"],
                    "close": row["close"], "volume": row["volume"],
                }
                mark_at_ts[sym] = row["close"]
                cursors[sym] += 1
                candle_indices[sym] += 1

        # Mark-to-market everything we have a fresh candle for
        if mark_at_ts:
            # Carry prior marks for symbols not closed this tick
            for sym, pos in sim.open_positions.items():
                if sym not in mark_at_ts:
                    mark_at_ts[sym] = pos.entry_price  # conservative; not used after this tick
            sim.update_equity(ts, mark_at_ts)

        # Check exits FIRST (intra-candle wick simulation)
        sim.check_exits(ts, ohlcv_at_ts)

        # Apply strategy decisions on the sampling cadence
        for sym, row in ohlcv_at_ts.items():
            if candle_indices[sym] % sample_every != 0:
                continue

            df = per_symbol[sym]
            row_ind = df.iloc[cursors[sym] - 1].to_dict()  # the candle we just consumed
            indicators = get_signal_summary(df.iloc[: cursors[sym]])
            indicators["interval_minutes"] = 5
            indicators["volume_available"] = True

            # Look up BTC regime at this timestamp (no look-ahead — series
            # was shifted forward 1 hour at construction).
            regime_val = btc_regime.asof(ts)
            btc_regime_bullish = bool(regime_val) if pd.notna(regime_val) else False

            try:
                signal = _decide(mode, sym, ts, indicators, brain_cache, btc_regime_bullish)
            except Exception as e:
                print(f"[backtest] decide({sym} @ {ts}) failed: {e}", flush=True)
                continue
            decisions += 1
            confidence = float(signal.get("confidence", 0))
            if confidence < confidence_threshold:
                continue
            signal["atr_pct"] = indicators.get("atr_pct", 0.0)
            sim.try_open(sym, signal, ts, row["close"])

        # Heartbeat every 10s
        now = time.time()
        if now - last_log > 10:
            pct = (tick_idx + 1) / len(timeline) * 100
            elapsed = now - t_start
            print(f"[backtest] {pct:5.1f}% ({tick_idx+1:>6,}/{len(timeline):,} ticks, "
                  f"{decisions:>5} decisions, {len(sim.closed_trades):>4} trades, "
                  f"cash=${sim.cash:,.2f}, t={elapsed:.0f}s)", flush=True)
            last_log = now

    # Close anything still open at the last marks
    last_marks: dict[str, float] = {}
    for sym, df in per_symbol.items():
        last_marks[sym] = float(df["close"].iloc[-1])
    sim.force_close_all(timeline[-1], last_marks)

    metrics = compute_metrics(sim)
    equity_payload = equity_for_report(sim.equity_curve)
    trades_payload = trades_for_report(sim.closed_trades)

    if brain_cache:
        print(f"[backtest] brain cache: {brain_cache.stats()}", flush=True)

    return sim, metrics, equity_payload, trades_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XYZTradingAE backtest harness")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                       help="Comma-separated list (Coinbase-listed only)")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--mode", choices=["heuristic", "brain"], default="heuristic")
    parser.add_argument("--sample-every", type=int, default=12,
                       help="Run strategy every Nth candle. 12 = 1h on 5-min data.")
    parser.add_argument("--confidence-threshold", type=float, default=0.55,
                       help="Match the production filter")
    parser.add_argument("--starting-cash", type=float, default=10000.0)
    parser.add_argument("--force-refresh", action="store_true",
                       help="Bypass the OHLCV cache and re-fetch from Coinbase")
    parser.add_argument("--fee-pct-per-side", type=float, default=None,
                       help="Override FEE_PCT_PER_SIDE for this run (e.g. 0.0 for maker-only)")
    parser.add_argument("--output", default=None,
                       help="Output HTML path (default: backtest/reports/report_<ts>.html)")
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    config = {
        "symbols": symbols,
        "days": args.days,
        "mode": args.mode,
        "sample_every": args.sample_every,
        "confidence_threshold": args.confidence_threshold,
        "starting_cash": args.starting_cash,
    }

    sim, metrics, equity_payload, trades_payload = run_backtest(
        symbols=symbols,
        days=args.days,
        mode=args.mode,
        sample_every=args.sample_every,
        starting_cash=args.starting_cash,
        confidence_threshold=args.confidence_threshold,
        force_refresh=args.force_refresh,
        fee_override=args.fee_pct_per_side,
    )

    if args.output:
        out_path = pathlib.Path(args.output)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = REPORTS_DIR / f"report_{ts}.html"

    render_report(metrics, equity_payload, trades_payload, config, out_path)

    # Print headline summary to stdout
    print()
    print("=" * 60)
    print(f"  BACKTEST SUMMARY  ({args.mode}, {args.days}d, {len(symbols)} symbols)")
    print("=" * 60)
    print(f"  Final equity:     ${metrics['final_equity']:,.2f}")
    print(f"  Total return:     {metrics['total_return_pct']:+.2f}%")
    print(f"  Total trades:     {metrics['total_trades']}")
    print(f"  Win rate:         {metrics['win_rate']:.1f}%")
    print(f"  Sharpe (ann.):    {metrics['sharpe']:.2f}")
    print(f"  Max drawdown:     {metrics['max_drawdown_pct']:+.2f}%")
    print(f"  Total fees paid:  ${metrics['total_fees']:,.2f}  ({metrics['fee_drag_pct']:.1f}% of gross)")
    print(f"  Avg hold time:    {metrics['avg_hold_minutes']:.0f} min")
    print(f"  Report written:   {out_path}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
