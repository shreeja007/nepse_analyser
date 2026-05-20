"""
NEPSE Analytics Engine — HTML Report Generator (v3.0)
Generates the complete dark-theme dashboard HTML matching the reference design.

All sections:
 1. 🔥 Tomorrow's Watchlist (top 10 ranked picks)
 2. 📊 Market Regime + Breadth
 3. 🎯 Trading Signals — Full Table
 4. 🏦 Broker Intelligence & BOOM Stocks
 5. ⚡ Momentum Screener
 6. 📈 Technical Signals
 7. 💼 Fundamental Analysis
 8. 🏢 Sector Rotation
 9. ⚠️ Risk Overview
10. 💰 Dividends & Corporate Actions
11. 🏅 Rankings
12. ⚠️ Circuit Breaker Watch
13. 📰 Research
"""

import os
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════
#  FORMATTING HELPERS
# ═══════════════════════════════════════════════════════════════════════

def fmt(v, decimals=2):
    """Format numeric value with K/M/B suffixes."""
    if v is None:
        return "—"
    try:
        v = float(v)
        if abs(v) >= 1e9:  return f"{v/1e9:.{decimals}f}B"
        if abs(v) >= 1e6:  return f"{v/1e6:.{decimals}f}M"
        if abs(v) >= 1e3:  return f"{v/1e3:.{decimals}f}K"
        return f"{v:,.{decimals}f}"
    except:
        return str(v)


def fmt_price(v):
    """Format as Rs X,XXX.XX."""
    if v is None:
        return "—"
    try:
        return f"Rs {float(v):,.2f}"
    except:
        return str(v)


def color_class(v, invert=False):
    """Return CSS class based on value sign."""
    try:
        v = float(v)
        if invert:
            v = -v
        if v > 0:
            return "text-green"
        if v < 0:
            return "text-red"
    except:
        pass
    return "text-yellow"


def signal_badge(signal):
    """Generate signal badge HTML."""
    signal = signal or "HOLD"
    cls_map = {
        "STRONG BUY":  ("bg-green pulse", "⬆️ STRONG BUY"),
        "BUY":         ("bg-green", "⬆️ BUY"),
        "HOLD":        ("bg-yellow", "➡️ HOLD"),
        "SELL":        ("bg-red", "⬇️ SELL"),
        "STRONG SELL": ("bg-red pulse", "⬇️ STRONG SELL"),
    }
    cls, label = cls_map.get(signal, ("bg-yellow", signal))
    return f'<span class="badge {cls}">{label}</span>'


def confidence_bar(pct):
    """Generate confidence bar HTML."""
    pct = max(0, min(100, int(pct or 0)))
    if pct >= 70:
        fill_cls = "confidence-high"
    elif pct >= 40:
        fill_cls = "confidence-medium"
    else:
        fill_cls = "confidence-low"
    return f'''<div style="font-weight: 600;">{pct}%</div>
<div class="confidence-bar">
<div class="confidence-fill {fill_cls}" style="width: {pct}%"></div>
</div>'''


def composite_color(score):
    """Color class for composite score."""
    if score >= 70:
        return "text-green"
    if score >= 50:
        return "text-yellow"
    return "text-red"


def risk_badge(level):
    """Risk level badge."""
    level = (level or "MEDIUM").upper()
    cls_map = {"HIGH": "bg-red", "MEDIUM": "bg-yellow", "LOW": "bg-green"}
    return f'<span class="badge {cls_map.get(level, "bg-yellow")}">{level}</span>'


def obv_badge(trend):
    """OBV trend badge."""
    trend = (trend or "FLAT").upper()
    cls_map = {"RISING": "bg-green", "FALLING": "bg-red", "FLAT": "bg-yellow"}
    return f'<span class="badge {cls_map.get(trend, "bg-yellow")}">{trend}</span>'


def truncate_reasons(reasons_str, max_reasons=3):
    """Get top N reasons for compact display."""
    if not reasons_str:
        return "—"
    parts = reasons_str.split(" | ")
    # Prioritize ✅ and ❌ over ℹ️
    priority = [p for p in parts if p.startswith("✅") or p.startswith("❌")]
    other = [p for p in parts if p not in priority]
    selected = (priority + other)[:max_reasons]
    return ", ".join(selected)


# ═══════════════════════════════════════════════════════════════════════
#  CSS (Dark Theme — matches dashboard reference)
# ═══════════════════════════════════════════════════════════════════════

