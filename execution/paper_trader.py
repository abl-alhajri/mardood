"""
XYZTradingAE — Paper Trading Engine

Simulates real trades with virtual $10,000.
Models taker fees + per-symbol slippage, ATR-sized stops, concurrent
position caps (meme coins as one bucket), and a daily drawdown halt.
"""
import sqlite3
from datetime import datetime, timezone
from config import (
    MEMORY_DB,
    MAX_POSITION_SIZE_PCT,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    ATR_SL_MULTIPLIER, ATR_RR_MULTIPLIER, MIN_SL_PCT, MAX_SL_PCT,
    MAX_CONCURRENT_POSITIONS, MAX_MEME_POSITIONS, MEME_SYMBOLS,
    DAILY_DRAWDOWN_HALT_PCT,
    FEE_PCT_PER_SIDE, SLIPPAGE_PCT_MAJOR, SLIPPAGE_PCT_MEME,
)

MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    return sqlite3.connect(MEMORY_DB)


def _now() -> str:
    return datetime.utcnow().isoformat()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _slippage_for(symbol: str) -> float:
    return SLIPPAGE_PCT_MEME if symbol in MEME_SYMBOLS else SLIPPAGE_PCT_MAJOR


def _friction_per_side(symbol: str) -> float:
    """Combined fee + slippage paid on each side of a round-trip."""
    return FEE_PCT_PER_SIDE + _slippage_for(symbol)


def _ensure_column(conn, table: str, col: str, col_def: str):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")


def init_paper_trading():
    """Create tables and apply schema migrations."""
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

        # Migration: daily-equity baseline columns for the drawdown circuit breaker
        _ensure_column(conn, "portfolio", "daily_start_value", "REAL DEFAULT 10000.0")
        _ensure_column(conn, "portfolio", "daily_start_date",  "TEXT")

        # Initialize portfolio if empty
        count = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
        if count == 0:
            conn.execute("""
                INSERT INTO portfolio (cash, total_trades, wins, losses, updated_at,
                                       daily_start_value, daily_start_date)
                VALUES (10000.0, 0, 0, 0, ?, 10000.0, ?)
            """, (_now(), _today_utc()))
        conn.commit()

    _cleanup_stale_stock_positions()


def _cleanup_stale_stock_positions():
    """One-shot: close any open stock positions left from before stocks were removed."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, symbol, quantity, entry_price, entry_time "
            "FROM positions WHERE status='OPEN' AND asset_type='stock'"
        ).fetchall()
        if not rows:
            return
        now = _now()
        refunded = 0.0
        for pid, sym, qty, entry, etime in rows:
            cost = qty * entry
            refunded += cost
            conn.execute("UPDATE positions SET status='CLOSED' WHERE id=?", (pid,))
            conn.execute("""
                INSERT INTO trade_history
                    (symbol, side, entry_price, exit_price, quantity, pnl, pnl_pct,
                     entry_time, exit_time, exit_reason)
                VALUES (?, 'BUY', ?, ?, ?, 0.0, 0.0, ?, ?, 'Stocks deprecated - refunded')
            """, (sym, entry, entry, qty, etime, now))
        conn.execute(
            "UPDATE portfolio SET cash=cash+?, updated_at=? WHERE id=1",
            (refunded, now),
        )
        conn.commit()
        print(f"[paper_trader] Refunded ${refunded:.2f} from {len(rows)} stale stock position(s)")


def get_portfolio() -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT cash, total_trades, wins, losses FROM portfolio WHERE id=1"
        ).fetchone()
        portfolio = {
            "cash": row[0],
            "total_trades": row[1],
            "wins": row[2],
            "losses": row[3],
        }
        positions = conn.execute(
            "SELECT id, symbol, asset_type, side, quantity, entry_price, "
            "       stop_loss, take_profit, entry_time, status "
            "FROM positions WHERE status='OPEN'"
        ).fetchall()
        portfolio["positions"] = [{
            "id": p[0], "symbol": p[1], "asset_type": p[2], "side": p[3],
            "quantity": p[4], "entry_price": p[5],
            "stop_loss": p[6], "take_profit": p[7],
            "entry_time": p[8], "status": p[9],
        } for p in positions]
        return portfolio


def _refresh_daily_baseline(conn):
    """Snapshot the day's starting equity if the UTC day has rolled over."""
    today = _today_utc()
    row = conn.execute(
        "SELECT cash, daily_start_date FROM portfolio WHERE id=1"
    ).fetchone()
    cash, daily_date = row[0], row[1]
    if daily_date == today:
        return
    open_notional = conn.execute(
        "SELECT COALESCE(SUM(quantity*entry_price), 0) FROM positions WHERE status='OPEN'"
    ).fetchone()[0]
    total = cash + open_notional
    conn.execute(
        "UPDATE portfolio SET daily_start_value=?, daily_start_date=? WHERE id=1",
        (total, today),
    )
    conn.commit()


