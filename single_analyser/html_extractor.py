"""
NEPSE Single-Stock Deep Analysis — HTML Report Generator (v1.0)

Generates a detailed single-stock analysis report inspired by the reference
all_stocks_analysis HTML. Light theme with blue accent, Chart.js charts,
comprehensive technical/fundamental/volume breakdown, strengths/weaknesses,
broker activity, and price levels.
"""

import os, json
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════
#  FORMATTING HELPERS
# ═══════════════════════════════════════════════════════════════════════

def fmt(v, decimals=2):
    if v is None: return "—"
    try:
        v = float(v)
        if abs(v) >= 1e9: return f"{v/1e9:.{decimals}f}B"
        if abs(v) >= 1e6: return f"{v/1e6:.{decimals}f}M"
        if abs(v) >= 1e3: return f"{v/1e3:.{decimals}f}K"
        return f"{v:,.{decimals}f}"
    except:
        return str(v)

def fmt_price(v):
    if v is None: return "—"
    try: return f"Rs. {float(v):,.2f}"
    except: return str(v)

def fmt_pct(v):
    if v is None: return "—"
    try: return f"{float(v):+.2f}%"
    except: return str(v)

def color_class(v):
    try:
        v = float(v)
        if v > 0: return "text-success"
        if v < 0: return "text-danger"
    except: pass
    return "text-warning"

def signal_class(signal):
    signal = (signal or "HOLD").upper()
    return {
        "STRONG BUY": "signal-strong-buy",
        "BUY": "signal-buy",
        "HOLD": "signal-hold",
        "SELL": "signal-sell",
        "STRONG SELL": "signal-strong-sell",
    }.get(signal, "signal-hold")

def broker_color(activity):
    if "BUYING" in (activity or ""): return "text-success"
    if "SELLING" in (activity or ""): return "text-danger"
    return "text-warning"

def risk_color(level):
    if level == "High": return "text-danger"
    if level == "Medium": return "text-warning"
    return "text-success"


# ═══════════════════════════════════════════════════════════════════════
#  CSS
# ═══════════════════════════════════════════════════════════════════════

CSS = """
:root {
    --primary: #2563eb;
    --primary-light: #dbeafe;
    --success: #16a34a;
    --warning: #d97706;
    --danger: #dc2626;
    --dark: #1f2937;
    --light: #f9fafb;
    --gray: #6b7280;
    --gray-light: #e5e7eb;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--light);
    color: var(--dark);
    line-height: 1.6;
}
.container { max-width: 1200px; margin: 0 auto; padding: 20px; }

/* Header */
.header {
    background: linear-gradient(135deg, #1e40af, #3b82f6);
    color: white; padding: 32px; border-radius: 16px;
    margin-bottom: 24px;
}
.header h1 { font-size: 2rem; margin-bottom: 4px; }
.header-symbol { font-size: 1.3rem; opacity: 0.9; margin-bottom: 4px; }
.header-meta { font-size: 0.9rem; opacity: 0.8; }
.header-price {
    font-size: 2.5rem; font-weight: 800; margin-top: 12px;
}
.header-change { font-size: 1.1rem; margin-top: 4px; }

/* Cards */
.card {
    background: white; border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    padding: 24px; margin-bottom: 24px;
}
.card-title {
    font-size: 1.1rem; font-weight: 700; margin-bottom: 16px;
    padding-bottom: 12px; border-bottom: 2px solid var(--gray-light);
    display: flex; align-items: center; gap: 8px;
}

/* Grid System */
.grid { display: grid; gap: 24px; }
.grid-2 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
.grid-3 { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.grid-4 { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }

/* Signal Badge */
.signal-badge {
    display: inline-block; padding: 8px 20px; border-radius: 50px;
    font-weight: 700; font-size: 1rem; text-transform: uppercase;
    letter-spacing: 0.5px;
}
.signal-strong-buy { background: var(--success); color: white; }
.signal-buy { background: #22c55e; color: white; }
.signal-hold { background: var(--warning); color: white; }
.signal-sell { background: #f97316; color: white; }
.signal-strong-sell { background: var(--danger); color: white; }

/* Price Levels */
.price-levels { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 16px; }
.pl { padding: 12px; text-align: center; border-radius: 8px; font-size: 0.85rem; }
.pl strong { display: block; margin-bottom: 4px; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; }
.pl-entry { background: #dbeafe; color: var(--primary); }
.pl-stop { background: #fee2e2; color: var(--danger); }
.pl-t1 { background: #dcfce7; color: var(--success); }
.pl-t2 { background: #bbf7d0; color: #15803d; }

/* Score Bar */
.score-row { display: flex; align-items: center; margin-bottom: 10px; gap: 12px; }
.score-label { min-width: 140px; font-size: 0.85rem; color: var(--gray); }
.score-bar-wrap { flex: 1; height: 8px; background: var(--gray-light); border-radius: 4px; overflow: hidden; }
.score-bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.score-value { min-width: 40px; text-align: right; font-weight: 600; font-size: 0.85rem; }

/* Metric Rows */
.metric-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid var(--gray-light);
}
.metric-row:last-child { border-bottom: none; }
.metric-label { color: var(--gray); font-size: 0.9rem; }
.metric-value { font-weight: 600; font-size: 0.9rem; }

/* Colors */
.text-success { color: var(--success); }
.text-danger { color: var(--danger); }
.text-warning { color: var(--warning); }
.text-primary { color: var(--primary); }
.text-gray { color: var(--gray); }

/* Strengths/Weaknesses */
.sw-item { padding: 6px 0; font-size: 0.9rem; display: flex; align-items: flex-start; gap: 8px; }
.sw-icon { flex-shrink: 0; margin-top: 2px; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--gray-light); }
th { background: var(--light); font-weight: 600; color: var(--gray); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.5px; position: sticky; top: 0; }
tr:hover { background: #f8fafc; }

/* Chart */
.chart-container { position: relative; height: 300px; margin-top: 16px; }
.chart-container-sm { position: relative; height: 200px; margin-top: 12px; }

/* Stat Cards */
.stat-card {
    text-align: center; padding: 16px;
    border-radius: 8px; background: var(--light);
}
.stat-value { font-size: 1.5rem; font-weight: 700; }
.stat-label { font-size: 0.8rem; color: var(--gray); margin-top: 4px; }

/* Info Banner */
.info-banner {
    background: #fef3c7; border-left: 4px solid #f59e0b;
    padding: 12px 16px; border-radius: 0 8px 8px 0;
    margin-bottom: 24px; font-size: 0.9rem;
}
.info-banner strong { color: #92400e; }

/* Responsive */
@media (max-width: 768px) {
    .header h1 { font-size: 1.4rem; }
    .header-price { font-size: 1.8rem; }
    .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
    .price-levels { grid-template-columns: repeat(2, 1fr); }
}
"""


# ═══════════════════════════════════════════════════════════════════════
#  SECTION BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def _build_header(a):
    """Build the gradient header with price and signal."""
    change_cls = "color: #86efac;" if a.get("change_pct", 0) >= 0 else "color: #fca5a5;"
    change_arrow = "▲" if a.get("change_pct", 0) >= 0 else "▼"
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    return f'''<div class="header">
<div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap;">
<div>
    <h1>{a["symbol"]} — {a.get("company_name", a["symbol"])}</h1>
    <div class="header-symbol">{a.get("sector", "")} | {a.get("total_candles", 0)} trading days</div>
    <div class="header-meta">Generated {timestamp} | Data: {a.get("data_days", 0)} sessions</div>
</div>
<div style="text-align:right;">
    <div class="header-price">{fmt_price(a["price"])}</div>
    <div class="header-change" style="{change_cls}">
        {change_arrow} {fmt_pct(a.get("change_pct"))} ({fmt_price(a.get("change_abs"))})
    </div>
    <div style="margin-top:8px;">
        <span class="signal-badge {signal_class(a.get("signal"))}">{a.get("signal", "HOLD")}</span>
    </div>
</div>
</div>
</div>
'''


