"""
Mardood — Live Dashboard
"""
import os
from flask import Flask, jsonify, render_template_string
import sqlite3
import threading
import requests
import yfinance as yf
from config import MEMORY_DB, STOCKS_WATCHLIST, CRYPTO_WATCHLIST

app = Flask(__name__)
price_cache = {}
cache_lock = threading.Lock()

def fetch_live_prices():
    prices = {}
    for ticker in STOCKS_WATCHLIST:
        try:
            df = yf.Ticker(ticker).history(period="1d", interval="1m")
            if not df.empty:
                price = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[0])
                chg_pct = round((price - prev) / prev * 100, 2)
                prices[ticker] = {"price": price, "change_pct": chg_pct}
        except: pass
    for symbol in CRYPTO_WATCHLIST:
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
            d = r.json()
            prices[symbol] = {"price": float(d["lastPrice"]), "change_pct": round(float(d["priceChangePercent"]), 2)}
        except: pass
    with cache_lock:
        price_cache.update(prices)

def fmt_price(p):
    if p >= 1: return f"${p:,.2f}"
    elif p >= 0.01: return f"${p:.4f}"
    else: return f"${p:.8f}"

def get_db_data():
    try:
        with sqlite3.connect(MEMORY_DB) as conn:
            row = conn.execute("SELECT cash, total_trades, wins, losses FROM portfolio WHERE id=1").fetchone()
            portfolio = {"cash": row[0], "total_trades": row[1], "wins": row[2], "losses": row[3]} if row else {"cash": 10000, "total_trades": 0, "wins": 0, "losses": 0}
            
            positions = conn.execute("SELECT symbol, asset_type, quantity, entry_price, stop_loss, take_profit, entry_time FROM positions WHERE status='OPEN'").fetchall()
            pos_list = []
            for p in positions:
                with cache_lock:
                    live = price_cache.get(p[0], {})
                cur = live.get("price", p[3])
                pnl = round((cur - p[3]) * p[2], 4)
                pnl_pct = round((cur - p[3]) / p[3] * 100, 2) if p[3] > 0 else 0
                pos_list.append({"symbol": p[0], "quantity": p[2], "entry_price": p[3], "stop_loss": p[4], "take_profit": p[5], "entry_time": p[6], "current_price": cur, "pnl": pnl, "pnl_pct": pnl_pct})
            portfolio["positions"] = pos_list

            signals = conn.execute("SELECT timestamp, symbol, signal, confidence, risk_level, reasoning FROM signals ORDER BY timestamp DESC LIMIT 20").fetchall()
            signal_list = [{"timestamp": s[0][:16], "symbol": s[1], "signal": s[2], "confidence": s[3], "risk_level": s[4], "reasoning": s[5]} for s in signals]

            trades = conn.execute("SELECT symbol, entry_price, exit_price, pnl, pnl_pct, exit_time, exit_reason FROM trade_history ORDER BY exit_time DESC LIMIT 15").fetchall()
            trade_list = [{"symbol": t[0], "entry_price": t[1], "exit_price": t[2], "pnl": t[3], "pnl_pct": t[4], "exit_time": t[5][:16] if t[5] else "", "exit_reason": t[6]} for t in trades]

            open_pnl = sum(p["pnl"] for p in pos_list)
            closed_pnl = sum(t[3] for t in trades) if trades else 0
            total_pnl = round(open_pnl + closed_pnl, 2)
            win_rate = round(portfolio["wins"] / portfolio["total_trades"] * 100, 1) if portfolio["total_trades"] > 0 else 0

            return {"portfolio": portfolio, "signals": signal_list, "trades": trade_list, "total_pnl": total_pnl, "open_pnl": round(open_pnl, 2), "closed_pnl": round(closed_pnl, 2), "win_rate": win_rate, "portfolio_value": round(portfolio["cash"] + open_pnl, 2), "prices": dict(price_cache)}
    except Exception as e:
        return {"error": str(e), "portfolio": {"cash": 10000, "total_trades": 0, "wins": 0, "losses": 0, "positions": []}, "signals": [], "trades": [], "total_pnl": 0, "open_pnl": 0, "closed_pnl": 0, "win_rate": 0, "portfolio_value": 10000, "prices": {}}

HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Mardood Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0a0e1a;color:#e2e8f0}
.header{background:#0d1117;border-bottom:1px solid #1e2836;padding:14px 24px;display:flex;align-items:center;justify-content:space-between}
.logo{font-size:18px;font-weight:700;letter-spacing:2px;color:#1D9E75}
.live{display:flex;align-items:center;gap:6px;font-size:12px;color:#64748b}
.dot{width:7px;height:7px;border-radius:50%;background:#1D9E75;animation:pulse 2s infinite}
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
.price-card{background:#111827;border:1px solid #1e2836;border-radius:8px;padding:10px;cursor:pointer;transition:border-color .2s}
.price-card:hover{border-color:#378ADD}
.price-sym{font-size:11px;font-weight:700;color:#e2e8f0;margin-bottom:3px}
.price-val{font-size:14px;font-weight:700;color:#378ADD}
.price-chg{font-size:11px;margin-top:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
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
.reasoning{font-size:11px;color:#64748b;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pbar{background:#1e2836;border-radius:3px;height:4px;width:60px;display:inline-block;vertical-align:middle;margin-left:6px}
.pfill{height:4px;border-radius:3px;background:#378ADD}
.profit-summary{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px}
.ps-item{background:#111827;border-radius:8px;padding:10px;text-align:center}
.ps-label{font-size:10px;color:#64748b;margin-bottom:4px}
.ps-value{font-size:16px;font-weight:700}
</style>
</head>
<body>
<div class="header">
  <div class="logo">🤖 MARDOOD</div>
  <div style="display:flex;align-items:center;gap:14px">
    <div class="live"><div class="dot"></div>Live · Asia/Dubai</div>
    <div id="timerBadge" style="font-size:11px;color:#64748b"></div>
    <div class="badge">Phase 2 — Paper Trading</div>
  </div>
</div>

<div class="main">

  <!-- 6 Metric Cards -->
  <div class="metrics">
    <div class="metric">
      <div class="mlabel">Portfolio value</div>
      <div class="mvalue {{ 'green' if data.portfolio_value >= 10000 else 'red' }}">${{ "{:,.2f}".format(data.portfolio_value) }}</div>
      <div class="msub">Started at $10,000.00</div>
    </div>
    <div class="metric">
      <div class="mlabel">Total P&L</div>
      <div class="mvalue {{ 'green' if data.total_pnl >= 0 else 'red' }}">{{ '+' if data.total_pnl >= 0 else '' }}${{ "{:,.2f}".format(data.total_pnl) }}</div>
      <div class="msub">Open: ${{ "{:,.2f}".format(data.open_pnl) }} | Closed: ${{ "{:,.2f}".format(data.closed_pnl) }}</div>
    </div>
    <div class="metric">
      <div class="mlabel">Win rate</div>
      <div class="mvalue blue">{{ data.win_rate }}%</div>
      <div class="msub">✅ {{ data.portfolio.wins }} wins / ❌ {{ data.portfolio.losses }} losses</div>
    </div>
    <div class="metric">
      <div class="mlabel">Total trades</div>
      <div class="mvalue">{{ data.portfolio.total_trades }}</div>
      <div class="msub">Since start</div>
    </div>
    <div class="metric">
      <div class="mlabel">Open positions</div>
      <div class="mvalue amber">{{ data.portfolio.positions|length }}</div>
      <div class="msub">Active now</div>
    </div>
    <div class="metric">
      <div class="mlabel">Cash available</div>
      <div class="mvalue">${{ "{:,.2f}".format(data.portfolio.cash) }}</div>
      <div class="msub">Free to deploy</div>
    </div>
  </div>

  <!-- Live Prices -->
  <div class="card">
    <div class="ctitle">
      <span>Live market prices</span>
      <span style="color:#378ADD;font-size:10px">Updates every 30s</span>
    </div>
    <div class="prices-grid">
      {% for sym, p in data.prices.items() %}
      <div class="price-card">
        <div class="price-sym">{{ sym.replace('USDT','') }}</div>
        <div class="price-val">
          {% if p.price >= 1 %}${{ "{:,.2f}".format(p.price) }}
          {% elif p.price >= 0.01 %}${{ "{:.4f}".format(p.price) }}
          {% else %}${{ "{:.8f}".format(p.price) }}{% endif %}
        </div>
        <div class="price-chg {{ 'green' if p.change_pct >= 0 else 'red' }}">
          {{ '+' if p.change_pct >= 0 else '' }}{{ p.change_pct }}% (24h)
        </div>
      </div>
      {% endfor %}
      {% if not data.prices %}<div class="empty" style="grid-column:span 5">جاري تحميل الأسعار...</div>{% endif %}
    </div>
  </div>

  <div class="grid2">

    <!-- Open Positions -->
    <div class="card">
      <div class="ctitle">
        <span>Open positions — live P&L</span>
        <span class="amber">{{ data.portfolio.positions|length }} active</span>
      </div>
      {% if data.portfolio.positions %}
      <table>
        <tr><th>Symbol</th><th>Current</th><th>Entry</th><th>P&L</th><th>Stop</th><th>Target</th></tr>
        {% for p in data.portfolio.positions %}
        <tr>
          <td><strong>{{ p.symbol.replace('USDT','') }}</strong></td>
          <td class="blue">
            {% if p.current_price >= 1 %}${{ "{:,.2f}".format(p.current_price) }}
            {% elif p.current_price >= 0.01 %}${{ "{:.4f}".format(p.current_price) }}
            {% else %}${{ "{:.8f}".format(p.current_price) }}{% endif %}
          </td>
          <td style="color:#64748b">
            {% if p.entry_price >= 1 %}${{ "{:,.2f}".format(p.entry_price) }}
            {% elif p.entry_price >= 0.01 %}${{ "{:.4f}".format(p.entry_price) }}
            {% else %}${{ "{:.8f}".format(p.entry_price) }}{% endif %}
          </td>
          <td class="{{ 'green' if p.pnl >= 0 else 'red' }}">
            <strong>{{ '+' if p.pnl >= 0 else '' }}${{ "{:.4f}".format(p.pnl) }}</strong><br>
            <small>{{ '+' if p.pnl_pct >= 0 else '' }}{{ "{:.2f}".format(p.pnl_pct) }}%</small>
          </td>
          <td class="red" style="font-size:11px">
            {% if p.stop_loss >= 1 %}${{ "{:,.2f}".format(p.stop_loss) }}
            {% else %}${{ "{:.4f}".format(p.stop_loss) }}{% endif %}
          </td>
          <td class="green" style="font-size:11px">
            {% if p.take_profit >= 1 %}${{ "{:,.2f}".format(p.take_profit) }}
            {% else %}${{ "{:.4f}".format(p.take_profit) }}{% endif %}
          </td>
        </tr>
        {% endfor %}
      </table>
      {% else %}<div class="empty">لا توجد صفقات مفتوحة</div>{% endif %}
    </div>

    <!-- Latest Signals -->
    <div class="card">
      <div class="ctitle">
        <span>Latest signals</span>
        <span style="color:#64748b">{{ data.signals|length }} total</span>
      </div>
      {% if data.signals %}
      <table>
        <tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Conf</th><th>Risk</th></tr>
        {% for s in data.signals[:10] %}
        <tr>
          <td style="color:#64748b;font-size:10px">{{ s.timestamp[11:] if s.timestamp|length > 10 else s.timestamp }}</td>
          <td><strong>{{ s.symbol.replace('USDT','') }}</strong></td>
          <td><span class="pill {{ s.signal.lower() }}-pill">{{ s.signal }}</span></td>
          <td>
            {{ "%.0f"|format(s.confidence * 100) }}%
            <span class="pbar"><span class="pfill" style="width:{{ (s.confidence * 100)|int }}%"></span></span>
          </td>
          <td><span class="pill {{ (s.risk_level or 'low').lower() }}-pill">{{ s.risk_level or '—' }}</span></td>
        </tr>
        {% endfor %}
      </table>
      {% else %}<div class="empty">لا توجد إشارات — شغّل python main.py</div>{% endif %}
    </div>

  </div>

  <!-- Trade History -->
  <div class="card">
    <div class="ctitle">
      <span>Trade history — closed positions</span>
      <span class="{{ 'green' if data.closed_pnl >= 0 else 'red' }}">Realized P&L: {{ '+' if data.closed_pnl >= 0 else '' }}${{ "{:,.4f}".format(data.closed_pnl) }}</span>
    </div>
    {% if data.trades %}
    <div class="profit-summary">
      <div class="ps-item">
        <div class="ps-label">Total closed trades</div>
        <div class="ps-value">{{ data.trades|length }}</div>
      </div>
      <div class="ps-item">
        <div class="ps-label">Best trade</div>
        <div class="ps-value green">+${{ "{:.4f}".format(data.trades|map(attribute='pnl')|max) }}</div>
      </div>
      <div class="ps-item">
        <div class="ps-label">Worst trade</div>
        <div class="ps-value red">${{ "{:.4f}".format(data.trades|map(attribute='pnl')|min) }}</div>
      </div>
    </div>
    <table>
      <tr><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Return</th><th>Reason</th></tr>
      {% for t in data.trades %}
      <tr>
        <td style="color:#64748b;font-size:10px">{{ t.exit_time }}</td>
        <td><strong>{{ t.symbol.replace('USDT','') }}</strong></td>
        <td style="color:#64748b">
          {% if t.entry_price >= 1 %}${{ "{:,.2f}".format(t.entry_price) }}
          {% else %}${{ "{:.6f}".format(t.entry_price) }}{% endif %}
        </td>
        <td>
          {% if t.exit_price >= 1 %}${{ "{:,.2f}".format(t.exit_price) }}
          {% else %}${{ "{:.6f}".format(t.exit_price) }}{% endif %}
        </td>
        <td class="{{ 'green' if t.pnl > 0 else 'red' }}"><strong>{{ '+' if t.pnl > 0 else '' }}${{ "{:.4f}".format(t.pnl) }}</strong></td>
        <td class="{{ 'green' if t.pnl_pct > 0 else 'red' }}">{{ '+' if t.pnl_pct > 0 else '' }}{{ "{:.2f}".format(t.pnl_pct) }}%</td>
        <td style="color:#64748b;font-size:11px">{{ t.exit_reason }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}<div class="empty">لا توجد صفقات مغلقة بعد — مردود ينتظر Stop Loss أو Take Profit</div>{% endif %}
  </div>

  <div class="timer" id="timerText">تحديث تلقائي كل 15 ثانية</div>
</div>

<script>
let c = 15;
const t = document.getElementById('timerText');
const b = document.getElementById('timerBadge');
setInterval(() => {
  c--;
  if(c <= 0){ location.reload(); c = 15; }
  t.textContent = 'تحديث خلال ' + c + ' ثانية';
  b.textContent = '🔄 ' + c + 's';
}, 1000);
</script>
</body>
</html>'''

@app.route('/')
def dashboard():
    threading.Thread(target=fetch_live_prices, daemon=True).start()
    data = get_db_data()
    class Obj:
        def __init__(self, d):
            self.__dict__.update(d)
            if 'positions' in d:
                self.positions = [Obj(p) for p in d['positions']]
    data['portfolio'] = Obj(data['portfolio'])
    return render_template_string(HTML, data=type('D', (), data)())

@app.route('/api/data')
def api_data():
    return jsonify(get_db_data())

if __name__ == '__main__':
    print("Mardood Dashboard → http://localhost:5000")
    fetch_live_prices()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)