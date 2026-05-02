"""
XYZTradingAE — Technical Indicators (no external libraries needed)
Calculates RSI, MACD, Bollinger Bands, EMA, ATR, and volume-spike
ratios manually using pandas only.
"""
import pandas as pd
from config import VOLUME_SPIKE_RATIO


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]

    # EMAs
    df["ema_20"]  = ema(close, 20)
    df["ema_50"]  = ema(close, 50)
    df["ema_200"] = ema(close, 200)

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    df["macd"] = ema12 - ema26
    df["macd_signal"] = ema(df["macd"], 9)
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_mid"]   = sma20
    df["bb_lower"] = sma20 - 2 * std20

    # ATR(14) — volatility for risk-adjusted stops
    high_low  = df["high"] - df["low"]
    high_pc   = (df["high"] - close.shift()).abs()
    low_pc    = (df["low"]  - close.shift()).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    df["atr"]     = tr.rolling(14).mean()
    df["atr_pct"] = df["atr"] / close

    # Volume — current vs trailing 20-candle avg. Spikes are the highest-
    # quality breakout confirmation in scalping.
    df["volume_avg_20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"]  = df["volume"] / df["volume_avg_20"].replace(0, 1e-10)

    return df.dropna(subset=["ema_20", "rsi"])


def get_signal_summary(df: pd.DataFrame) -> dict:
    latest = df.iloc[-1]
    prev   = df.iloc[-2]

    bb_range = latest["bb_upper"] - latest["bb_lower"]
    bb_pos = round((latest["close"] - latest["bb_lower"]) / bb_range, 2) if bb_range != 0 else 0.5

    return {
        "price":          round(float(latest["close"]), 6),
        "rsi":            round(float(latest["rsi"]), 1),
        "macd":           round(float(latest["macd"]), 6),
        "macd_signal":    round(float(latest["macd_signal"]), 6),
        "macd_hist":      round(float(latest["macd_hist"]), 6),
        "macd_crossed_up": bool(prev["macd"] < prev["macd_signal"] and latest["macd"] > latest["macd_signal"]),
        "ema_20":         round(float(latest["ema_20"]), 6),
        "ema_50":         round(float(latest["ema_50"]), 6),
        "ema_200":        round(float(latest["ema_200"]), 6),
        "bb_upper":       round(float(latest["bb_upper"]), 6),
        "bb_lower":       round(float(latest["bb_lower"]), 6),
        "bb_position":    bb_pos,
        "atr":            round(float(latest["atr"]), 6) if pd.notna(latest["atr"]) else 0.0,
        "atr_pct":        round(float(latest["atr_pct"]), 5) if pd.notna(latest["atr_pct"]) else 0.0,
        "above_ema20":    bool(latest["close"] > latest["ema_20"]),
        "above_ema50":    bool(latest["close"] > latest["ema_50"]),
        "above_ema200":   bool(latest["close"] > latest["ema_200"]),
        "volume":         float(latest["volume"]),
        "volume_avg_20":  round(float(latest["volume_avg_20"]), 2) if pd.notna(latest["volume_avg_20"]) else 0.0,
        "volume_ratio":   round(float(latest["volume_ratio"]), 2) if pd.notna(latest["volume_ratio"]) else 1.0,
        "volume_spike":   bool(latest["volume_ratio"] > VOLUME_SPIKE_RATIO) if pd.notna(latest["volume_ratio"]) else False,
    }