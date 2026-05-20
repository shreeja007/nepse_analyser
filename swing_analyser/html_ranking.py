"""
NEPSE Swing Trading Analyser — Ranking HTML Report Generator (v1.0)

Produces a self-contained, dark-themed HTML report with:
- Hotlist banner (must-not-miss stocks)
- Score distribution chart
- Full ranking table with search/filter/sort (vanilla JS)
- Sector breadth heatmap
- Methodology section

Matches the CSS variables and dark theme from html_report.py exactly.
"""

import os
from datetime import datetime

# Reuse helpers from the existing report module
from swing_analyser.html_report import (
    _fmt, _setup_badge, _regime_badge,
)

def _base_css():
    """Shared CSS block for the ranking and full reports."""
    return '''
  :root {
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
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
    min-height: 100vh;
  }
  .container { max-width: 1440px; margin: 0 auto; padding: 24px; }
  .header {
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px 40px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
  }
  .header h1 {
    font-size: 2em;
    font-weight: 800;
    background: linear-gradient(135deg, #ff6e40, var(--accent-cyan));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }
  .header .subtitle { color: var(--text-secondary); font-size: 1em; }
  .header .meta {
    display: flex; gap: 20px; margin-top: 16px; flex-wrap: wrap; align-items: center;
  }
  .header .meta-item {
    background: rgba(255,255,255,0.05);
    padding: 6px 14px; border-radius: 8px; font-size: 0.85em;
    color: var(--text-secondary);
    backdrop-filter: blur(4px);
    border: 1px solid rgba(255,255,255,0.05);
  }
  .header .meta-item b { color: var(--text-primary); }
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 24px;
    margin-bottom: 20px;
    transition: border-color 0.3s;
  }
  .card:hover { border-color: rgba(0,229,255,0.2); }
  .card h2 {
    font-size: 1.2em; font-weight: 700; margin-bottom: 16px;
    color: var(--text-primary); display: flex; align-items: center; gap: 8px;
  }
  .data-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  .data-table th {
    background: #0d1117; padding: 10px 12px; text-align: left;
    font-weight: 600; font-size: 0.8em; color: var(--text-secondary);
    text-transform: uppercase; letter-spacing: 0.5px;
    border-bottom: 2px solid var(--border); position: sticky; top: 0; z-index: 1;
  }
  .data-table td {
    padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle;
  }
  .rank-row { transition: background 0.2s; }
  .rank-row:hover { background: var(--bg-card-hover) !important; }
  .rank-row:nth-child(even) { background: rgba(255,255,255,0.02); }
  .wl-row { cursor: pointer; transition: background 0.2s; }
  .wl-row:hover { background: var(--bg-card-hover) !important; }
  .wl-row:nth-child(4n+1) { background: rgba(255,255,255,0.02); }
  .detail-row td { border-bottom: 2px solid var(--accent-cyan) !important; }
  .hidden { display: none; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }
  .stat-box {
    background: rgba(124,77,255,0.05); border: 1px solid rgba(124,77,255,0.15);
    border-radius: 10px; padding: 16px; text-align: center;
  }
  .stat-box .number { font-size: 2em; font-weight: 800; color: var(--accent-purple); line-height: 1; }
  .stat-box .label { font-size: 0.78em; color: var(--text-secondary); margin-top: 4px; }
  .methodology {
    background: linear-gradient(135deg, #0f172a, #1a1a2e);
    border: 1px solid var(--border); border-radius: 14px; padding: 24px;
    margin-top: 20px; font-size: 0.85em; color: var(--text-secondary); line-height: 1.8;
  }
  @keyframes fadeInUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes hotlistPulse {
    0%, 100% { border-color: rgba(255,110,64,0.3); }
    50% { border-color: rgba(255,110,64,0.6); }
  }
  .card, .header { animation: fadeInUp 0.5s ease-out backwards; }
  @media (max-width: 1024px) {
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
    .data-table { font-size: 0.8em; }
  }
  .footer { text-align: center; padding: 32px; color: #455a64; font-size: 0.8em; }
'''


