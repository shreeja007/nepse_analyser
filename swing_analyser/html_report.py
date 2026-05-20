"""
NEPSE Swing Trading Analyser — HTML Report Generator (v1.0)

Produces a self-contained, dark-themed HTML report with:
- Market context panel
- Ranked swing watchlist with entry/exit levels
- Setup distribution chart
- Sector heatmap
- Risk dashboard
- Rejected candidates section
"""

import os
from datetime import datetime


def _fmt(val, decimals=2):
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        return f"{val:,.{decimals}f}"
    return str(val)


def _signal_badge(signal):
    colors = {
        "STRONG BUY": ("#00e676", "#1b5e20"),
        "BUY": ("#69f0ae", "#2e7d32"),
        "HOLD": ("#ffd54f", "#e65100"),
    }
    bg, border = colors.get(signal, ("#90a4ae", "#455a64"))
    return f'<span style="background:{bg};color:#000;padding:3px 10px;border-radius:12px;font-weight:700;font-size:0.8em;border:1px solid {border}">{signal}</span>'


def _setup_badge(setup_type):
    icons = {
        "PULLBACK_TO_SUPPORT": "🔄",
        "BREAKOUT_ACCUMULATION": "💎",
        "GOLDEN_CROSS_ENTRY": "✨",
        "OVERSOLD_REVERSAL": "📈",
        "BASE_BREAKOUT": "🚀",
        "TREND_CONTINUATION": "📊",
    }
    label = setup_type.replace("_", " ").title()
    icon = icons.get(setup_type, "📌")
    return f'{icon} {label}'


def _regime_badge(regime):
    r = regime.get("regime", "NEUTRAL")
    chg = regime.get("chg", 0)
    colors = {"BULLISH": "#00e676", "BEARISH": "#ff5252", "NEUTRAL": "#ffd54f"}
    c = colors.get(r, "#90a4ae")
    return f'<span style="background:{c};color:#000;padding:4px 12px;border-radius:8px;font-weight:700">{r} ({chg:+.2f}%)</span>'


def _score_bar(score, label, color="#00e5ff"):
    w = max(0, min(100, score))
    return f'''<div style="margin:2px 0">
      <div style="display:flex;justify-content:space-between;font-size:0.75em;color:#aaa">
        <span>{label}</span><span>{score:.0f}</span>
      </div>
      <div style="background:#1a1a2e;border-radius:4px;height:6px;overflow:hidden">
        <div style="width:{w}%;height:100%;background:{color};border-radius:4px;transition:width 0.6s ease"></div>
      </div>
    </div>'''