CSS = """
:root {
    --primary: #2563eb;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --dark: #1e293b;
    --light: #f8fafc;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #e2e8f0; margin: 0; padding: 20px; min-height: 100vh;
}
.container { max-width: 1400px; margin: 0 auto; }
.header { text-align: center; margin-bottom: 30px; padding: 20px; }
.header h1 {
    margin: 0; font-size: 2.5rem;
    background: linear-gradient(135deg, #60a5fa, #34d399);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.header p { color: #94a3b8; margin: 10px 0 0; }
.card {
    background: rgba(30, 41, 59, 0.8); backdrop-filter: blur(10px);
    border: 1px solid rgba(148, 163, 184, 0.1); border-radius: 16px;
    padding: 24px; margin-bottom: 24px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);
}
.card-header {
    display: flex; align-items: center; margin-bottom: 20px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.2); padding-bottom: 15px;
}
.card-icon { font-size: 1.75rem; margin-right: 12px; }
.card-title { font-size: 1.3rem; font-weight: 700; color: #f1f5f9; margin: 0; }
.signal-card {
    background: linear-gradient(135deg, rgba(34, 197, 94, 0.1) 0%, rgba(30, 41, 59, 0.9) 100%);
    border: 1px solid rgba(34, 197, 94, 0.3);
}
.sell-card {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(30, 41, 59, 0.9) 100%);
    border: 1px solid rgba(239, 68, 68, 0.3);
}
.boom-card {
    background: linear-gradient(135deg, rgba(245, 158, 11, 0.1) 0%, rgba(30, 41, 59, 0.9) 100%);
    border: 1px solid rgba(245, 158, 11, 0.3);
}
.grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
@media(max-width: 1024px) { .grid-3 { grid-template-columns: repeat(2, 1fr); } }
@media(max-width: 768px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
.market-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 30px; }
@media(max-width: 768px) { .market-stats { grid-template-columns: repeat(2, 1fr); } }
.stat-box {
    background: rgba(30, 41, 59, 0.6); padding: 20px; border-radius: 12px;
    text-align: center; border: 1px solid rgba(148, 163, 184, 0.1);
}
.stat-val { font-size: 1.75rem; font-weight: 800; color: #60a5fa; }
.stat-lbl { font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; margin-top: 8px; letter-spacing: 0.05em; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th {
    text-align: left; padding: 14px 12px; background: rgba(15, 23, 42, 0.5);
    color: #94a3b8; font-weight: 600; font-size: 0.75rem;
    text-transform: uppercase; letter-spacing: 0.05em;
    cursor: pointer; user-select: none; white-space: nowrap;
    border-bottom: 2px solid rgba(148, 163, 184, 0.2);
}
th:hover { color: #e2e8f0; }
th::after { content: '⇅'; margin-left: 4px; opacity: .3; }
td { padding: 14px 12px; border-bottom: 1px solid rgba(148, 163, 184, 0.1); }
tr:last-child td { border-bottom: none; }
tr:hover { background: rgba(148, 163, 184, 0.05); }
.badge { padding: 6px 12px; border-radius: 8px; font-size: 0.75rem; font-weight: 700; display: inline-block; }
.bg-green { background: rgba(34, 197, 94, 0.2); color: #22c55e; }
.bg-red { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
.bg-blue { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
.bg-yellow { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
.bg-purple { background: rgba(168, 85, 247, 0.2); color: #a855f7; }
.text-green { color: #22c55e; font-weight: 600; }
.text-red { color: #ef4444; font-weight: 600; }
.text-yellow { color: #fbbf24; font-weight: 600; }
.text-muted { color: #64748b; }
.symbol { font-weight: 700; color: #f1f5f9; }
.price { color: #e2e8f0; }
.confidence-bar { width: 100%; height: 8px; background: rgba(148, 163, 184, 0.2); border-radius: 4px; overflow: hidden; margin-top: 4px; }
.confidence-fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }
.confidence-high { background: linear-gradient(90deg, #22c55e, #34d399); }
.confidence-medium { background: linear-gradient(90deg, #fbbf24, #f59e0b); }
.confidence-low { background: linear-gradient(90deg, #ef4444, #f87171); }
.vol-bar-bg { width: 80px; height: 8px; background: rgba(148, 163, 184, 0.2); border-radius: 4px; display: inline-block; }
.vol-bar-fill { height: 100%; background: linear-gradient(90deg, #60a5fa, #3b82f6); border-radius: 4px; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
.pulse { animation: pulse 2s infinite; }
.tabs {
    display: flex; gap: 4px; padding: 8px 16px; background: rgba(30, 41, 59, 0.8);
    border-bottom: 1px solid rgba(148, 163, 184, 0.1);
    overflow-x: auto; flex-wrap: nowrap; position: sticky; top: 0; z-index: 100;
    backdrop-filter: blur(10px); border-radius: 12px; margin-bottom: 20px;
}
.tab {
    padding: 8px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500;
    white-space: nowrap; color: #94a3b8; border: 1px solid transparent; transition: all .2s;
}
.tab:hover { color: #e2e8f0; background: rgba(148, 163, 184, 0.1); }
.tab.active { color: #22c55e; background: rgba(34, 197, 94, 0.1); border-color: rgba(34, 197, 94, 0.3); }
.section { display: none; animation: fadeIn .3s ease; }
.section.active { display: block; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.range-card {
    background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 10px; padding: 14px; margin-top: 8px; font-size: 0.85rem;
}
.range-card .rc-row { display: flex; justify-content: space-between; padding: 3px 0; }
.range-card .rc-label { color: #94a3b8; }
.range-card .rc-value { font-weight: 600; }
.footer { text-align: center; padding: 20px; color: #64748b; font-size: 0.85rem; }
.reason-text { font-size: 0.8rem; color: #94a3b8; max-width: 350px; white-space: normal; line-height: 1.4; }
"""

# ═══════════════════════════════════════════════════════════════════════
#  JAVASCRIPT (Tab switching + table sorting)
# ═══════════════════════════════════════════════════════════════════════

JS = """
function showTab(id) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    var tab = document.querySelector('[data-tab="' + id + '"]');
    if (tab) tab.classList.add('active');
}
function sortTable(th) {
    var table = th.closest('table'), tbody = table.querySelector('tbody'),
        rows = Array.from(tbody.querySelectorAll('tr')),
        idx = Array.from(th.parentNode.children).indexOf(th),
        asc = th.dataset.sort !== 'asc';
    th.parentNode.querySelectorAll('th').forEach(t => delete t.dataset.sort);
    th.dataset.sort = asc ? 'asc' : 'desc';
    rows.sort(function(a, b) {
        var av = a.children[idx].textContent.trim().replace(/[,%BKMRS₨ ]/g, ''),
            bv = b.children[idx].textContent.trim().replace(/[,%BKMRS₨ ]/g, '');
        var an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    rows.forEach(r => tbody.appendChild(r));
}
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('th').forEach(th => th.addEventListener('click', function() { sortTable(this); }));
    showTab('watchlist');
});
"""

# ═══════════════════════════════════════════════════════════════════════
#  TAB DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════

TABS = [
    ("watchlist",    "🔥 Watchlist"),
    ("overview",     "📊 Overview"),
    ("signals",      "🎯 Signals"),
    ("broker",       "🏦 Broker Intel"),
    ("momentum",     "⚡ Momentum"),
    ("technicals",   "📈 Technicals"),
    ("fundamentals", "💼 Fundamentals"),
    ("sectors",      "🏢 Sectors"),
    ("risk",         "⚠️ Risk"),
    ("dividends",    "💰 Dividends"),
    ("rankings",     "🏅 Rankings"),
    ("gainers",      "🏆 Gainers/Losers"),
    ("circuit",      "⚠️ Circuit Watch"),
    ("research",     "📰 Research"),
]


# ═══════════════════════════════════════════════════════════════════════
#  MAIN HTML BUILDER
# ═══════════════════════════════════════════════════════════════════════