def _tier_badge(tier_name, tier_icon, tier_color):
    return (
        f'<span style="background:{tier_color};color:#000;padding:3px 10px;'
        f'border-radius:12px;font-weight:700;font-size:0.8em">'
        f'{tier_icon} {tier_name}</span>'
    )


def _build_hotlist_section(hotlist, gen_time):
    """Hotlist banner — always visible, even when empty."""
    if not hotlist:
        return '''
  <div class="card" style="border-color:rgba(255,110,64,0.3);background:linear-gradient(135deg,#1a1a2e,#0f172a)">
    <h2 style="color:#ff6e40">🎯 HOTLIST — Must-Not-Miss Stocks</h2>
    <div style="text-align:center;padding:40px;color:#546e7a">
      <div style="font-size:2em;margin-bottom:12px">🌙</div>
      <div style="font-size:1.1em;font-weight:600;color:#78909c">No hotlist stocks today</div>
      <div style="font-size:0.85em;margin-top:6px">Market not offering ideal swing setups.
        Check back on the next trading session.</div>
    </div>
  </div>'''


def _build_swing_watchlist_fallback(swing_data):
    """Fallback watchlist section used when swing HTML markers are unavailable."""
    watchlist = swing_data.get("watchlist", [])
    rows = ""

    for i, s in enumerate(watchlist, 1):
        entry_lo, entry_hi = s.get("entry_zone", (0, 0))
        setup_type = s.get("setup_type")
        setup_html = _setup_badge(setup_type) if setup_type else '<span style="color:#455a64">—</span>'
        signal = (s.get("signal") or "HOLD").upper()
        signal_color = {
            "STRONG BUY": "#00e676",
            "BUY": "#69f0ae",
            "HOLD": "#ffd54f",
        }.get(signal, "#90a4ae")
        rr = float(s.get("rr_ratio") or 0)
        score = float(s.get("composite") or 0)

        rows += f'''
        <tr class="rank-row">
          <td style="text-align:center;color:#546e7a;font-weight:600">{i}</td>
          <td>
            <div style="font-weight:700;color:#e0e0e0">{s.get("symbol", "")}</div>
            <div style="font-size:0.72em;color:#546e7a">{s.get("sector", "")}</div>
          </td>
          <td style="text-align:center;font-size:0.85em">{setup_html}</td>
          <td style="text-align:right;font-weight:600">Rs {_fmt(s.get("price"), 0)}</td>
          <td style="text-align:center;color:#80cbc4">Rs {_fmt(entry_lo, 0)}–{_fmt(entry_hi, 0)}</td>
          <td style="text-align:right;color:#ff8a80">Rs {_fmt(s.get("stop_loss"), 0)}</td>
          <td style="text-align:right;color:#a5d6a7">Rs {_fmt(s.get("target_1"), 0)}</td>
          <td style="text-align:center;color:{signal_color};font-weight:700">{signal}</td>
          <td style="text-align:center;color:{'#00e676' if rr >= 2 else '#ffd54f'};font-weight:700">{rr:.1f}:1</td>
          <td style="text-align:center;color:{'#00e676' if score >= 70 else '#ffd54f' if score >= 50 else '#ff8a80'};font-weight:700">{score:.1f}</td>
        </tr>'''

    return f'''
  <!-- MAIN WATCHLIST -->
  <div class="card">
    <h2>🎯 Swing Watchlist — Top {len(watchlist)} Candidates</h2>
    <p style="color:var(--text-secondary);font-size:0.85em;margin-bottom:12px">
      Fallback section generated directly from swing_data to preserve visibility when template markers change.
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
          <th style="text-align:center">Signal</th>
          <th style="text-align:center">R:R</th>
          <th style="text-align:center">Score</th>
        </tr>
      </thead>
      <tbody>
        {rows if rows else '<tr><td colspan="10" style="text-align:center;color:#546e7a;padding:32px">No swing candidates match all filters today.</td></tr>'}
      </tbody>
    </table>
    </div>
  </div>'''

    cards_html = ""
    for i, s in enumerate(hotlist):
        entry_lo, entry_hi = s.get("entry_zone", (0, 0))
        setup_label = (s.get("setup_type") or "").replace("_", " ").title()
        setup_icons = {
            "PULLBACK_TO_SUPPORT": "🔄", "BREAKOUT_ACCUMULATION": "💎",
            "GOLDEN_CROSS_ENTRY": "✨", "OVERSOLD_REVERSAL": "📈",
            "BASE_BREAKOUT": "🚀", "TREND_CONTINUATION": "📊",
        }
        icon = setup_icons.get(s.get("setup_type", ""), "📌")

        score_color = "#ff6e40" if s["universal_score"] >= 80 else "#00e676"

        cards_html += f'''
        <div style="background:linear-gradient(135deg,rgba(255,110,64,0.08),rgba(0,230,118,0.04));
                    border:1px solid rgba(255,110,64,0.3);border-radius:14px;padding:20px;
                    position:relative;overflow:hidden;
                    animation:hotlistPulse 3s ease-in-out infinite">
          <div style="position:absolute;top:-30px;right:-30px;width:100px;height:100px;
                      background:radial-gradient(circle,rgba(255,110,64,0.15),transparent);
                      pointer-events:none"></div>
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
            <div>
              <div style="font-size:1.3em;font-weight:800;color:#e0e0e0">{s["symbol"]}</div>
              <div style="font-size:0.8em;color:#78909c">{s.get("sector","")}</div>
            </div>
            <div style="text-align:right">
              <div style="font-size:2em;font-weight:900;color:{score_color};line-height:1">
                {s["universal_score"]:.0f}
              </div>
              <div style="font-size:0.7em;color:#90a4ae">SCORE</div>
            </div>
          </div>
          <div style="background:rgba(255,110,64,0.15);border-radius:8px;padding:8px 12px;
                      margin-bottom:12px;font-size:0.9em;font-weight:600;color:#ff6e40">
            {icon} {setup_label}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;
                      font-size:0.82em;margin-bottom:12px">
            <div style="text-align:center;background:rgba(0,0,0,0.2);border-radius:6px;padding:6px">
              <div style="color:#78909c;font-size:0.85em">Price</div>
              <div style="font-weight:700;color:#e0e0e0">Rs {s["price"]:,.0f}</div>
            </div>
            <div style="text-align:center;background:rgba(0,0,0,0.2);border-radius:6px;padding:6px">
              <div style="color:#78909c;font-size:0.85em">Entry</div>
              <div style="font-weight:600;color:#80cbc4">Rs {entry_lo:,.0f}–{entry_hi:,.0f}</div>
            </div>
            <div style="text-align:center;background:rgba(0,0,0,0.2);border-radius:6px;padding:6px">
              <div style="color:#78909c;font-size:0.85em">Stop Loss</div>
              <div style="font-weight:600;color:#ff8a80">Rs {s["stop_loss"]:,.0f}</div>
            </div>
            <div style="text-align:center;background:rgba(0,0,0,0.2);border-radius:6px;padding:6px">
              <div style="color:#78909c;font-size:0.85em">R:R</div>
              <div style="font-weight:700;color:{'#00e676' if s['rr_ratio']>=2 else '#ffd54f'}">
                {s["rr_ratio"]:.1f}:1
              </div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;
                      font-size:0.82em;margin-bottom:10px">
            <div style="text-align:center;background:rgba(0,230,118,0.08);border-radius:6px;padding:6px">
              <div style="color:#78909c;font-size:0.85em">Target 1</div>
              <div style="font-weight:600;color:#a5d6a7">Rs {s["target_1"]:,.0f}</div>
            </div>
            <div style="text-align:center;background:rgba(0,230,118,0.12);border-radius:6px;padding:6px">
              <div style="color:#78909c;font-size:0.85em">Target 2</div>
              <div style="font-weight:600;color:#69f0ae">Rs {s["target_2"]:,.0f}</div>
            </div>
          </div>
          <div style="font-size:0.82em;color:#b0bec5;font-style:italic;
                      border-top:1px solid rgba(255,255,255,0.05);padding-top:8px">
            💡 {s.get("hotlist_reason", "Strong multi-factor alignment")}
          </div>
          <div style="font-size:0.72em;color:#455a64;margin-top:6px">
            First flagged: {gen_time}
          </div>
        </div>'''

    grid_cols = "1fr" if len(hotlist) == 1 else "1fr 1fr" if len(hotlist) <= 4 else "1fr 1fr 1fr"

    return f'''
  <div class="card" style="border-color:rgba(255,110,64,0.3);
              background:linear-gradient(135deg,#1a1a2e,#0f172a)">
    <h2 style="color:#ff6e40">🎯 HOTLIST — {len(hotlist)} Must-Not-Miss Stock{"s" if len(hotlist) != 1 else ""}</h2>
    <p style="color:var(--text-secondary);font-size:0.85em;margin-bottom:16px">
      Score ≥ 65 with an active swing setup. These are your highest-conviction opportunities.
    </p>
    <div style="display:grid;grid-template-columns:{grid_cols};gap:16px">
      {cards_html}
    </div>
  </div>'''


