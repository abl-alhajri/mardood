"""
MARDOOD � Configuration
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

CRYPTO_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "SHIBUSDT", "PEPEUSDT",
    "WIFUSDT", "BONKUSDT", "FLOKIUSDT"
]

CLAUDE_MODEL                = "gemini-2.0-flash"
SIGNAL_CONFIDENCE_THRESHOLD = 0.40
MAX_POSITION_SIZE_PCT       = 0.30
STOP_LOSS_PCT               = 0.05
TAKE_PROFIT_PCT             = 0.25
SCAN_INTERVAL_MINUTES       = 30
REPORT_TIME                 = "08:00"
TIMEZONE                    = "Asia/Dubai"
MARDOOD_PHASE               = 2
BASE_DIR                    = pathlib.Path(__file__).parent
MEMORY_DB                   = BASE_DIR / "memory" / "mardood.db"
LOGS_DIR                    = BASE_DIR / "logs"
REPORTS_DIR                 = BASE_DIR / "reports" / "output"
