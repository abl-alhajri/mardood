"""
XYZTradingAE — backtest harness.

Replays historical 5-min OHLCV through a strategy (heuristic or brain),
simulates the production paper-trader's risk model, and renders an HTML
report with equity curve + headline metrics.

Completely isolated from production: no live DB writes, no live API calls
to Anthropic in heuristic mode, all caches under backtest/cache/.
"""