def _build_tier_chart(tiers, total):
    """Score distribution bar chart — CSS only."""
    tier_meta = [
        ("PRIME", "🔥", "#ff6e40"),
        ("STRONG", "✅", "#00e676"),
        ("WATCH", "👀", "#ffd740"),
        ("WEAK", "⚠️", "#ff9800"),
        ("AVOID", "❌", "#ff5252"),
    ]
    bars = ""
    for name, icon, color in tier_meta:
        count = tiers.get(name, 0)
        pct = round(count / total * 100, 1) if total > 0 else 0
        w = max(2, pct)  # min 2% width for visibility
        bars += f'''
        <div style="margin:8px 0">
          <div style="display:flex;justify-content:space-between;font-size:0.85em;color:#cfd8dc;margin-bottom:3px">
            <span>{icon} {name} (score {"80–100" if name == "PRIME" else "65–79" if name == "STRONG" else "50–64" if name == "WATCH" else "35–49" if name == "WEAK" else "0–34"})</span>
            <span style="font-weight:700;color:{color}">{count} ({pct:.0f}%)</span>
          </div>
          <div style="background:#1a1a2e;border-radius:6px;height:14px;overflow:hidden">
            <div style="width:{w}%;height:100%;background:{color};border-radius:6px;
                        transition:width 0.8s ease;min-width:4px"></div>
          </div>
        </div>'''

    return f'''
  <div class="card">
    <h2>📊 Score Distribution — Market Health at a Glance</h2>
    <p style="color:var(--text-secondary);font-size:0.85em;margin-bottom:12px">
      {total} stocks scored. Distribution shows overall market swing-tradability.
    </p>
    {bars}
  </div>'''


