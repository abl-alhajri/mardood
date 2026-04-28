"""
MARDOOD — Configuration
"""
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ────────────────────────────────────────────
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
ALPACA_API_KEY      = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY   = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL     = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
BINANCE_API_KEY     = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY  = os.getenv("BINANCE_SECRET_KEY")
NEWS_API_KEY        = os.getenv("NEWS_API_KEY")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")

# ─── Watchlists ───────────────────────────────────────────
STOCKS_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
    "GOOGL", "META", "AMD", "PLTR", "SPY"
]

CRYPTO_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "SHIBUSDT", "PEPEUSDT",
    "WIFUSDT", "BONKUSDT", "FLOKIUSDT"
]

# ─── Analysis Settings ────────────────────────────────────
CLAUDE_MODEL                = "gemini-2.0-flash"
SIGNAL_CONFIDENCE_THRESHOLD = 0.65
MAX_POSITION_SIZE_PCT       = 0.05
STOP_LOSS_PCT               = 0.03
TAKE_PROFIT_PCT             = 0.09

# ─── Intervals ────────────────────────────────────────────
SCAN_INTERVAL_MINUTES = 30
REPORT_TIME           = "08:00"
TIMEZONE              = "Asia/Dubai"

# ─── Phase ───────────────────────────────────────────────
MARDOOD_PHASE = 2

# ─── Paths ───────────────────────────────────────────────
BASE_DIR    = pathlib.Path(__file__).parent
MEMORY_DB   = BASE_DIR / "memory" / "mardood.db"
LOGS_DIR    = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports" / "output"
SIGNAL_CONFIDENCE_THRESHOLD = 0.60  # يقبل إشارات أكثر

MAX_POSITION_SIZE_PCT = 0.10   # 15% لكل صفقة = 6-7 صفقات بنفس الوقت

STOP_LOSS_PCT   = 0.02   # يوقف الخسارة بـ 2% سريع
TAKE_PROFIT_PCT = 0.04   # ياخذ الربح بـ 4% سريع (نسبة 2:1)