def _build_signal_score_panel(a):
    """Signal badge, score, confidence, risk, and price levels."""
    tech = a.get("tech_score", 0)
    fund = a.get("fund_score", 0)
    vol = a.get("vol_score", 0)
    bt = a.get("bt_score", 0)
    comp = a.get("composite", 0)

    def score_bar(label, value, weight, color):
        pct = max(0, min(100, value))
        return f'''<div class="score-row">
<span class="score-label">{label} ({weight}%)</span>
<div class="score-bar-wrap"><div class="score-bar-fill" style="width:{pct}%;background:{color};"></div></div>
<span class="score-value" style="color:{color}">{value:.0f}</span>
</div>'''

    # Entry zone
    atr_val = float(a.get("atr") or 0)
    entry_lo = a["price"] - 0.5 * atr_val if atr_val > 0 else a["price"] * 0.995
    entry_hi = a["price"] + 0.5 * atr_val if atr_val > 0 else a["price"] * 1.005

    h = '<div class="grid-2">\n'

    # Left: Signal + Score + Price Levels
    h += '<div class="card">\n'
    h += f'<div style="text-align:center;margin-bottom:16px;">\n'
    h += f'<span class="signal-badge {signal_class(a.get("signal"))}" style="font-size:1.2rem;padding:12px 24px;">{a.get("signal", "HOLD")}</span>\n'
    h += f'</div>\n'
    h += f'<div style="text-align:center;margin-bottom:8px;">\n'
    h += f'<div class="stat-value" style="font-size:2rem;">{comp:.1f}</div>\n'
    h += f'<div class="stat-label">Composite Score / 100</div>\n'
    h += f'</div>\n'
    h += f'<div style="text-align:center;margin-bottom:8px;">\n'
    h += f'<div style="font-weight:600;">Confidence: {a.get("confidence", 0):.0f}%</div>\n'
    h += f'<div style="color:var(--gray);font-size:0.85rem;">Risk: <span class="{risk_color(a.get("risk_level", "Low"))}">{a.get("risk_level", "Low")}</span></div>\n'
    h += f'</div>\n'

    # Price Levels
    h += '<div class="price-levels">\n'
    h += f'<div class="pl pl-entry"><strong>Entry</strong>{fmt_price(entry_lo)}<br>– {fmt_price(entry_hi)}</div>\n'
    h += f'<div class="pl pl-stop"><strong>Stop</strong>{fmt_price(a.get("stop_loss"))}</div>\n'
    h += f'<div class="pl pl-t1"><strong>T1</strong>{fmt_price(a.get("target1"))}</div>\n'
    h += f'<div class="pl pl-t2"><strong>T2</strong>{fmt_price(a.get("target2"))}</div>\n'
    h += '</div>\n'
    h += f'<div style="text-align:center;margin-top:12px;font-size:0.85rem;color:var(--gray);">R:R Ratio: <strong>{a.get("rr_ratio", 0):.1f}:1</strong> | Position Size: <strong>{a.get("position_size", 0)} shares</strong></div>\n'
    h += '</div>\n'

    # Right: Score Breakdown
    h += '<div class="card">\n'
    h += '<div class="card-title">📊 Score Breakdown</div>\n'
    h += score_bar("Technical", tech, 30, "#3b82f6")
    h += score_bar("Fundamental", fund, 35, "#8b5cf6")
    h += score_bar("Volume", vol, 15, "#06b6d4")
    h += score_bar("Backtest", bt, 20, "#f59e0b")

    # Modifiers
    def modifier_row(label, val):
        if val == 0: return ""
        color = "var(--success)" if val > 0 else "var(--danger)"
        return f'<div class="metric-row"><span class="metric-label">{label}</span><span class="metric-value" style="color:{color}">{val:+d}</span></div>\n'

    mods = modifier_row("Broker Modifier", a.get("broker_mod", 0))
    mods += modifier_row("Market Modifier", a.get("market_mod", 0))
    mods += modifier_row("Sector Modifier", a.get("sector_mod", 0))
    if mods:
        h += f'<div style="margin-top:12px;border-top:1px solid var(--gray-light);padding-top:12px;">\n{mods}</div>\n'

    h += '</div>\n</div>\n'
    return h


def _build_technicals_fundamentals_volume(a):
    """3-column grid: Technical, Fundamentals, Volume Analysis."""
    fd = a.get("fund_data", {})

    def metric(label, value, cls=""):
        cls_str = f' class="{cls}"' if cls else ""
        return f'<div class="metric-row"><span class="metric-label">{label}</span><span class="metric-value"{cls_str}>{value}</span></div>\n'

    h = '<div class="grid-3">\n'

    # Technical Indicators
    h += '<div class="card">\n<div class="card-title">📈 Technical Indicators</div>\n'
    h += metric("Price", fmt_price(a["price"]))

    rsi = a.get("rsi")
    rsi_cls = ""
    if rsi is not None:
        if rsi > 80: rsi_cls = "text-danger"
        elif rsi < 20: rsi_cls = "text-success"
    h += metric("RSI (14)", f"{rsi:.1f}" if rsi else "—", rsi_cls)

    macd = a.get("macd_hist")
    h += metric("MACD", f"{macd:.2f}" if macd is not None else "—",
                "text-success" if macd and macd > 0 else ("text-danger" if macd and macd < 0 else ""))

    h += metric("SMA 20", fmt_price(a.get("sma20")))
    h += metric("SMA 50", fmt_price(a.get("sma50")))
    h += metric("SMA 200", fmt_price(a.get("sma200")))
    h += metric("Trend", f'<span class="{color_class(1 if "Up" in (a.get("trend") or "") else (-1 if "Down" in (a.get("trend") or "") else 0))}">{a.get("trend", "—")}</span>')
    h += metric("ATR (14)", fmt_price(a.get("atr")))

    stoch_k = a.get("stoch_k")
    stoch_d = a.get("stoch_d")
    stoch_str = f"{stoch_k:.0f}/{stoch_d:.0f}" if stoch_k is not None and stoch_d is not None else "—"
    h += metric("Stoch K/D", stoch_str)

    h += metric("BB %B", f"{a.get('bb_pct', 0):.1f}%" if a.get("bb_pct") is not None else "—")
    h += metric("ROC (20)", fmt_pct(a.get("roc_20")))

    patterns = a.get("patterns", [])
    h += metric("Patterns", ", ".join(patterns) if patterns else "None")
    h += '</div>\n'

    # Fundamentals
    h += '<div class="card">\n<div class="card-title">💼 Fundamentals</div>\n'
    pe = fd.get("pe_ratio", 0)
    pe_cls = "text-success" if 0 < pe < 15 else ("text-danger" if pe > 40 else "")
    h += metric("P/E Ratio", f"{pe:.2f}" if pe else "—", pe_cls)

    pbv = fd.get("pbv")
    h += metric("P/B Ratio", f"{pbv:.2f}" if pbv else "—")

    eps = fd.get("eps", 0)
    h += metric("EPS", fmt_price(eps) if eps else "—")

    eps_growth = a.get("eps_growth")
    h += metric("EPS Growth", fmt_pct(eps_growth) if eps_growth is not None else "—",
                color_class(eps_growth) if eps_growth is not None else "")

    h += metric("Book Value", fmt_price(fd.get("book_value")))

    div_yield = fd.get("div_yield", 0)
    h += metric("Div Yield", f"{div_yield:.2f}%" if div_yield else "—")

    roe = fd.get("roe", 0)
    h += metric("ROE", f"{roe:.1f}%" if roe else "—")
    h += metric(
        "Fundamental Freshness",
        "Stale" if a.get("fundamental_stale") else "Fresh",
        "text-warning" if a.get("fundamental_stale") else "text-success",
    )
    h += metric("Published Date", fd.get("published_date") or "—")

    h += metric("Fiscal Year", fd.get("fiscal_year") or "—")
    h += metric("Quarter", fd.get("quarter") or "—")
    h += '</div>\n'

    # Volume Analysis
    h += '<div class="card">\n<div class="card-title">📊 Volume Analysis</div>\n'
    last_vol = 0
    chart = a.get("price_chart", {})
    if chart and chart.get("volumes"):
        last_vol = chart["volumes"][-1]
    h += metric("Today Vol", fmt(last_vol))
    h += metric("Avg Vol 20", fmt(a.get("vol_avg")))

    vr = a.get("vol_ratio", 0)
    vr_cls = "text-success" if vr >= 1.5 else ("text-danger" if vr < 0.5 else "")
    h += metric("Vol Ratio", f"{vr:.2f}x", vr_cls)

    obv = a.get("obv_trend", "—")
    obv_cls = "text-success" if obv == "RISING" else ("text-danger" if obv == "FALLING" else "")
    h += metric("OBV Trend", f'<span class="{obv_cls}">{obv}</span>')

    mfi = a.get("mfi")
    h += metric("MFI", f"{mfi:.1f}" if mfi is not None else "—")

    vwap = a.get("vwap")
    h += metric(
        "VWAP",
        fmt_price(vwap) if vwap else "—",
        "text-success" if a.get("vwap_trusted") else "text-warning",
    )
    intraday_quality = a.get("intraday_quality", {})
    vwap_quality = "Trusted" if a.get("vwap_trusted") else (intraday_quality.get("reason") or "Not trusted")
    h += metric("VWAP Quality", vwap_quality, "text-success" if a.get("vwap_trusted") else "text-warning")
    h += metric(
        "Broker Signal",
        a.get("broker_signal_reliability", "HIGH"),
        "text-success" if a.get("broker_signal_reliability") == "HIGH" else "text-warning",
    )

    h += metric("52W High", fmt_price(a.get("hi52")))
    h += metric("52W Low", fmt_price(a.get("lo52")))
    h += metric("52W Range", f"{a.get('range_pct', 0):.1f}%")
    h += '</div>\n'

    h += '</div>\n'
    return h