def _build_ranking_table(ranked):
    """Full ranking table with search/filter/sort (vanilla JS)."""
    # Build sector options
    sectors = sorted(set(r.get("sector") or "Other" for r in ranked))
    sector_options = '<option value="">All Sectors</option>'
    for sec in sectors:
        sector_options += f'<option value="{sec}">{sec}</option>'

    # Build rows
    rows = ""
    for i, s in enumerate(ranked, 1):
        setup_html = _setup_badge(s["setup_type"]) if s.get("setup_type") else '<span style="color:#455a64">—</span>'
        tier_html = _tier_badge(s["tier_name"], s["tier_icon"], s["tier_color"])

        macd_color = "#69f0ae" if s.get("macd_hist") and s["macd_hist"] > 0 else "#ff8a80" if s.get("macd_hist") and s["macd_hist"] < 0 else "#90a4ae"
        rsi_val = s.get("rsi")
        rsi_color = "#ff8a80" if rsi_val and rsi_val > 70 else "#69f0ae" if rsi_val and rsi_val < 30 else "#e0e0e0"
        obv_color = "#69f0ae" if s.get("obv_trend") == "RISING" else "#ff8a80" if s.get("obv_trend") == "FALLING" else "#90a4ae"

        score = s["universal_score"]
        score_color = s["tier_color"]

        rows += f'''
        <tr class="rank-row" data-sector="{s.get("sector","Other")}" data-score="{score:.0f}">
          <td style="text-align:center;color:#546e7a;font-weight:600">{i}</td>
          <td>
            <div style="font-weight:700;color:#e0e0e0">{s["symbol"]}</div>
            <div style="font-size:0.72em;color:#546e7a">{s.get("sector","")}</div>
          </td>
          <td style="text-align:right;font-weight:600">Rs {s["price"]:,.0f}</td>
          <td style="text-align:center;font-weight:800;font-size:1.05em;color:{score_color}">{score:.0f}</td>
          <td style="text-align:center">{tier_html}</td>
          <td style="text-align:center;font-size:0.85em">{setup_html}</td>
          <td style="text-align:center;color:{rsi_color}">{_fmt(rsi_val, 0)}</td>
          <td style="text-align:center;color:{macd_color}">{_fmt(s.get("macd_hist"), 2)}</td>
          <td style="text-align:center;color:{obv_color};font-size:0.85em">{s.get("obv_trend","—")}</td>
          <td style="text-align:center">{s.get("vol_ratio",0):.1f}x</td>
        </tr>'''

    return f'''
  <div class="card">
    <h2>📋 Full Market Ranking — All {len(ranked)} Stocks</h2>
    <p style="color:var(--text-secondary);font-size:0.85em;margin-bottom:16px">
      Every equity ranked by Universal Swing Score. Search, filter by sector, or adjust score range.
    </p>

    <!-- FILTERS -->
    <div id="rankFilters" style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;align-items:center">
      <input type="text" id="rankSearch" placeholder="🔍 Search symbol..."
             style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;
                    padding:8px 14px;color:#e0e0e0;font-size:0.9em;width:200px;
                    font-family:inherit;outline:none" oninput="filterRankTable()">
      <select id="rankSector"
              style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;
                     padding:8px 14px;color:#e0e0e0;font-size:0.9em;
                     font-family:inherit;outline:none;cursor:pointer"
              onchange="filterRankTable()">
        {sector_options}
      </select>
      <div style="display:flex;align-items:center;gap:8px;font-size:0.85em;color:#90a4ae">
        <label>Score ≥</label>
        <input type="range" id="rankMinScore" min="0" max="100" value="0"
               style="width:120px;accent-color:#00e5ff" oninput="filterRankTable();
               document.getElementById('scoreVal').textContent=this.value">
        <span id="scoreVal" style="color:#00e5ff;font-weight:700;min-width:24px">0</span>
      </div>
      <div id="rankCount" style="margin-left:auto;font-size:0.82em;color:#546e7a">
        Showing {len(ranked)} of {len(ranked)}
      </div>
    </div>

    <div style="overflow-x:auto;max-height:70vh;overflow-y:auto">
    <table class="data-table" id="rankTable">
      <thead>
        <tr>
          <th style="text-align:center;cursor:pointer" onclick="sortRankTable(0,'num')">#</th>
          <th style="cursor:pointer" onclick="sortRankTable(1,'text')">Symbol</th>
          <th style="text-align:right;cursor:pointer" onclick="sortRankTable(2,'num')">Price</th>
          <th style="text-align:center;cursor:pointer" onclick="sortRankTable(3,'num')">Score ▼</th>
          <th style="text-align:center">Tier</th>
          <th style="text-align:center">Setup</th>
          <th style="text-align:center;cursor:pointer" onclick="sortRankTable(6,'num')">RSI</th>
          <th style="text-align:center;cursor:pointer" onclick="sortRankTable(7,'num')">MACD</th>
          <th style="text-align:center">OBV</th>
          <th style="text-align:center;cursor:pointer" onclick="sortRankTable(9,'num')">Vol</th>
        </tr>
      </thead>
      <tbody id="rankBody">
        {rows}
      </tbody>
    </table>
    </div>
  </div>

  <script>
  function filterRankTable() {{
    var search = document.getElementById('rankSearch').value.toLowerCase();
    var sector = document.getElementById('rankSector').value;
    var minScore = parseInt(document.getElementById('rankMinScore').value) || 0;
    var rows = document.querySelectorAll('#rankBody .rank-row');
    var shown = 0;
    rows.forEach(function(row) {{
      var sym = row.children[1].textContent.toLowerCase();
      var rowSector = row.getAttribute('data-sector');
      var rowScore = parseInt(row.getAttribute('data-score')) || 0;
      var match = true;
      if (search && sym.indexOf(search) === -1) match = false;
      if (sector && rowSector !== sector) match = false;
      if (rowScore < minScore) match = false;
      row.style.display = match ? '' : 'none';
      if (match) shown++;
    }});
    document.getElementById('rankCount').textContent = 'Showing ' + shown + ' of ' + rows.length;
  }}

  var sortDir = {{}};
  function sortRankTable(colIdx, type) {{
    var tbody = document.getElementById('rankBody');
    var rows = Array.from(tbody.querySelectorAll('.rank-row'));
    var dir = sortDir[colIdx] === 'asc' ? 'desc' : 'asc';
    sortDir[colIdx] = dir;
    rows.sort(function(a, b) {{
      var aVal = a.children[colIdx].textContent.replace(/[^0-9.-]/g, '');
      var bVal = b.children[colIdx].textContent.replace(/[^0-9.-]/g, '');
      if (type === 'num') {{
        aVal = parseFloat(aVal) || 0;
        bVal = parseFloat(bVal) || 0;
      }}
      if (dir === 'asc') return aVal > bVal ? 1 : -1;
      return aVal < bVal ? 1 : -1;
    }});
    rows.forEach(function(row) {{ tbody.appendChild(row); }});
  }}
  </script>'''


