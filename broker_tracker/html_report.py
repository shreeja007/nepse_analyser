"""broker_tracker.html_report

Self-contained HTML report generator for broker tracker.

Matches the dark dashboard style used in analysor/html_extractor.py and uses
vanilla JS collapsibles like swing_analyser/html_report.py.
"""

from __future__ import annotations

import os
import html
import json
from datetime import datetime
from typing import Any

import pandas as pd

from broker_tracker.config import OUTPUT_DIR, TOP_N_SIGNALS


def fmt(v, decimals=2):
    if v is None:
        return "—"
    try:
        if pd.isna(v):
            return "—"
    except Exception:
        pass
    try:
        v = float(v)
        if abs(v) >= 1e9:
            return f"{v/1e9:.{decimals}f}B"
        if abs(v) >= 1e6:
            return f"{v/1e6:.{decimals}f}M"
        if abs(v) >= 1e3:
            return f"{v/1e3:.{decimals}f}K"
        return f"{v:,.{decimals}f}"
    except Exception:
        return str(v)


def fmt_int(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "—"
        return f"{int(v):,}"
    except Exception:
        return str(v)


def fmt_price(v):
    if v is None:
        return "—"
    try:
        if pd.isna(v):
            return "—"
    except Exception:
        pass
    try:
        return f"Rs {float(v):,.2f}"
    except Exception:
        return str(v)


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{html.escape(text)}</span>'


def trust_badge(trust_label: str, trust_score: float | None) -> str:
    label = (trust_label or "UNRATED").upper()
    if label == "HIGH":
        return badge(f"🟢 HIGH {trust_score:.1f}" if trust_score is not None else "🟢 HIGH", "bg-green")
    if label == "MEDIUM":
        return badge(f"🟡 MEDIUM {trust_score:.1f}" if trust_score is not None else "🟡 MEDIUM", "bg-yellow")
    if label == "LOW":
        return badge(f"🔴 LOW {trust_score:.1f}" if trust_score is not None else "🔴 LOW", "bg-red")
    return badge("⚪ UNRATED", "bg-muted")


def state_badge(state: str) -> str:
    state = (state or "").upper()
    cls = {
        "ACCUMULATING": "state-acc",
        "ENTERING": "state-ent",
        "HOLDING": "state-hold",
        "DISTRIBUTING": "state-dist",
        "EXITING": "state-exit",
        "FLAT": "state-flat",
    }.get(state, "state-flat")
    return badge(state, cls)


CSS = """
:root {
    --primary: #2563eb;
    --success: #00c853;
    --warning: #ffd600;
    --danger:  #f44336;
    --info:    #42a5f5;
    --muted:   #9e9e9e;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #e2e8f0;
    margin: 0;
    padding: 20px;
    min-height: 100vh;
}
.container { max-width: 1400px; margin: 0 auto; }
.header { text-align: center; margin-bottom: 22px; padding: 10px; }
.header h1 {
    margin: 0;
    font-size: 2.2rem;
    background: linear-gradient(135deg, #60a5fa, #34d399);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.header p { color: #94a3b8; margin: 8px 0 0; }
.card {
    background: rgba(30, 41, 59, 0.8);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(148, 163, 184, 0.1);
    border-radius: 16px;
    padding: 22px;
    margin-bottom: 20px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.3);
}
.card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.2);
    padding-bottom: 12px;
}
.card-title {
    font-size: 1.2rem;
    font-weight: 800;
    color: #f1f5f9;
    margin: 0;
}
.subtle { color: #94a3b8; font-size: 0.9rem; }
.banner {
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 18px;
    border: 1px solid rgba(245, 158, 11, 0.35);
    background: linear-gradient(135deg, rgba(245, 158, 11, 0.12) 0%, rgba(30, 41, 59, 0.85) 100%);
    color: #fbbf24;
    font-weight: 700;
}
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
@media(max-width: 1024px) { .grid-3 { grid-template-columns: 1fr; } }

.table-wrap { overflow-x: auto; }

table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th {
    text-align: left;
    padding: 12px 10px;
    background: rgba(15, 23, 42, 0.5);
    color: #94a3b8;
    font-weight: 700;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
    border-bottom: 2px solid rgba(148, 163, 184, 0.2);
}
td {
    padding: 12px 10px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.1);
    vertical-align: top;
}
tr:hover { background: rgba(148, 163, 184, 0.05); }

.badge {
    padding: 5px 10px;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 800;
    display: inline-block;
    white-space: nowrap;
}
.bg-green  { background: rgba(0, 200, 83, 0.18); color: var(--success); }
.bg-yellow { background: rgba(255, 214, 0, 0.16); color: var(--warning); }
.bg-red    { background: rgba(244, 67, 54, 0.16); color: var(--danger); }
.bg-muted  { background: rgba(158, 158, 158, 0.12); color: var(--muted); }

.state-acc  { background: rgba(0, 200, 83, 0.18); color: var(--success); }
.state-ent  { background: rgba(255, 214, 0, 0.16); color: var(--warning); }
.state-hold { background: rgba(66, 165, 245, 0.16); color: var(--info); }
.state-dist { background: rgba(244, 67, 54, 0.14); color: var(--danger); }
.state-exit { background: rgba(244, 67, 54, 0.18); color: var(--danger); }
.state-flat { background: rgba(158, 158, 158, 0.12); color: var(--muted); }

.row-acc td  { border-left: 3px solid var(--success); }
.row-ent td  { border-left: 3px solid var(--warning); }
.row-hold td { border-left: 3px solid var(--info); }
.row-dist td { border-left: 3px solid var(--danger); }
.row-exit td { border-left: 3px solid var(--danger); }
.row-flat td { border-left: 3px solid var(--muted); }

.kv { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.kv div { padding: 10px; border-radius: 12px; background: rgba(15, 23, 42, 0.35); border: 1px solid rgba(148, 163, 184, 0.1); }
.kv .k { color: #94a3b8; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }
.kv .v { margin-top: 4px; font-weight: 800; color: #e2e8f0; }

.toggle {
    cursor: pointer;
    user-select: none;
    padding: 10px 12px;
    border-radius: 12px;
    background: rgba(15, 23, 42, 0.35);
    border: 1px solid rgba(148, 163, 184, 0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.toggle:hover { background: rgba(148, 163, 184, 0.06); }
.hidden { display: none; }
.small { font-size: 0.85rem; color: #94a3b8; }
.symbol { font-weight: 900; color: #f1f5f9; }
.symbol-link {
    font-weight: 900;
    color: #f1f5f9;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    text-decoration: underline dotted rgba(241, 245, 249, 0.45);
    cursor: pointer;
}
.symbol-link:hover { color: #93c5fd; text-decoration-color: rgba(147, 197, 253, 0.8); }

.why-modal-backdrop {
    position: fixed;
    inset: 0;
    display: none;
    align-items: center;
    justify-content: center;
    background: rgba(2, 6, 23, 0.72);
    z-index: 9999;
    padding: 18px;
}
.why-modal-backdrop.open { display: flex; }
.why-modal {
    width: min(920px, 96vw);
    max-height: 90vh;
    overflow-y: auto;
    border-radius: 14px;
    border: 1px solid rgba(148, 163, 184, 0.28);
    background: linear-gradient(180deg, rgba(30, 41, 59, 0.97) 0%, rgba(15, 23, 42, 0.98) 100%);
    box-shadow: 0 24px 64px rgba(2, 6, 23, 0.7);
    padding: 18px;
}
.why-modal-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
}
.why-modal-title { font-size: 1.15rem; font-weight: 800; color: #f8fafc; }
.why-close {
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 10px;
    background: rgba(15, 23, 42, 0.6);
    color: #cbd5e1;
    padding: 6px 10px;
    cursor: pointer;
}
.why-close:hover { background: rgba(71, 85, 105, 0.4); }
.why-summary {
    margin: 8px 0 14px;
    color: #dbeafe;
    font-weight: 600;
}
.why-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: 14px;
}
.why-grid .item {
    padding: 10px;
    border-radius: 10px;
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(148, 163, 184, 0.16);
}
.why-grid .label {
    color: #94a3b8;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.why-grid .value {
    margin-top: 4px;
    font-weight: 800;
    color: #f1f5f9;
}
.why-points {
    margin: 0 0 14px 16px;
    padding: 0;
}
.why-points li { margin-bottom: 6px; color: #d1d5db; }
.why-subtitle { font-size: 0.9rem; font-weight: 800; color: #e2e8f0; margin: 14px 0 8px; }
.why-mini-table-wrap { overflow-x: auto; }
.why-mini-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
.why-mini-table th,
.why-mini-table td {
    padding: 8px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}
.why-mini-table th {
    color: #94a3b8;
    background: rgba(15, 23, 42, 0.45);
    text-align: left;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
@media(max-width: 920px) {
    .why-grid { grid-template-columns: 1fr; }
}
.footer { text-align: center; padding: 14px; color: #64748b; font-size: 0.85rem; }
"""


JS = """
function toggleSection(id) {
  var el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('hidden');
}

function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function fmtInt(v) {
    if (v === null || v === undefined) return '—';
    try { return Number(v).toLocaleString('en-US'); } catch(e) { return String(v); }
}

function fmtPrice(v) {
    if (v === null || v === undefined) return '—';
    try {
        var n = Number(v);
        if (!isFinite(n)) return '—';
        return 'Rs ' + n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    } catch(e) {
        return '—';
    }
}

function fmtAsym(v) {
    if (v === null || v === undefined) return '—';
    try {
        var n = Number(v);
        if (!isFinite(n)) return '—';
        return Math.round(n) + '%';
    } catch(e) {
        return '—';
    }
}

function stateBadge(state) {
    var st = (state || '').toUpperCase();
    var cls = {
        'ACCUMULATING': 'state-acc',
        'ENTERING': 'state-ent',
        'HOLDING': 'state-hold',
        'DISTRIBUTING': 'state-dist',
        'EXITING': 'state-exit',
        'FLAT': 'state-flat'
    }[st] || 'state-flat';
    return '<span class="badge ' + cls + '">' + escapeHtml(st) + '</span>';
}

function rowClass(state) {
    var st = (state || '').toUpperCase();
    return {
        'ACCUMULATING': 'row-acc',
        'ENTERING': 'row-ent',
        'HOLDING': 'row-ent',
        'DISTRIBUTING': 'row-dist',
        'EXITING': 'row-exit',
        'FLAT': 'row-flat'
    }[st] || 'row-flat';
}

function fmtPct(v, decimals) {
    if (v === null || v === undefined) return '—';
    var d = (decimals === undefined ? 1 : decimals);
    try {
        var n = Number(v);
        if (!isFinite(n)) return '—';
        return n.toFixed(d) + '%';
    } catch(e) {
        return '—';
    }
}

function openWhyFromSymbol(btn) {
    if (!btn) return;
    var raw = btn.getAttribute('data-why') || '';
    if (!raw) return;
    try {
        var payload = JSON.parse(raw);
        openWhyModal(payload);
    } catch(e) {
        console.error('Failed to parse why payload', e);
    }
}

function openWhyModal(payload) {
    var backdrop = document.getElementById('why_modal_backdrop');
    var titleEl = document.getElementById('why_modal_title');
    var bodyEl = document.getElementById('why_modal_body');
    if (!backdrop || !titleEl || !bodyEl) return;

    var symbol = payload && payload.symbol ? String(payload.symbol) : 'Unknown';
    var signalType = payload && payload.signal_type ? String(payload.signal_type) : 'SIGNAL';
    var brokerCount = payload && payload.broker_count !== undefined ? payload.broker_count : 0;
    var brokerIds = (payload && Array.isArray(payload.broker_ids)) ? payload.broker_ids : [];
    var contributors = (payload && Array.isArray(payload.contributors)) ? payload.contributors : [];
    var trustLabel = payload && payload.broker_trust_label ? payload.broker_trust_label : 'UNRATED';
    var trustScore = payload && payload.broker_trust_score !== null && payload.broker_trust_score !== undefined
        ? Number(payload.broker_trust_score).toFixed(1)
        : '—';
    var stockScore = payload && payload.stock_score !== null && payload.stock_score !== undefined
        ? Number(payload.stock_score).toFixed(1)
        : '—';
    var strength = payload && payload.signal_strength ? payload.signal_strength : '—';
    var asym = payload ? payload.latest_asymmetry : null;
    var move = payload ? payload.price_move_since_entry_pct : null;
    var summary = payload && payload.why_summary ? String(payload.why_summary) : '';
    var points = (payload && Array.isArray(payload.why_points)) ? payload.why_points : [];

    titleEl.innerHTML = 'Why ' + escapeHtml(signalType) + ' for ' + escapeHtml(symbol) + '?';

    var pointsHtml = '';
    for (var i = 0; i < points.length; i++) {
        pointsHtml += '<li>' + escapeHtml(points[i]) + '</li>';
    }
    if (!pointsHtml) pointsHtml = '<li>No additional explanation available.</li>';

    var contributorsHtml = '';
    for (var j = 0; j < contributors.length; j++) {
        var c = contributors[j] || {};
        var cName = c.broker_name ? (' - ' + String(c.broker_name)) : '';
        contributorsHtml += '<tr>' +
            '<td>' + escapeHtml(String(c.broker_id !== undefined ? c.broker_id : '—')) + escapeHtml(cName) + '</td>' +
            '<td>' + escapeHtml(String(c.broker_trust_label || 'UNRATED')) + '</td>' +
            '<td>' + escapeHtml(String(c.signal_strength || 'WEAK')) + '</td>' +
            '<td>' + stateBadge(c.current_state || '') + '</td>' +
            '<td>' + fmtAsym(c.latest_asymmetry) + '</td>' +
            '<td>' + fmtInt(c.cumulative_net_qty) + '</td>' +
            '</tr>';
    }
    if (!contributorsHtml) {
        contributorsHtml = '<tr><td colspan="6" class="small">No broker contributors available.</td></tr>';
    }

    var brokerIdsText = brokerIds.length ? brokerIds.join(', ') : '—';

    bodyEl.innerHTML =
        '<div class="why-summary">' + escapeHtml(summary || 'Signal matched the configured analyzer conditions.') + '</div>' +
        '<div class="why-grid">' +
            '<div class="item"><div class="label">Contributing Brokers</div><div class="value">' + fmtInt(brokerCount) + '</div></div>' +
            '<div class="item"><div class="label">Broker IDs</div><div class="value">' + escapeHtml(brokerIdsText) + '</div></div>' +
            '<div class="item"><div class="label">Trust</div><div class="value">' + escapeHtml(String(trustLabel)) + ' (' + escapeHtml(String(trustScore)) + ')</div></div>' +
            '<div class="item"><div class="label">Strength</div><div class="value">' + escapeHtml(String(strength)) + '</div></div>' +
            '<div class="item"><div class="label">Latest Asymmetry</div><div class="value">' + fmtAsym(asym) + '</div></div>' +
            '<div class="item"><div class="label">Move Since Entry</div><div class="value">' + fmtPct(move, 1) + '</div></div>' +
            '<div class="item"><div class="label">Stock Score</div><div class="value">' + escapeHtml(String(stockScore)) + '</div></div>' +
        '</div>' +
        '<div class="why-subtitle">Rule checks that passed</div>' +
        '<ul class="why-points">' + pointsHtml + '</ul>' +
        '<div class="why-subtitle">Top broker contributors</div>' +
        '<div class="why-mini-table-wrap"><table class="why-mini-table"><tr>' +
            '<th>Broker</th><th>Trust</th><th>Strength</th><th>State</th><th>Asym</th><th>Cumulative</th>' +
        '</tr>' + contributorsHtml + '</table></div>';

    backdrop.classList.add('open');
    backdrop.setAttribute('aria-hidden', 'false');
}

function closeWhyModal() {
    var backdrop = document.getElementById('why_modal_backdrop');
    if (!backdrop) return;
    backdrop.classList.remove('open');
    backdrop.setAttribute('aria-hidden', 'true');
}

function onWhyBackdropClick(e) {
    if (e && e.target && e.target.id === 'why_modal_backdrop') {
        closeWhyModal();
    }
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeWhyModal();
    }
});

function toggleBroker(sectionId, brokerId) {
    toggleSection(sectionId);
    var el = document.getElementById(sectionId);
    if (!el) return;
    if (!el.classList.contains('hidden')) {
        renderBroker(brokerId);
    }
}

function renderBroker(brokerId) {
    var section = document.getElementById('broker_' + brokerId);
    if (!section || section.dataset.loaded === '1') return;

    var script = document.getElementById('bt_data_' + brokerId);
    if (!script) return;

    var data = null;
    try {
        data = JSON.parse(script.textContent || '{}');
    } catch(e) {
        data = null;
    }
    if (!data) return;

    // Position history table
    var rows = data.rows || [];
    var tableHtml = '<table>' +
        '<tr>' +
        '<th>Date</th><th>Symbol</th><th>Sector</th>' +
        '<th>Bought</th><th>Sold</th><th>Net</th><th>Cumulative</th>' +
        '<th>Avg Buy</th><th>Avg Sell</th><th>Asym</th><th>State</th><th>Unrealized P&L</th>' +
        '</tr>';

    for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var date = r[0];
        var sym = r[1];
        var sector = r[2];
        var bq = r[3];
        var sq = r[4];
        var nq = r[5];
        var cq = r[6];
        var abp = r[7];
        var asp = r[8];
        var asym = r[9];
        var state = r[10];
        var pnl = r[11];

        tableHtml += '<tr class="' + rowClass(state) + '">' +
            '<td>' + escapeHtml(date) + '</td>' +
            '<td class="symbol">' + escapeHtml(sym) + '</td>' +
            '<td>' + escapeHtml(sector || '—') + '</td>' +
            '<td>' + fmtInt(bq) + '</td>' +
            '<td>' + fmtInt(sq) + '</td>' +
            '<td>' + fmtInt(nq) + '</td>' +
            '<td>' + fmtInt(cq) + '</td>' +
            '<td>' + fmtPrice(abp) + '</td>' +
            '<td>' + fmtPrice(asp) + '</td>' +
            '<td>' + fmtAsym(asym) + '</td>' +
            '<td>' + stateBadge(state) + '</td>' +
            '<td>' + (pnl === null || pnl === undefined ? '—' : fmtInt(Math.round(Number(pnl)))) + '</td>' +
            '</tr>';
    }
    tableHtml += '</table>';

    var tableWrap = document.getElementById('bt_table_' + brokerId);
    if (tableWrap) {
        tableWrap.innerHTML = '<div class="table-wrap">' + tableHtml + '</div>';
    }

    // Timeline
    var tl = data.timeline || {};
    var symbols = Object.keys(tl).sort();
    var tlHtml = '';
    for (var j = 0; j < symbols.length; j++) {
        var s = symbols[j];
        var parts = tl[s] || [];
        var segs = [];
        for (var k = 0; k < parts.length; k++) {
            var st = parts[k][0];
            var d = parts[k][1];
            segs.push('[' + escapeHtml(st) + ' ' + escapeHtml(d) + ']');
        }
        tlHtml += '<div><b>' + escapeHtml(s) + '</b>: ' + segs.join(' → ') + '</div>';
    }

    var tlEl = document.getElementById('bt_timeline_' + brokerId);
    if (tlEl) {
        tlEl.innerHTML = tlHtml || '<span class="subtle">—</span>';
    }

    section.dataset.loaded = '1';
}
"""


def _json_for_script(obj: Any) -> str:
        """Minified JSON safe to embed inside a <script> tag."""
        s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        # Prevent accidental </script> termination.
        return s.replace("</", "<\\/")


def _data_summary_cards(meta: dict[str, Any]) -> str:
    return f"""
<div class="card">
  <div class="card-header">
    <div>
      <div class="card-title">📊 Data Summary</div>
      <div class="subtle">Date range: {html.escape(str(meta.get('min_date','—')))} → {html.escape(str(meta.get('max_date','—')))}</div>
    </div>
    <div class="subtle">Generated: {html.escape(meta.get('generated_at',''))}</div>
  </div>
  <div class="kv">
    <div><div class="k">Brokers tracked</div><div class="v">{fmt_int(meta.get('brokers_tracked'))}</div></div>
    <div><div class="k">Stocks covered</div><div class="v">{fmt_int(meta.get('stocks_covered'))}</div></div>
    <div><div class="k">Total transactions</div><div class="v">{fmt_int(meta.get('total_transactions'))}</div></div>
    <div><div class="k">Trading sessions</div><div class="v">{fmt_int(meta.get('trading_sessions'))}</div></div>
  </div>
</div>
"""


def _signal_why_payload(r: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "signal_type": str(r.get("signal_type") or kind),
        "symbol": str(r.get("symbol") or ""),
        "broker_id": r.get("broker_id"),
        "broker_name": str(r.get("broker_name") or ""),
        "broker_count": r.get("broker_count"),
        "broker_ids": r.get("broker_ids") if isinstance(r.get("broker_ids"), list) else [],
        "contributors": r.get("contributors") if isinstance(r.get("contributors"), list) else [],
        "broker_trust_label": str(r.get("broker_trust_label") or "UNRATED"),
        "broker_trust_score": r.get("broker_trust_score"),
        "stock_score": r.get("stock_score"),
        "current_state": str(r.get("current_state") or ""),
        "signal_strength": str(r.get("signal_strength") or ""),
        "latest_asymmetry": r.get("latest_asymmetry"),
        "price_move_since_entry_pct": r.get("price_move_since_entry_pct"),
        "why_summary": str(r.get("why_summary") or ""),
        "why_points": r.get("why_points") if isinstance(r.get("why_points"), list) else [],
        "recent_sessions": r.get("recent_sessions") if isinstance(r.get("recent_sessions"), list) else [],
    }


def _select_top_rows(rows: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    if not rows:
        return []
    return rows[:top_n]


def _signals_table(title: str, icon: str, rows: list[dict[str, Any]], kind: str) -> str:
    # kind: BUY/WATCH/EXIT for styling
    if not rows:
        return f"""
<div class="card">
  <div class="card-header"><div class="card-title">{icon} {html.escape(title)}</div><div class="small">No signals</div></div>
  <div class="subtle">—</div>
</div>
"""

    total_rows = len(rows)
    rows = _select_top_rows(rows, TOP_N_SIGNALS)

    if kind in ("BUY", "WATCH"):
        th = """<tr>
<th>Symbol</th><th>Brokers</th><th>Trust</th>
<th>Avg Buy</th><th>Current</th><th>Move %</th><th>Asym</th><th>Strength</th><th>Score</th>
</tr>"""
        tr = ""
        for r in rows:
            why_json = html.escape(json.dumps(_signal_why_payload(r, kind), ensure_ascii=False), quote=True)
            tr += "<tr>" \
                f"<td class='symbol'><button type='button' class='symbol-link' data-why=\"{why_json}\" onclick='openWhyFromSymbol(this)'>{html.escape(str(r.get('symbol','')))}</button></td>" \
                                f"<td>{fmt_int(r.get('broker_count'))}</td>" \
                f"<td>{trust_badge(str(r.get('broker_trust_label')), r.get('broker_trust_score'))}</td>" \
                f"<td>{fmt_price(r.get('avg_buy_price'))}</td>" \
                f"<td>{fmt_price(r.get('current_price'))}</td>" \
                f"<td>{fmt(r.get('price_move_since_entry_pct'),1)}%</td>" \
                f"<td>{fmt(r.get('latest_asymmetry'),0)}%</td>" \
                                f"<td>{badge(str(r.get('signal_strength','')), 'bg-green' if kind=='BUY' else 'bg-yellow')}</td>" \
                                f"<td>{fmt(r.get('stock_score'),1)}</td>" \
                "</tr>\n"
        return f"""
<div class="card">
        <div class="card-header"><div class="card-title">{icon} {html.escape(title)} ({total_rows} total)</div><div class="small">Top {TOP_N_SIGNALS}</div></div>
  <div class="table-wrap"><table>{th}{tr}</table></div>
</div>
"""

    # EXIT
    th = """<tr>
<th>Symbol</th><th>Brokers</th><th>Trust</th><th>State Changed</th>
<th>Qty Remaining</th><th>Avg Buy</th><th>Current</th><th>P&L If Held</th><th>Score</th>
</tr>"""
    tr = ""
    for r in rows:
        why_json = html.escape(json.dumps(_signal_why_payload(r, kind), ensure_ascii=False), quote=True)
        pnl = r.get("pnl_if_held")
        pnl_cls = "bg-green" if pnl is not None and pnl > 0 else "bg-red" if pnl is not None and pnl < 0 else "bg-muted"
        tr += "<tr>" \
            f"<td class='symbol'><button type='button' class='symbol-link' data-why=\"{why_json}\" onclick='openWhyFromSymbol(this)'>{html.escape(str(r.get('symbol','')))}</button></td>" \
            f"<td>{fmt_int(r.get('broker_count'))}</td>" \
            f"<td>{trust_badge(str(r.get('broker_trust_label')), r.get('broker_trust_score'))}</td>" \
            f"<td>{badge('YES' if r.get('state_changed') else '—', 'bg-red')}</td>" \
            f"<td>{fmt_int(r.get('cumulative_net_qty'))}</td>" \
            f"<td>{fmt_price(r.get('avg_buy_price'))}</td>" \
            f"<td>{fmt_price(r.get('current_price'))}</td>" \
            f"<td>{badge(fmt(pnl,0), pnl_cls)}</td>" \
            f"<td>{fmt(r.get('stock_score'),1)}</td>" \
            "</tr>\n"

    return f"""
<div class="card">
    <div class="card-header"><div class="card-title">{icon} {html.escape(title)} ({total_rows} total)</div><div class="small">Top {TOP_N_SIGNALS}</div></div>
  <div class="table-wrap"><table>{th}{tr}</table></div>
</div>
"""


def _leaderboard_table(profiles: list[dict[str, Any]]) -> str:
    if not profiles:
        return """
<div class="card"><div class="card-header"><div class="card-title">🏆 Broker Leaderboard</div></div><div class="subtle">No brokers</div></div>
"""

    th = """<tr>
<th>Rank</th><th>Broker</th><th>Trust</th><th>Win Rate</th><th>Cycles</th>
<th>Avg Hold</th><th>Preferred Sectors</th><th>Accumulating</th><th>Distributing</th>
</tr>"""
    tr = ""
    for i, p in enumerate(profiles, 1):
        win_rate = p.get("win_rate")
        win_rate_txt = f"{float(win_rate)*100:.0f}%" if win_rate is not None else "—"
        tr += "<tr>" \
            f"<td>{i}</td>" \
            f"<td><span class='symbol'>{html.escape(str(p.get('broker_id')))}</span> — {html.escape(str(p.get('broker_name') or ''))}</td>" \
            f"<td>{trust_badge(str(p.get('trust_label')), p.get('trust_score'))}</td>" \
            f"<td>{win_rate_txt}</td>" \
            f"<td>{fmt_int(p.get('completed_cycles'))}</td>" \
            f"<td>{fmt(p.get('avg_hold_sessions'),1)}</td>" \
            f"<td>{html.escape(', '.join(p.get('preferred_sectors') or [])) or '—'}</td>" \
            f"<td>{html.escape(', '.join(p.get('currently_accumulating') or [])) or '—'}</td>" \
            f"<td>{html.escape(', '.join(p.get('currently_distributing') or [])) or '—'}</td>" \
            "</tr>\n"

    return f"""
<div class="card">
  <div class="card-header"><div class="card-title">🏆 Broker Leaderboard</div><div class="small">Ranked by trust (or value if unrated)</div></div>
  <div class="table-wrap"><table>{th}{tr}</table></div>
</div>
"""


def _broker_deep_dives(
    profiles: list[dict[str, Any]],
    broker_payload_json_by_id: dict[int, str],
) -> str:
        if not profiles:
                return """
<div class="card"><div class="card-header"><div class="card-title">🧩 Per-Broker Deep Dives</div></div><div class="subtle">No data</div></div>
"""

        h = (
                '<div class="card">'
                '<div class="card-header">'
                '<div class="card-title">🧩 Per-Broker Deep Dives</div>'
                '<div class="small">Click to expand</div>'
                '</div>'
        )

        for p in profiles:
                bid = int(p.get("broker_id") or 0)
                name = str(p.get("broker_name") or "")
                tid = f"broker_{bid}"

                trust = trust_badge(str(p.get("trust_label")), p.get("trust_score"))
                maturity = badge(
                        str(p.get("data_maturity")),
                        "bg-yellow" if p.get("data_maturity") == "LOW" else "bg-muted",
                )

                h += f"""
<div class="toggle" onclick="toggleBroker('{tid}', {bid})">
    <div><span class="symbol">Broker {bid}</span> — {html.escape(name)} <span class="small">({fmt_int(p.get('total_stocks_traded'))} stocks)</span></div>
    <div>{trust} {maturity}</div>
</div>
<div id="{tid}" class="hidden" data-loaded="0" style="margin-top:12px;margin-bottom:18px;">
    <div class="grid-3" style="margin-bottom:12px;">
        <div class="card" style="margin-bottom:0;">
            <div class="card-header"><div class="card-title">Summary</div></div>
            <div class="small">
                Completed cycles: <b>{fmt_int(p.get('completed_cycles'))}</b><br>
                Win rate: <b>{(str(int(float(p.get('win_rate') or 0)*100))+'%') if p.get('win_rate') is not None else '—'}</b><br>
                Avg hold (sessions): <b>{fmt(p.get('avg_hold_sessions'),1)}</b><br>
                Avg buy size: <b>{fmt_price(p.get('avg_position_size_rs'))}</b>
            </div>
        </div>
        <div class="card" style="margin-bottom:0;">
            <div class="card-header"><div class="card-title">Preferred Sectors</div></div>
            <div class="small">{html.escape(', '.join(p.get('preferred_sectors') or [])) or '—'}</div>
        </div>
        <div class="card" style="margin-bottom:0;">
            <div class="card-header"><div class="card-title">Current Focus</div></div>
            <div class="small">
                Accumulating: {html.escape(', '.join(p.get('currently_accumulating') or [])) or '—'}<br>
                Distributing: {html.escape(', '.join(p.get('currently_distributing') or [])) or '—'}
            </div>
        </div>
    </div>
"""

                payload_json = broker_payload_json_by_id.get(
                        bid, _json_for_script({"rows": [], "timeline": {}})
                )

                h += f"""
    <div class="card" style="margin-bottom:12px;">
        <div class="card-header"><div class="card-title">Position History</div><div class="small">Trades only</div></div>
        <div id="bt_table_{bid}"><span class="subtle">Expand to load…</span></div>
    </div>
    <div class="card" style="margin-bottom:0;">
        <div class="card-header"><div class="card-title">State Transition Timeline</div></div>
        <div id="bt_timeline_{bid}" class="small"><span class="subtle">Expand to load…</span></div>
    </div>
    <script type="application/json" id="bt_data_{bid}">{payload_json}</script>
</div>
"""

        h += "</div>"  # end main card
        return h


def _stock_level_activity(
    signals_symbols: list[str],
    summary_df: pd.DataFrame,
    latest_prices: dict[str, dict[str, Any]] | None,
) -> str:
    latest_prices = latest_prices or {}

    if not signals_symbols:
        return """
<div class="card"><div class="card-header"><div class="card-title">📊 Stock-Level Broker Activity</div></div><div class="subtle">No active-signal symbols</div></div>
"""

    th = """<tr>
<th>Symbol</th><th>Current Price</th><th>Brokers Accumulating</th><th>Brokers Distributing</th><th>Net Sentiment</th>
</tr>"""
    tr = ""

    for sym in sorted(set(signals_symbols)):
        s = summary_df.loc[summary_df["symbol"] == sym] if summary_df is not None and not summary_df.empty else pd.DataFrame()
        acc = s.loc[s["session_state"] == "ACCUMULATING", "broker_id"].tolist() if not s.empty else []
        dist = s.loc[s["session_state"].isin(["DISTRIBUTING", "EXITING"]), "broker_id"].tolist() if not s.empty else []

        sentiment = len(acc) - len(dist)
        sentiment = max(-5, min(5, sentiment))

        cur_price = None
        try:
            cur_price = latest_prices.get(sym, {}).get("close_price")
        except Exception:
            cur_price = None

        tr += "<tr>" \
            f"<td class='symbol'>{html.escape(sym)}</td>" \
            f"<td>{fmt_price(cur_price)}</td>" \
            f"<td>{html.escape(', '.join([str(x) for x in acc]) or '—')}</td>" \
            f"<td>{html.escape(', '.join([str(x) for x in dist]) or '—')}</td>" \
            f"<td>{badge(str(sentiment), 'bg-green' if sentiment>0 else 'bg-red' if sentiment<0 else 'bg-muted')}</td>" \
            "</tr>\n"

    return f"""
<div class="card">
  <div class="card-header"><div class="card-title">📊 Stock-Level Broker Activity</div><div class="small">Only symbols with active signals</div></div>
  <div class="table-wrap"><table>{th}{tr}</table></div>
</div>
"""


def _build_broker_payload_json_by_id(
    profiles: list[dict[str, Any]],
    sessions_df: pd.DataFrame | None,
    transitions: dict[tuple[int, str], list[dict[str, Any]]],
    sector_map: dict[str, dict[str, Any]] | None,
) -> dict[int, str]:
    """Build compact (minified) per-broker JSON payloads for the HTML report.

    Payload contains:
    - rows: trades-only session rows (no synthetic HOLDING rows)
    - timeline: state transitions per symbol
    """
    sector_map = sector_map or {}
    wanted = {int(p.get("broker_id") or 0) for p in (profiles or []) if p.get("broker_id") is not None}

    def _none(v):
        try:
            if v is None or pd.isna(v):
                return None
        except Exception:
            if v is None:
                return None
        return v

    def _f(v, nd=2):
        v = _none(v)
        if v is None:
            return None
        try:
            return round(float(v), nd)
        except Exception:
            return None

    # Build timelines per broker
    timeline_by_broker: dict[int, dict[str, list[list[str]]]] = {}
    for (bid, sym), arc in (transitions or {}).items():
        try:
            bid_int = int(bid)
        except Exception:
            continue
        if wanted and bid_int not in wanted:
            continue
        sym_str = str(sym)
        parts: list[list[str]] = []
        for a in arc or []:
            st = a.get("state")
            d = a.get("trading_date")
            if not st:
                continue
            parts.append([str(st), str(d) if d is not None else ""])
        if parts:
            timeline_by_broker.setdefault(bid_int, {})[sym_str] = parts

    payload_json_by_id: dict[int, str] = {}

    # Default payloads for brokers with no rows
    for bid in wanted:
        payload_json_by_id[bid] = _json_for_script({"rows": [], "timeline": timeline_by_broker.get(bid, {})})

    if sessions_df is None or sessions_df.empty or not wanted:
        return payload_json_by_id

    df = sessions_df
    if "is_synthetic" in df.columns:
        df = df.loc[(~df["is_synthetic"]) & (df["total_qty"] > 0)].copy()
    else:
        df = df.copy()

    needed_cols = [
        "trading_date",
        "symbol",
        "bought_qty",
        "sold_qty",
        "net_qty",
        "cumulative_net_qty",
        "avg_buy_price",
        "avg_sell_price",
        "asymmetry",
        "session_state",
        "unrealized_pnl",
        "broker_id",
    ]
    for c in needed_cols:
        if c not in df.columns:
            return payload_json_by_id

    df = df[needed_cols]

    for bid, g in df.groupby("broker_id", dropna=False):
        try:
            bid_int = int(bid)
        except Exception:
            continue
        if bid_int not in wanted:
            continue

        g = g.sort_values(["symbol", "trading_date"], ascending=True)
        rows: list[list[Any]] = []

        for r in g.itertuples(index=False):
            sym = str(getattr(r, "symbol")) if getattr(r, "symbol") is not None else ""
            sector = (sector_map.get(sym) or {}).get("sector_name")
            rows.append(
                [
                    str(getattr(r, "trading_date")),
                    sym,
                    sector,
                    int(_none(getattr(r, "bought_qty")) or 0),
                    int(_none(getattr(r, "sold_qty")) or 0),
                    int(_none(getattr(r, "net_qty")) or 0),
                    int(_none(getattr(r, "cumulative_net_qty")) or 0),
                    _f(getattr(r, "avg_buy_price"), 2),
                    _f(getattr(r, "avg_sell_price"), 2),
                    _f(getattr(r, "asymmetry"), 1),
                    str(getattr(r, "session_state") or ""),
                    _f(getattr(r, "unrealized_pnl"), 2),
                ]
            )

        payload_json_by_id[bid_int] = _json_for_script({"rows": rows, "timeline": timeline_by_broker.get(bid_int, {})})

    return payload_json_by_id


def build_html(report: dict[str, Any]) -> str:
    """Build full HTML report."""
    meta = report.get("meta", {})
    buy_signals = report.get("buy_signals", [])
    watch_signals = report.get("watch_signals", [])
    exit_signals = report.get("exit_signals", [])
    profiles = report.get("profiles", [])
    sessions_df = report.get("sessions_df")
    summary_df = report.get("summary_df")
    transitions = report.get("transitions", {})
    sector_map = report.get("sector_map", {})
    latest_prices = report.get("latest_prices", {})

    signals_symbols = [s.get("symbol") for s in (buy_signals + watch_signals + exit_signals) if s.get("symbol")]

    maturity_banner = ""
    if int(meta.get("trading_sessions") or 0) < 30:
        maturity_banner = '<div class="banner">⚠ Data maturity: LOW (&lt; 30 trading sessions of floorsheet history)</div>'

    leaderboard = _leaderboard_table(profiles)

    broker_payload_json_by_id = _build_broker_payload_json_by_id(
        profiles=profiles,
        sessions_df=sessions_df,
        transitions=transitions,
        sector_map=sector_map,
    )

    deep_dives = _broker_deep_dives(
        profiles=profiles,
        broker_payload_json_by_id=broker_payload_json_by_id,
    )

    stock_activity = _stock_level_activity(
        signals_symbols=signals_symbols,
        summary_df=summary_df,
        latest_prices=latest_prices,
    )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>NEPSE Broker Tracker</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🏦 NEPSE Broker Tracker</h1>
      <p>Broker accumulation/distribution lifecycle + signals</p>
    </div>

    {maturity_banner}

    {_data_summary_cards(meta)}

    <div class="grid-3">
      {_signals_table('BUY Signals', '🚨', buy_signals, 'BUY')}
      {_signals_table('WATCH Signals', '👁', watch_signals, 'WATCH')}
      {_signals_table('EXIT Signals', '⚠', exit_signals, 'EXIT')}
    </div>

    {leaderboard}

    {deep_dives}

    {stock_activity}

    <div class="footer">Generated by Broker Tracker • {html.escape(meta.get('generated_at',''))}</div>
  </div>

    <div id="why_modal_backdrop" class="why-modal-backdrop" aria-hidden="true" onclick="onWhyBackdropClick(event)">
        <div class="why-modal" role="dialog" aria-modal="true" aria-labelledby="why_modal_title">
            <div class="why-modal-head">
                <div id="why_modal_title" class="why-modal-title">Why this signal?</div>
                <button type="button" class="why-close" onclick="closeWhyModal()">Close</button>
            </div>
            <div id="why_modal_body"></div>
        </div>
    </div>

  <script>{JS}</script>
</body>
</html>
"""

    return html_out


def write_report(html_text: str, output_dir: str | None = None) -> str:
    """Write HTML report to disk and return filepath."""
    if output_dir is None:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(root_dir, OUTPUT_DIR)

    os.makedirs(output_dir, exist_ok=True)

    now = datetime.now()
    currentdate = now.strftime("%Y-%m-%d")
    filename = f"broker_tracker_{currentdate}.html"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_text)
    return filepath