def _build_strengths_weaknesses(a):
    """Strengths and Weaknesses two-column layout."""
    strengths = a.get("strengths", [])
    weaknesses = a.get("weaknesses", [])

    h = '<div class="grid-2">\n'

    # Strengths
    h += '<div class="card">\n'
    h += '<div class="card-title" style="color:var(--success);">✓ Strengths</div>\n'
    if strengths:
        for s in strengths:
            h += f'<div class="sw-item"><span class="sw-icon" style="color:var(--success);">✓</span><span>{s}</span></div>\n'
    else:
        h += '<div class="text-gray" style="padding:12px;">No significant strengths identified</div>\n'
    h += '</div>\n'

    # Weaknesses
    h += '<div class="card">\n'
    h += '<div class="card-title" style="color:var(--danger);">✗ Weaknesses</div>\n'
    if weaknesses:
        for w in weaknesses:
            h += f'<div class="sw-item"><span class="sw-icon" style="color:var(--danger);">✗</span><span>{w}</span></div>\n'
    else:
        h += '<div class="text-gray" style="padding:12px;">No significant weaknesses identified</div>\n'
    h += '</div>\n'

    h += '</div>\n'
    return h


def _build_price_chart(a):
    """Price history chart with SMA lines and volume bars."""
    chart_data = a.get("price_chart", {})
    if not chart_data or not chart_data.get("labels"):
        return ""

    labels = json.dumps(chart_data["labels"])
    prices = json.dumps(chart_data["prices"])
    volumes = json.dumps(chart_data["volumes"])
    sma20 = json.dumps(chart_data.get("sma20", []))
    sma50 = json.dumps(chart_data.get("sma50", []))

    h = '<div class="card">\n'
    h += '<div class="card-title">📉 Price History (60 Days)</div>\n'
    h += '<div class="chart-container"><canvas id="priceChart"></canvas></div>\n'
    h += f'''<script>
(function() {{
    const ctx = document.getElementById('priceChart').getContext('2d');
    new Chart(ctx, {{
        type: 'line',
        data: {{
            labels: {labels},
            datasets: [
                {{
                    label: 'Close Price',
                    data: {prices},
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37,99,235,0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                    yAxisID: 'y'
                }},
                {{
                    label: 'SMA 20',
                    data: {sma20},
                    borderColor: '#f59e0b',
                    borderDash: [5, 5],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    yAxisID: 'y'
                }},
                {{
                    label: 'SMA 50',
                    data: {sma50},
                    borderColor: '#8b5cf6',
                    borderDash: [5, 5],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    yAxisID: 'y'
                }},
                {{
                    label: 'Volume',
                    data: {volumes},
                    type: 'bar',
                    backgroundColor: 'rgba(148,163,184,0.3)',
                    yAxisID: 'y1'
                }}
            ]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            interaction: {{ mode: 'index', intersect: false }},
            plugins: {{
                legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 16 }} }}
            }},
            scales: {{
                x: {{ display: true, grid: {{ display: false }}, ticks: {{ maxTicksLimit: 10, font: {{ size: 10 }} }} }},
                y: {{ display: true, position: 'left', grid: {{ color: '#e5e7eb' }}, ticks: {{ font: {{ size: 10 }} }} }},
                y1: {{ display: false, position: 'right', grid: {{ display: false }}, beginAtZero: true }}
            }}
        }}
    }});
}})();
</script>\n'''
    h += '</div>\n'
    return h


def _build_intraday_chart(a):
    """Intraday price chart."""
    chart_data = a.get("intraday_chart")
    if not chart_data or not chart_data.get("labels"):
        return ""

    labels = json.dumps(chart_data["labels"])
    prices = json.dumps(chart_data["prices"])
    volumes = json.dumps(chart_data["volumes"])

    h = '<div class="card">\n'
    h += '<div class="card-title">⏱️ Intraday Price (Latest Session)</div>\n'
    h += '<div class="chart-container-sm"><canvas id="intradayChart"></canvas></div>\n'
    h += f'''<script>
(function() {{
    const ctx = document.getElementById('intradayChart').getContext('2d');
    new Chart(ctx, {{
        type: 'line',
        data: {{
            labels: {labels},
            datasets: [
                {{
                    label: 'Price',
                    data: {prices},
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37,99,235,0.05)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    borderWidth: 2,
                    yAxisID: 'y'
                }},
                {{
                    label: 'Volume',
                    data: {volumes},
                    type: 'bar',
                    backgroundColor: 'rgba(148,163,184,0.3)',
                    yAxisID: 'y1'
                }}
            ]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            interaction: {{ mode: 'index', intersect: false }},
            plugins: {{
                legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 16 }} }}
            }},
            scales: {{
                x: {{ display: true, grid: {{ display: false }}, ticks: {{ maxTicksLimit: 15, font: {{ size: 9 }} }} }},
                y: {{ display: true, position: 'left', grid: {{ color: '#e5e7eb' }} }},
                y1: {{ display: false, position: 'right', grid: {{ display: false }}, beginAtZero: true }}
            }}
        }}
    }});
}})();
</script>\n'''
    h += '</div>\n'
    return h


def _build_support_resistance(a):
    """Pivot Points and Fibonacci levels."""
    pivots = a.get("pivots", {})
    fib = a.get("fib", {})

    if not pivots and not fib:
        return ""

    h = '<div class="card">\n'
    h += '<div class="card-title">🎯 Support & Resistance Levels</div>\n'
    h += '<div class="grid-2">\n'

    if pivots:
        h += '<div>\n<h3 style="font-size:0.9rem;font-weight:600;margin-bottom:12px;">Pivot Points</h3>\n'
        for key, label in [("R2_fib", "R2 (Fib)"), ("R1_fib", "R1 (Fib)"), ("R1", "R1 (Standard)"),
                           ("P", "Pivot"), ("S1", "S1 (Standard)"), ("S1_fib", "S1 (Fib)"), ("S2_fib", "S2 (Fib)")]:
            val = pivots.get(key)
            if val:
                cls = "text-success" if "R" in key else ("text-danger" if "S" in key else "text-primary")
                h += f'<div class="metric-row"><span class="metric-label">{label}</span><span class="metric-value {cls}">{fmt_price(val)}</span></div>\n'
        h += '</div>\n'

    if fib:
        h += '<div>\n<h3 style="font-size:0.9rem;font-weight:600;margin-bottom:12px;">Fibonacci Retracement</h3>\n'
        h += f'<div class="metric-row"><span class="metric-label">52W High</span><span class="metric-value text-success">{fmt_price(a.get("hi52"))}</span></div>\n'
        for key, label in [("fib_382", "38.2%"), ("fib_500", "50.0%"), ("fib_618", "61.8%")]:
            val = fib.get(key)
            if val:
                cls = "text-danger" if a["price"] < val else "text-success"
                h += f'<div class="metric-row"><span class="metric-label">{label}</span><span class="metric-value {cls}">{fmt_price(val)}</span></div>\n'
        h += f'<div class="metric-row"><span class="metric-label">52W Low</span><span class="metric-value text-danger">{fmt_price(a.get("lo52"))}</span></div>\n'
        h += '</div>\n'

    h += '</div>\n</div>\n'
    return h