def _build_sector_breadth(sector_breadth):
    """Sector breadth heatmap — same rendering as html_report.py."""
    rows = ""
    sorted_sectors = sorted(sector_breadth.items(), key=lambda x: -x[1].get("pct", 0))
    for sec, sb in sorted_sectors[:12]:
        pct = sb.get("pct", 0)
        total = sb.get("total", 0)
        above = sb.get("above_sma50", 0)
        color = "#00e676" if pct > 60 else "#ffd54f" if pct > 40 else "#ff8a80"
        rows += f'''
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

    return f'''
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
      <tbody>{rows}</tbody>
    </table>
  </div>'''


def _ranking_methodology():
    """Methodology section for the universal scoring."""
    return '''
  <div class="methodology">
    <h2 style="color:var(--text-primary);margin-bottom:12px;font-size:1.1em">📚 Universal Scoring Methodology</h2>
    <p><b>Universal Swing Score (0–100):</b> Penalty-based scoring that ranks EVERY stock.
       Hard filters become scoring penalties, not gates — so no stock is hidden.</p>
    <p style="margin-top:8px"><b>Score Dimensions:</b>
       Trend Alignment (25%) + Momentum Timing (20%) + Volume Conviction (20%) +
       Setup Bonus (15%) + Volatility Suitability (10%) + Risk Headroom (5%) + Fundamental Floor (5%).</p>
    <p style="margin-top:8px"><b>Tier System:</b>
       🔥 PRIME (80–100) — exceptional candidate |
       ✅ STRONG (65–79) — high-quality setup |
       👀 WATCH (50–64) — worth monitoring |
       ⚠️ WEAK (35–49) — marginal conditions |
       ❌ AVOID (0–34) — not tradeable for swing.</p>
    <p style="margin-top:8px"><b>Hotlist Criteria:</b>
       Score ≥ 65 AND at least one of the 6 swing setups actively detected
       (Pullback, Breakout Accumulation, Golden Cross, Oversold Reversal, Base Breakout, Trend Continuation).</p>
    <p style="margin-top:8px"><b>Penalty vs Gate:</b>
       Below SMA200 = trend score capped at 30 (not excluded) |
       Low volume = volume deduction (not excluded) |
       High ATR% = volatility penalty (not excluded) |
       No setup = neutral 25 score (not zero).</p>
    <p style="margin-top:12px;color:#546e7a;font-size:0.9em">⚠️ This is a quantitative screening tool, not financial advice. Always conduct your own due diligence before trading.</p>
  </div>'''


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def build_ranking_html(data):
    """Build the ranking-mode HTML report (hotlist + ranking table + chart)."""
    ranked = data.get("ranked", [])
    hotlist = data.get("hotlist", [])
    tiers = data.get("tiers", {})
    sector_breadth = data.get("sector_breadth", {})
    regime = data.get("regime", {})
    gen_time = data.get("generation_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    total_ranked = data.get("total_ranked", len(ranked))
    top_score = ranked[0]["universal_score"] if ranked else 0

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="NEPSE Universal Swing Score — Full market ranking with hotlist for must-not-miss trades">
<title>📊 NEPSE Universal Swing Score</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
{_base_css()}
  .header::before {{
    content: '';
    position: absolute;
    top: -50%;
    right: -20%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(255,110,64,0.08) 0%, transparent 70%);
    pointer-events: none;
  }}
  .header h1 {{
    font-size: 2em;
    font-weight: 800;
    background: linear-gradient(135deg, #ff6e40, #ffd740);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }}
</style>
</head>
<body>
<div class="container">

  <!-- HEADER -->
  <div class="header">
    <h1>📊 NEPSE Universal Swing Score</h1>
    <div class="subtitle">Full Market Ranking — Every Stock Scored 0–100</div>
    <div class="meta">
      <div class="meta-item">🕐 <b>{gen_time}</b></div>
      <div class="meta-item">📊 Market: {_regime_badge(regime)}</div>
      <div class="meta-item">🔢 <b>{total_ranked}</b> stocks ranked</div>
      <div class="meta-item">🎯 <b>{len(hotlist)}</b> hotlist</div>
      <div class="meta-item">🏆 Top score: <b>{top_score:.0f}</b></div>
    </div>
  </div>

  <!-- SUMMARY STATS -->
  <div class="grid-3" style="margin-bottom:20px">
    <div class="stat-box">
      <div class="number">{tiers.get("PRIME",0)}</div>
      <div class="label">🔥 PRIME Stocks (80+)</div>
    </div>
    <div class="stat-box" style="border-color:rgba(0,230,118,0.3);background:rgba(0,230,118,0.05)">
      <div class="number" style="color:var(--accent-green)">{tiers.get("STRONG",0)}</div>
      <div class="label">✅ STRONG Stocks (65+)</div>
    </div>
    <div class="stat-box" style="border-color:rgba(0,229,255,0.3);background:rgba(0,229,255,0.05)">
      <div class="number" style="color:var(--accent-cyan)">{len(hotlist)}</div>
      <div class="label">🎯 Hotlist (Setup + Score ≥ 65)</div>
    </div>
  </div>

  <!-- HOTLIST -->
  {_build_hotlist_section(hotlist, gen_time)}

  <!-- TIER DISTRIBUTION -->
  {_build_tier_chart(tiers, total_ranked)}

  <!-- FULL RANKING TABLE -->
  {_build_ranking_table(ranked)}

  <!-- SECTOR BREADTH -->
  {_build_sector_breadth(sector_breadth)}

  <!-- METHODOLOGY -->
  {_ranking_methodology()}

  <div class="footer">
    NEPSE Universal Swing Score v1.0 — Generated {gen_time}<br>
    Powered by nepsego database · Quantitative Research Engine
  </div>

</div>
</body>
</html>'''
    return html


