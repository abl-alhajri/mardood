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
SIGNAL_CONFIDENCE_THRESHOLD = 0.40
MAX_POSITION_SIZE_PCT       = 0.30
SCAN_INTERVAL_MINUTES       = 30
REPORT_TIME                 = "08:00"
TIMEZONE                    = "Asia/Dubai"
MARDOOD_PHASE               = 2

# --- Risk management ----------------------------------------------------
# Default % stops/targets — used as a fallback when ATR isn't available.
# These mirror the brain's stated strategy (4:1 reward/risk).
STOP_LOSS_PCT       = 0.02   # 2%
TAKE_PROFIT_PCT     = 0.08   # 8% (4 * SL)

# ATR-based stops (preferred when atr_pct is on the signal). Distance
# scales with realised volatility, but is bounded so meme coins don't
# blow out into 30%+ stops.
ATR_SL_MULTIPLIER   = 1.5
ATR_RR_MULTIPLIER   = 4.0
MIN_SL_PCT          = 0.01
MAX_SL_PCT          = 0.05

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