def _build_broker_activity(a):
    """Broker activity table — top buyers and sellers."""
    bs = a.get("broker_summary", {})
    buyers = bs.get("buyers", [])
    sellers = bs.get("sellers", [])

    if not buyers and not sellers:
        return ""

    h = '<div class="card">\n'
    h += '<div class="card-title">🏦 Broker Activity</div>\n'

    activity = a.get("broker_activity", "NEUTRAL")
    h += f'<div style="margin-bottom:16px;">Activity: <strong class="{broker_color(activity)}">{activity}</strong>'
    h += f' | Asymmetry Score: <strong>{a.get("asym_score", 50):.1f}</strong></div>\n'

    h += '<div class="grid-2">\n'

    # Top Buyers
    if buyers:
        h += '<div>\n<h3 style="font-size:0.9rem;font-weight:600;margin-bottom:8px;color:var(--success);">Top Buyers</h3>\n'
        h += '<table><thead><tr><th>Broker</th><th>Trades</th><th>Amount</th><th>Sessions</th></tr></thead><tbody>\n'
        for b in buyers[:7]:
            h += f'<tr><td>{b.get("broker_name", "—")}</td><td>{b.get("trades", 0)}</td>'
            h += f'<td>{fmt(b.get("total_amt"))}</td><td>{b.get("sessions", 0)}</td></tr>\n'
        h += '</tbody></table>\n</div>\n'

    # Top Sellers
    if sellers:
        h += '<div>\n<h3 style="font-size:0.9rem;font-weight:600;margin-bottom:8px;color:var(--danger);">Top Sellers</h3>\n'
        h += '<table><thead><tr><th>Broker</th><th>Trades</th><th>Amount</th><th>Sessions</th></tr></thead><tbody>\n'
        for s in sellers[:7]:
            h += f'<tr><td>{s.get("broker_name", "—")}</td><td>{s.get("trades", 0)}</td>'
            h += f'<td>{fmt(s.get("total_amt"))}</td><td>{s.get("sessions", 0)}</td></tr>\n'
        h += '</tbody></table>\n</div>\n'

    h += '</div>\n</div>\n'
    return h


def _build_company_info(a):
    """Company information card."""
    info = a.get("company_info", {})
    if not info.get("name"):
        return ""

    def metric(label, value):
        return f'<div class="metric-row"><span class="metric-label">{label}</span><span class="metric-value">{value}</span></div>\n'

    h = '<div class="card">\n'
    h += '<div class="card-title">🏢 Company Information</div>\n'
    h += '<div class="grid-2">\n<div>\n'
    h += metric("Company", info.get("name", "—"))
    h += metric("Sector", info.get("sector", "—"))
    h += metric("Listed Shares", fmt(info.get("listed_shares")))
    h += metric("Market Cap", fmt(info.get("market_cap")))
    h += '</div>\n<div>\n'
    h += metric("Listing Date", info.get("listing_date", "—") or "—")
    h += metric("Promoter %", f"{info.get('promoter_pct', 0):.1f}%")
    h += metric("Public %", f"{info.get('public_pct', 0):.1f}%")

    # Rankings
    ranking = a.get("ranking", {})
    if ranking:
        for cat, data in ranking.items():
            h += metric(f"Rank ({cat})", f"#{data.get('rank', '—')}")
    h += '</div>\n</div>\n</div>\n'
    return h


def _build_dividend_history(a):
    """Dividend history table."""
    divs = a.get("dividend_history", [])
    if not divs:
        return ""

    h = '<div class="card">\n'
    h += '<div class="card-title">💰 Dividend History</div>\n'
    h += '<div style="max-height:300px;overflow-y:auto;">\n'
    h += '<table><thead><tr><th>Date</th><th>Bonus %</th><th>Cash %</th></tr></thead><tbody>\n'
    for d in divs[:10]:
        bonus = float(d.get("bonus_share_percent") or 0)
        cash = float(d.get("cash_dividend_percent") or 0)
        date = str(d.get("book_close_date") or "—")[:10]
        h += f'<tr><td>{date}</td><td>{bonus:.1f}%</td><td>{cash:.1f}%</td></tr>\n'
    h += '</tbody></table>\n</div>\n</div>\n'
    return h


def _build_sector_peers(a):
    """Sector peers comparison mini-table."""
    peers = a.get("sector_peers", [])
    if not peers:
        return ""

    h = '<div class="card">\n'
    h += f'<div class="card-title">🏭 Sector Peers — {a.get("sector", "")}</div>\n'
    h += '<div style="max-height:300px;overflow-y:auto;">\n'
    h += '<table><thead><tr><th>Symbol</th><th>Price</th></tr></thead><tbody>\n'
    for p in peers:
        price = float(p.get("price") or 0)
        h += f'<tr><td>{p.get("symbol", "—")}</td><td>{fmt_price(price)}</td></tr>\n'
    h += '</tbody></table>\n</div>\n</div>\n'
    return h


def _build_market_alert(a):
    """Market-level warning banner if applicable."""
    market = a.get("market", {})
    idx = market.get("index", {})
    chg = float(idx.get("change_percent") or 0)

    alerts = []
    if chg < -1:
        alerts.append(f"Broad market weakness detected (NEPSE {chg:+.2f}%)")
    if a.get("circuit_flag"):
        alerts.append("This stock has hit circuit breakers recently — exercise caution")
    if a.get("liquidity_flag"):
        alerts.append("Low liquidity stock — difficult to exit large positions")
    if a.get("fib_618_broken"):
        alerts.append("Price below Fibonacci 61.8% — Uptrend invalidated")

    data_conf = int(a.get("data_confidence") or 0)
    if data_conf < 60:
        alerts.append(f"Low data confidence ({data_conf}/100) — reduce conviction")
    elif data_conf < 75:
        alerts.append(f"Moderate data confidence ({data_conf}/100)")

    for msg in a.get("data_quality_alerts", []):
        if msg and msg not in alerts:
            alerts.append(msg)

    if not alerts:
        return ""

    h = '<div class="info-banner">\n'
    h += '<strong>⚠️ Alert: </strong>'
    h += " | ".join(alerts)
    h += '\n</div>\n'
    return h


def _build_stat_cards(a):
    """Quick stat cards row."""
    fd = a.get("fund_data", {})
    data_conf = int(a.get("data_confidence") or 0)
    data_conf_color = "var(--success)" if data_conf >= 75 else ("var(--warning)" if data_conf >= 60 else "var(--danger)")

    stats = [
        ("Data Confidence", f"{data_conf}/100", data_conf_color),
        ("52W High Prox", f"{a.get('high_prox', 0):.1f}%", "var(--primary)"),
        ("Vol Ratio", f"{a.get('vol_ratio', 0):.2f}x", "var(--warning)" if a.get("vol_ratio", 0) >= 1.5 else "var(--gray)"),
        ("RSI (14)", f"{a.get('rsi', 0):.1f}" if a.get("rsi") else "—", "var(--danger)" if a.get("rsi") and a["rsi"] > 80 else ("var(--success)" if a.get("rsi") and a["rsi"] < 20 else "var(--primary)")),
    ]

    h = '<div class="grid-4">\n'
    for label, value, color in stats:
        h += f'<div class="stat-card"><div class="stat-value" style="color:{color};">{value}</div><div class="stat-label">{label}</div></div>\n'
    h += '</div>\n'
    return h