def build_full_html(swing_data, ranking_data):
    """
    Combined mode: ranking hotlist + tier chart at top,
    then existing swing watchlist, then full ranking table.
    """
    from swing_analyser.html_report import build_html as build_swing_html

    ranked = ranking_data.get("ranked", [])
    hotlist = ranking_data.get("hotlist", [])
    tiers = ranking_data.get("tiers", {})
    sector_breadth = ranking_data.get("sector_breadth", {})
    regime = ranking_data.get("regime", {})
    gen_time = ranking_data.get("generation_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    watchlist = swing_data.get("watchlist", [])
    total_ranked = ranking_data.get("total_ranked", len(ranked))
    top_score = ranked[0]["universal_score"] if ranked else 0

    # Get the swing HTML and extract just the body content
    swing_html = build_swing_html(swing_data)
    watchlist_block = _build_swing_watchlist_fallback(swing_data)
    if "<!-- MAIN WATCHLIST -->" in swing_html and "<!-- SETUP DISTRIBUTION" in swing_html:
      extracted = swing_html.split("<!-- MAIN WATCHLIST -->")[1].split("<!-- SETUP DISTRIBUTION")[0]
      if extracted.strip():
        watchlist_block = "<!-- MAIN WATCHLIST -->\n" + extracted

    # Build the combined report using ranking layout with swing watchlist injected
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="NEPSE Full Swing Analysis — Universal ranking plus strict-filter watchlist">
<title>📊 NEPSE Full Swing Analysis</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
{_base_css()}
  .header h1 {{
    background: linear-gradient(135deg, var(--accent-purple), var(--accent-cyan));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .header::before {{
    content: '';
    position: absolute;
    top: -50%;
    right: -20%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(124,77,255,0.08) 0%, transparent 70%);
    pointer-events: none;
  }}
  .stat-box .number {{ color: var(--accent-purple); }}
</style>
</head>
<body>
<div class="container">

  <!-- HEADER -->
  <div class="header">
    <h1>📊 NEPSE Full Swing Analysis</h1>
    <div class="subtitle">Universal Ranking + Strict-Filter Watchlist — Combined View</div>
    <div class="meta">
      <div class="meta-item">🕐 <b>{gen_time}</b></div>
      <div class="meta-item">📊 Market: {_regime_badge(regime)}</div>
      <div class="meta-item">🔢 <b>{total_ranked}</b> ranked</div>
      <div class="meta-item">🎯 <b>{len(hotlist)}</b> hotlist</div>
      <div class="meta-item">🔄 <b>{len(watchlist)}</b> swing watchlist</div>
      <div class="meta-item">🏆 Top: <b>{top_score:.0f}</b></div>
    </div>
  </div>

  <!-- SUMMARY STATS -->
  <div class="grid-3" style="margin-bottom:20px">
    <div class="stat-box" style="border-color:rgba(255,110,64,0.3);background:rgba(255,110,64,0.05)">
      <div class="number" style="color:#ff6e40">{tiers.get("PRIME",0)}</div>
      <div class="label">🔥 PRIME Stocks (80+)</div>
    </div>
    <div class="stat-box" style="border-color:rgba(0,230,118,0.3);background:rgba(0,230,118,0.05)">
      <div class="number" style="color:var(--accent-green)">{tiers.get("STRONG",0) + tiers.get("PRIME",0)}</div>
      <div class="label">✅ Actionable (≥ 65)</div>
    </div>
    <div class="stat-box">
      <div class="number">{len(hotlist)}</div>
      <div class="label">🎯 Hotlist (Score + Setup)</div>
    </div>
  </div>

  <!-- HOTLIST -->
  {_build_hotlist_section(hotlist, gen_time)}

  <!-- WATCHLIST -->
  {watchlist_block}

  <!-- TIER DISTRIBUTION -->
  {_build_tier_chart(tiers, total_ranked)}

  <!-- FULL RANKING TABLE -->
  {_build_ranking_table(ranked)}

  <!-- SECTOR BREADTH -->
  {_build_sector_breadth(sector_breadth)}

  <!-- METHODOLOGY -->
  {_ranking_methodology()}

  <div class="footer">
    NEPSE Full Swing Analysis v1.0 — Generated {gen_time}<br>
    Powered by nepsego database · Quantitative Research Engine
  </div>

</div>
</body>
</html>'''
    return html


def write_ranking_report(html, output_dir=None):
    """Write ranking HTML to file and return the absolute path."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"swing_ranking_{date_str}.html"
    if output_dir:
        filepath = os.path.join(output_dir, filename)
    else:
        filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return os.path.abspath(filepath)
