# XYZTradingAE

## Project Overview

AI-driven crypto paper-trading agent (formerly "mardood" — legacy DB rename
lives in `config.py:92-96`). Phase 2 of the project simulates trades with
$10,000 virtual capital, driven by an Anthropic Claude "brain"
(`claude-sonnet-4-6`) plus heuristic signal generation. Notifications go
out via Telegram. Runs continuously on Railway with a persistent SQLite
volume at `/data`.

## Architecture

- `main.py` — entry point and scheduler. `run_scan()` runs every
  `SCAN_INTERVAL_MINUTES` (240, one 4h candle). Each scan:
  1. Polls live prices for open positions, runs `check_stop_loss_take_profit`
     and emits Telegram exits.
  2. Calls `signals.generator.run_full_scan` for new candidates.
  3. Sorts by confidence, then runs greedy correlation-aware diversification
     (`main.py:82-119`) to fill free slots without piling into BTC-beta.
  4. Executes paper trades via `execution.paper_trader.execute_paper_trade`
     and logs a portfolio + effective-BTC-exposure summary.
- `config.py` — all tunables (thresholds, risk profile, watchlist, paths).
- `analysis/brain.py` — Claude API call (reads `ANTHROPIC_API_KEY` directly).
- `analysis/correlation.py` — pairwise correlation matrix used for slot
  diversification and the BTC-beta metric.
- `data/crypto/fetcher.py` — Coinbase OHLCV + live prices (1h resampled to 4h).
- `execution/paper_trader.py` — virtual portfolio, ATR-sized stops, daily
  drawdown halt, fee+slippage modelling, mark-to-market summaries.
- `memory/` — SQLite DB (`xyztradingae.db`), trade log, shadow decisions,
  correlations cache.
- `alerts/notifier.py` — low-level Telegram transport (raw HTTP via
  `requests`).
- `bot/telegram_bot.py` — sync outbound formatters
  (`send_signal_alert`, `send_trade_alert`, `send_exit_alert`,
  `send_portfolio_summary`) plus a `python-telegram-bot` Application that
  serves `/start /status /positions /signals /portfolio /help`. Polling
  runs in a daemon thread started from `main.py` with
  `run_polling(stop_signals=None)` so PTB doesn't try to install signal
  handlers off the main thread. Commands are gated to `TELEGRAM_CHAT_ID`;
  any other chat is silently ignored. If either Telegram env var is
  missing, the polling thread is skipped and the trading loop runs
  normally.

## Risk Profile

Short-term swing on 4h candles:

- Stop loss: flat 2% (`STOP_LOSS_PCT`, `MIN_SL_PCT == MAX_SL_PCT == 0.02`
  disables ATR scaling).
- Take profit: 8% (4:1 RR, `ATR_RR_MULTIPLIER = 4.0`).
- Max position size: 30% of equity (`MAX_POSITION_SIZE_PCT`).
- Concurrent positions: 5 (`MAX_CONCURRENT_POSITIONS`).
- Daily drawdown circuit breaker: halt new entries at -5% from UTC-day
  starting equity (`DAILY_DRAWDOWN_HALT_PCT`).
- Friction: 0.1% Coinbase taker fee + 0.05% slippage, per side.
- Confidence threshold: 0.72 (raised from 0.65 to filter the noise-floor
  65-68% cluster the brain emits in BTC bull regimes).

`SHADOW_MODE=False` runs live paper trades. Flipping to True logs brain
and heuristic decisions to `shadow_decisions` without opening new
positions; SL/TP exits on existing positions still run.

## Watchlist

13 Coinbase-listed majors (`config.py:17-30`):

`BTC, SOL, XRP, AVAX, LINK, DOT, ADA, ARB, OP, UNI, SUI, TON, POL`

POL is the rebranded MATIC successor. Excluded:

- BNB, TRX — CoinGecko-only, rate-limited on Railway shared IPs; both
  >80% BTC-correlated so diversification loss is minimal.
- ETH, DOGE, SHIB, memes (PEPE/WIF/BONK/FLOKI) — excluded per backtest
  rationale; see commit history.

`_LEGACY_DROPPED_SYMBOLS` in `execution/paper_trader.py:23-27` refunds
any orphaned positions in dropped symbols on next deploy.

## Recent Changes

- `12b8d73` Mark-to-market in `paper_trader.get_performance_summary`.
- `ee3d041` Dashboard `portfolio_value` includes open position value, not
  just realized PnL.
- `8613ab0` Bias brain toward HOLD; threshold raised to 0.72.
- `e1dd92d` Data-driven correlation-aware position selection
  (greedy diversification in `main.py`).
- `7b543cd` Drop BNB and TRX from watchlist; all symbols now on Coinbase.

## Development Commands

```
python main.py            # live loop, scans every SCAN_INTERVAL_MINUTES
python main.py --once     # run one scan and exit
python main.py --stats    # print performance panel
```

Environment variables (loaded via `.env`):
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`,
`HUGGINGFACE_API_KEY`, `FINNHUB_API_KEY`, `DATA_DIR` (Railway volume mount;
falls back to `./memory` locally).
