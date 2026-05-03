"""
Compute performance metrics from a Simulator's final state.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict

import pandas as pd

from .simulator import Simulator, Trade


def _equity_to_series(curve: list[tuple[pd.Timestamp, float]]) -> pd.Series:
    if not curve:
        return pd.Series(dtype=float)
    ts, vals = zip(*curve)
    return pd.Series(vals, index=pd.DatetimeIndex(ts))


def _sharpe_annualized(equity: pd.Series) -> float:
    """
    Annualized Sharpe from equity curve. Resamples to daily, takes
    pct_change, divides mean by std. Crypto trades 24/7, so we use
    sqrt(365). Risk-free rate assumed 0.
    """
    if equity.empty:
        return 0.0
    daily = equity.resample("1D").last().dropna()
    if len(daily) < 2:
        return 0.0
    rets = daily.pct_change().dropna()
    if rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * math.sqrt(365))


def _max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min() * 100)


def _per_symbol_stats(trades: list[Trade]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sym in sorted(set(t.symbol for t in trades)):
        s = [t for t in trades if t.symbol == sym]
        wins = [t for t in s if t.pnl > 0]
        losses = [t for t in s if t.pnl <= 0]
        out[sym] = {
            "trades": len(s),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(s) * 100, 1) if s else 0.0,
            "pnl": round(sum(t.pnl for t in s), 2),
            "avg_pnl": round(sum(t.pnl for t in s) / len(s), 4) if s else 0.0,
            "fees": round(sum(t.fees_paid for t in s), 2),
        }
    return out


def _exit_reason_breakdown(trades: list[Trade]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    counter = Counter(t.exit_reason for t in trades)
    for reason, count in counter.most_common():
        s = [t for t in trades if t.exit_reason == reason]
        wins = sum(1 for t in s if t.pnl > 0)
        out[reason] = {
            "count": count,
            "wins": wins,
            "win_rate": round(wins / count * 100, 1) if count else 0.0,
            "pnl": round(sum(t.pnl for t in s), 2),
        }
    return out


def _avg_hold_minutes(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    holds = [(t.exit_time - t.entry_time).total_seconds() / 60 for t in trades]
    return round(sum(holds) / len(holds), 1)


def compute_metrics(sim: Simulator) -> dict:
    trades = sim.closed_trades
    starting = sim.starting_cash
    final_equity = sim.final_equity()
    total_return_pct = (final_equity - starting) / starting * 100 if starting > 0 else 0.0

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    total_fees = sum(t.fees_paid for t in trades)
    # Gross PnL = realized PnL + fees paid (i.e. what we'd have made without friction).
    # Fee drag is fees relative to the absolute gross movement — meaningful even
    # when gross_pnl is negative (strategy lost money AND paid fees on top).
    gross_pnl = sum(t.pnl for t in trades) + total_fees
    fee_drag = (total_fees / abs(gross_pnl) * 100) if gross_pnl != 0 else 0.0
    avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0.0
    profit_factor = (
        sum(t.pnl for t in wins) / abs(sum(t.pnl for t in losses))
        if losses and sum(t.pnl for t in losses) < 0 else float("inf") if wins else 0.0
    )

    equity = _equity_to_series(sim.equity_curve)

    return {
        "starting_cash": starting,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return_pct, 2),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "largest_win": round(max((t.pnl for t in wins), default=0.0), 4),
        "largest_loss": round(min((t.pnl for t in losses), default=0.0), 4),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "sharpe": round(_sharpe_annualized(equity), 2),
        "max_drawdown_pct": round(_max_drawdown_pct(equity), 2),
        "total_fees": round(total_fees, 2),
        "fee_drag_pct": round(fee_drag, 1),
        "avg_hold_minutes": _avg_hold_minutes(trades),
        "per_symbol": _per_symbol_stats(trades),
        "exit_reasons": _exit_reason_breakdown(trades),
        "skip_counts": {
            "already_long":   sim.rejected_for_already_long,
            "cooldown":       sim.rejected_for_cooldown,
            "max_concurrent": sim.rejected_for_concurrent_cap,
            "meme_cap":       sim.rejected_for_meme_cap,
            "dd_halt":        sim.rejected_for_dd,
        },
    }


def trades_for_report(trades: list[Trade]) -> list[dict]:
    """Serialize trades for embedding in the HTML report."""
    return [
        {
            "symbol": t.symbol,
            "entry_time": t.entry_time.isoformat(),
            "exit_time":  t.exit_time.isoformat(),
            "entry_price": t.entry_price,
            "exit_price":  t.exit_price,
            "pnl":  round(t.pnl, 4),
            "pnl_pct": round(t.pnl_pct, 2),
            "fees": round(t.fees_paid, 4),
            "reason": t.exit_reason,
        }
        for t in trades
    ]


def equity_for_report(curve: list[tuple[pd.Timestamp, float]]) -> list[dict]:
    """Serialize equity curve for Chart.js. Downsamples if too dense."""
    if not curve:
        return []
    # Cap at ~1500 points so the HTML stays light
    step = max(1, len(curve) // 1500)
    return [{"t": ts.isoformat(), "v": round(v, 2)} for ts, v in curve[::step]]
