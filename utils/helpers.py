"""
XYZTradingAE — Shared Utilities
"""
from datetime import datetime
import pytz
from config import TIMEZONE


def now_local() -> datetime:
    """Current time in the configured local timezone."""
    return datetime.now(pytz.timezone(TIMEZONE))


def format_price(price: float, decimals: int = 2) -> str:
    return f"${price:,.{decimals}f}"


def pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return round((new - old) / old * 100, 2)
