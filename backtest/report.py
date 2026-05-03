"""
Render a single self-contained HTML report from the metrics + equity curve.
No Python plotting dependencies — Chart.js is loaded from a CDN.
"""
from __future__ import annotations

import html
import json
import pathlib
from datetime import datetime
from typing import Iterable


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>XYZTradingAE Backtest — {date}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0a0e1a;color:#e2e8f0;padding:24px}}
h1{{color:#1D9E75;font-size:22px;letter-spacing:2px;margin-bottom:6px}}
h2{{color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin:24px 0 10px}}
.config{{color:#64748b;font-size:13px;margin-bottom:24px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:24px}}
.metric{{background:#0d1117;border:1px solid #1e2836;border-radius:10px;padding:14px}}
.mlabel{{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}}
.mvalue{{font-size:22px;font-weight:700}}
.green{{color:#1D9E75}}.red{{color:#e24b4a}}.blue{{color:#378ADD}}.amber{{color:#EF9F27}}
.card{{background:#0d1117;border:1px solid #1e2836;border-radius:10px;padding:16px;margin-bottom:16px}}
.chart-wrap{{position:relative;height:340px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{text-align:left;color:#64748b;font-size:10px;font-weight:500;padding:0 8px 8px 0;border-bottom:1px solid #1e2836;text-transform:uppercase;letter-spacing:.5px}}
td{{padding:6px 8px 6px 0;border-bottom:1px solid #111827}}
tr:hover td{{background:#111827}}
small{{color:#64748b}}
.muted{{color:#64748b}}
</style>
</head>
<body>
<h1>XYZTradingAE — Backtest Report</h1>
<div class="config">
  Generated {date} · {symbols_str} · {days}d · mode={mode} · sample every {sample_every} candles
</div>

<h2>Headline metrics</h2>
<div class="metrics">{metric_cards}</div>

<h2>Equity curve</h2>
<div class="card"><div class="chart-wrap"><canvas id="equityChart"></canvas></div></div>

<h2>Drawdown</h2>
<div class="card"><div class="chart-wrap"><canvas id="ddChart"></canvas></div></div>

<h2>Per-symbol breakdown</h2>
<div class="card"><table>
  <tr><th>Symbol</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win rate</th><th>Total P&amp;L</th><th>Avg P&amp;L</th><th>Fees</th></tr>
  {per_symbol_rows}
</table></div>

<h2>Exit reasons</h2>
<div class="card"><table>
  <tr><th>Reason</th><th>Count</th><th>Wins</th><th>Win rate</th><th>Total P&amp;L</th></tr>
  {exit_reason_rows}
</table></div>

<h2>Pre-flight rejections</h2>
<div class="card"><table>
  <tr><th>Reason</th><th>Count</th></tr>
  {skip_rows}
</table></div>

<h2>Recent trades (last 50)</h2>
<div class="card"><table>
  <tr><th>Entry time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>%</th><th>Fees</th><th>Reason</th></tr>
  {trade_rows}
</table></div>

<script>
const equity = {equity_json};
const ddData = (() => {{
  let peak = -Infinity;
  return equity.map(p => {{
    peak = Math.max(peak, p.v);
    return {{ t: p.t, v: peak > 0 ? (p.v - peak) / peak * 100 : 0 }};
  }});
}})();

const baseChartCfg = {{
  type: 'line',
  options: {{
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ type: 'time', time: {{ unit: 'day' }}, ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e2836' }} }},
      y: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e2836' }} }},
    }},
    elements: {{ point: {{ radius: 0 }} }},
  }}
}};

new Chart(document.getElementById('equityChart').getContext('2d'), {{
  ...baseChartCfg,
  data: {{
    datasets: [{{
      label: 'Equity ($)',
      data: equity.map(p => ({{ x: p.t, y: p.v }})),
      borderColor: '#1D9E75', borderWidth: 1.5, fill: true,
      backgroundColor: 'rgba(29,158,117,0.10)',
    }}]
  }}
}});

new Chart(document.getElementById('ddChart').getContext('2d'), {{
  ...baseChartCfg,
  data: {{
    datasets: [{{
      label: 'Drawdown (%)',
      data: ddData.map(p => ({{ x: p.t, y: p.v }})),
      borderColor: '#e24b4a', borderWidth: 1.5, fill: true,
      backgroundColor: 'rgba(226,75,74,0.10)',
    }}]
  }}
}});
</script>
</body>
</html>
"""


def _metric_card(label: str, value: str, color: str = "") -> str:
    color_cls = f" {color}" if color else ""
    return (
        f'<div class="metric"><div class="mlabel">{html.escape(label)}</div>'
        f'<div class="mvalue{color_cls}">{html.escape(value)}</div></div>'
    )


def _fmt_pct(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"


def _fmt_money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _classify(value: float) -> str:
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return ""


def render_report(
    metrics: dict,
    equity: list[dict],
    trades: list[dict],
    config: dict,
    output_path: pathlib.Path,
) -> pathlib.Path:
    # ── Headline cards ────────────────────────────────────────────────
    cards = [
        _metric_card("Final equity", _fmt_money(metrics["final_equity"]),
                    _classify(metrics["final_equity"] - metrics["starting_cash"])),
        _metric_card("Total return", _fmt_pct(metrics["total_return_pct"]),
                    _classify(metrics["total_return_pct"])),
        _metric_card("Sharpe (ann.)", f"{metrics['sharpe']:.2f}",
                    "green" if metrics["sharpe"] > 1 else "red" if metrics["sharpe"] < 0 else "amber"),
        _metric_card("Max drawdown", _fmt_pct(metrics["max_drawdown_pct"]),
                    "red" if metrics["max_drawdown_pct"] < -5 else "amber"),
        _metric_card("Trades", str(metrics["total_trades"])),
        _metric_card("Win rate", f"{metrics['win_rate']:.1f}%",
                    "green" if metrics["win_rate"] >= 55 else "red" if metrics["win_rate"] < 45 else "amber"),
        _metric_card("Profit factor",
                    f"{metrics['profit_factor']:.2f}" if metrics["profit_factor"] is not None else "∞"),
        _metric_card("Avg win",  _fmt_money(metrics["avg_win"]),  "green"),
        _metric_card("Avg loss", _fmt_money(metrics["avg_loss"]), "red"),
        _metric_card("Total fees", _fmt_money(metrics["total_fees"]), "amber"),
        _metric_card("Fee drag", f"{metrics['fee_drag_pct']:.1f}% of gross",
                    "red" if metrics["fee_drag_pct"] > 30 else "amber"),
        _metric_card("Avg hold", f"{metrics['avg_hold_minutes']:.0f} min"),
    ]

    # ── Per-symbol rows ───────────────────────────────────────────────
    sym_rows = []
    for sym, s in metrics["per_symbol"].items():
        cls = _classify(s["pnl"])
        sym_rows.append(
            f'<tr><td><strong>{html.escape(sym)}</strong></td>'
            f'<td>{s["trades"]}</td><td class="green">{s["wins"]}</td>'
            f'<td class="red">{s["losses"]}</td>'
            f'<td>{s["win_rate"]:.1f}%</td>'
            f'<td class="{cls}">{_fmt_money(s["pnl"])}</td>'
            f'<td class="{cls}">{_fmt_money(s["avg_pnl"])}</td>'
            f'<td class="muted">{_fmt_money(s["fees"])}</td></tr>'
        )
    if not sym_rows:
        sym_rows = ['<tr><td colspan="8" class="muted">No closed trades yet.</td></tr>']

    # ── Exit reasons ──────────────────────────────────────────────────
    er_rows = []
    for reason, s in metrics["exit_reasons"].items():
        cls = _classify(s["pnl"])
        er_rows.append(
            f'<tr><td>{html.escape(reason)}</td>'
            f'<td>{s["count"]}</td><td>{s["wins"]}</td>'
            f'<td>{s["win_rate"]:.1f}%</td>'
            f'<td class="{cls}">{_fmt_money(s["pnl"])}</td></tr>'
        )
    if not er_rows:
        er_rows = ['<tr><td colspan="5" class="muted">—</td></tr>']

    # ── Skip counts ───────────────────────────────────────────────────
    skip_rows = [
        f'<tr><td>{html.escape(reason.replace("_", " "))}</td><td>{count}</td></tr>'
        for reason, count in metrics["skip_counts"].items() if count > 0
    ]
    if not skip_rows:
        skip_rows = ['<tr><td colspan="2" class="muted">No rejections.</td></tr>']

    # ── Recent trades ─────────────────────────────────────────────────
    recent = list(reversed(trades[-50:]))
    trade_rows = []
    for t in recent:
        pnl_cls = _classify(t["pnl"])
        trade_rows.append(
            f'<tr><td class="muted">{html.escape(t["entry_time"][:16])}</td>'
            f'<td><strong>{html.escape(t["symbol"])}</strong></td>'
            f'<td class="muted">${t["entry_price"]:,.6f}</td>'
            f'<td>${t["exit_price"]:,.6f}</td>'
            f'<td class="{pnl_cls}"><strong>{_fmt_money(t["pnl"])}</strong></td>'
            f'<td class="{pnl_cls}">{_fmt_pct(t["pnl_pct"])}</td>'
            f'<td class="muted">{_fmt_money(t["fees"])}</td>'
            f'<td class="muted">{html.escape(t["reason"])}</td></tr>'
        )
    if not trade_rows:
        trade_rows = ['<tr><td colspan="8" class="muted">No closed trades.</td></tr>']

    # ── Render ────────────────────────────────────────────────────────
    rendered = HTML_TEMPLATE.format(
        date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        symbols_str=html.escape(", ".join(config["symbols"])),
        days=config["days"],
        mode=config["mode"],
        sample_every=config["sample_every"],
        metric_cards="".join(cards),
        per_symbol_rows="".join(sym_rows),
        exit_reason_rows="".join(er_rows),
        skip_rows="".join(skip_rows),
        trade_rows="".join(trade_rows),
        equity_json=json.dumps(equity),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path
