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
    "BTCUSDT", "SOLUSDT",
    "BNBUSDT", "XRPUSDT",
    # DOGE and SHIB removed: 90-day backtest showed combined $-661 loss
    # from 50 trades. Their 0.6% round-trip friction makes scalp RR negative
    # even on winners. Skipping them in scalper mode entirely.
    # ETH removed: persistent underperformer across v1/v2/v3 backtests
    # (6.7% / 21.4% / 0% / 11.1% win rates over 90 days). Likely the
    # heuristic doesn't fit ETH's regime during the test window.
    "PEPEUSDT", "WIFUSDT", "BONKUSDT", "FLOKIUSDT"
]

# Meme coins are treated as one bucket for concurrent-position caps —
# they're correlated and should not consume more than one risk slot.
MEME_SYMBOLS = {
    "PEPEUSDT", "WIFUSDT", "BONKUSDT", "FLOKIUSDT",
}

CLAUDE_MODEL                = "claude-sonnet-4-6"
SIGNAL_CONFIDENCE_THRESHOLD = 0.65
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
MEMORY_DB   = BASE_DIR / "memory" / "xyztradingae.db"
LOGS_DIR    = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports" / "output"

# Rebrand migration: rename the legacy mardood.db -> xyztradingae.db once.
# Runs at the first config import in any process. Safe and idempotent.
_legacy_db = BASE_DIR / "memory" / "mardood.db"
if _legacy_db.exists() and not MEMORY_DB.exists():
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    _legacy_db.rename(MEMORY_DB)
    print(f"[config] DB migrated: {_legacy_db.name} -> {MEMORY_DB.name}", flush=True)