def build_html(data):
    """Build complete HTML dashboard from analysis data."""
    print("\n📝 Generating HTML report...")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    regime = data.get("regime", {"regime": "NEUTRAL", "factor": 1.0, "chg": 0})
    ov = data.get("overview", {})
    sm = ov.get("summary", {})

    # Tab navigation
    tabs_html = ""
    for tid, label in TABS:
        tabs_html += f'<div class="tab" data-tab="{tid}" onclick="showTab(\'{tid}\')">{label}</div>\n'

    sections = []

    # ══════════════════════════════════════════════════════════════
    # 1. WATCHLIST
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_watchlist_section(data))

    # ══════════════════════════════════════════════════════════════
    # 2. OVERVIEW
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_overview_section(data, regime))

    # ══════════════════════════════════════════════════════════════
    # 3. TRADING SIGNALS
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_signals_section(data))

    # ══════════════════════════════════════════════════════════════
    # 4. BROKER INTELLIGENCE
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_broker_section(data))

    # ══════════════════════════════════════════════════════════════
    # 5. MOMENTUM
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_momentum_section(data))

    # ══════════════════════════════════════════════════════════════
    # 6. TECHNICALS
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_technicals_section(data))

    # ══════════════════════════════════════════════════════════════
    # 7. FUNDAMENTALS
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_fundamentals_section(data))

    # ══════════════════════════════════════════════════════════════
    # 8. SECTORS
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_sectors_section(data))

    # ══════════════════════════════════════════════════════════════
    # 9. RISK
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_risk_section(data))

    # ══════════════════════════════════════════════════════════════
    # 10. DIVIDENDS
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_dividends_section(data))

    # ══════════════════════════════════════════════════════════════
    # 11. RANKINGS
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_rankings_section(data))

    # ══════════════════════════════════════════════════════════════
    # 12. GAINERS / LOSERS
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_gainers_section(data))

    # ══════════════════════════════════════════════════════════════
    # 13. CIRCUIT BREAKER WATCH
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_circuit_section(data))

    # ══════════════════════════════════════════════════════════════
    # 14. RESEARCH
    # ══════════════════════════════════════════════════════════════
    sections.append(_build_research_section(data))

    sections_html = "\n".join(sections)

    r_cls = regime["regime"].lower()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEPSE Trading Assistant v3 — {now}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🎯 NEPSE Trading Assistant</h1>
        <p>AI-Powered Technical Analysis • Generated: {now}
        &nbsp; <span class="badge {'bg-green' if r_cls == 'bullish' else 'bg-red' if r_cls == 'bearish' else 'bg-yellow'}">{regime['regime']} MARKET ({regime['chg']:+.2f}%)</span></p>
    </div>
    <div class="tabs">{tabs_html}</div>
    {sections_html}
    <div class="footer">
        NEPSE Analytics Engine v3.0 — RSI 80/20 NEPSE Calibrated |
        ATR-Based Risk Management | Broker Intelligence | Generated: {now}
    </div>
</div>
<script>{JS}</script>
</body>
</html>"""
    return html


# ═══════════════════════════════════════════════════════════════════════
#  SECTION BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def _build_watchlist_section(data):
    """🔥 Tomorrow's Watchlist — Ready to Execute."""
    watchlist = data.get("watchlist", [])
    h = '<div id="watchlist" class="section active">\n'
    h += '<div class="card signal-card">\n'
    h += '<div class="card-header"><span class="card-icon">🔥</span><h2 class="card-title">Tomorrow\'s Watchlist — Ready to Execute</h2></div>\n'

    if not watchlist:
        h += '<p class="text-muted">No stocks passed all filters (liquidity, circuit, trend, R:R ≥ 2.0) today.</p>\n'
    else:
        h += '<table><thead><tr>'
        h += '<th>#</th><th>Symbol</th><th>LTP</th><th>Signal</th><th>Confidence</th>'
        h += '<th>Entry</th><th>Stop Loss</th><th>Target 1</th><th>Target 2</th><th>R:R</th>'
        h += '<th>Composite</th><th>Top Reasons</th><th>Boom</th>'
        h += '</tr></thead><tbody>\n'

        for i, s in enumerate(watchlist, 1):
            boom_flag = "🔥" if s.get("asym_score", 0) > 65 else ""
            extreme = " 🚀" if s.get("extreme_momentum") else ""
            comp_cls = composite_color(s.get("composite", 0))
            reasons_short = truncate_reasons(s.get("reasons", ""), 3)
            atr_val = float(s.get("atr") or 0)
            entry_lo = s["price"] - 0.5 * atr_val if atr_val > 0 else s["price"] * 0.995
            entry_hi = s["price"] + 0.5 * atr_val if atr_val > 0 else s["price"] * 1.005

            h += f'''<tr>
<td>{i}</td>
<td><span class="symbol">{s["symbol"]}</span></td>
<td class="price">{fmt_price(s["price"])}</td>
<td>{signal_badge(s.get("signal", "HOLD"))}</td>
<td>{confidence_bar(s.get("confidence", 0))}</td>
<td class="price">{fmt_price(entry_lo)} – {fmt_price(entry_hi)}</td>
<td class="text-red">{fmt_price(s.get("stop_loss"))}</td>
<td class="text-green">{fmt_price(s.get("target1"))}</td>
<td class="text-green">{fmt_price(s.get("target2"))}</td>
<td><span class="badge bg-blue">{s.get("rr_ratio", 0):.1f}:1</span></td>
<td><span class="{comp_cls}">{s.get("composite", 0):.0f}{extreme}</span></td>
<td><span class="reason-text">{reasons_short}</span></td>
<td>{boom_flag}</td>
</tr>\n'''

        h += '</tbody></table>\n'

        # Range cards for top 3
        h += '<div class="grid-3" style="margin-top: 16px;">\n'
        for s in watchlist[:3]:
            atr_val = float(s.get("atr") or 0)
            entry_lo = s["price"] - 0.5 * atr_val if atr_val > 0 else s["price"] * 0.995
            entry_hi = s["price"] + 0.5 * atr_val if atr_val > 0 else s["price"] * 1.005
            h += f'''<div class="range-card">
<div style="font-weight:700;color:#f1f5f9;margin-bottom:8px;">{s["symbol"]} — {signal_badge(s.get("signal"))}</div>
<div class="rc-row"><span class="rc-label">LTP</span><span class="rc-value">{fmt_price(s["price"])}</span></div>
<div class="rc-row"><span class="rc-label">Entry Zone</span><span class="rc-value">{fmt_price(entry_lo)} – {fmt_price(entry_hi)}</span></div>
<div class="rc-row"><span class="rc-label">Stop Loss</span><span class="rc-value text-red">{fmt_price(s.get("stop_loss"))}</span></div>
<div class="rc-row"><span class="rc-label">Target 1</span><span class="rc-value text-green">{fmt_price(s.get("target1"))}</span></div>
<div class="rc-row"><span class="rc-label">Target 2</span><span class="rc-value text-green">{fmt_price(s.get("target2"))}</span></div>
<div class="rc-row"><span class="rc-label">R:R Ratio</span><span class="rc-value">{s.get("rr_ratio", 0):.1f}:1</span></div>
<div class="rc-row"><span class="rc-label">ATR(14)</span><span class="rc-value">{fmt_price(s.get("atr"))}</span></div>
<div class="rc-row"><span class="rc-label">Position Size</span><span class="rc-value">{s.get("position_size", 0)} shares</span></div>
</div>\n'''
        h += '</div>\n'

    h += '</div></div>\n'
    return h