def build_html(data):
    watchlist = data.get("watchlist", [])
    rejected = data.get("rejected", [])
    setup_dist = data.get("setup_distribution", {})
    sector_breadth = data.get("sector_breadth", {})
    regime = data.get("regime", {})
    gen_time = data.get("generation_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # ── Watchlist rows ──
    wl_rows = ""
    for i, s in enumerate(watchlist, 1):
        reasoning_items = ""
        for r in s.get("setup_reasoning", []):
            reasoning_items += f"<li>{r}</li>"

        # Bullish/bearish reasons
        bull_reasons = []
        bear_reasons = []
        if s.get("cross") in ("GOLDEN", "BULLISH"):
            bull_reasons.append(f"✅ MA Cross: {s['cross']}")
        if s.get("macd_hist") and s["macd_hist"] > 0:
            bull_reasons.append(f"✅ MACD Bullish ({s['macd_hist']:.2f})")
        if s.get("macd_just_bullish"):
            bull_reasons.append("✅ Fresh MACD Crossover")
        if s.get("obv_trend") == "RISING":
            bull_reasons.append("✅ OBV Rising")
        if s.get("weekly_uptrend"):
            bull_reasons.append("✅ Weekly Uptrend")
        if s.get("broker_asym", 50) > 60:
            bull_reasons.append(f"✅ Broker Accumulation ({s['broker_asym']:.0f})")
        if s.get("patterns"):
            bull_reasons.append(f"✅ Patterns: {', '.join(s['patterns'])}")
        if s.get("bb_squeeze"):
            bull_reasons.append("✅ Bollinger Squeeze")
        if s.get("rsi") and s["rsi"] < 40:
            bull_reasons.append(f"✅ RSI Oversold Zone ({s['rsi']:.0f})")

        if s.get("rsi") and s["rsi"] > 70:
            bear_reasons.append(f"⚠️ RSI Elevated ({s['rsi']:.0f})")
        if s.get("macd_hist") and s["macd_hist"] < 0:
            bear_reasons.append(f"⚠️ MACD Bearish ({s['macd_hist']:.2f})")
        if s.get("obv_trend") == "FALLING":
            bear_reasons.append("⚠️ OBV Falling")
        if s.get("adx") and s["adx"] < 15:
            bear_reasons.append(f"⚠️ ADX Low ({s['adx']:.0f}) — Weak Trend")
        if s.get("high_prox") and s.get("high_prox") < 3:
            bear_reasons.append(f"⚠️ Near 52W High ({s['high_prox']:.1f}%)")

        reasons_html = ""
        if bull_reasons:
            reasons_html += "<div style='color:#69f0ae;font-size:0.8em;margin-top:4px'>" + "<br>".join(bull_reasons) + "</div>"
        if bear_reasons:
            reasons_html += "<div style='color:#ffd54f;font-size:0.8em;margin-top:2px'>" + "<br>".join(bear_reasons) + "</div>"

        score_bars = (
            _score_bar(s.get("trend_score", 0), "Trend", "#00e5ff") +
            _score_bar(s.get("momentum_score", 0), "Momentum", "#7c4dff") +
            _score_bar(s.get("volume_score", 0), "Volume", "#ff6e40") +
            _score_bar(s.get("setup_score", 0), "Setup", "#00e676") +
            _score_bar(s.get("risk_score", 0), "Risk", "#ffd740") +
            _score_bar(s.get("fundamental_score", 0), "Funda", "#40c4ff")
        )

        entry_lo, entry_hi = s.get("entry_zone", (0, 0))

        wl_rows += f'''
        <tr class="wl-row" onclick="this.nextElementSibling.classList.toggle('hidden')">
          <td style="text-align:center;font-weight:700;color:#546e7a">{i}</td>
          <td>
            <div style="font-weight:700;font-size:1.05em;color:#e0e0e0">{s["symbol"]}</div>
            <div style="font-size:0.75em;color:#78909c">{s.get("sector","")}</div>
          </td>
          <td style="text-align:center">{_setup_badge(s["setup_type"])}</td>
          <td style="text-align:right;font-weight:600">Rs {s["price"]:,.0f}</td>
          <td style="text-align:center;font-size:0.9em;color:#80cbc4">
            Rs {entry_lo:,.0f}–{entry_hi:,.0f}
          </td>
          <td style="text-align:right;color:#ff8a80">Rs {s["stop_loss"]:,.0f}</td>
          <td style="text-align:right;color:#a5d6a7">Rs {s["target_1"]:,.0f}</td>
          <td style="text-align:right;color:#69f0ae">Rs {s["target_2"]:,.0f}</td>
          <td style="text-align:center;font-weight:700;color:{'#00e676' if s['rr_ratio']>=3 else '#ffd54f'}">{s["rr_ratio"]:.1f}:1</td>
          <td style="text-align:center;font-size:0.85em;color:#b0bec5">{s.get("hold_period","—")}</td>
          <td style="text-align:center">{_signal_badge(s["signal"])}</td>
          <td style="text-align:center;font-weight:700;font-size:1.1em;
                      color:{'#00e676' if s['composite']>=70 else '#ffd54f' if s['composite']>=50 else '#ff8a80'}">
            {s["composite"]:.1f}
          </td>
        </tr>
        <tr class="detail-row hidden">
          <td colspan="12" style="padding:12px 20px;background:#0d1117">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">
              <div>
                <div style="font-weight:600;color:#90a4ae;margin-bottom:6px;font-size:0.85em">📋 Setup Reasoning</div>
                <ul style="margin:0;padding-left:16px;color:#b0bec5;font-size:0.85em">
                  {reasoning_items}
                </ul>
                {reasons_html}
              </div>
              <div>
                <div style="font-weight:600;color:#90a4ae;margin-bottom:6px;font-size:0.85em">📊 Score Breakdown</div>
                {score_bars}
              </div>
              <div>
                <div style="font-weight:600;color:#90a4ae;margin-bottom:6px;font-size:0.85em">📈 Key Indicators</div>
                <div style="font-size:0.82em;color:#b0bec5;line-height:1.7">
                  RSI: <b>{_fmt(s.get('rsi'),1)}</b> | MACD: <b>{_fmt(s.get('macd_hist'),2)}</b><br>
                  ADX: <b>{_fmt(s.get('adx'),1)}</b> | ATR: <b>{_fmt(s.get('atr'),2)}</b><br>
                  Stoch: <b>{_fmt(s.get('stoch_k'),0)}/{_fmt(s.get('stoch_d'),0)}</b> | OBV: <b>{s.get('obv_trend','—')}</b><br>
                  BB%: <b>{_fmt(s.get('bb_pct'),1)}</b> | Vol: <b>{s.get('vol_ratio',0):.1f}x</b><br>
                  52W Prox: <b>{_fmt(s.get('high_prox'),1)}%</b> | Cross: <b>{s.get('cross','—')}</b><br>
                  EPS: <b>{_fmt(s.get('eps'),1)}</b> | PE: <b>{_fmt(s.get('pe'),1)}</b><br>
                  Position Size: <b>{s.get('position_size',0)} shares</b> (Rs 1L, 1.5% risk)
                </div>
              </div>
            </div>
          </td>
        </tr>
        '''

    # ── Setup distribution ──
    setup_items = ""
    setup_colors = {
        "PULLBACK_TO_SUPPORT": "#00e5ff",
        "BREAKOUT_ACCUMULATION": "#7c4dff",
        "GOLDEN_CROSS_ENTRY": "#ffd740",
        "OVERSOLD_REVERSAL": "#ff6e40",
        "BASE_BREAKOUT": "#00e676",
        "TREND_CONTINUATION": "#40c4ff",
    }
    total_setups = sum(setup_dist.values()) or 1
    for st, count in sorted(setup_dist.items(), key=lambda x: -x[1]):
        pct = count / total_setups * 100
        color = setup_colors.get(st, "#90a4ae")
        label = st.replace("_", " ").title()
        setup_items += f'''
        <div style="margin:6px 0">
          <div style="display:flex;justify-content:space-between;font-size:0.85em;color:#cfd8dc">
            <span>{label}</span><span>{count} ({pct:.0f}%)</span>
          </div>
          <div style="background:#1a1a2e;border-radius:4px;height:10px;overflow:hidden">
            <div style="width:{pct}%;height:100%;background:{color};border-radius:4px;transition:width 0.8s ease"></div>
          </div>
        </div>'''

    # ── Sector breadth ──
    sector_rows = ""
    sorted_sectors = sorted(sector_breadth.items(), key=lambda x: -x[1].get("pct", 0))
    for sec, sb in sorted_sectors[:12]:
        pct = sb.get("pct", 0)
        total = sb.get("total", 0)
        above = sb.get("above_sma50", 0)
        color = "#00e676" if pct > 60 else "#ffd54f" if pct > 40 else "#ff8a80"
        sector_rows += f'''
        <tr>
          <td style="color:#e0e0e0">{sec}</td>
          <td style="text-align:center">{above}/{total}</td>
          <td style="text-align:center">
            <div style="display:flex;align-items:center;gap:6px">
              <div style="flex:1;background:#1a1a2e;border-radius:3px;height:8px;overflow:hidden">
                <div style="width:{pct}%;height:100%;background:{color};border-radius:3px"></div>
              </div>
              <span style="color:{color};font-weight:600;min-width:40px">{pct:.0f}%</span>
            </div>
          </td>
        </tr>'''

    # ── Rejected candidates ──
    rejected_rows = ""
    for r in rejected[:10]:
        rej_reason = "Below R:R threshold" if r.get("rr_ratio", 0) < 2 else "Signal not strong enough"
        rejected_rows += f'''
        <tr>
          <td style="color:#b0bec5">{r["symbol"]}</td>
          <td style="font-size:0.85em">{_setup_badge(r.get("setup_type",""))}</td>
          <td style="text-align:right">Rs {r.get("price",0):,.0f}</td>
          <td style="text-align:center;color:{'#ffd54f' if r.get('confidence',0)>=50 else '#ff8a80'}">{r.get("confidence",0):.0f}%</td>
          <td style="text-align:center">{r.get("composite",0):.1f}</td>
          <td style="color:#78909c;font-size:0.82em">{rej_reason}</td>
        </tr>'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="NEPSE Swing Trading Analyser — Mid-term swing trade watchlist with entry/exit levels and risk management">
<title>🔄 NEPSE Swing Trading Analyser</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg-primary: #0a0e17;
    --bg-card: #111827;
    --bg-card-hover: #1a2332;
    --border: #1e293b;
    --text-primary: #e2e8f0;
    --text-secondary: #94a3b8;
    --accent-cyan: #00e5ff;
    --accent-green: #00e676;
    --accent-red: #ff5252;
    --accent-gold: #ffd740;
    --accent-purple: #7c4dff;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
    min-height: 100vh;
  }}
  .container {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}

  /* Header */
  .header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px 40px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
  }}
  .header::before {{
    content: '';
    position: absolute;
    top: -50%;
    right: -20%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(0,229,255,0.08) 0%, transparent 70%);
    pointer-events: none;
  }}
  .header h1 {{
    font-size: 2em;
    font-weight: 800;
    background: linear-gradient(135deg, var(--accent-cyan), var(--accent-green));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }}
  .header .subtitle {{ color: var(--text-secondary); font-size: 1em; }}
  .header .meta {{
    display: flex;
    gap: 20px;
    margin-top: 16px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .header .meta-item {{
    background: rgba(255,255,255,0.05);
    padding: 6px 14px;
    border-radius: 8px;
    font-size: 0.85em;
    color: var(--text-secondary);
    backdrop-filter: blur(4px);
    border: 1px solid rgba(255,255,255,0.05);
  }}
  .header .meta-item b {{ color: var(--text-primary); }}

  /* Cards */
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 24px;
    margin-bottom: 20px;
    transition: border-color 0.3s;
  }}
  .card:hover {{ border-color: rgba(0,229,255,0.2); }}
  .card h2 {{
    font-size: 1.2em;
    font-weight: 700;
    margin-bottom: 16px;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  /* Tables */
  .data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9em;
  }}
  .data-table th {{
    background: #0d1117;
    padding: 10px 12px;
    text-align: left;
    font-weight: 600;
    font-size: 0.8em;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 2px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 1;
  }}
  .data-table td {{
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }}
  .wl-row {{
    cursor: pointer;
    transition: background 0.2s;
  }}
  .wl-row:hover {{
    background: var(--bg-card-hover) !important;
  }}
  .wl-row:nth-child(4n+1) {{
    background: rgba(255,255,255,0.02);
  }}
  .detail-row td {{
    border-bottom: 2px solid var(--accent-cyan) !important;
  }}
  .hidden {{ display: none; }}

  /* Grid */
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }}

  /* Stats */
  .stat-box {{
    background: rgba(0,229,255,0.05);
    border: 1px solid rgba(0,229,255,0.15);
    border-radius: 10px;
    padding: 16px;
    text-align: center;
  }}
  .stat-box .number {{
    font-size: 2em;
    font-weight: 800;
    color: var(--accent-cyan);
    line-height: 1;
  }}
  .stat-box .label {{
    font-size: 0.78em;
    color: var(--text-secondary);
    margin-top: 4px;
  }}

  /* Methodology */
  .methodology {{
    background: linear-gradient(135deg, #0f172a, #1a1a2e);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 24px;
    margin-top: 20px;
    font-size: 0.85em;
    color: var(--text-secondary);
    line-height: 1.8;
  }}

  /* Animations */
  @keyframes fadeInUp {{
    from {{ opacity: 0; transform: translateY(20px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}
  .card, .header {{ animation: fadeInUp 0.5s ease-out backwards; }}
  .card:nth-child(2) {{ animation-delay: 0.1s; }}
  .card:nth-child(3) {{ animation-delay: 0.2s; }}
  .card:nth-child(4) {{ animation-delay: 0.3s; }}

  /* Responsive */
  @media (max-width: 1024px) {{
    .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
    .data-table {{ font-size: 0.8em; }}
  }}

  /* Footer */
  .footer {{
    text-align: center;
    padding: 32px;
    color: #455a64;
    font-size: 0.8em;
  }}
</style>
</head>
<body>
<div class="container">

  <!-- HEADER -->
  <div class="header">
    <h1>🔄 NEPSE Swing Trading Analyser</h1>
    <div class="subtitle">Mid-Term Swing Trade Scanner — 1 to 2 Month Hold Period</div>
    <div class="meta">
      <div class="meta-item">🕐 <b>{gen_time}</b></div>
      <div class="meta-item">📊 Market: {_regime_badge(regime)}</div>
      <div class="meta-item">🔍 <b>{data.get("total_analyzed",0)}</b> symbols scanned</div>
      <div class="meta-item">🎯 <b>{len(watchlist)}</b> swing candidates</div>
    </div>
  </div>

  <!-- SUMMARY STATS -->
  <div class="grid-3" style="margin-bottom:20px">
    <div class="stat-box">
      <div class="number">{len(watchlist)}</div>
      <div class="label">Active Swing Setups</div>
    </div>
    <div class="stat-box" style="border-color:rgba(124,77,255,0.3);background:rgba(124,77,255,0.05)">
      <div class="number" style="color:var(--accent-purple)">{data.get("total_candidates",0)}</div>
      <div class="label">Total Candidates (Pre-Filter)</div>
    </div>
    <div class="stat-box" style="border-color:rgba(0,230,118,0.3);background:rgba(0,230,118,0.05)">
      <div class="number" style="color:var(--accent-green)">{max((s.get("composite",0) for s in watchlist), default=0):.0f}</div>
      <div class="label">Highest Composite Score</div>
    </div>
  </div>

  <!-- MAIN WATCHLIST -->
  <div class="card">
    <h2>🎯 Swing Watchlist — Top {len(watchlist)} Candidates</h2>
    <p style="color:var(--text-secondary);font-size:0.85em;margin-bottom:12px">
      Click any row to expand detailed reasoning, score breakdown, and key indicators.
    </p>
    <div style="overflow-x:auto">
    <table class="data-table">
      <thead>
        <tr>
          <th style="text-align:center">#</th>
          <th>Symbol</th>
          <th style="text-align:center">Setup</th>
          <th style="text-align:right">Price</th>
          <th style="text-align:center">Entry Zone</th>
          <th style="text-align:right">Stop Loss</th>
          <th style="text-align:right">Target 1</th>
          <th style="text-align:right">Target 2</th>
          <th style="text-align:center">R:R</th>
          <th style="text-align:center">Hold</th>
          <th style="text-align:center">Signal</th>
          <th style="text-align:center">Score</th>
        </tr>
      </thead>
      <tbody>
        {wl_rows if wl_rows else '<tr><td colspan="12" style="text-align:center;color:#546e7a;padding:40px">No swing candidates match all filters today. Market conditions may not favor swing entries.</td></tr>'}
      </tbody>
    </table>
    </div>
  </div>

  <!-- SETUP DISTRIBUTION + SECTOR HEATMAP -->
  <div class="grid-2">
    <div class="card">
      <h2>📊 Setup Distribution</h2>
      {setup_items if setup_items else '<p style="color:#546e7a">No setups detected</p>'}
    </div>
    <div class="card">
      <h2>🗺️ Sector Breadth (% Above SMA50)</h2>
      <table class="data-table">
        <thead>
          <tr>
            <th>Sector</th>
            <th style="text-align:center">Above/Total</th>
            <th>Breadth</th>
          </tr>
        </thead>
        <tbody>{sector_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- REJECTED CANDIDATES -->
  {"" if not rejected_rows else f"""
  <div class="card">
    <h2>🚫 Near-Miss Candidates</h2>
    <p style="color:var(--text-secondary);font-size:0.85em;margin-bottom:12px">
      Stocks that showed swing setups but didn't pass all filters. Watch for improvements.
    </p>
    <table class="data-table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Setup</th>
          <th style="text-align:right">Price</th>
          <th style="text-align:center">Confidence</th>
          <th style="text-align:center">Score</th>
          <th>Rejection Reason</th>
        </tr>
      </thead>
      <tbody>{rejected_rows}</tbody>
    </table>
  </div>
  """}

  <!-- METHODOLOGY -->
  <div class="methodology">
    <h2 style="color:var(--text-primary);margin-bottom:12px;font-size:1.1em">📚 Methodology</h2>
    <p><b>Swing Setup Types:</b> Pullback to Support, Breakout Accumulation, Golden Cross Entry, Oversold Reversal, Base Breakout, Trend Continuation.</p>
    <p style="margin-top:8px"><b>Composite Score (0–100):</b> Trend Alignment (25%) + Momentum Timing (20%) + Volume Profile (20%) + Setup Quality (15%) + Risk/Reward (10%) + Fundamental Floor (10%).</p>
    <p style="margin-top:8px"><b>Filters:</b> Min avg volume &gt; 5,000 | No circuit breaker history | R:R ≥ 2.0 | Above SMA200 | Weekly uptrend | ATR% &lt; 8%.</p>
    <p style="margin-top:8px"><b>Risk Management:</b> Stop = Entry − 1.5×ATR(14) | Target 1 = Entry + 3.0×ATR | Target 2 = Entry + 5.0×ATR | Position size = 1.5% equity risked per trade.</p>
    <p style="margin-top:8px"><b>NEPSE-Specific:</b> RSI calibrated to 80/20 thresholds | Ashad/Shrawan seasonal bonus (+5 pts Jun-Jul) | Post-festive penalty (-5 pts Jan-Feb) | Corporate action adjustment applied.</p>
    <p style="margin-top:12px;color:#546e7a;font-size:0.9em">⚠️ This is a quantitative screening tool, not financial advice. Always conduct your own due diligence before trading.</p>
  </div>

  <div class="footer">
    NEPSE Swing Trading Analyser v1.0 — Generated {gen_time}<br>
    Powered by nepsego database · Quantitative Research Engine
  </div>

</div>
</body>
</html>'''
    return html


def write_report(html, output_dir=None):
    """Write HTML to file and return the absolute path."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"swing_report_{date_str}.html"
    if output_dir:
        filepath = os.path.join(output_dir, filename)
    else:
        filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return os.path.abspath(filepath)
