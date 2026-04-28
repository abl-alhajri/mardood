"""
Mardood — Shared Utilities
"""
from datetime import datetime
import pytz
from config import TIMEZONE


def now_local() -> datetime:
    """Current time in your local timezone (Dubai)."""
    return datetime.now(pytz.timezone(TIMEZONE))


def is_market_open() -> bool:
    """Check if the US stock market is currently open."""
    now_ny = now_local().astimezone(pytz.timezone("America/New_York"))
    if now_ny.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    open_t  = now_ny.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now_ny.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now_ny <= close_t


def format_price(price: float, decimals: int = 2) -> str:
    return f"${price:,.{decimals}f}"


def pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return round((new - old) / old * 100, 2)