def _build_overview_section(data, regime):
    """📊 Market Overview + Breadth."""
    ov = data.get("overview", {})
    sm = ov.get("summary", {})
    indices = ov.get("indices", [])
    subs = ov.get("sub_indices", [])
    breadth = ov.get("breadth", {})

    nepse_idx = next((i for i in indices if i.get("index_name") == "NEPSE"), {})
    idx_val = fmt(nepse_idx.get("current_value"), 2) if nepse_idx else "—"
    idx_chg = nepse_idx.get("change_points", 0)
    idx_pct = nepse_idx.get("change_percent", 0)

    adv = breadth.get("advances", 0)
    dec = breadth.get("declines", 0)
    ad_ratio = round(adv / dec, 2) if dec > 0 else 0

    # Breadth classification
    if ad_ratio > 1.5:
        breadth_label = "VERY BULLISH"
        breadth_cls = "text-green"
    elif ad_ratio > 1:
        breadth_label = "BULLISH"
        breadth_cls = "text-green"
    elif ad_ratio > 0.5:
        breadth_label = "BEARISH"
        breadth_cls = "text-red"
    else:
        breadth_label = "VERY BEARISH"
        breadth_cls = "text-red"

    total_syms = adv + dec + breadth.get("unchanged", 0)

    h = '<div id="overview" class="section">\n'

    # Market stats cards
    h += '<div class="market-stats">\n'
    h += f'''<div class="stat-box"><div class="stat-val">{total_syms}</div><div class="stat-lbl">Active Symbols</div></div>
<div class="stat-box"><div class="stat-val {color_class(idx_pct)}">{adv} : {dec}</div><div class="stat-lbl">Advancers / Decliners</div></div>
<div class="stat-box"><div class="stat-val">Rs {fmt(sm.get("total_turnover"))}</div><div class="stat-lbl">Total Turnover</div></div>
<div class="stat-box"><div class="stat-val {breadth_cls}">{breadth_label}</div><div class="stat-lbl">Market Breadth (A/D: {ad_ratio})</div></div>
<div class="stat-box"><div class="stat-val {color_class(idx_pct)}">{idx_pct:+.2f}%</div><div class="stat-lbl">NEPSE Index Change</div></div>
<div class="stat-box"><div class="stat-val">{idx_val}</div><div class="stat-lbl">NEPSE Index</div></div>
<div class="stat-box"><div class="stat-val">{fmt(sm.get("total_traded_shares"), 0)}</div><div class="stat-lbl">Traded Shares</div></div>
<div class="stat-box"><div class="stat-val">Rs {fmt(sm.get("total_market_cap"))}</div><div class="stat-lbl">Market Cap</div></div>
'''
    h += '</div>\n'

    # Market Indices table
    h += '<div class="card"><div class="card-header"><span class="card-icon">📊</span><h2 class="card-title">Market Indices</h2></div>\n'
    h += '<table><thead><tr><th>Index</th><th>Value</th><th>Change Pts</th><th>Change %</th></tr></thead><tbody>\n'
    for i in indices:
        c = color_class(i.get("change_percent", 0))
        h += f'<tr><td>{i["index_name"]}</td><td>{fmt(i.get("current_value"))}</td>'
        h += f'<td class="{c}">{fmt(i.get("change_points"))}</td>'
        h += f'<td class="{c}">{fmt(i.get("change_percent"))}%</td></tr>\n'
    h += '</tbody></table></div>\n'

    # Sub-Indices table
    h += '<div class="card"><div class="card-header"><span class="card-icon">📈</span><h2 class="card-title">Sub-Indices</h2></div>\n'
    h += '<table><thead><tr><th>Index</th><th>Value</th><th>Change Pts</th><th>Change %</th></tr></thead><tbody>\n'
    for s in subs:
        c = color_class(s.get("percent_change", 0))
        h += f'<tr><td>{s["index_name"]}</td><td>{fmt(s.get("current_value"))}</td>'
        h += f'<td class="{c}">{fmt(s.get("points_change"))}</td>'
        h += f'<td class="{c}">{fmt(s.get("percent_change"))}%</td></tr>\n'
    h += '</tbody></table></div>\n'

    h += '</div>\n'
    return h


def _build_signals_section(data):
    """🎯 Trading Signals — Full Table."""
    signals = data.get("trading_signals", [])
    h = '<div id="signals" class="section">\n'
    h += '<div class="card"><div class="card-header"><span class="card-icon">🎯</span>'
    h += '<h2 class="card-title">Trading Signals (RSI + MACD + Trend Analysis)</h2></div>\n'
    h += '<table><thead><tr>'
    h += '<th>Symbol</th><th>LTP</th><th>Signal</th><th>Confidence</th>'
    h += '<th>Entry</th><th>Stop Loss</th><th>Target</th><th>R:R</th>'
    h += '<th>RSI</th><th>MACD</th><th>Stoch</th><th>Key Reasons</th>'
    h += '</tr></thead><tbody>\n'

    for s in signals[:100]:
        rsi_cls = "text-muted"
        if s.get("rsi") and s["rsi"] > 80:
            rsi_cls = "text-red"
        elif s.get("rsi") and s["rsi"] < 20:
            rsi_cls = "text-green"

        stoch_k = s.get("stoch_k")
        stoch_d = s.get("stoch_d")
        stoch_str = f"{stoch_k:.0f}/{stoch_d:.0f}" if stoch_k is not None and stoch_d is not None else "—"
        stoch_cls = "text-green" if stoch_k and stoch_k < 20 else ("text-red" if stoch_k and stoch_k > 80 else "text-muted")

        reasons_short = truncate_reasons(s.get("reasons", ""), 4)
        atr_val = float(s.get("atr") or 0)
        entry_lo = s["price"] - 0.5 * atr_val if atr_val > 0 else s["price"] * 0.995
        entry_hi = s["price"] + 0.5 * atr_val if atr_val > 0 else s["price"] * 1.005

        h += f'''<tr>
<td><span class="symbol">{s["symbol"]}</span></td>
<td class="price">{fmt_price(s["price"])}</td>
<td>{signal_badge(s.get("signal"))}</td>
<td>{confidence_bar(s.get("confidence", 0))}</td>
<td class="price">{fmt(entry_lo)} – {fmt(entry_hi)}</td>
<td class="text-red">{fmt(s.get("stop_loss"))}</td>
<td class="text-green">{fmt(s.get("target1"))}</td>
<td><span class="badge bg-blue">{s.get("rr_ratio", 0):.1f}:1</span></td>
<td><span class="{rsi_cls}">{s.get("rsi") or "—"}</span></td>
<td><span class="{color_class(s.get("macd_hist"))}">{fmt(s.get("macd_hist"))}</span></td>
<td><span class="{stoch_cls}">{stoch_str}</span></td>
<td><span class="reason-text">{reasons_short}</span></td>
</tr>\n'''

    h += '</tbody></table></div></div>\n'
    return h


