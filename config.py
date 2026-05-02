"""
XYZTRADINGAE - Configuration
"""
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
ALPACA_API_KEY      = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY   = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL     = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
BINANCE_API_KEY     = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY  = os.getenv("BINANCE_SECRET_KEY")
NEWS_API_KEY        = os.getenv("NEWS_API_KEY")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

CRYPTO_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "SHIBUSDT", "PEPEUSDT",
    "WIFUSDT", "BONKUSDT", "FLOKIUSDT"
]

# Meme coins are treated as one bucket for concurrent-position caps —
# they're correlated and should not consume more than one risk slot.
MEME_SYMBOLS = {
    "DOGEUSDT", "SHIBUSDT", "PEPEUSDT",
    "WIFUSDT",  "BONKUSDT", "FLOKIUSDT",
}

CLAUDE_MODEL                = "claude-sonnet-4-6"
SIGNAL_CONFIDENCE_THRESHOLD = 0.55
MAX_POSITION_SIZE_PCT       = 0.30
SCAN_INTERVAL_MINUTES       = 2
REPORT_TIME                 = "08:00"
TIMEZONE                    = "Asia/Dubai"
MARDOOD_PHASE               = 2

# --- Scalping risk profile ----------------------------------------------
# Default % stops/targets — used as a fallback when ATR isn't available.
# Tight stops + 3:1 reward/risk for fast scalps (minutes to 2 hours hold).
STOP_LOSS_PCT       = 0.005    # 0.5%
TAKE_PROFIT_PCT     = 0.015    # 1.5%  (3 * SL)

# ATR-based stops (preferred when atr_pct is on the signal). Distances
# scale with realised volatility on 5-min candles but are bounded.
ATR_SL_MULTIPLIER   = 1.5
ATR_RR_MULTIPLIER   = 3.0
MIN_SL_PCT          = 0.003    # 0.3% — 5m candles have small ATR
MAX_SL_PCT          = 0.015    # 1.5% — scalp-tight ceiling

# Volume-spike detection threshold (used by indicators)
VOLUME_SPIKE_RATIO  = 2.0      # current candle volume / 20-candle avg

# Concurrent-position caps
MAX_CONCURRENT_POSITIONS = 5
MAX_MEME_POSITIONS       = 1   # all meme coins share one effective slot

# Daily drawdown circuit breaker — halt new entries if down this much
# from the day's starting equity (UTC day boundaries).
DAILY_DRAWDOWN_HALT_PCT = 0.05

# Execution friction — applied per side on every paper trade.
FEE_PCT_PER_SIDE     = 0.001    # 0.1% (Binance taker)
SLIPPAGE_PCT_MAJOR   = 0.0005   # 0.05% per side for liquid majors
SLIPPAGE_PCT_MEME    = 0.002    # 0.2% per side for meme coins

BASE_DIR    = pathlib.Path(__file__).parent
MEMORY_DB   = BASE_DIR / "memory" / "mardood.db"
LOGS_DIR    = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports" / "output"
