"""
XYZTradingAE — Live Dashboard (SSE-powered, no page refresh)
"""
import os
import json
import time
from flask import Flask, jsonify, render_template_string, Response
import sqlite3
import threading
import requests
from config import MEMORY_DB, CRYPTO_WATCHLIST
from data.crypto.fetcher import (
    get_simple_prices,
    get_coinbase_prices,
    COINBASE_SYMBOLS,
)

app = Flask(__name__)
price_cache = {}
cache_lock = threading.Lock()

PRICE_REFRESH_SECONDS = 10
STREAM_PUSH_SECONDS = 2
STREAM_KEEPALIVE_SECONDS = 15  # send a comment ping if no data has flowed

# CoinGecko meme/BNB prices change slowly enough that a 5-min TTL is fine,
# and it drops the dashboard's CoinGecko load from ~6/min to ~0.2/min.
MEME_PRICE_TTL_SECONDS = 5 * 60
_meme_cache = {"ts": 0.0, "prices": {}}
_meme_cache_lock = threading.Lock()

DEFAULT_PORTFOLIO = {"cash": 10000, "total_trades": 0, "wins": 0, "losses": 0, "positions": []}
DEFAULT_PAYLOAD = {
    "portfolio": DEFAULT_PORTFOLIO,
    "signals": [],
    "trades": [],
    "total_pnl": 0,
    "open_pnl": 0,
    "closed_pnl": 0,
    "win_rate": 0,
    "portfolio_value": 10000,
    "prices": {},
    "error": None,
}


def _fetch_meme_prices_cached(symbols: list[str]) -> dict:
    """5-min TTL cache around CoinGecko's batched /simple/price. Serves stale on error."""
    if not symbols:
        return {}
    now = time.time()
    with _meme_cache_lock:
        if _meme_cache["prices"] and now - _meme_cache["ts"] < MEME_PRICE_TTL_SECONDS:
            return dict(_meme_cache["prices"])
    try:
        fresh = get_simple_prices(symbols)
    except Exception as e:
        print(f"[dashboard] CoinGecko meme price fetch failed: {e}; serving stale cache", flush=True)
        with _meme_cache_lock:
            return dict(_meme_cache["prices"])
    with _meme_cache_lock:
        _meme_cache["ts"] = now
        _meme_cache["prices"] = fresh
    return fresh


def fetch_live_prices():
    """
    Hybrid price refresh:
      - Coinbase /products/{X-USD}/stats for the 6 majors (always fresh, parallel)
      - CoinGecko /simple/price for the remaining symbols (5-min TTL cache)
    """
    coinbase_syms  = [s for s in CRYPTO_WATCHLIST if s in COINBASE_SYMBOLS]
    coingecko_syms = [s for s in CRYPTO_WATCHLIST if s not in COINBASE_SYMBOLS]

    prices: dict = {}
    if coinbase_syms:
        try:
            prices.update(get_coinbase_prices(coinbase_syms))
        except Exception as e:
            print(f"[dashboard] Coinbase price fetch failed: {e}", flush=True)

    if coingecko_syms:
        prices.update(_fetch_meme_prices_cached(coingecko_syms))

    if prices:
        with cache_lock:
            price_cache.update(prices)


def price_loop():
    while True:
        try:
            fetch_live_prices()
        except Exception:
            pass
        time.sleep(PRICE_REFRESH_SECONDS)