def _build_broker_section(data):
    """🏦 Broker Intelligence & BOOM Stocks."""
    boom = data.get("boom_stocks", [])
    fl = data.get("floorsheet", {})
    fl_days = data.get("floorsheet_days", 0)

    h = '<div id="broker" class="section">\n'

    # BOOM Stocks
    h += '<div class="card boom-card"><div class="card-header"><span class="card-icon">🔥</span>'
    h += '<h2 class="card-title">Smart Money BOOM Stocks</h2></div>\n'
    if fl_days > 0:
        h += f'<p style="color:#fbbf24;font-size:0.8rem;margin-bottom:12px;">⚠️ Based on {fl_days} day{"s" if fl_days != 1 else ""} of floorsheet data. Confidence improves with more data (ideal: 30 days).</p>\n'

    if not boom:
        h += '<p class="text-muted">No stocks met all BOOM criteria today (Asymmetry > 65, consistent buyer, vol ratio ≥ 1.3, RSI 40-75, above SMA20).</p>\n'
    else:
        h += '<table><thead><tr>'
        h += '<th>Symbol</th><th>LTP</th><th>Asymmetry</th><th>Top Buyers</th>'
        h += '<th>Sessions</th><th>Vol Ratio</th><th>RSI</th><th>Signal</th>'
        h += '</tr></thead><tbody>\n'
        for b in boom:
            buyers_str = ", ".join([f"{x['broker_name']} ({x['sessions']}d)"
                                    for x in b.get("top_buyers", [])[:3]])
            max_sessions = max([x["sessions"] for x in b.get("top_buyers", [])[:3]], default=0)
            h += f'''<tr>
<td><span class="symbol">{b["symbol"]}</span></td>
<td class="price">{fmt_price(b["price"])}</td>
<td><span class="badge bg-green">{b["asym_score"]:.0f}</span></td>
<td><span class="text-muted" style="font-size:0.8rem">{buyers_str}</span></td>
<td>{max_sessions}</td>
<td>{b["vol_ratio"]:.2f}x</td>
<td>{b["rsi"]}</td>
<td><span class="badge bg-yellow">{b["signal"]}</span></td>
</tr>\n'''
        h += '</tbody></table>\n'

    h += '</div>\n'

    # Top Brokers
    h += '<div class="grid-2">\n'
    h += '<div class="card"><div class="card-header"><span class="card-icon">🟢</span>'
    h += '<h2 class="card-title">Top Buyer Brokers</h2></div>\n'
    h += '<table><thead><tr><th>#</th><th>Broker</th><th>Trades</th><th>Amount</th><th>Symbols</th></tr></thead><tbody>\n'
    for i, b in enumerate(fl.get("top_buyers", []), 1):
        h += f'<tr><td>{i}</td><td>{b["broker"]}</td><td>{fmt(b.get("trades"),0)}</td>'
        h += f'<td>Rs {fmt(b.get("total_amt"))}</td><td>{b.get("symbols_traded","—")}</td></tr>\n'
    h += '</tbody></table></div>\n'

    h += '<div class="card"><div class="card-header"><span class="card-icon">🔴</span>'
    h += '<h2 class="card-title">Top Seller Brokers</h2></div>\n'
    h += '<table><thead><tr><th>#</th><th>Broker</th><th>Trades</th><th>Amount</th><th>Symbols</th></tr></thead><tbody>\n'
    for i, s in enumerate(fl.get("top_sellers", []), 1):
        h += f'<tr><td>{i}</td><td>{s["broker"]}</td><td>{fmt(s.get("trades"),0)}</td>'
        h += f'<td>Rs {fmt(s.get("total_amt"))}</td><td>{s.get("symbols_traded","—")}</td></tr>\n'
    h += '</tbody></table></div>\n'
    h += '</div>\n'

    # Most traded
    h += '<div class="card"><div class="card-header"><span class="card-icon">📊</span>'
    h += '<h2 class="card-title">Most Traded Securities</h2></div>\n'
    h += '<table><thead><tr><th>#</th><th>Symbol</th><th>Trades</th><th>Qty</th><th>Amount</th>'
    h += '<th>Min Rate</th><th>Max Rate</th><th>Avg Rate</th></tr></thead><tbody>\n'
    for i, m in enumerate(fl.get("most_traded", []), 1):
        h += f'<tr><td>{i}</td><td><span class="symbol">{m["symbol"]}</span></td>'
        h += f'<td>{fmt(m.get("trades"),0)}</td><td>{fmt(m.get("total_qty"),0)}</td>'
        h += f'<td>Rs {fmt(m.get("total_amt"))}</td>'
        h += f'<td>{fmt(m.get("min_rate"))}</td><td>{fmt(m.get("max_rate"))}</td>'
        h += f'<td>{fmt(m.get("avg_rate"))}</td></tr>\n'
    h += '</tbody></table></div>\n'

    h += '</div>\n'
    return h