def _build_risk_metrics(a):
    """Risk metrics card."""
    h = '<div class="card">\n'
    h += '<div class="card-title">⚠️ Risk Metrics</div>\n'

    def metric(label, value, cls=""):
        cls_str = f' class="{cls}"' if cls else ""
        return f'<div class="metric-row"><span class="metric-label">{label}</span><span class="metric-value"{cls_str}>{value}</span></div>\n'

    data_conf = int(a.get("data_confidence") or 0)
    h += metric("Risk Level", a.get("risk_level", "Low"), risk_color(a.get("risk_level", "Low")))
    h += metric(
        "Data Confidence",
        f"{data_conf}/100",
        "text-success" if data_conf >= 75 else ("text-warning" if data_conf >= 60 else "text-danger"),
    )
    h += metric("Volatility (20d)", f"{a.get('vol_20d', 0):.2f}%")
    h += metric("Max Drawdown", f"{a.get('max_drawdown', 0):.1f}%",
                "text-danger" if a.get("max_drawdown", 0) > 30 else "")
    h += metric("ATR / Price", f"{(a.get('atr', 0) / a['price'] * 100):.2f}%" if a.get("atr") and a["price"] > 0 else "—")
    h += metric("Circuit History", "⚠️ Yes" if a.get("circuit_flag") else "✓ No",
                "text-danger" if a.get("circuit_flag") else "text-success")
    h += metric("Liquidity", "⚠️ Low" if a.get("liquidity_flag") else "✓ Normal",
                "text-danger" if a.get("liquidity_flag") else "text-success")
    h += metric("52W Context", "Proxy (<252 bars)" if a.get("is_52w_proxy") else "Full 252-session context",
                "text-warning" if a.get("is_52w_proxy") else "text-success")
    h += '</div>\n'
    return h


# ═══════════════════════════════════════════════════════════════════════
#  MAIN BUILD & WRITE
# ═══════════════════════════════════════════════════════════════════════

def build_html(data):
    """Build the complete single-stock HTML report."""
    if not data:
        return "<html><body><h1>No data available</h1></body></html>"

    h = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{data["symbol"]} — NEPSE Single Stock Analysis</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>{CSS}</style>
</head>
<body>
<div class="container">
'''

    h += _build_header(data)
    h += _build_market_alert(data)
    h += _build_stat_cards(data)
    h += _build_signal_score_panel(data)
    h += _build_technicals_fundamentals_volume(data)
    h += _build_price_chart(data)
    h += _build_intraday_chart(data)
    h += _build_strengths_weaknesses(data)
    h += _build_support_resistance(data)
    h += _build_broker_activity(data)
    h += _build_risk_metrics(data)

    # Two-column: Company Info + Dividend History
    h += '<div class="grid-2">\n'
    h += _build_company_info(data)
    h += _build_dividend_history(data)
    h += '</div>\n'

    h += _build_sector_peers(data)

    # Footer
    h += f'''
<div style="text-align:center;padding:24px;color:var(--gray);font-size:0.8rem;">
    NEPSE Single Stock Analysis — Generated {datetime.now().strftime("%B %d, %Y at %I:%M %p")}<br>
    Powered by NEPSE Analytics Engine v3.0 | For educational &amp; research use only<br>
    <strong>Disclaimer:</strong> This is not financial advice. All analysis is algorithmic and may contain errors.
