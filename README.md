# 🤖 Mardood — AI Trading Agent

Your personal AI agent for US stocks and crypto analysis, signals, and execution.

## Project Structure
```
mardood/
├── main.py                  # Entry point — run Mardood
├── config.py                # All API keys and settings
├── .env                     # Your secret keys (never commit this)
├── requirements.txt         # Python dependencies
│
├── data/                    # Data fetching layer
│   ├── stocks/              # US stock market data
│   │   ├── fetcher.py       # Yahoo Finance / Alpaca
│   │   └── screener.py      # Filter stocks by criteria
│   ├── crypto/              # Crypto market data
│   │   ├── fetcher.py       # Binance / CoinGecko
│   │   └── screener.py      # Filter crypto by criteria
│   └── news/
│       └── fetcher.py       # News & sentiment feeds
│
├── analysis/                # Analysis engine (Claude API brain)
│   ├── technical/
│   │   └── indicators.py    # RSI, MACD, Bollinger Bands, EMA
│   ├── fundamental/
│   │   └── analyzer.py      # P/E ratio, earnings, financials
│   ├── sentiment/
│   │   └── analyzer.py      # Fear/greed index, social sentiment
│   └── brain.py             # Claude API — master analyst
│
├── signals/
│   └── generator.py         # BUY / HOLD / SELL with confidence score
│
├── execution/
│   ├── paper_trader.py      # Simulated trades (Phase 2)
│   └── live_trader.py       # Real execution (Phase 3)
│
├── alerts/
│   └── notifier.py          # Telegram / email alerts
│
├── reports/
│   └── chart_builder.py     # Plotly charts and daily reports
│
├── memory/
│   └── trade_log.py         # SQLite trade history and logs
│
└── utils/
    └── helpers.py           # Shared utilities
```

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Add your API keys to `.env`

3. Run Mardood:
   ```bash
   python main.py
   ```

## Phases
- **Phase 1** (current): Analysis + alerts
- **Phase 2**: Charts, reports, paper trading
- **Phase 3**: Live auto-execution

