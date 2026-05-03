"""
Rule-based heuristic decision — shared by the backtest harness and
production shadow mode. Mirrors the production brain's playbook with
a deterministic six-condition entry filter.

Same gate used in the backtest, where 90 days of historical data
showed +5.93% / Sharpe 2.41 with maker fees + every-candle sampling.
"""
from __future__ import annotations


def heuristic_decision(indicators: dict, btc_regime_bullish: bool = True) -> dict:
    """
    Single high-conviction BUY path. Six confirming layers required:

      1. BTC regime: BTC above its 1h EMA200 (broad market trending up)
      2. Bullish EMA stack on the symbol (price > EMA20 > EMA50 > EMA200)
      3. MACD histogram meaningfully positive (> 0.05% of price — filters
         micro-crosses near zero AND captures established momentum)
      4. RSI in 55-70 (bullish without being overbought)
      5. bb_position > 0.65 (price actively breaking out, not mid-range)
      6. volume_spike=true (real breakout, not chop)

    Returns the same dict shape as the brain's record_signal tool output,
    so production can log them side-by-side for comparison.
    """
    rsi = float(indicators.get("rsi", 50))
    macd_hist = float(indicators.get("macd_hist", 0))
    bb_pos = float(indicators.get("bb_position", 0.5))
    above_ema20 = bool(indicators.get("above_ema20", False))
    above_ema50 = bool(indicators.get("above_ema50", False))
    above_ema200 = bool(indicators.get("above_ema200", False))
    volume_spike = bool(indicators.get("volume_spike", False))
    price = float(indicators.get("price", 0))

    bullish_stack = above_ema20 and above_ema50 and above_ema200

    # MACD histogram normalized to price scale — works across BTC's
    # dollar-scale and SHIB's microscopic histogram values.
    macd_hist_pct = (macd_hist / price) if price > 0 else 0.0
    macd_meaningful = macd_hist_pct > 0.0005

    if (
        btc_regime_bullish
        and bullish_stack
        and macd_meaningful
        and 55 <= rsi <= 70
        and bb_pos > 0.65
        and volume_spike
    ):
        return {
            "signal": "BUY", "confidence": 0.82,
            "reasoning": (
                f"BTC trend OK + bullish stack + MACD hist {macd_hist_pct*100:.3f}% "
                f"+ RSI {rsi:.0f} + bb {bb_pos:.2f} + volume_spike"
            ),
            "key_factors": ["BTC regime", "EMA stack", "MACD momentum", "volume spike"],
            "risk_level": "MEDIUM", "timeframe": "SHORT",
        }

    return {
        "signal": "HOLD", "confidence": 0.50,
        "reasoning": "no high-conviction setup",
        "key_factors": [],
        "risk_level": "LOW", "timeframe": "SHORT",
    }
