"""
In-memory paper-trading simulator.

Mirrors execution.paper_trader's risk model — concurrent caps, meme bucket,
ATR-based stops with bounds, fees + slippage on both sides, daily drawdown
halt — but writes nothing to disk. State lives in lists/dicts on the
simulator instance.

Intra-candle SL/TP triggers use the candle's high/low (matches the
production wick-check fix).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from config import (
    MAX_POSITION_SIZE_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    ATR_SL_MULTIPLIER, ATR_RR_MULTIPLIER, MIN_SL_PCT, MAX_SL_PCT,
    MAX_CONCURRENT_POSITIONS, MAX_MEME_POSITIONS, MEME_SYMBOLS,
    DAILY_DRAWDOWN_HALT_PCT,
    FEE_PCT_PER_SIDE, SLIPPAGE_PCT_MAJOR, SLIPPAGE_PCT_MEME,
)


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float
    entry_cost: float       # cash decreased by this amount on open
    stop_loss: float
    take_profit: float
    entry_time: pd.Timestamp
    entry_friction: float


@dataclass
class Trade:
    symbol: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    pnl: float
    pnl_pct: float
    fees_paid: float
    exit_reason: str


@dataclass
class Simulator:
    starting_cash: float = 10000.0
    cash: float = 10000.0
    # Optional override for FEE_PCT_PER_SIDE — useful for testing
    # maker-only economics (set to 0.0) or higher-fee scenarios.
    # None means "use the config default".
    fee_pct_per_side: Optional[float] = None
    open_positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)
    skip_log: list[tuple[pd.Timestamp, str, str]] = field(default_factory=list)

    daily_start_value: float = 10000.0
    daily_start_date: Optional[str] = None

    # Cooldown after a stop-out: don't re-enter the same symbol for N minutes
    last_stop_out: dict[str, pd.Timestamp] = field(default_factory=dict)
    cooldown_minutes: int = 60

    # Tracking
    rejected_for_dd: int = 0
    rejected_for_concurrent_cap: int = 0
    rejected_for_meme_cap: int = 0
    rejected_for_already_long: int = 0
    rejected_for_cooldown: int = 0

    def __post_init__(self):
        self.cash = self.starting_cash
        self.daily_start_value = self.starting_cash

    # ───── helpers ─────────────────────────────────────────────────────

    def _slippage(self, symbol: str) -> float:
        return SLIPPAGE_PCT_MEME if symbol in MEME_SYMBOLS else SLIPPAGE_PCT_MAJOR

    def _friction(self, symbol: str) -> float:
        fee = self.fee_pct_per_side if self.fee_pct_per_side is not None else FEE_PCT_PER_SIDE
        return fee + self._slippage(symbol)

    def _compute_stops(self, price: float, atr_pct: Optional[float]) -> tuple[float, float, float, float]:
        if atr_pct and atr_pct > 0:
            sl_dist = max(MIN_SL_PCT, min(MAX_SL_PCT, ATR_SL_MULTIPLIER * atr_pct))
            tp_dist = sl_dist * ATR_RR_MULTIPLIER
        else:
            sl_dist = STOP_LOSS_PCT
            tp_dist = TAKE_PROFIT_PCT
        return price * (1 - sl_dist), price * (1 + tp_dist), sl_dist, tp_dist

    def _open_notional(self) -> float:
        return sum(p.quantity * p.entry_price for p in self.open_positions.values())

    def _refresh_daily_baseline(self, ts: pd.Timestamp):
        today = ts.strftime("%Y-%m-%d")
        if self.daily_start_date != today:
            self.daily_start_value = self.cash + self._open_notional()
            self.daily_start_date = today

    def _drawdown_pct(self) -> float:
        current = self.cash + self._open_notional()
        if self.daily_start_value <= 0:
            return 0.0
        return (self.daily_start_value - current) / self.daily_start_value

    # ───── public API ──────────────────────────────────────────────────

    def update_equity(self, ts: pd.Timestamp, mark_prices: dict[str, float]):
        """Mark-to-market the equity curve at the given timestamp."""
        unrealized = 0.0
        for sym, pos in self.open_positions.items():
            mark = mark_prices.get(sym, pos.entry_price)
            unrealized += (mark - pos.entry_price) * pos.quantity
        self.equity_curve.append((ts, self.cash + self._open_notional() + unrealized))

    def check_exits(self, ts: pd.Timestamp, ohlcv_row: dict[str, dict]):
        """Walk open positions and fire SL/TP based on candle high/low."""
        for sym in list(self.open_positions.keys()):
            row = ohlcv_row.get(sym)
            if not row:
                continue
            pos = self.open_positions[sym]
            high, low = row["high"], row["low"]
            # SL first (conservative)
            if low <= pos.stop_loss:
                self._close(pos, ts, pos.stop_loss, "Stop-loss hit (wick)")
            elif high >= pos.take_profit:
                self._close(pos, ts, pos.take_profit, "Take-profit hit (wick)")

    def try_open(self, symbol: str, signal: dict, ts: pd.Timestamp, price: float) -> str:
        """Apply signal. Returns 'OPENED', 'SKIPPED:<reason>', or 'NOOP'."""
        sig = signal.get("signal", "HOLD")
        atr_pct = signal.get("atr_pct")

        # SELL signals are ignored — see paper_trader.execute_paper_trade for rationale.
        if sig != "BUY":
            return "NOOP"

        # Pre-flight gates
        if symbol in self.open_positions:
            self.rejected_for_already_long += 1
            self.skip_log.append((ts, symbol, "already long"))
            return "SKIPPED:already_long"

        # Cooldown: don't re-enter a symbol within N minutes of a stop-out.
        # Stop-outs imply the local trend just rolled — re-entering immediately
        # tends to stack into the same losing setup.
        if symbol in self.last_stop_out:
            elapsed_min = (ts - self.last_stop_out[symbol]).total_seconds() / 60
            if elapsed_min < self.cooldown_minutes:
                self.rejected_for_cooldown += 1
                self.skip_log.append(
                    (ts, symbol, f"cooldown ({elapsed_min:.0f}/{self.cooldown_minutes} min)"))
                return "SKIPPED:cooldown"

        if len(self.open_positions) >= MAX_CONCURRENT_POSITIONS:
            self.rejected_for_concurrent_cap += 1
            self.skip_log.append((ts, symbol, f"max concurrent ({MAX_CONCURRENT_POSITIONS})"))
            return "SKIPPED:max_concurrent"

        if symbol in MEME_SYMBOLS:
            meme_count = sum(1 for s in self.open_positions if s in MEME_SYMBOLS)
            if meme_count >= MAX_MEME_POSITIONS:
                self.rejected_for_meme_cap += 1
                self.skip_log.append((ts, symbol, "meme bucket full"))
                return "SKIPPED:meme_cap"

        self._refresh_daily_baseline(ts)
        if self._drawdown_pct() >= DAILY_DRAWDOWN_HALT_PCT:
            self.rejected_for_dd += 1
            self.skip_log.append((ts, symbol, "daily DD halt"))
            return "SKIPPED:dd_halt"

        position_value = self.cash * MAX_POSITION_SIZE_PCT
        if position_value < 10:
            self.skip_log.append((ts, symbol, f"insufficient cash ${self.cash:.2f}"))
            return "SKIPPED:no_cash"

        friction = self._friction(symbol)
        quantity = position_value / (price * (1 + friction))
        sl, tp, _, _ = self._compute_stops(price, atr_pct)

        pos = Position(
            symbol=symbol, quantity=quantity, entry_price=price,
            entry_cost=position_value,
            stop_loss=sl, take_profit=tp,
            entry_time=ts, entry_friction=friction,
        )
        self.open_positions[symbol] = pos
        self.cash -= position_value
        return "OPENED"

    def _close(self, pos: Position, ts: pd.Timestamp, exit_price: float, reason: str):
        # Use friction as it was at entry (locked at open) for the cost,
        # current friction for the exit.
        exit_friction = self._friction(pos.symbol)
        exit_proceeds = pos.quantity * exit_price * (1 - exit_friction)
        pnl = exit_proceeds - pos.entry_cost
        pnl_pct = (pnl / pos.entry_cost) * 100 if pos.entry_cost > 0 else 0.0

        # Total fees paid round-trip — useful for the report's fee-drag stat
        entry_fees = pos.quantity * pos.entry_price * pos.entry_friction
        exit_fees = pos.quantity * exit_price * exit_friction
        fees_paid = entry_fees + exit_fees

        self.closed_trades.append(Trade(
            symbol=pos.symbol,
            entry_price=pos.entry_price, exit_price=exit_price,
            quantity=pos.quantity,
            entry_time=pos.entry_time, exit_time=ts,
            pnl=pnl, pnl_pct=pnl_pct, fees_paid=fees_paid,
            exit_reason=reason,
        ))
        self.cash += exit_proceeds
        # Trip the cooldown clock if this was a stop-out (not a TP or end-of-test)
        if reason.startswith("Stop-loss"):
            self.last_stop_out[pos.symbol] = ts
        del self.open_positions[pos.symbol]

    def force_close_all(self, ts: pd.Timestamp, mark_prices: dict[str, float]):
        """At end of backtest, close any still-open positions at last mark."""
        for sym in list(self.open_positions.keys()):
            pos = self.open_positions[sym]
            mark = mark_prices.get(sym, pos.entry_price)
            self._close(pos, ts, mark, "End of backtest")

    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.starting_cash
