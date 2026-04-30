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

# أسهم أمريكية (100 سهم)
STOCKS_WATCHLIST = [
    # Tech Giants
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "PLTR", "SPY",
    # Semiconductors
    "INTC", "QCOM", "AVGO", "MU", "AMAT", "KLAC", "LRCX", "ASML", "TSM", "ARM",
    # Finance & Crypto Stocks
    "JPM", "BAC", "GS", "MS", "V", "MA", "PYPL", "SQ", "COIN", "HOOD",
    # AI & Cloud
    "SMCI", "MSTR", "CRWD", "NET", "SNOW", "DDOG", "ZS", "PANW", "AI", "SOUN",
    # ETFs
    "QQQ", "IWM", "DIA", "SOXX", "ARKK",
    # Energy
    "XOM", "CVX", "OXY", "GLD", "SLV",
    # Healthcare
    "JNJ", "PFE", "MRNA", "ABBV", "UNH",
    # Consumer
    "NFLX", "DIS", "SBUX", "NKE", "MCD",
    # Electric Vehicles
    "RIVN", "LCID", "NIO", "LI", "XPEV",
    # Space & Defense
    "BA", "LMT", "RTX", "NOC", "SPCE",
    # Small Cap Growth
    "IONQ", "RGTI", "QUBT", "BBAI", "AEVA",
    # Social Media
    "SNAP", "PINS", "RDDT", "SPOT", "RBLX",
    # Real Estate Tech
    "UBER", "LYFT", "ABNB", "DASH", "GRAB",
    # Biotech
    "CRSP", "EDIT", "NTLA", "BEAM", "RXRX",
]

# كريبتو رئيسي + ميم كوينز (50 عملة)
CRYPTO_WATCHLIST = [
    # Layer 1 - الكبار
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT",
    "ATOMUSDT", "NEARUSDT", "APTUSDT", "SUIUSDT", "SEIUSDT",

    # Layer 2
    "ARBUSDT", "OPUSDT", "STRKUSDT", "ZKUSDT", "IMXUSDT",

    # DeFi
    "UNIUSDT", "AAVEUSDT", "MKRUSDT", "CRVUSDT", "COMPUSDT",
    "JUPUSDT", "RAYUSDT", "ORCAUSDT",

    # AI & Data
    "FETUSDT", "AGIXUSDT", "RNDRУСДТ", "INJUSDT", "TAOУСДТ",
    "WLDUSDT", "OCEANUSDT",

    # Meme Coins 🐸
    "DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT",
    "FLOKIUSDT", "MEMEUSDT", "BRETTUSDT", "MOGUSDT", "POPCAT",
    "NEIROUSDT", "GOATUSDT", "PNUTUSDT", "ACTUSDT", "LUNCUSDT",

    # Gaming & Metaverse
    "AXSUSDT", "SANDUSDT", "MANAUSDT", "GALAUSDT", "ILVUSDT",
]

# ─── Analysis Settings ────────────────────────────────────
CLAUDE_MODEL                = "claude-sonnet-4-5"
SIGNAL_CONFIDENCE_THRESHOLD = 0.60
MAX_POSITION_SIZE_PCT       = 0.10   # 10% لكل صفقة
STOP_LOSS_PCT               = 0.02   # وقف خسارة 2%
TAKE_PROFIT_PCT             = 0.08   # هدف ربح 8%

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