def _build_momentum_section(data):
    """⚡ Momentum Screener."""
    mom = data.get("momentum", [])
    h = '<div id="momentum" class="section">\n'
    h += '<div class="card"><div class="card-header"><span class="card-icon">⚡</span>'
    h += '<h2 class="card-title">Momentum Leaders — Top 50</h2></div>\n'
    h += '<p style="color:#94a3b8;font-size:0.85rem;margin-bottom:12px;">Score = 0.4×ROC₂₀ + 0.3×RSI₁₄ + 0.3×Volume Ratio (min-max normalized to 0–100)</p>\n'
    h += '<table><thead><tr>'
    h += '<th>#</th><th>Symbol</th><th>LTP</th><th>RSI(14)</th><th>MACD</th><th>MACD Hist</th>'
    h += '<th>Stoch %K</th><th>Stoch %D</th><th>OBV</th>'
    h += '<th>ROC 20D</th><th>ROC 60D</th><th>Vol Ratio</th><th>Score</th>'
    h += '</tr></thead><tbody>\n'

    for i, m in enumerate(mom, 1):
        extreme = " 🚀" if m.get("extreme_momentum") else ""
        h += f'''<tr>
<td>{i}</td>
<td><span class="symbol">{m["symbol"]}</span></td>
<td class="price">{fmt_price(m["price"])}</td>
<td>{m.get("rsi") or "—"}</td>
<td class="{color_class(m.get("macd_val"))}">{fmt(m.get("macd_val"))}</td>
<td class="{color_class(m.get("macd_hist"))}">{fmt(m.get("macd_hist"))}</td>
<td>{m.get("stoch_k") or "—"}</td>
<td>{m.get("stoch_d") or "—"}</td>
<td>{obv_badge(m.get("obv_trend"))}</td>
<td class="{color_class(m.get("roc_20"))}">{m.get("roc_20") or "—"}%</td>
<td class="{color_class(m.get("roc_60"))}">{m.get("roc_60") or "—"}%</td>
<td>{m.get("vol_ratio", 0):.2f}x</td>
<td><b class="{composite_color(m.get("momentum_score", 0))}">{m.get("momentum_score", 0):.0f}{extreme}</b></td>
</tr>\n'''

    h += '</tbody></table></div></div>\n'
    return h


def _build_technicals_section(data):
    """📈 Technical Signals."""
    tech = data.get("technicals", [])
    h = '<div id="technicals" class="section">\n'
    h += '<div class="card"><div class="card-header"><span class="card-icon">📈</span>'
    h += '<h2 class="card-title">Technical Signals</h2></div>\n'
    h += '<table><thead><tr>'
    h += '<th>#</th><th>Symbol</th><th>LTP</th><th>SMA20</th><th>SMA50</th>'
    h += '<th>BB%</th><th>ATR</th><th>Stop Loss</th><th>Target 1</th>'
    h += '<th>52W Range%</th><th>Breakout</th><th>Cross</th><th>Patterns</th><th>Signal</th>'
    h += '</tr></thead><tbody>\n'

    for i, t in enumerate(tech, 1):
        brk = ""
        if t.get("breakout_52w"):
            brk = '<span class="badge bg-blue">52W HIGH</span>'
        elif t.get("breakout_candidate"):
            brk = '<span class="badge bg-purple">BREAKOUT</span>'
        pat = ", ".join(t.get("patterns", [])) if t.get("patterns") else "—"

        h += f'''<tr>
<td>{i}</td>
<td><span class="symbol">{t["symbol"]}</span></td>
<td class="price">{fmt_price(t["price"])}</td>
<td>{fmt(t.get("sma20"))}</td>
<td>{fmt(t.get("sma50"))}</td>
<td>{t.get("bb_pct") or "—"}%</td>
<td>{fmt(t.get("atr"))}</td>
<td class="text-red">{fmt(t.get("stop_loss"))}</td>
<td class="text-green">{fmt(t.get("target1"))}</td>
<td>{t.get("range_pct") or "—"}%</td>
<td>{brk or "—"}</td>
<td>{t.get("cross", "—")}</td>
<td><span class="text-muted">{pat}</span></td>
<td>{signal_badge(t.get("signal"))}</td>
</tr>\n'''

    h += '</tbody></table></div></div>\n'
    return h


def _build_fundamentals_section(data):
    """💼 Fundamental Analysis."""
    fund_dict = data.get("fundamentals", {})
    # Sort by fund_score descending
    fund = sorted(fund_dict.values(), key=lambda x: x.get("fund_score", 0), reverse=True)[:50]

    h = '<div id="fundamentals" class="section">\n'
    h += '<div class="card"><div class="card-header"><span class="card-icon">💼</span>'
    h += '<h2 class="card-title">Fundamental Analysis — Top 50</h2></div>\n'
    h += '<table><thead><tr>'
    h += '<th>#</th><th>Symbol</th><th>Sector</th><th>EPS</th><th>P/E</th>'
    h += '<th>Book Value</th><th>P/BV</th><th>ROE%</th><th>Div Yield%</th>'
    h += '<th>Net Profit</th><th>FY / Qtr</th><th>Score</th>'
    h += '</tr></thead><tbody>\n'

    for i, f in enumerate(fund, 1):
        # Try to get LTP from all_analysis
        all_a = data.get("all_analysis", {})
        ltp = all_a.get(f["symbol"], {}).get("price")

        h += f'''<tr>
<td>{i}</td>
<td><span class="symbol">{f["symbol"]}</span></td>
<td>{f.get("sector") or "—"}</td>
<td class="{color_class(f["eps"])}">{fmt(f["eps"])}</td>
<td>{fmt(f["pe_ratio"])}</td>
<td>{fmt(f["book_value"])}</td>
<td>{fmt(f.get("pbv"))}</td>
<td class="{color_class(f.get("roe"))}">{fmt(f.get("roe"))}%</td>
<td class="{color_class(f.get("div_yield"))}">{fmt(f.get("div_yield"))}%</td>
<td>{fmt(f.get("net_profit"))}</td>
<td>{f.get("fiscal_year", "—")} {(f.get("quarter") or "")[:10]}</td>
<td><b>{f.get("fund_score", 0)}</b></td>
</tr>\n'''

    h += '</tbody></table></div></div>\n'
    return h