</div>
'''

    h += '</div>\n</body>\n</html>'
    return h


def write_report(html, symbol, output_dir=None):
    """Write the HTML report to disk."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{symbol}_analysis_{date_str}.html"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  ✅ Report written: {filepath}")
    return filepath


# ═══════════════════════════════════════════════════════════════════════
#  COMBINED ALL-STOCKS HTML  (--all mode)
# ═══════════════════════════════════════════════════════════════════════

_ALL_CSS = """
:root {
    --primary: #2563eb;
    --success: #16a34a;
    --warning: #d97706;
    --danger: #dc2626;
    --dark: #1f2937;
    --light: #f9fafb;
    --gray: #6b7280;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--light);
    color: var(--dark);
    line-height: 1.6;
}
.container { max-width: 1600px; margin: 0 auto; padding: 20px; }

.header {
    background: linear-gradient(135deg, var(--primary), #1e40af);
    color: white; padding: 30px; border-radius: 16px; margin-bottom: 24px;
}
.header h1 { font-size: 2rem; margin-bottom: 8px; }
.header-meta { opacity: 0.9; font-size: 0.9rem; }

.card {
    background: white; border-radius: 12px; padding: 24px;
    margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.card-title {
    font-size: 1.25rem; font-weight: 600; margin-bottom: 16px;
    padding-bottom: 12px; border-bottom: 2px solid var(--light);
}

.grid { display: grid; gap: 24px; }
.grid-2 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
.grid-3 { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.grid-4 { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
.grid-5 { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }

.stat-card {
    text-align: center; padding: 24px;
    background: var(--light); border-radius: 12px;
}
.stat-value { font-size: 2.5rem; font-weight: 700; color: var(--primary); }
.stat-label { font-size: 0.9rem; color: var(--gray); margin-top: 4px; }

.signal-badge {
    display: inline-block; padding: 6px 14px; border-radius: 50px;
    font-weight: 600; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px;
}
.signal-strong-buy { background: var(--success); color: white; }
.signal-buy { background: #22c55e; color: white; }
.signal-hold { background: var(--warning); color: white; }
.signal-sell { background: #f97316; color: white; }
.signal-strong-sell { background: var(--danger); color: white; }

table { width: 100%; border-collapse: collapse; }
th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }
th {
    background: var(--light); font-weight: 600; font-size: 0.85rem;
    text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0;
    cursor: pointer;
}
tr:hover { background: #f8fafc; }

.controls { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.search-box {
    flex: 1; min-width: 200px; padding: 12px 16px;
    border: 1px solid #e5e7eb; border-radius: 8px; font-size: 1rem;
}
.filter-select {
    padding: 12px 16px; border: 1px solid #e5e7eb; border-radius: 8px;
    font-size: 1rem; background: white; min-width: 150px;
}

.score-bar { display: flex; align-items: center; gap: 12px; }
.score-bar-fill { flex: 1; height: 8px; background: #e5e7eb; border-radius: 4px; overflow: hidden; }
.score-bar-fill-inner { height: 100%; border-radius: 4px; }

.metric-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e5e7eb; }
.metric-row:last-child { border-bottom: none; }
.metric-label { color: var(--gray); }
.metric-value { font-weight: 600; }

.price-levels { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }
.pl { padding: 8px; text-align: center; border-radius: 6px; font-size: 0.85rem; }
.pl-entry { background: #dbeafe; color: var(--primary); }
.pl-stop { background: #fee2e2; color: var(--danger); }
.pl-t1 { background: #dcfce7; color: var(--success); }
.pl-t2 { background: #bbf7d0; color: #15803d; }

.chart-container { height: 300px; margin-top: 16px; }

.text-success { color: var(--success); }
.text-danger { color: var(--danger); }
.text-warning { color: var(--warning); }
.text-primary { color: var(--primary); }

@media (max-width: 768px) {
    .grid-2, .grid-3, .grid-4, .grid-5 { grid-template-columns: 1fr; }
    .header h1 { font-size: 1.5rem; }
    .price-levels { grid-template-columns: repeat(2, 1fr); }
}
"""


def _rsi_class(rsi):
    """CSS class for RSI display."""
    try:
        v = float(rsi or 0)
        if v > 70: return "text-danger"
        if v < 30: return "text-success"
    except: pass
    return ""


def _broker_html(activity):
    """Inline broker activity badge."""
    act = (activity or "").upper()
    if "BUYING" in act:
        return f'<span style="font-size:0.75rem;font-weight:600;color:var(--success)">{activity}</span>'
    if "SELLING" in act:
        return f'<span style="font-size:0.75rem;font-weight:600;color:var(--danger)">{activity}</span>'
    return f'<span style="font-size:0.75rem;font-weight:600;color:var(--gray)">{activity or "N/A"}</span>'


def _safe(v, d=2, prefix=""):
    """Safe format a numeric value."""
    if v is None: return "—"
    try:
        v = float(v)
        return f"{prefix}{v:,.{d}f}"
    except:
        return str(v)


def build_all_stocks_html(all_data, failed=None):
    """Build a single combined HTML report for all analyzed stocks.

    Parameters
    ----------
    all_data : list[dict]
        List of analysis dicts returned by analyze_single_stock().
    failed : list[str] | None
        Symbols that could not be analyzed.

    Returns
    -------
    str  — Complete HTML document.
    """
    if failed is None:
        failed = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    total = len(all_data)

    # ── Sort by composite descending ──
    all_data.sort(key=lambda d: float(d.get("composite", 0)), reverse=True)

    # ── Signal counts ──
    sig_counts = {"STRONG BUY": 0, "BUY": 0, "HOLD": 0, "SELL": 0, "STRONG SELL": 0}
    sectors_set = set()
    for d in all_data:
        sig = (d.get("signal") or "HOLD").upper()
        sig_counts[sig] = sig_counts.get(sig, 0) + 1
        sec = d.get("sector") or d.get("company_info", {}).get("sector", "")
        if sec:
            sectors_set.add(sec)
    sectors = sorted(sectors_set)

    sb = sig_counts["STRONG BUY"]
    b = sig_counts["BUY"]
    ho = sig_counts["HOLD"]
    se = sig_counts["SELL"]
    ss = sig_counts["STRONG SELL"]
    sell_total = se + ss

    # ── Check for broad market weakness ──
    show_warning = sell_total > total * 0.5

    # ── Start HTML ──
    h = '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    h += '<meta charset="UTF-8">\n'
    h += '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    h += '<title>NEPSE All Stocks Deep Analysis Report</title>\n'
    h += '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>\n'
    h += f'<style>{_ALL_CSS}</style>\n'
    h += '</head>\n<body>\n<div class="container">\n'

    # ── Header ──
    h += '<div class="header">\n'
    h += '<h1>📊 NEPSE All Stocks Deep Analysis Report</h1>\n'
    h += f'<div class="header-meta">\n'
    h += f'<span>Generated: {now_str}</span> |\n'
    h += f'<span>Total Stocks Analyzed: {total} / {total + len(failed)}</span>\n'
    h += '</div>\n</div>\n'

    # ── Market warning banner ──
    if show_warning:
        h += '<div class="card" style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 16px 20px;">\n'
        h += f'<strong style="color: #92400e;">⚠️ Broad market weakness detected — '
        h += f'{sell_total} of {total} stocks show SELL signals. '
        h += 'SELL ratings may reflect market conditions, not stock-specific issues.</strong>\n'
        h += '</div>\n'

    # ── Signal distribution cards ──
    h += '<div class="card">\n'
    h += '<h2 class="card-title">📈 Market Summary</h2>\n'
    h += '<div class="grid grid-5">\n'
    for label, count, color_var, color_hex in [
        ("Strong Buy", sb, "var(--success)", None),
        ("Buy", b, None, "#22c55e"),
        ("Hold", ho, "var(--warning)", None),
        ("Sell", se, None, "#f97316"),
        ("Strong Sell", ss, "var(--danger)", None),
    ]:
        border_color = color_var or color_hex
        h += f'<div class="stat-card" style="border-left: 4px solid {border_color};">\n'
        if color_var:
            h += f'<div class="stat-value" style="color: {border_color};">{count}</div>\n'
        else:
            h += f'<div class="stat-value" style="color: {color_hex};">{count}</div>\n'
        h += f'<div class="stat-label">{label}</div>\n'
        h += '</div>\n'
    h += '</div>\n</div>\n'

    # ── Signal distribution chart ──
    h += '<div class="card">\n'
    h += '<h2 class="card-title">📊 Signal Distribution</h2>\n'
    h += '<div class="chart-container"><canvas id="signalChart"></canvas></div>\n'
    h += '</div>\n'

    # ── Top 10 picks ──
    top10 = all_data[:10]
    h += '<div class="card">\n'
    h += '<h2 class="card-title">🏆 Top 10 Picks (Highest Composite Scores)</h2>\n'
    h += '<div style="overflow-x: auto;"><table><thead><tr>\n'
    h += '<th>Rank</th><th>Symbol</th><th>Company</th><th>Sector</th>'
    h += '<th>Price</th><th>Score</th><th>Signal</th>'
    h += '<th>Entry Zone</th><th>Target 1</th><th>Upside %</th>\n'
    h += '</tr></thead><tbody>\n'
    for rank, d in enumerate(top10, 1):
        sym = d["symbol"]
        name = d.get("company_name", "")
        sec = d.get("sector", "")
        price = float(d.get("price", 0))
        comp = float(d.get("composite", 0))
        sig = d.get("signal", "HOLD")
        atr_val = float(d.get("atr") or 0)
        entry_lo = price - 0.5 * atr_val if atr_val > 0 else price * 0.995
        entry_hi = price + 0.5 * atr_val if atr_val > 0 else price * 1.005
        t1 = float(d.get("target1") or price)
        upside = round((t1 - price) / price * 100, 1) if price > 0 else 0
        sc = signal_class(sig)
        h += '<tr>\n'
        h += f'<td><strong>{rank}</strong></td>\n'
        h += f'<td><strong>{sym}</strong></td>\n'
        h += f'<td>{name}</td><td>{sec}</td>\n'
        h += f'<td>Rs. {price:,.2f}</td>\n'
        h += '<td><div class="score-bar">'
        h += f'<span style="min-width: 40px;">{comp:.1f}</span>'
        h += '<div class="score-bar-fill">'
        h += f'<div class="score-bar-fill-inner" style="width: {comp}%; background: var(--primary);"></div>'
        h += '</div></div></td>\n'
        h += f'<td><span class="signal-badge {sc}">{sig}</span></td>\n'
        h += f'<td style="font-size:0.85rem;">Rs. {entry_lo:,.2f}<br>– Rs. {entry_hi:,.2f}</td>\n'
        h += f'<td>Rs. {t1:,.2f}</td>\n'
        upside_cls = "text-success" if upside >= 0 else "text-danger"
        h += f'<td class="{upside_cls}">{upside:.1f}%</td>\n'
        h += '</tr>\n'
    h += '</tbody></table></div>\n</div>\n'

    # ── All stocks table with controls ──
    h += '<div class="card">\n'
    h += '<h2 class="card-title">📋 All Stocks Analysis</h2>\n'

    # Controls: search, signal filter, sector filter
    h += '<div class="controls">\n'
    h += '<input type="text" class="search-box" id="searchBox" placeholder="Search by symbol or company name...">\n'
    h += '<select class="filter-select" id="signalFilter">\n'
    h += '<option value="">All Signals</option>\n'
    for sl in ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]:
        label = sl.title()
        h += f'<option value="{sl}">{label}</option>\n'
    h += '</select>\n'
    h += '<select class="filter-select" id="sectorFilter">\n'
    h += '<option value="">All Sectors</option>\n'
    for sec in sectors:
        h += f'<option value="{sec}">{sec}</option>\n'
    h += '</select>\n'
    h += '</div>\n'

    # Scrollable table
    h += '<div style="overflow-x: auto; max-height: 600px; overflow-y: auto;">\n'
    h += '<table id="stockTable"><thead><tr>\n'
    h += '<th onclick="sortTable(0)">Symbol ↕</th>\n'
    h += '<th onclick="sortTable(1)">Company</th>\n'
    h += '<th onclick="sortTable(2)">Sector</th>\n'
    h += '<th onclick="sortTable(3)">Price ↕</th>\n'
    h += '<th onclick="sortTable(4)">Change ↕</th>\n'
    h += '<th onclick="sortTable(5)">Score ↕</th>\n'
    h += '<th onclick="sortTable(6)">Signal</th>\n'
    h += '<th onclick="sortTable(7)">RSI ↕</th>\n'
    h += '<th onclick="sortTable(8)">P/E ↕</th>\n'
    h += '<th>Broker</th>\n'
    h += '<th>Actions</th>\n'
    h += '</tr></thead><tbody>\n'

    for d in all_data:
        sym = d["symbol"]
        name = d.get("company_name", "")
        sec = d.get("sector", "")
        price = float(d.get("price", 0))
        chg = float(d.get("change_pct", 0))
        comp = float(d.get("composite", 0))
        sig = (d.get("signal") or "HOLD").upper()
        rsi_v = d.get("rsi")
        pe = (d.get("fund_data") or {}).get("pe_ratio")
        broker = d.get("broker_activity", "")
        sc = signal_class(sig)
        chg_cls = "text-success" if chg > 0 else ("text-danger" if chg < 0 else "")
        rsi_cls = _rsi_class(rsi_v)

        h += f'<tr data-symbol="{sym}" data-signal="{sig}" data-sector="{sec}">\n'
        h += f'<td><strong>{sym}</strong></td>\n'
        h += f'<td>{name}</td>\n'
        h += f'<td>{sec}</td>\n'
        h += f'<td>Rs. {price:,.2f}</td>\n'
        h += f'<td class="{chg_cls}">{chg:+.2f}%</td>\n'
        h += f'<td>{comp:.1f}</td>\n'
        h += f'<td><span class="signal-badge {sc}">{sig}</span></td>\n'
        h += f'<td class="{rsi_cls}">{_safe(rsi_v, 1)}</td>\n'
        h += f'<td>{_safe(pe, 2)}</td>\n'
        h += f'<td>{_broker_html(broker)}</td>\n'
        h += f'<td><button onclick="showDetail(\'{sym}\')" style="padding: 6px 12px; cursor: pointer; '
        h += 'border: 1px solid var(--primary); background: white; color: var(--primary); '
        h += 'border-radius: 6px;">View</button></td>\n'
        h += '</tr>\n'

    h += '</tbody></table>\n</div>\n</div>\n'

    # ── Detail cards (hidden by default) ──
    for d in all_data:
        h += _build_detail_card(d)

    # ── Failed stocks card ──
    if failed:
        h += '<div class="card">\n'
        h += f'<h2 class="card-title" style="color: var(--danger);">⚠️ Failed to Analyze ({len(failed)} stocks)</h2>\n'
        h += '<p style="color: var(--gray);">These symbols could not be analyzed due to insufficient data:</p>\n'
        h += '<div style="margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px;">\n'
        for sym in failed:
            h += f'<span style="background: #fee2e2; color: var(--danger); padding: 4px 12px; border-radius: 4px; font-size: 0.85rem;">{sym}</span>\n'
        h += '</div>\n</div>\n'

    # ── Footer ──
    h += '<div style="text-align: center; padding: 20px; color: var(--gray); font-size: 0.9rem;">\n'
    h += '<p><strong>Disclaimer:</strong> This report is for informational purposes only and should not be considered as financial advice. '
    h += 'Past performance is not indicative of future results. Always conduct your own research before making investment decisions.</p>\n'
    h += f'<p style="margin-top: 8px;">Generated by NEPSE Single Stock Deep Analyser | {now_str}</p>\n'
    h += '</div>\n'

    # ── JavaScript ──
    h += '<script>\n'
    # Signal chart
    h += "const signalCtx = document.getElementById('signalChart').getContext('2d');\n"
    h += "new Chart(signalCtx, {\n"
    h += "  type: 'doughnut',\n"
    h += "  data: {\n"
    h += "    labels: ['Strong Buy', 'Buy', 'Hold', 'Sell', 'Strong Sell'],\n"
    h += f"    datasets: [{{ data: [{sb}, {b}, {ho}, {se}, {ss}],\n"
    h += "      backgroundColor: ['#16a34a', '#22c55e', '#d97706', '#f97316', '#dc2626'],\n"
    h += "      borderWidth: 2, borderColor: 'white' }]\n"
    h += "  },\n"
    h += "  options: { responsive: true, maintainAspectRatio: false,\n"
    h += "    plugins: { legend: { position: 'right', labels: { font: { size: 14 } } } } }\n"
    h += "});\n\n"

    # Filter / search
    h += "document.getElementById('searchBox').addEventListener('input', filterTable);\n"
    h += "document.getElementById('signalFilter').addEventListener('change', filterTable);\n"
    h += "document.getElementById('sectorFilter').addEventListener('change', filterTable);\n\n"
    h += """function filterTable() {
    const search = document.getElementById('searchBox').value.toLowerCase();
    const signal = document.getElementById('signalFilter').value;
    const sector = document.getElementById('sectorFilter').value;
    document.querySelectorAll('#stockTable tbody tr').forEach(row => {
        const symbol = row.dataset.symbol.toLowerCase();
        const rowSignal = row.dataset.signal;
        const rowSector = row.dataset.sector;
        const company = row.querySelector('td:nth-child(2)').textContent.toLowerCase();
        const matchSearch = symbol.includes(search) || company.includes(search);
        const matchSignal = !signal || rowSignal === signal;
        const matchSector = !sector || rowSector === sector;
        row.style.display = (matchSearch && matchSignal && matchSector) ? '' : 'none';
    });
}\n\n"""

    # Show / hide detail
    h += """function showDetail(symbol) {
    document.querySelectorAll('.stock-detail-card').forEach(el => el.style.display = 'none');
    const detail = document.getElementById('detail-' + symbol);
    if (detail) {
        detail.style.display = 'block';
        detail.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}
function hideDetail(symbol) {
    const detail = document.getElementById('detail-' + symbol);
    if (detail) { detail.style.display = 'none'; }
}\n\n"""

    # Sort
    h += """let sortDir = {};
function sortTable(col) {
    const table = document.getElementById('stockTable');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    sortDir[col] = !sortDir[col];
    rows.sort((a, b) => {
        let aVal = a.querySelectorAll('td')[col].textContent.trim();
        let bVal = b.querySelectorAll('td')[col].textContent.trim();
        const aNum = parseFloat(aVal.replace(/[^0-9.\\-]/g, ''));
        const bNum = parseFloat(bVal.replace(/[^0-9.\\-]/g, ''));
        if (!isNaN(aNum) && !isNaN(bNum)) {
            return sortDir[col] ? aNum - bNum : bNum - aNum;
        }
        return sortDir[col] ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });
    rows.forEach(row => tbody.appendChild(row));
}\n"""

    h += '</script>\n</div>\n</body>\n</html>'
    return h


def _build_detail_card(d):
    """Build a hidden detail card for one stock (used in --all combined view)."""
    sym = d["symbol"]
    name = d.get("company_name", "")
    sec = d.get("sector", "")
    sig = (d.get("signal") or "HOLD").upper()
    comp = float(d.get("composite", 0))
    conf = d.get("confidence", 50)
    risk = d.get("risk_level", "Medium")
    sc = signal_class(sig)

    price = float(d.get("price", 0))
    atr_val = float(d.get("atr") or 0)
    entry_lo = price - 0.5 * atr_val if atr_val > 0 else price * 0.995
    entry_hi = price + 0.5 * atr_val if atr_val > 0 else price * 1.005
    stop = float(d.get("stop_loss") or 0)
    t1 = float(d.get("target1") or 0)
    t2 = float(d.get("target2") or 0)

    tech = d.get("tech_score", 0)
    fund = d.get("fund_score", 0)
    vol = d.get("vol_score", 0)
    bt = d.get("bt_score", 0)
    bmod = d.get("broker_mod", 0)
    mmod = d.get("market_mod", 0)
    smod = d.get("sector_mod", 0)

    rsi_v = d.get("rsi")
    macd_v = d.get("macd_val")
    sma20 = d.get("sma20")
    sma50 = d.get("sma50")
    trend = d.get("trend", "")

    fd = d.get("fund_data") or {}
    pe = fd.get("pe_ratio")
    pbv = fd.get("pbv")
    eps = fd.get("eps")
    bv = fd.get("book_value")
    roe_v = fd.get("roe")
    div_y = fd.get("div_yield")
    eps_g = d.get("eps_growth")

    vol_today = float(d.get("vol_avg", 0)) * float(d.get("vol_ratio", 0)) if d.get("vol_avg") and d.get("vol_ratio") else None
    vol_avg = d.get("vol_avg")
    vol_ratio = d.get("vol_ratio")
    obv = d.get("obv_trend", "")
    mfi_v = d.get("mfi")

    broker = d.get("broker_activity", "")
    strengths = d.get("strengths", [])
    weaknesses = d.get("weaknesses", [])

    h = f'<div class="card stock-detail-card" id="detail-{sym}" style="display: none;">\n'

    # Title + close button
    h += '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">\n'
    h += '<div>\n'
    h += f'<h2 class="card-title" style="border: none; padding: 0; margin: 0;">{sym} - {name}</h2>\n'
    h += f'<div style="color: var(--gray);">{sec}</div>\n'
    h += '</div>\n'
    h += f'<button onclick="hideDetail(\'{sym}\')" style="padding: 8px 16px; cursor: pointer; border: 1px solid #e5e7eb; background: white; border-radius: 6px;">✕ Close</button>\n'
    h += '</div>\n'

    # Grid-2: Signal + Score breakdown
    h += '<div class="grid grid-2">\n'

    # Left: signal + price levels
    h += '<div>\n'
    h += '<div style="text-align: center; padding: 20px;">\n'
    h += f'<span class="signal-badge {sc}" style="font-size: 1.2rem; padding: 12px 24px;">{sig}</span>\n'
    h += '<div style="margin-top: 16px;">\n'
    h += f'<span style="font-size: 2rem; font-weight: 700;">{comp:.1f}</span>\n'
    h += '<span style="color: var(--gray);">/100</span>\n'
    h += '</div>\n'
    h += f'<div style="margin-top: 8px; color: var(--gray);">Confidence: {conf}% | Risk: {risk}</div>\n'
    h += '</div>\n'
    h += '<div class="price-levels">\n'
    h += f'<div class="pl pl-entry"><strong>Entry</strong><br>Rs. {entry_lo:,.2f}<br>– Rs. {entry_hi:,.2f}</div>\n'
    h += f'<div class="pl pl-stop"><strong>Stop</strong><br>Rs. {stop:,.2f}</div>\n'
    h += f'<div class="pl pl-t1"><strong>T1</strong><br>Rs. {t1:,.2f}</div>\n'
    h += f'<div class="pl pl-t2"><strong>T2</strong><br>Rs. {t2:,.2f}</div>\n'
    h += '</div>\n</div>\n'

    # Right: score breakdown
    h += '<div>\n'
    h += '<h4 style="margin-bottom: 12px;">Score Breakdown</h4>\n'
    h += f'<div class="metric-row"><span class="metric-label">Technical (30%)</span><span class="metric-value">{tech:.0f}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">Fundamental (35%)</span><span class="metric-value">{fund:.0f}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">Volume (15%)</span><span class="metric-value">{vol:.0f}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">Backtest (20%)</span><span class="metric-value">{bt:.0f}</span></div>\n'

    if bmod:
        cls = "text-success" if bmod > 0 else "text-danger"
        h += f'<div class="metric-row"><span class="metric-label">Broker Modifier</span><span class="metric-value {cls}">{bmod:+d}</span></div>\n'
    if mmod:
        cls = "text-success" if mmod > 0 else "text-danger"
        h += f'<div class="metric-row"><span class="metric-label">Market Modifier</span><span class="metric-value {cls}">{mmod:+d}</span></div>\n'
    if smod:
        cls = "text-success" if smod > 0 else "text-danger"
        h += f'<div class="metric-row"><span class="metric-label">Sector Modifier</span><span class="metric-value {cls}">{smod:+d}</span></div>\n'

    h += '</div>\n</div>\n'

    # Grid-3: Technical, Fundamentals, Volume
    h += '<div class="grid grid-3" style="margin-top: 24px;">\n'

    # Technical indicators
    h += '<div>\n<h4 style="margin-bottom: 12px;">Technical Indicators</h4>\n'
    h += f'<div class="metric-row"><span class="metric-label">Price</span><span class="metric-value">Rs. {price:,.2f}</span></div>\n'
    rsi_cls = _rsi_class(rsi_v)
    h += f'<div class="metric-row"><span class="metric-label">RSI (14)</span><span class="metric-value {rsi_cls}">{_safe(rsi_v, 1)}</span></div>\n'
    macd_cls = "text-success" if (macd_v or 0) > 0 else "text-danger" if (macd_v or 0) < 0 else ""
    h += f'<div class="metric-row"><span class="metric-label">MACD</span><span class="metric-value {macd_cls}">{_safe(macd_v, 2)}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">SMA 20</span><span class="metric-value">{_safe(sma20, 2)}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">SMA 50</span><span class="metric-value">{_safe(sma50, 2)}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">Trend</span><span class="metric-value">{trend}</span></div>\n'
    h += '</div>\n'

    # Fundamentals
    h += '<div>\n<h4 style="margin-bottom: 12px;">Fundamentals</h4>\n'
    h += f'<div class="metric-row"><span class="metric-label">P/E Ratio</span><span class="metric-value">{_safe(pe, 2)}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">P/B Ratio</span><span class="metric-value">{_safe(pbv, 2)}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">EPS</span><span class="metric-value">{_safe(eps, 2, "Rs. ")}</span></div>\n'
    epsg_cls = "text-success" if (eps_g or 0) > 0 else "text-danger" if (eps_g or 0) < 0 else ""
    h += f'<div class="metric-row"><span class="metric-label">EPS Growth</span><span class="metric-value {epsg_cls}">{_safe(eps_g, 1)}%</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">Book Value</span><span class="metric-value">{_safe(bv, 2, "Rs. ")}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">Div Yield</span><span class="metric-value">{_safe(div_y, 2)}%</span></div>\n'
    h += '</div>\n'

    # Volume Analysis
    h += '<div>\n<h4 style="margin-bottom: 12px;">Volume Analysis</h4>\n'
    h += f'<div class="metric-row"><span class="metric-label">Today Vol</span><span class="metric-value">{fmt(vol_today)}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">Avg Vol 20</span><span class="metric-value">{fmt(vol_avg)}</span></div>\n'
    vr_cls = "text-success" if (vol_ratio or 0) > 1.5 else "text-danger" if (vol_ratio or 0) < 0.5 else ""
    h += f'<div class="metric-row"><span class="metric-label">Vol Ratio</span><span class="metric-value {vr_cls}">{_safe(vol_ratio, 2)}x</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">OBV Trend</span><span class="metric-value">{obv}</span></div>\n'
    h += f'<div class="metric-row"><span class="metric-label">MFI</span><span class="metric-value">{_safe(mfi_v, 1)}</span></div>\n'
    h += '</div>\n</div>\n'

    # Strengths & Weaknesses
    if strengths or weaknesses:
        h += '<div class="grid grid-2" style="margin-top: 24px;">\n'
        h += '<div>\n<h4 style="color: var(--success); margin-bottom: 12px;">✓ Strengths</h4>\n'
        h += '<ul style="list-style: none; padding: 0;">\n'
        for s in strengths:
            h += '<li style="padding: 4px 0; padding-left: 20px; position: relative;">'
            h += '<span style="position: absolute; left: 0; color: var(--success);">✓</span>'
            h += f'{s}</li>\n'
        h += '</ul>\n</div>\n'
        h += '<div>\n<h4 style="color: var(--danger); margin-bottom: 12px;">✗ Weaknesses</h4>\n'
        h += '<ul style="list-style: none; padding: 0;">\n'
        for w in weaknesses:
            h += '<li style="padding: 4px 0; padding-left: 20px; position: relative;">'
            h += '<span style="position: absolute; left: 0; color: var(--danger);">✗</span>'
            h += f'{w}</li>\n'
        h += '</ul>\n</div>\n</div>\n'

    h += '</div>\n'
    return h


def write_all_stocks_report(html, output_dir=None):
    """Write combined all-stocks HTML to disk.

    Returns
    -------
    str  — Absolute file path of the written report.
    """
    if output_dir is None:
        output_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"py_analyser_all_stocks_analysis_{date_str}.html"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    return filepath