def _daily_drawdown_pct(conn) -> tuple[float, float]:
    """Returns (drawdown_fraction, daily_start_value). Drawdown is positive when down."""
    row = conn.execute(
        "SELECT cash, daily_start_value FROM portfolio WHERE id=1"
    ).fetchone()
    cash = row[0]
    daily_start = row[1] or cash
    open_notional = conn.execute(
        "SELECT COALESCE(SUM(quantity*entry_price), 0) FROM positions WHERE status='OPEN'"
    ).fetchone()[0]
    current_total = cash + open_notional
    if daily_start <= 0:
        return 0.0, daily_start
    return (daily_start - current_total) / daily_start, daily_start


def _compute_stops(current_price: float, atr_pct: float | None) -> tuple[float, float, float, float]:
    """
    Returns (stop_loss_price, take_profit_price, sl_dist_pct, tp_dist_pct).
    Uses ATR when available, falls back to flat % from config.
    Always preserves the configured reward:risk ratio.
    """
    if atr_pct and atr_pct > 0:
        sl_dist = max(MIN_SL_PCT, min(MAX_SL_PCT, ATR_SL_MULTIPLIER * atr_pct))
        tp_dist = sl_dist * ATR_RR_MULTIPLIER
    else:
        sl_dist = STOP_LOSS_PCT
        tp_dist = TAKE_PROFIT_PCT
    return (
        current_price * (1 - sl_dist),
        current_price * (1 + tp_dist),
        sl_dist,
        tp_dist,
    )


