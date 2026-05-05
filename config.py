"""
XYZTRADINGAE - Configuration
"""
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

# API keys actually used by the codebase
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
FINNHUB_API_KEY     = os.getenv("FINNHUB_API_KEY")
# ANTHROPIC_API_KEY is read directly via os.getenv in analysis/brain.py

CRYPTO_WATCHLIST = [
    # All on Coinbase Exchange — real volume, 4h candles via 1h->4h resample.
    # POL = the rebranded MATIC (Coinbase delisted MATIC-USD when Polygon
    # migrated tokens; POL-USD is the live successor).
    "BTCUSDT", "SOLUSDT", "XRPUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "ADAUSDT",
    "ARBUSDT", "OPUSDT", "UNIUSDT", "SUIUSDT", "TONUSDT", "POLUSDT",
    # NOTE: BNB and TRX were dropped — only watchlist symbols still on
    # CoinGecko, whose free tier rate-limited Railway's shared IPs hard
    # enough to make TRX miss scans entirely. Both 80%+ BTC-correlated,
    # so the diversification loss is minimal.
    # Memes (PEPE/WIF/BONK/FLOKI), ETH, DOGE, SHIB also intentionally
    # excluded — see commit history for backtest rationale.
]

CLAUDE_MODEL                = "claude-sonnet-4-6"
# Raised from 0.65 (2026-05) to filter the noise-floor 65-68% cluster
# the brain emits during BTC bull regimes. Real asset-specific setups
# should clear 0.72 comfortably; if scans go days without crossing
# this threshold, the brain may need fundamental rework.
SIGNAL_CONFIDENCE_THRESHOLD = 0.72
MAX_POSITION_SIZE_PCT       = 0.30
SCAN_INTERVAL_MINUTES       = 240   # 4 hours — once per 4h candle close

# Shadow mode: log brain and heuristic decisions to shadow_decisions
# but skip opening new paper-trading positions. Existing positions are
# still managed (SL/TP exits run normally so they can close out).
# Flip to True to observe brain-vs-heuristic divergence on live data
# without compounding live trades.
SHADOW_MODE                 = False
REPORT_TIME                 = "08:00"
TIMEZONE                    = "Asia/Dubai"
XYZTRADINGAE_PHASE          = 2

# --- Swing trading risk profile -----------------------------------------
# Reverted from scalper to short-term swing on 4h candles. Stops are
# fixed at 2% and targets at 8% (4:1 RR) per user spec — ATR-scaling
# disabled by clamping MIN_SL == MAX_SL.
STOP_LOSS_PCT       = 0.02     # 2%  (fallback when atr_pct is missing)
TAKE_PROFIT_PCT     = 0.08     # 8%  (4 * SL — matches RR multiplier below)

# ATR-based stops: with MIN_SL == MAX_SL, the ATR computation always
# clamps to exactly 2%. ATR_SL_MULTIPLIER becomes irrelevant in this
# mode. Widen the bounds later if reverting to ATR-scaling.
ATR_SL_MULTIPLIER   = 1.5
ATR_RR_MULTIPLIER   = 4.0      # 4:1 reward:risk
MIN_SL_PCT          = 0.02     # flat 2% floor
MAX_SL_PCT          = 0.02     # flat 2% ceiling (= MIN, ATR scaling off)

# Volume-spike detection threshold (used by indicators)
VOLUME_SPIKE_RATIO  = 2.0      # current candle volume / 20-candle avg

# Concurrent-position cap
MAX_CONCURRENT_POSITIONS = 5

# Daily drawdown circuit breaker — halt new entries if down this much
# from the day's starting equity (UTC day boundaries).
DAILY_DRAWDOWN_HALT_PCT = 0.05

# Execution friction — applied per side on every paper trade.
# Single tier now that memes are gone; was MAJOR/MEME split.
FEE_PCT_PER_SIDE  = 0.001    # 0.1% (Coinbase taker)
SLIPPAGE_PCT      = 0.0005   # 0.05% per side for liquid majors

BASE_DIR    = pathlib.Path(__file__).parent
# DATA_DIR is the persistent volume mount on Railway (/data via env var).
# Falls back to the in-repo memory/ folder for local dev where the env
# var isn't set. The DB lives inside DATA_DIR so it survives redeploys.
DATA_DIR    = pathlib.Path(os.getenv("DATA_DIR", BASE_DIR / "memory"))
MEMORY_DB   = DATA_DIR / "xyztradingae.db"
LOGS_DIR    = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports" / "output"

# Rebrand migration: rename the legacy mardood.db -> xyztradingae.db once.
# Runs at the first config import in any process. Safe and idempotent.
_legacy_db = DATA_DIR / "mardood.db"
if _legacy_db.exists() and not MEMORY_DB.exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _legacy_db.rename(MEMORY_DB)
    print(f"[config] DB migrated: {_legacy_db.name} -> {MEMORY_DB.name}", flush=True)