def _build_sectors_section(data):
    """🏢 Sector Rotation."""
    sect = data.get("sectors", {})
    sector_breadth = data.get("sector_breadth", {})

    h = '<div id="sectors" class="section">\n'

    # Sector breadth
    if sector_breadth:
        h += '<div class="card"><div class="card-header"><span class="card-icon">📊</span>'
        h += '<h2 class="card-title">Sector Breadth (% above SMA50)</h2></div>\n'
        h += '<table><thead><tr><th>Sector</th><th>Stocks</th><th>Above SMA50</th><th>%</th><th>Trend</th></tr></thead><tbody>\n'
        sorted_sb = sorted(sector_breadth.items(), key=lambda x: x[1].get("pct", 0), reverse=True)
        for sector, sb in sorted_sb:
            trend_badge = '<span class="badge bg-green">UPTREND</span>' if sb.get("uptrend") else '<span class="badge bg-red">DOWNTREND</span>'
            h += f'<tr><td>{sector}</td><td>{sb["total"]}</td><td>{sb["above_sma50"]}</td>'
            h += f'<td class="{color_class(sb["pct"] - 50)}">{sb["pct"]:.1f}%</td><td>{trend_badge}</td></tr>\n'
        h += '</tbody></table></div>\n'

    h += '<div class="grid-2">\n'

    # Sub-Index Performance
    h += '<div class="card"><div class="card-header"><span class="card-icon">📈</span>'
    h += '<h2 class="card-title">Sub-Index Performance</h2></div>\n'
    h += '<table><thead><tr><th>Index</th><th>Value</th><th>Change</th><th>%</th></tr></thead><tbody>\n'
    for s in sect.get("sub_indices", []):
        c = color_class(s.get("percent_change", 0))
        h += f'<tr><td>{s["index_name"]}</td><td>{fmt(s.get("current_value"))}</td>'
        h += f'<td class="{c}">{fmt(s.get("points_change"))}</td>'
        h += f'<td class="{c}">{fmt(s.get("percent_change"))}%</td></tr>\n'
    h += '</tbody></table></div>\n'

    # Sector Turnover
    h += '<div class="card"><div class="card-header"><span class="card-icon">💰</span>'
    h += '<h2 class="card-title">Sector Turnover</h2></div>\n'
    h += '<table><thead><tr><th>Sector</th><th>Turnover</th><th>Volume</th><th>Stocks</th><th>Avg Chg%</th></tr></thead><tbody>\n'
    for s in sect.get("sectors", []):
        c = color_class(s.get("avg_change", 0))
        h += f'<tr><td>{s["sector"]}</td><td>Rs {fmt(s.get("total_turnover"))}</td>'
        h += f'<td>{fmt(s.get("total_volume"),0)}</td><td>{s["stock_count"]}</td>'
        h += f'<td class="{c}">{fmt(s.get("avg_change"))}%</td></tr>\n'
    h += '</tbody></table></div>\n'
    h += '</div>\n'

    h += '</div>\n'
    return h


def _build_risk_section(data):
    """⚠️ Risk Overview."""
    risk = data.get("risk", [])
    h = '<div id="risk" class="section">\n'
    h += '<div class="card"><div class="card-header"><span class="card-icon">⚠️</span>'
    h += '<h2 class="card-title">Risk Overview — Most Volatile Stocks</h2></div>\n'
    h += '<table><thead><tr>'
    h += '<th>#</th><th>Symbol</th><th>LTP</th><th>Vol 20D</th><th>Max DD%</th>'
    h += '<th>52W Range%</th><th>52W High</th><th>52W Low</th><th>ATR</th><th>Risk</th>'
    h += '</tr></thead><tbody>\n'

    for i, r in enumerate(risk, 1):
        rng = round((r.get("hi52", 0) - r.get("lo52", 0)) / r.get("lo52", 1) * 100, 1) if r.get("lo52", 0) > 0 else 0
        h += f'''<tr>
<td>{i}</td>
<td><span class="symbol">{r["symbol"]}</span></td>
<td class="price">{fmt_price(r["price"])}</td>
<td>{r.get("vol_20d", 0)}</td>
<td class="text-red">{r.get("max_drawdown", 0)}%</td>
<td>{rng}%</td>
<td>{fmt(r.get("hi52"))}</td>
<td>{fmt(r.get("lo52"))}</td>
<td>{fmt(r.get("atr"))}</td>
<td>{risk_badge(r.get("risk_level"))}</td>
</tr>\n'''

    h += '</tbody></table></div></div>\n'
    return h


def _build_dividends_section(data):
    """💰 Dividends & Corporate Actions."""
    da = data.get("dividends_actions", {})
    h = '<div id="dividends" class="section">\n'
    h += '<div class="grid-2">\n'

    # Dividends
    h += '<div class="card"><div class="card-header"><span class="card-icon">💰</span>'
    h += '<h2 class="card-title">Recent Dividends</h2></div>\n'
    h += '<table><thead><tr><th>Symbol</th><th>FY</th><th>Bonus%</th><th>Cash%</th><th>Book Close</th><th>Sector</th></tr></thead><tbody>\n'
    for d in da.get("dividends", [])[:25]:
        h += f'''<tr><td><span class="symbol">{d["symbol"]}</span></td>
<td>{d.get("fiscal_year","—")}</td>
<td class="text-green">{fmt(d.get("bonus_share_percent"))}%</td>
<td class="text-green">{fmt(d.get("cash_dividend_percent"))}%</td>
<td>{d.get("book_close_date","—")}</td>
<td>{d.get("sector_name","—")}</td></tr>\n'''
    h += '</tbody></table></div>\n'

    # Corporate Actions
    h += '<div class="card"><div class="card-header"><span class="card-icon">📋</span>'
    h += '<h2 class="card-title">Recent Corporate Actions</h2></div>\n'
    h += '<table><thead><tr><th>Symbol</th><th>Action</th><th>Ratio</th><th>Notify Date</th><th>Book Close</th></tr></thead><tbody>\n'
    for a in da.get("actions", [])[:25]:
        h += f'''<tr><td><span class="symbol">{a["symbol"]}</span></td>
<td>{a.get("action_type","—")}</td>
<td>{a.get("ratio","—")}</td>
<td>{a.get("notify_date","—")}</td>
<td>{a.get("book_close_date","—")}</td></tr>\n'''
    h += '</tbody></table></div>\n'
    h += '</div></div>\n'
    return h