def execute_paper_trade(signal: dict, current_price: float) -> dict | None:
    """
    Execute a paper trade. Returns either a {"action": "OPENED"|"CLOSED"} dict,
    a {"action": "SKIPPED", "reason": ...} dict, or None when the signal isn't actionable.
    """
    symbol = signal["symbol"]
    sig = signal["signal"]
    atr_pct = signal.get("atr_pct")

    portfolio = get_portfolio()
    cash = portfolio["cash"]
    open_positions = {p["symbol"]: p for p in portfolio["positions"]}
    open_count = len(open_positions)
    meme_count = sum(1 for s in open_positions if s in MEME_SYMBOLS)

    # SELL: close existing position
    if sig == "SELL" and symbol in open_positions:
        return close_position(open_positions[symbol], current_price, "SELL signal")

    if sig != "BUY":
        return None

    # --- Pre-flight gates --------------------------------------------------
    if symbol in open_positions:
        return {"action": "SKIPPED", "symbol": symbol, "reason": "already long"}

    if open_count >= MAX_CONCURRENT_POSITIONS:
        return {"action": "SKIPPED", "symbol": symbol,
                "reason": f"max concurrent positions ({MAX_CONCURRENT_POSITIONS})"}

    if symbol in MEME_SYMBOLS and meme_count >= MAX_MEME_POSITIONS:
        return {"action": "SKIPPED", "symbol": symbol,
                "reason": f"meme bucket full ({MAX_MEME_POSITIONS} open)"}

    with get_conn() as conn:
        _refresh_daily_baseline(conn)
        dd_pct, _ = _daily_drawdown_pct(conn)
    if dd_pct >= DAILY_DRAWDOWN_HALT_PCT:
        return {"action": "SKIPPED", "symbol": symbol,
                "reason": f"daily drawdown halt (-{dd_pct*100:.1f}%)"}

    position_value = cash * MAX_POSITION_SIZE_PCT
    if position_value < 10:
        return {"action": "SKIPPED", "symbol": symbol,
                "reason": f"insufficient cash (${cash:.2f})"}

    # --- Open the position ------------------------------------------------
    # Friction: pay slippage + fee on entry. position_value is exactly what
    # cash decreases by; quantity is reduced so qty*price*(1+friction) == position_value.
    friction = _friction_per_side(symbol)
    quantity = position_value / (current_price * (1 + friction))
    entry_price = current_price  # store mid; SL/TP triggers compare mid prices

    sl_price, tp_price, sl_dist, tp_dist = _compute_stops(current_price, atr_pct)

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO positions
                (symbol, asset_type, side, quantity, entry_price,
                 stop_loss, take_profit, entry_time)
            VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?)
        """, (symbol, signal.get("asset_type", ""), quantity,
              entry_price, sl_price, tp_price, _now()))
        conn.execute(
            "UPDATE portfolio SET cash=cash-?, total_trades=total_trades+1, updated_at=? WHERE id=1",
            (position_value, _now()),
        )
        conn.commit()

    return {
        "action": "OPENED",
        "symbol": symbol,
        "quantity": round(quantity, 6),
        "entry_price": round(entry_price, 6),
        "stop_loss": round(sl_price, 6),
        "take_profit": round(tp_price, 6),
        "sl_pct": round(sl_dist * 100, 2),
        "tp_pct": round(tp_dist * 100, 2),
        "atr_used": bool(atr_pct and atr_pct > 0),
        "cost": round(position_value, 2),
        "friction_pct": round(friction * 100, 3),
    }


def close_position(position: dict, exit_price_mid: float, reason: str) -> dict:
    """Close a position, applying slippage + fee on exit."""
    symbol = position["symbol"]
    qty = position["quantity"]
    entry_mid = position["entry_price"]
    friction = _friction_per_side(symbol)

    # Reconstruct what we paid going in (cash decreased by this amount on open)
    entry_cost   = qty * entry_mid * (1 + friction)
    # What we receive coming out, after slippage + fee
    exit_proceeds = qty * exit_price_mid * (1 - friction)
    pnl = exit_proceeds - entry_cost
    pnl_pct = (pnl / entry_cost) * 100 if entry_cost > 0 else 0.0
    won = pnl > 0

    with get_conn() as conn:
        conn.execute("UPDATE positions SET status='CLOSED' WHERE id=?", (position["id"],))
        conn.execute("""
            INSERT INTO trade_history
                (symbol, side, entry_price, exit_price, quantity, pnl, pnl_pct,
                 entry_time, exit_time, exit_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, "BUY", entry_mid, exit_price_mid, qty, pnl, pnl_pct,
              position["entry_time"], _now(), reason))
        conn.execute("""
            UPDATE portfolio
            SET cash = cash + ?, wins = wins + ?, losses = losses + ?, updated_at = ?
            WHERE id = 1
        """, (exit_proceeds, 1 if won else 0, 0 if won else 1, _now()))
        conn.commit()

    return {
        "action": "CLOSED",
        "symbol": symbol,
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl_pct, 2),
        "reason": reason,
    }


def check_stop_loss_take_profit(current_prices: dict) -> list:
    """Check all open positions against fresh prices for SL/TP exits."""
    results = []
    portfolio = get_portfolio()

    for pos in portfolio["positions"]:
        price = current_prices.get(pos["symbol"])
        if not price:
            continue

        if price <= pos["stop_loss"]:
            results.append(close_position(pos, price, "Stop-loss hit"))
        elif price >= pos["take_profit"]:
            results.append(close_position(pos, price, "Take-profit hit"))

    return results


def get_performance_summary() -> dict:
    portfolio = get_portfolio()
    with get_conn() as conn:
        trades = conn.execute("SELECT * FROM trade_history").fetchall()

    total_pnl = sum(t[6] for t in trades) if trades else 0
    win_rate = (portfolio["wins"] / portfolio["total_trades"] * 100) if portfolio["total_trades"] > 0 else 0

    return {
        "cash":            round(portfolio["cash"], 2),
        "total_trades":    portfolio["total_trades"],
        "wins":            portfolio["wins"],
        "losses":          portfolio["losses"],
        "win_rate":        round(win_rate, 1),
        "total_pnl":       round(total_pnl, 2),
        "portfolio_value": round(portfolio["cash"] + total_pnl, 2),
    }


init_paper_trading()