def get_db_data():
    """Always returns a fully-shaped payload — even on error — so the client can render."""
    try:
        with sqlite3.connect(MEMORY_DB) as conn:
            row = conn.execute(
                "SELECT cash, total_trades, wins, losses FROM portfolio WHERE id=1"
            ).fetchone()
            portfolio = (
                {"cash": row[0], "total_trades": row[1], "wins": row[2], "losses": row[3]}
                if row
                else dict(DEFAULT_PORTFOLIO)
            )

            positions = conn.execute(
                "SELECT symbol, asset_type, quantity, entry_price, stop_loss, take_profit, entry_time "
                "FROM positions WHERE status='OPEN'"
            ).fetchall()
            pos_list = []
            for p in positions:
                with cache_lock:
                    live = price_cache.get(p[0], {})
                cur = live.get("price", p[3]) if p[3] is not None else 0
                entry = p[3] if p[3] is not None else 0
                qty = p[2] if p[2] is not None else 0
                pnl = round((cur - entry) * qty, 4)
                pnl_pct = round((cur - entry) / entry * 100, 2) if entry > 0 else 0
                pos_list.append({
                    "symbol": p[0] or "",
                    "asset_type": p[1] or "",
                    "quantity": qty,
                    "entry_price": entry,
                    "stop_loss": p[4] if p[4] is not None else 0,
                    "take_profit": p[5] if p[5] is not None else 0,
                    "entry_time": p[6] or "",
                    "current_price": cur,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                })
            portfolio["positions"] = pos_list

            signals = conn.execute(
                "SELECT timestamp, symbol, signal, confidence, risk_level, reasoning "
                "FROM signals ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()
            signal_list = [{
                "timestamp": (s[0] or "")[:16],
                "symbol": s[1] or "",
                "signal": s[2] or "HOLD",
                "confidence": float(s[3]) if s[3] is not None else 0.0,
                "risk_level": s[4] or "LOW",
                "reasoning": s[5] or "",
            } for s in signals]

            trades = conn.execute(
                "SELECT symbol, entry_price, exit_price, pnl, pnl_pct, exit_time, exit_reason "
                "FROM trade_history ORDER BY exit_time DESC LIMIT 15"
            ).fetchall()
            trade_list = [{
                "symbol": t[0] or "",
                "entry_price": float(t[1]) if t[1] is not None else 0.0,
                "exit_price": float(t[2]) if t[2] is not None else 0.0,
                "pnl": float(t[3]) if t[3] is not None else 0.0,
                "pnl_pct": float(t[4]) if t[4] is not None else 0.0,
                "exit_time": (t[5] or "")[:16],
                "exit_reason": t[6] or "",
            } for t in trades]

            open_pnl = sum(p["pnl"] for p in pos_list)
            closed_pnl = sum(t["pnl"] for t in trade_list) if trade_list else 0
            total_pnl = round(open_pnl + closed_pnl, 2)
            win_rate = (
                round(portfolio["wins"] / portfolio["total_trades"] * 100, 1)
                if portfolio["total_trades"] > 0 else 0
            )

            with cache_lock:
                prices = dict(price_cache)

            return {
                "portfolio": portfolio,
                "signals": signal_list,
                "trades": trade_list,
                "total_pnl": total_pnl,
                "open_pnl": round(open_pnl, 2),
                "closed_pnl": round(closed_pnl, 2),
                "win_rate": win_rate,
                "portfolio_value": round(portfolio["cash"] + open_pnl, 2),
                "prices": prices,
                "error": None,
            }
    except Exception as e:
        with cache_lock:
            prices = dict(price_cache)
        payload = dict(DEFAULT_PAYLOAD)
        payload["prices"] = prices
        payload["error"] = str(e)
        return payload


HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>XYZTradingAE Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0a0e1a;color:#e2e8f0}
.header{background:#0d1117;border-bottom:1px solid #1e2836;padding:14px 24px;display:flex;align-items:center;justify-content:space-between}
.logo{font-size:18px;font-weight:700;letter-spacing:2px;color:#1D9E75}
.live{display:flex;align-items:center;gap:6px;font-size:12px;color:#64748b}
.dot{width:7px;height:7px;border-radius:50%;background:#1D9E75;animation:pulse 2s infinite}
.dot.stale{background:#e24b4a}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.badge{background:#0f2d1f;border:1px solid #1D9E75;color:#1D9E75;font-size:11px;padding:2px 10px;border-radius:20px}
.main{padding:20px 24px;display:grid;gap:16px;max-width:1600px;margin:0 auto}
.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.metric{background:#0d1117;border:1px solid #1e2836;border-radius:10px;padding:14px}
.mlabel{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.mvalue{font-size:22px;font-weight:700}
.msub{font-size:11px;color:#64748b;margin-top:3px}
.green{color:#1D9E75}.red{color:#e24b4a}.blue{color:#378ADD}.amber{color:#EF9F27}
.card{background:#0d1117;border:1px solid #1e2836;border-radius:10px;padding:16px}
.ctitle{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px;font-weight:600;display:flex;align-items:center;justify-content:space-between}
.prices-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
.price-card{background:#111827;border:1px solid #1e2836;border-radius:8px;padding:10px;cursor:pointer;transition:border-color .2s,box-shadow .2s}
.price-card:hover{border-color:#378ADD}
.price-card.flash-up{border-color:#1D9E75;box-shadow:0 0 0 2px rgba(29,158,117,.25)}
.price-card.flash-down{border-color:#e24b4a;box-shadow:0 0 0 2px rgba(226,75,74,.25)}
.price-sym{font-size:11px;font-weight:700;color:#e2e8f0;margin-bottom:3px}
.price-val{font-size:14px;font-weight:700;color:#378ADD}
.price-chg{font-size:11px;margin-top:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:#64748b;font-size:10px;font-weight:500;padding:0 0 8px;border-bottom:1px solid #1e2836}
td{padding:8px 0;border-bottom:1px solid #111827;color:#e2e8f0;vertical-align:middle}
tr:last-child td{border-bottom:none}
.pill{font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;display:inline-block}
.buy-pill{background:#0f2d1f;color:#1D9E75;border:1px solid #1D9E75}
.sell-pill{background:#2d0f0f;color:#e24b4a;border:1px solid #e24b4a}
.hold-pill{background:#1e1e0f;color:#EF9F27;border:1px solid #EF9F27}
.low-pill{background:#0f2d1f;color:#1D9E75;padding:2px 6px;border-radius:10px}
.medium-pill{background:#1e1e0f;color:#EF9F27;padding:2px 6px;border-radius:10px}
.high-pill{background:#2d0f0f;color:#e24b4a;padding:2px 6px;border-radius:10px}
.empty{color:#64748b;font-size:12px;padding:16px 0;text-align:center}
.timer{font-size:10px;color:#64748b;text-align:right;padding:4px 0}
.pbar{background:#1e2836;border-radius:3px;height:4px;width:60px;display:inline-block;vertical-align:middle;margin-left:6px}
.pfill{height:4px;border-radius:3px;background:#378ADD}
.profit-summary{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px}
.ps-item{background:#111827;border-radius:8px;padding:10px;text-align:center}
.ps-label{font-size:10px;color:#64748b;margin-bottom:4px}
.ps-value{font-size:16px;font-weight:700}
.error-banner{background:#2d0f0f;border:1px solid #e24b4a;color:#e24b4a;padding:8px 14px;border-radius:8px;font-size:12px;display:none}
.error-banner.show{display:block}
</style>
</head>
<body>
<div class="header">
  <div class="logo">XYZTRADINGAE</div>
  <div style="display:flex;align-items:center;gap:14px">
    <div class="live"><div class="dot" id="liveDot"></div><span id="liveLabel">Connecting...</span></div>
    <div id="timerBadge" style="font-size:11px;color:#64748b">connecting...</div>
    <div class="badge">Phase 2 - Paper Trading</div>
  </div>
</div>

<div class="main">

  <div id="errorBanner" class="error-banner"></div>

  <!-- 6 Metric Cards -->
  <div class="metrics" id="metrics"></div>

  <!-- Live Prices -->
  <div class="card">
    <div class="ctitle">
      <span>Live market prices</span>
      <span style="color:#378ADD;font-size:10px">Streaming - SSE</span>
    </div>
    <div class="prices-grid" id="pricesGrid">
      <div class="empty" style="grid-column:span 5">Loading prices...</div>
    </div>
  </div>

  <div class="grid2">

    <!-- Open Positions -->
    <div class="card">
      <div class="ctitle">
        <span>Open positions - live P&amp;L</span>
        <span class="amber" id="positionsCount">0 active</span>
      </div>
      <div id="positionsBody"><div class="empty">No open positions</div></div>
    </div>

    <!-- Latest Signals -->
    <div class="card">
      <div class="ctitle">
        <span>Latest signals</span>
        <span style="color:#64748b" id="signalsCount">0 total</span>
      </div>
      <div id="signalsBody"><div class="empty">No signals yet - run python main.py</div></div>
    </div>

  </div>

  <!-- Trade History -->
  <div class="card">
    <div class="ctitle">
      <span>Trade history - closed positions</span>
      <span id="closedPnlLabel" class="green">Realized P&amp;L: $0.0000</span>
    </div>
    <div id="tradesBody"><div class="empty">No closed trades yet - waiting for stop loss or take profit</div></div>
  </div>

  <div class="timer" id="timerText">Waiting for live stream...</div>
</div>

<script>
const $ = (id) => document.getElementById(id);

function fmtPrice(p) {
  if (p == null || isNaN(p)) return '-';
  if (p >= 1) return '$' + Number(p).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  if (p >= 0.01) return '$' + Number(p).toFixed(4);
  return '$' + Number(p).toFixed(8);
}
function fmtMoney(p) {
  const n = Number(p);
  if (isNaN(n)) return '$0.00';
  return '$' + n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}
function fmtPnl(p) {
  const n = Number(p) || 0;
  return (n >= 0 ? '+$' : '-$') + Math.abs(n).toFixed(4);
}
function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function stripUSDT(s) { return String(s == null ? '' : s).replace('USDT',''); }

const lastPrices = {};

function renderMetrics(d) {
  const portfolio = d.portfolio || {};
  const pv = Number(d.portfolio_value) || 0;
  const tp = Number(d.total_pnl) || 0;
  const html = `
    <div class="metric">
      <div class="mlabel">Portfolio value</div>
      <div class="mvalue ${pv >= 10000 ? 'green' : 'red'}">${fmtMoney(pv)}</div>
      <div class="msub">Started at $10,000.00</div>
    </div>
    <div class="metric">
      <div class="mlabel">Total P&amp;L</div>
      <div class="mvalue ${tp >= 0 ? 'green' : 'red'}">${tp >= 0 ? '+' : ''}${fmtMoney(tp)}</div>
      <div class="msub">Open: ${fmtMoney(d.open_pnl)} | Closed: ${fmtMoney(d.closed_pnl)}</div>
    </div>
    <div class="metric">
      <div class="mlabel">Win rate</div>
      <div class="mvalue blue">${Number(d.win_rate) || 0}%</div>
      <div class="msub">${Number(portfolio.wins) || 0} wins / ${Number(portfolio.losses) || 0} losses</div>
    </div>
    <div class="metric">
      <div class="mlabel">Total trades</div>
      <div class="mvalue">${Number(portfolio.total_trades) || 0}</div>
      <div class="msub">Since start</div>
    </div>
    <div class="metric">
      <div class="mlabel">Open positions</div>
      <div class="mvalue amber">${(portfolio.positions || []).length}</div>
      <div class="msub">Active now</div>
    </div>
    <div class="metric">
      <div class="mlabel">Cash available</div>
      <div class="mvalue">${fmtMoney(portfolio.cash)}</div>
      <div class="msub">Free to deploy</div>
    </div>`;
  $('metrics').innerHTML = html;
}

function renderPrices(prices) {
  const entries = Object.entries(prices || {});
  if (!entries.length) {
    $('pricesGrid').innerHTML = '<div class="empty" style="grid-column:span 5">Loading prices...</div>';
    return;
  }
  const html = entries.map(([sym, p]) => {
    const price = Number(p && p.price);
    const chg = Number(p && p.change_pct) || 0;
    if (isNaN(price)) return '';
    const prev = lastPrices[sym];
    let flash = '';
    if (prev != null && price !== prev) flash = price > prev ? 'flash-up' : 'flash-down';
    lastPrices[sym] = price;
    return `<div class="price-card ${flash}" data-sym="${escapeHtml(sym)}">
      <div class="price-sym">${escapeHtml(stripUSDT(sym))}</div>
      <div class="price-val">${fmtPrice(price)}</div>
      <div class="price-chg ${chg >= 0 ? 'green' : 'red'}">
        ${chg >= 0 ? '+' : ''}${chg.toFixed(2)}% (24h)
      </div>
    </div>`;
  }).join('');
  $('pricesGrid').innerHTML = html || '<div class="empty" style="grid-column:span 5">Loading prices...</div>';
  setTimeout(() => {
    document.querySelectorAll('.price-card.flash-up,.price-card.flash-down').forEach(el => {
      el.classList.remove('flash-up', 'flash-down');
    });
  }, 800);
}

function renderPositions(positions) {
  positions = Array.isArray(positions) ? positions : [];
  $('positionsCount').textContent = positions.length + ' active';
  if (!positions.length) {
    $('positionsBody').innerHTML = '<div class="empty">No open positions</div>';
    return;
  }
  const rows = positions.map(p => {
    const pnl = Number(p.pnl) || 0;
    const pnlPct = Number(p.pnl_pct) || 0;
    return `
    <tr>
      <td><strong>${escapeHtml(stripUSDT(p.symbol))}</strong></td>
      <td class="blue">${fmtPrice(p.current_price)}</td>
      <td style="color:#64748b">${fmtPrice(p.entry_price)}</td>
      <td class="${pnl >= 0 ? 'green' : 'red'}">
        <strong>${fmtPnl(pnl)}</strong><br>
        <small>${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</small>
      </td>
      <td class="red" style="font-size:11px">${fmtPrice(p.stop_loss)}</td>
      <td class="green" style="font-size:11px">${fmtPrice(p.take_profit)}</td>
    </tr>`;
  }).join('');
  $('positionsBody').innerHTML = `<table>
    <tr><th>Symbol</th><th>Current</th><th>Entry</th><th>P&amp;L</th><th>Stop</th><th>Target</th></tr>
    ${rows}
  </table>`;
}

function renderSignals(signals) {
  signals = Array.isArray(signals) ? signals : [];
  $('signalsCount').textContent = signals.length + ' total';
  if (!signals.length) {
    $('signalsBody').innerHTML = '<div class="empty">No signals yet - run python main.py</div>';
    return;
  }
  const rows = signals.slice(0, 10).map(s => {
    const ts = String(s.timestamp || '');
    const tShort = ts.length > 10 ? ts.slice(11) : ts;
    const sigVal = String(s.signal || 'HOLD');
    const conf = Number(s.confidence) || 0;
    const risk = String(s.risk_level || 'LOW');
    return `<tr>
      <td style="color:#64748b;font-size:10px">${escapeHtml(tShort)}</td>
      <td><strong>${escapeHtml(stripUSDT(s.symbol))}</strong></td>
      <td><span class="pill ${escapeHtml(sigVal.toLowerCase())}-pill">${escapeHtml(sigVal)}</span></td>
      <td>
        ${Math.round(conf * 100)}%
        <span class="pbar"><span class="pfill" style="width:${Math.round(conf * 100)}%"></span></span>
      </td>
      <td><span class="pill ${escapeHtml(risk.toLowerCase())}-pill">${escapeHtml(risk)}</span></td>
    </tr>`;
  }).join('');
  $('signalsBody').innerHTML = `<table>
    <tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Conf</th><th>Risk</th></tr>
    ${rows}
  </table>`;
}

function renderTrades(trades, closedPnl) {
  trades = Array.isArray(trades) ? trades : [];
  closedPnl = Number(closedPnl) || 0;
  const lbl = $('closedPnlLabel');
  lbl.className = closedPnl >= 0 ? 'green' : 'red';
  lbl.textContent = `Realized P&L: ${closedPnl >= 0 ? '+' : ''}$${closedPnl.toFixed(4)}`;
  if (!trades.length) {
    $('tradesBody').innerHTML = '<div class="empty">No closed trades yet - waiting for stop loss or take profit</div>';
    return;
  }
  const pnls = trades.map(t => Number(t.pnl) || 0);
  const best = Math.max(...pnls);
  const worst = Math.min(...pnls);
  const rows = trades.map(t => {
    const pnl = Number(t.pnl) || 0;
    const pnlPct = Number(t.pnl_pct) || 0;
    return `
    <tr>
      <td style="color:#64748b;font-size:10px">${escapeHtml(t.exit_time)}</td>
      <td><strong>${escapeHtml(stripUSDT(t.symbol))}</strong></td>
      <td style="color:#64748b">${fmtPrice(t.entry_price)}</td>
      <td>${fmtPrice(t.exit_price)}</td>
      <td class="${pnl > 0 ? 'green' : 'red'}"><strong>${fmtPnl(pnl)}</strong></td>
      <td class="${pnlPct > 0 ? 'green' : 'red'}">${pnlPct > 0 ? '+' : ''}${pnlPct.toFixed(2)}%</td>
      <td style="color:#64748b;font-size:11px">${escapeHtml(t.exit_reason)}</td>
    </tr>`;
  }).join('');
  $('tradesBody').innerHTML = `
    <div class="profit-summary">
      <div class="ps-item">
        <div class="ps-label">Total closed trades</div>
        <div class="ps-value">${trades.length}</div>
      </div>
      <div class="ps-item">
        <div class="ps-label">Best trade</div>
        <div class="ps-value green">+$${best.toFixed(4)}</div>
      </div>
      <div class="ps-item">
        <div class="ps-label">Worst trade</div>
        <div class="ps-value red">$${worst.toFixed(4)}</div>
      </div>
    </div>
    <table>
      <tr><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Return</th><th>Reason</th></tr>
      ${rows}
    </table>`;
}

function renderError(msg) {
  const banner = $('errorBanner');
  if (msg) {
    banner.textContent = 'Backend error: ' + msg;
    banner.classList.add('show');
  } else {
    banner.classList.remove('show');
  }
}

function applyUpdate(d) {
  if (!d || typeof d !== 'object') return;
  // Defensive defaults — even with the server contract we hold the shape on the client
  if (!d.portfolio || typeof d.portfolio !== 'object') d.portfolio = {};
  if (!Array.isArray(d.portfolio.positions)) d.portfolio.positions = [];
  if (!Array.isArray(d.signals)) d.signals = [];
  if (!Array.isArray(d.trades)) d.trades = [];
  if (!d.prices || typeof d.prices !== 'object') d.prices = {};

  try { renderMetrics(d); } catch (e) { console.error('renderMetrics:', e); }
  try { renderPrices(d.prices); } catch (e) { console.error('renderPrices:', e); }
  try { renderPositions(d.portfolio.positions); } catch (e) { console.error('renderPositions:', e); }
  try { renderSignals(d.signals); } catch (e) { console.error('renderSignals:', e); }
  try { renderTrades(d.trades, d.closed_pnl); } catch (e) { console.error('renderTrades:', e); }
  renderError(d.error || null);
}

let lastTick = 0;
function setStatus(connected) {
  $('liveDot').classList.toggle('stale', !connected);
  $('liveLabel').textContent = connected ? 'Live' : 'Reconnecting...';
}

function connect() {
  const es = new EventSource('/api/stream');
  es.onopen = () => setStatus(true);
  es.onerror = () => setStatus(false);
  es.onmessage = (e) => {
    if (!e.data) return;
    let data;
    try { data = JSON.parse(e.data); }
    catch (err) { console.error('SSE parse:', err); return; }
    applyUpdate(data);
    lastTick = Date.now();
  };
  return es;
}

connect();

setInterval(() => {
  const ago = Math.max(0, Math.floor((Date.now() - lastTick) / 1000));
  $('timerBadge').textContent = lastTick ? `updated ${ago}s ago` : 'connecting...';
  $('timerText').textContent = lastTick
    ? `Last update: ${ago}s ago - live stream`
    : 'Waiting for live stream...';
}, 1000);
</script>
</body>
</html>'''


@app.route('/')
def dashboard():
    return render_template_string(HTML)


@app.route('/api/data')
def api_data():
    return jsonify(get_db_data())


@app.route('/api/stream')
def stream():
    def event_stream():
        last_send = 0.0
        while True:
            try:
                data = get_db_data()
                yield f"data: {json.dumps(data)}\n\n"
                last_send = time.time()
            except GeneratorExit:
                return
            except Exception as e:
                # Even on serializer error, send a usable shape so the client doesn't go dark
                fallback = dict(DEFAULT_PAYLOAD)
                fallback["error"] = f"stream: {e}"
                try:
                    yield f"data: {json.dumps(fallback)}\n\n"
                    last_send = time.time()
                except GeneratorExit:
                    return
            # Keepalive comment if we somehow went quiet (proxies drop idle SSE)
            if time.time() - last_send > STREAM_KEEPALIVE_SECONDS:
                try:
                    yield ": ping\n\n"
                    last_send = time.time()
                except GeneratorExit:
                    return
            time.sleep(STREAM_PUSH_SECONDS)

    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


# Prime the price cache once at import time so the first SSE push has data,
# then keep refreshing in a background loop.
threading.Thread(target=fetch_live_prices, daemon=True).start()
threading.Thread(target=price_loop, daemon=True).start()


if __name__ == '__main__':
    print("XYZTradingAE Dashboard -> http://localhost:5000")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