def _build_rankings_section(data):
    """🏅 Rankings."""
    rk = data.get("rankings", {})
    h = '<div id="rankings" class="section">\n'
    h += '<div class="grid-2">\n'

    # By Shares Traded
    h += '<div class="card"><div class="card-header"><span class="card-icon">📊</span>'
    h += '<h2 class="card-title">By Shares Traded</h2></div>\n'
    h += '<table><thead><tr><th>Rank</th><th>Symbol</th><th>Shares</th><th>Close</th></tr></thead><tbody>\n'
    for r in rk.get("by_trade", []):
        h += f'<tr><td>{r.get("rank","—")}</td><td><span class="symbol">{r["symbol"]}</span></td>'
        h += f'<td>{fmt(r.get("metric_value"),0)}</td><td>{fmt(r.get("closing_price"))}</td></tr>\n'
    h += '</tbody></table>\n'

    # By Turnover
    h += '<h3 style="margin:16px 0 8px;font-size:1rem;color:#f1f5f9;">By Turnover</h3>\n'
    h += '<table><thead><tr><th>Rank</th><th>Symbol</th><th>Turnover</th><th>Close</th></tr></thead><tbody>\n'
    for r in rk.get("by_turnover", []):
        h += f'<tr><td>{r.get("rank","—")}</td><td><span class="symbol">{r["symbol"]}</span></td>'
        h += f'<td>Rs {fmt(r.get("metric_value"))}</td><td>{fmt(r.get("closing_price"))}</td></tr>\n'
    h += '</tbody></table></div>\n'

    # By Transaction Count
    h += '<div class="card"><div class="card-header"><span class="card-icon">🔢</span>'
    h += '<h2 class="card-title">By Transaction Count</h2></div>\n'
    h += '<table><thead><tr><th>Rank</th><th>Symbol</th><th>Transactions</th><th>Close</th></tr></thead><tbody>\n'
    for r in rk.get("by_transaction", []):
        h += f'<tr><td>{r.get("rank","—")}</td><td><span class="symbol">{r["symbol"]}</span></td>'
        h += f'<td>{fmt(r.get("metric_value"),0)}</td><td>{fmt(r.get("closing_price"))}</td></tr>\n'
    h += '</tbody></table></div>\n'
    h += '</div></div>\n'
    return h


def _build_gainers_section(data):
    """🏆 Gainers / Losers."""
    gl = data.get("gainers_losers", {})
    h = '<div id="gainers" class="section">\n'
    h += '<div class="grid-2">\n'

    # Gainers
    h += '<div class="card"><div class="card-header"><span class="card-icon">🟢</span>'
    h += '<h2 class="card-title">Top Gainers</h2></div>\n'
    h += '<table><thead><tr><th>#</th><th>Symbol</th><th>LTP</th><th>Prev Close</th><th>Change</th><th>%</th></tr></thead><tbody>\n'
    for i, g in enumerate(gl.get("gainers", []), 1):
        h += f'''<tr><td>{i}</td><td><span class="symbol">{g["symbol"]}</span></td>
<td class="price">{fmt(g.get("ltp"))}</td>
<td>{fmt(g.get("previous_close"))}</td>
<td class="text-green">{fmt(g.get("point_change"))}</td>
<td class="text-green">{fmt(g.get("percent_change"))}%</td></tr>\n'''
    h += '</tbody></table></div>\n'

    # Losers
    h += '<div class="card"><div class="card-header"><span class="card-icon">🔴</span>'
    h += '<h2 class="card-title">Top Losers</h2></div>\n'
    h += '<table><thead><tr><th>#</th><th>Symbol</th><th>LTP</th><th>Prev Close</th><th>Change</th><th>%</th></tr></thead><tbody>\n'
    for i, l in enumerate(gl.get("losers", []), 1):
        h += f'''<tr><td>{i}</td><td><span class="symbol">{l["symbol"]}</span></td>
<td class="price">{fmt(l.get("ltp"))}</td>
<td>{fmt(l.get("previous_close"))}</td>
<td class="text-red">{fmt(l.get("point_change"))}</td>
<td class="text-red">{fmt(l.get("percent_change"))}%</td></tr>\n'''
    h += '</tbody></table></div>\n'
    h += '</div></div>\n'
    return h


def _build_circuit_section(data):
    """⚠️ Circuit Breaker Watch."""
    alerts = data.get("circuit_alerts", [])
    h = '<div id="circuit" class="section">\n'
    h += '<div class="card sell-card"><div class="card-header"><span class="card-icon">⚠️</span>'
    h += '<h2 class="card-title">Circuit Breaker Watch — Excluded from Signals</h2></div>\n'

    if not alerts:
        h += '<p class="text-muted">No stocks hit circuit breaker limits in recent sessions.</p>\n'
    else:
        h += '<p style="color:#f87171;font-size:0.85rem;margin-bottom:12px;">These stocks hit the 10% circuit limit on >2 of the last 5 sessions and are excluded from all signal tables.</p>\n'
        h += '<table><thead><tr>'
        h += '<th>Symbol</th><th>LTP</th><th>Sector</th><th>Volatility</th><th>Max DD%</th><th>Reason</th>'
        h += '</tr></thead><tbody>\n'
        for a in alerts:
            h += f'''<tr>
<td><span class="symbol">{a["symbol"]}</span></td>
<td class="price">{fmt_price(a["price"])}</td>
<td>{a.get("sector", "—")}</td>
<td class="text-red">{a.get("vol_20d", 0)}</td>
<td class="text-red">{a.get("max_drawdown", 0)}%</td>
<td><span class="reason-text">⚠️ Hit 10% circuit limit >2 times in last 5 sessions</span></td>
</tr>\n'''
        h += '</tbody></table>\n'

    h += '</div></div>\n'
    return h


def _build_research_section(data):
    """📰 Research."""
    research = data.get("research", [])
    h = '<div id="research" class="section">\n'
    h += '<div class="card"><div class="card-header"><span class="card-icon">📰</span>'
    h += '<h2 class="card-title">Research Insights — NEPSE Analytics v3.0</h2></div>\n'

    for r in research:
        h += f'''<div style="background:rgba(15,23,42,0.5);border:1px solid rgba(148,163,184,0.1);border-radius:10px;padding:16px;margin-bottom:12px;">
<h3 style="font-size:1rem;color:#f1f5f9;margin-bottom:8px;">{r["title"]}</h3>
<p style="color:#94a3b8;font-size:0.9rem;line-height:1.6;">{r["body"]}</p>
</div>\n'''

    h += '</div></div>\n'
    return h


# ═══════════════════════════════════════════════════════════════════════
#  WRITE REPORT
# ═══════════════════════════════════════════════════════════════════════

def write_report(html, output_dir=None):
    """Write the HTML report to disk."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    now = datetime.now()
    currentdate = now.strftime("%Y-%m-%d")
    filename = f"py_analyser_report_{currentdate}.html"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  ✅ Report written: {filepath}")
    return filepath
