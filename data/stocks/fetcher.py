"""
Mardood — Stock Data Fetcher
Fetches OHLCV data, volume, and fundamentals for US stocks.
"""
import yfinance as yf
import pandas as pd
from config import STOCKS_WATCHLIST


def get_stock_data(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch historical OHLCV data for a stock.

    Args:
        ticker:   Stock symbol e.g. "AAPL"
        period:   "1d", "5d", "1mo", "3mo", "6mo", "1y"
        interval: "1m","5m","15m","30m","1h","1d","1wk"

    Returns:
        DataFrame with Open, High, Low, Close, Volume columns
    """
    stock = yf.Ticker(ticker)
    df = stock.history(period=period, interval=interval)
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    return df


def get_stock_info(ticker: str) -> dict:
    """Fetch fundamental info: P/E, market cap, sector, earnings."""
    stock = yf.Ticker(ticker)
    return stock.info


def get_watchlist_data(period: str = "3mo") -> dict:
    """Fetch data for all stocks in watchlist."""
    return {ticker: get_stock_data(ticker, period) for ticker in STOCKS_WATCHLIST}
