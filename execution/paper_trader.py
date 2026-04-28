"""
Mardood — Paper Trading Engine
Simulates real trades with virtual $10,000.
Tracks performance so we know if Mardood is profitable.
"""
import json
import sqlite3
from datetime import datetime
from config import MEMORY_DB, MAX_POSITION_SIZE_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT

MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    return sqlite3.connect(MEMORY_DB)


def init_paper_trading():
    """Create paper trading tables."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id           INTEGER PRIMARY KEY,
                cash         REAL DEFAULT 10000.0,
                total_trades INTEGER DEFAULT 0,
                wins         INTEGER DEFAULT 0,
                losses       INTEGER DEFAULT 0,
                updated_at   TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL,
                asset_type   TEXT NOT NULL,
                side         TEXT NOT NULL,
                quantity     REAL,
                entry_price  REAL,
                stop_loss    REAL,
                take_profit  REAL,
                entry_time   TEXT,
                status       TEXT DEFAULT 'OPEN'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT,
                side         TEXT,
                entry_price  REAL,
                exit_price   REAL,
                quantity     REAL,
                pnl          REAL,
                pnl_pct      REAL,
                entry_time   TEXT,
                exit_time    TEXT,
                exit_reason  TEXT
            )
        """)
        # Initialize portfolio if empty
        count = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
        if count == 0:
            conn.execute("""
                INSERT INTO portfolio (cash, total_trades, wins, losses, updated_at)
                VALUES (10000.0, 0, 0, 0, ?)
            """, (datetime.utcnow().isoformat(),))
        conn.commit()


def get_portfolio() -> dict:
    """Get current portfolio state."""
    with get_conn() as conn:
        row = conn.execute("SELECT cash, total_trades, wins, losses FROM portfolio WHERE id=1").fetchone()
        portfolio = {
            "cash": row[0],
            "total_trades": row[1],
            "wins": row[2],
            "losses": row[3]
        }
        positions = conn.execute(
            "SELECT id, symbol, asset_type, side, quantity, entry_price, stop_loss, take_profit, entry_time, status FROM positions WHERE status='OPEN'"
        ).fetchall()
        portfolio["positions"] = [
            {
                "id": p[0], "symbol": p[1], "asset_type": p[2],
                "side": p[3], "quantity": p[4], "entry_price": p[5],
                "stop_loss": p[6], "take_profit": p[7],
                "entry_time": p[8], "status": p[9]
            }
            for p in positions
        ]
        return portfolio


def execute_paper_trade(signal: dict, current_price: float) -> dict | None:
    """
    Execute a paper trade based on a signal.
    Returns trade details or None if trade was skipped.
    """
    symbol = signal["symbol"]
    sig = signal["signal"]
    confidence = signal.get("confidence", 0)

    portfolio = get_portfolio()
    cash = portfolio["cash"]
    open_positions = {p["symbol"]: p for p in portfolio["positions"]}

    # --- SELL logic: close existing position ---
    if sig == "SELL" and symbol in open_positions:
        pos = open_positions[symbol]
        return close_position(pos, current_price, "SELL signal")

    # --- BUY logic: open new position ---
    if sig == "BUY":
        position_value = cash * MAX_POSITION_SIZE_PCT  # Max 5% of portfolio
        if position_value < 10:
            return None  # Not enough cash

        quantity = position_value / current_price
        stop_loss   = current_price * (1 - STOP_LOSS_PCT)
        take_profit = current_price * (1 + TAKE_PROFIT_PCT)

        with get_conn() as conn:
            conn.execute("""
                INSERT INTO positions
                    (symbol, asset_type, side, quantity, entry_price, stop_loss, take_profit, entry_time)
                VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?)
            """, (symbol, signal.get("asset_type",""), quantity,
                  current_price, stop_loss, take_profit,
                  datetime.utcnow().isoformat()))
            conn.execute("""
                UPDATE portfolio SET cash=cash-?, total_trades=total_trades+1, updated_at=?
                WHERE id=1
            """, (position_value, datetime.utcnow().isoformat()))
            conn.commit()

        return {
            "action": "OPENED",
            "symbol": symbol,
            "quantity": round(quantity, 6),
            "entry_price": current_price,
            "stop_loss": round(stop_loss, 4),
            "take_profit": round(take_profit, 4),
            "cost": round(position_value, 2)
        }

    return None


def close_position(position: dict, exit_price: float, reason: str) -> dict:
    """Close an open position and record P&L."""
    pnl = (exit_price - position["entry_price"]) * position["quantity"]
    pnl_pct = (exit_price - position["entry_price"]) / position["entry_price"] * 100
    won = pnl > 0

    with get_conn() as conn:
        conn.execute("""
            UPDATE positions SET status='CLOSED' WHERE id=?
        """, (position["id"],))
        conn.execute("""
            INSERT INTO trade_history
                (symbol, side, entry_price, exit_price, quantity, pnl, pnl_pct, entry_time, exit_time, exit_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (position["symbol"], "BUY", position["entry_price"],
              exit_price, position["quantity"], pnl, pnl_pct,
              position["entry_time"], datetime.utcnow().isoformat(), reason))
        conn.execute("""
            UPDATE portfolio
            SET cash=cash+?,
                wins=wins+?,
                losses=losses+?,
                updated_at=?
            WHERE id=1
        """, (exit_price * position["quantity"],
              1 if won else 0,
              0 if won else 1,
              datetime.utcnow().isoformat()))
        conn.commit()

    return {
        "action": "CLOSED",
        "symbol": position["symbol"],
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "reason": reason
    }


def check_stop_loss_take_profit(current_prices: dict) -> list:
    """Check all open positions for stop-loss or take-profit hits."""
    results = []
    portfolio = get_portfolio()

    for pos in portfolio["positions"]:
        symbol = pos["symbol"]
        price = current_prices.get(symbol)
        if not price:
            continue

        if price <= pos["stop_loss"]:
            result = close_position(pos, price, "Stop-loss hit")
            results.append(result)
        elif price >= pos["take_profit"]:
            result = close_position(pos, price, "Take-profit hit")
            results.append(result)

    return results


def get_performance_summary() -> dict:
    """Get overall performance stats."""
    portfolio = get_portfolio()
    with get_conn() as conn:
        trades = conn.execute("SELECT * FROM trade_history").fetchall()

    total_pnl = sum(t[6] for t in trades) if trades else 0
    win_rate = (portfolio["wins"] / portfolio["total_trades"] * 100) if portfolio["total_trades"] > 0 else 0

    return {
        "cash":          round(portfolio["cash"], 2),
        "total_trades":  portfolio["total_trades"],
        "wins":          portfolio["wins"],
        "losses":        portfolio["losses"],
        "win_rate":      round(win_rate, 1),
        "total_pnl":     round(total_pnl, 2),
        "portfolio_value": round(portfolio["cash"] + total_pnl, 2)
    }


init_paper_trading()