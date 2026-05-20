"""Unified HTML report generator for NEPSE Master Trader."""

from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from typing import Any


def _fmt(v: Any, decimals: int = 2) -> str:
    if v is None:
        return "-"
    try:
        n = float(v)
        if abs(n) >= 1e9:
            return f"{n / 1e9:.{decimals}f}B"
        if abs(n) >= 1e6:
            return f"{n / 1e6:.{decimals}f}M"
        if abs(n) >= 1e3:
            return f"{n / 1e3:.{decimals}f}K"
        return f"{n:,.{decimals}f}"
    except Exception:
        return str(v)


def _esc(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return escape(str(v), quote=True)
    except Exception:
        return "-"


def _fmt_price(v: Any) -> str:
  try:
    return f"Rs {float(v):,.2f}"
  except Exception:
    return "-"


def _fmt_money(v: Any, decimals: int = 2) -> str:
    t = _fmt(v, decimals)
    return "-" if t == "-" else f"Rs {t}"


def _fmt_ratio(v: Any) -> str:
    try:
        return f"{float(v):.2f}x"
    except Exception:
        return "-"


def _fmt_pct(v: Any) -> str:
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "-"


def _id_token(value: Any) -> str:
  text = str(value or "x")
  out = []
  for ch in text:
    if ch.isalnum():
      out.append(ch.lower())
    else:
      out.append("-")
  token = "".join(out)
  while "--" in token:
    token = token.replace("--", "-")
  token = token.strip("-")
  return token or "x"


def _flow_badge(signal: Any) -> str:
  raw = str(signal or "NO_FLOW").upper()
  labels = {
    "BUY_HEAVY": "BUY HEAVY",
    "SELL_HEAVY": "SELL HEAVY",
    "TWO_WAY": "TWO-WAY",
    "NO_FLOW": "NO FLOW",
  }
  cls = {
    "BUY_HEAVY": "flow-buy",
    "SELL_HEAVY": "flow-sell",
    "TWO_WAY": "flow-mixed",
    "NO_FLOW": "flow-neutral",
  }.get(raw, "flow-neutral")
  label = labels.get(raw, raw.replace("_", " "))
  return f"<span class='flow-badge {cls}'>{_esc(label)}</span>"


def _convergence_badge(flag: Any) -> str:
  raw = str(flag or "NONE").upper()
  labels = {
    "HIGH_TRUST_CONVERGENCE": "CONVERGENCE: HIGH",
    "MEDIUM_PLUS_CONVERGENCE": "CONVERGENCE: MED+",
    "SINGLE_HIGH_TRUST": "CONVERGENCE: SINGLE",
    "NONE": "CONVERGENCE: NONE",
  }
  cls = {
    "HIGH_TRUST_CONVERGENCE": "flow-buy",
    "MEDIUM_PLUS_CONVERGENCE": "flow-mixed",
    "SINGLE_HIGH_TRUST": "flow-neutral",
    "NONE": "flow-neutral",
  }.get(raw, "flow-neutral")
  label = labels.get(raw, raw.replace("_", " "))
  return f"<span class='flow-badge {cls}'>{_esc(label)}</span>"


def _formal_exit_badge(formal_exit: Any, signal_bias: Any, trust_label: Any) -> str:
  is_formal_exit = bool(formal_exit)
  raw_signal = str(signal_bias or "WATCH").upper()
  raw_trust = str(trust_label or "UNRATED").upper()

  if is_formal_exit:
    return "<span class='flow-badge flow-sell'>FORMAL EXIT: YES</span>"
  if raw_signal == "EXIT":
    if raw_trust in {"LOW", "UNRATED"}:
      return "<span class='flow-badge flow-mixed'>EXIT SIGNAL: LOW TRUST</span>"
    return "<span class='flow-badge flow-mixed'>EXIT SIGNAL: UNCONFIRMED</span>"
  return "<span class='flow-badge flow-neutral'>FORMAL EXIT: NO</span>"


def _bucket_badge(label: str) -> str:
    colors = {
        "short": "#00e5ff",
        "swing": "#00e676",
        "long": "#ffd740",
    }
    c = colors.get(label, "#90a4ae")
    return f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:rgba(0,0,0,0.25);border:1px solid {c};color:{c};font-size:0.75em">{_esc(label).upper()}</span>'


def _action_badge(action: Any) -> str:
    label = str(action or "WATCH").upper()
    cls = {
        "BUY": "action-buy",
        "WATCH": "action-watch",
        "AVOID": "action-avoid",
    }.get(label, "action-watch")
    return f'<span class="action-badge {cls}">{_esc(label)}</span>'


def _criterion_item(text: Any) -> str:
    content = str(text or "-")
    upper = content.upper()
    if upper.startswith("PASS:"):
        cls = "crit-pass"
        tag = "PASS"
    elif upper.startswith("FAIL:"):
        cls = "crit-fail"
        tag = "FAIL"
    else:
        cls = "crit-neutral"
        tag = "INFO"
    return (
        f"<div class='crit-item {cls}'>"
        f"<span class='crit-tag'>{tag}</span>"
        f"<span>{_esc(content)}</span>"
        "</div>"
    )


def _bullet_lines(items: list[Any], empty_text: str, item_cls: str) -> str:
    if not items:
        return f"<div class='muted'>{_esc(empty_text)}</div>"
    rows = "".join(f"<div class='{item_cls}'>{_esc(item)}</div>" for item in items)
    return rows


def _plan_detail_cards(plans: list[dict[str, Any]], section_key: str) -> str:
    if not plans:
        return ""

    section_id = _id_token(section_key)
    index_rows = ""
    cards = ""

    for p in plans:
        symbol = str(p.get("symbol", "-"))
        detail_id = f"detail-{section_id}-{_id_token(symbol)}"

        criteria = p.get("bucket_criteria", [])
        criteria_html = "".join(_criterion_item(item) for item in criteria[:6])
        criteria_preview = "<br>".join(_esc(item) for item in criteria[:2]) or "<span class='muted'>No criteria captured.</span>"
        strengths_html = _bullet_lines(p.get("strengths", [])[:5], "No major strengths captured.", "line strength")
        weaknesses_html = _bullet_lines(p.get("weaknesses", [])[:5], "No major weaknesses captured.", "line weakness")
        setup_html = _bullet_lines(p.get("setup_reasoning", [])[:5], "No setup reasoning available.", "line")

        sector_rank = p.get("sector_rank")
        sector_size = p.get("sector_size")
        sector_ctx = "-" if sector_rank is None else f"{int(sector_rank)}/{int(sector_size or 0)}"
        ratio_text = _fmt_ratio(p.get("broker_buy_sell_ratio"))
        broker_state = str(p.get("broker_state") or "-")
        broker_signal_bias = str(p.get("broker_signal_bias") or "WATCH")
        broker_signal_strength = str(p.get("broker_signal_strength") or "WEAK")
        broker_trust = str(p.get("broker_trust_label") or "UNRATED")
        broker_maturity = str(p.get("broker_data_maturity") or "LOW")
        high_trust_accum = int(float(p.get("high_trust_accum_brokers") or 0))
        medium_plus_accum = int(float(p.get("medium_plus_accum_brokers") or 0))
        convergence_badge = _convergence_badge(p.get("broker_convergence_flag"))
        formal_exit_badge = _formal_exit_badge(p.get("broker_formal_exit"), broker_signal_bias, broker_trust)
        veto_reasons = p.get("veto_reasons") or []
        veto_preview = ", ".join(_esc(v) for v in veto_reasons[:3]) if veto_reasons else "none"

        buy_brokers = p.get("top_buy_brokers", [])
        sell_brokers = p.get("top_sell_brokers", [])
        buy_brokers_text = ", ".join(_esc(item) for item in buy_brokers[:3]) if buy_brokers else "-"
        sell_brokers_text = ", ".join(_esc(item) for item in sell_brokers[:3]) if sell_brokers else "-"

        index_rows += f"""
      <tr>
        <td><strong>{_esc(symbol)}</strong></td>
        <td>{_esc(p.get('sector', 'Other'))}</td>
        <td style='text-align:center'>{_action_badge(p.get('action_label'))}</td>
        <td style='text-align:center'>{_fmt(p.get('score'), 1)}</td>
        <td style='text-align:right'>{_fmt_money(p.get('broker_buy_amt'))}</td>
        <td style='text-align:right'>{_fmt_money(p.get('broker_sell_amt'))}</td>
        <td style='text-align:center'>{ratio_text}</td>
        <td style='text-align:center'>{_flow_badge(p.get('broker_flow_signal'))}</td>
        <td class='muted' style='font-size:0.78rem'>{criteria_preview}</td>
        <td style='text-align:center'>
          <button class='view-btn' type='button' onclick="showPlanDetail('{detail_id}')">View</button>
        </td>
      </tr>
"""

        cards += f"""
      <article class="detail-card stock-detail-card" id="{detail_id}" style="display:none">
        <div class="detail-head">
          <div>
            <div class="sym">{_esc(symbol)}</div>
            <div class="muted" style="font-size:0.82rem">{_esc(p.get('sector', 'Other'))}</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            {_flow_badge(p.get('broker_flow_signal'))}
            {_action_badge(p.get('action_label'))}
            <span class="muted">score {_fmt(p.get('score'), 1)}</span>
            <button class="detail-close" type="button" onclick="hidePlanDetail('{detail_id}')">Close</button>
          </div>
        </div>

        <div class="detail-grid-two">
          <div class="detail-block">
            <h4>Selection Criteria</h4>
            {criteria_html or '<div class="muted">No criteria available.</div>'}
          </div>
          <div class="detail-block">
            <h4>Setup Reasoning</h4>
            {setup_html}
          </div>
          <div class="detail-block">
            <h4>Why Buy</h4>
            {strengths_html}
          </div>
          <div class="detail-block">
            <h4>Why Sell Or Trim Risk</h4>
            {weaknesses_html}
          </div>
          <div class="detail-block detail-risk">
            <h4>Risk Snapshot</h4>
            <div class="line">Fused Score: {_fmt(p.get('fused_score'), 2)}</div>
            <div class="line">Priority Tier: {_esc(p.get('priority_tier') or '-')}</div>
            <div class="line">Execution Confidence: {_fmt(p.get('execution_confidence'), 1)}</div>
            <div class="line">Data Quality Grade: {_esc(p.get('data_quality_grade') or '-')}</div>
            <div class="line">Broker Alignment: {_esc(p.get('broker_alignment_flag') or '-')}</div>
            <div class="line">R:R: {_fmt(p.get('rr_ratio'), 2)}</div>
            <div class="line">Sector Rank: {_esc(sector_ctx)}</div>
            <div class="line">Broker Asym: {_fmt(p.get('broker_asym'), 1)}</div>
            <div class="line">RS Delta: {_fmt_pct(p.get('rs_delta'))}</div>
            <div class="line">Volatility 20D: {_fmt(p.get('vol_20d'), 2)}%</div>
            <div class="line">Max Drawdown: {_fmt(p.get('max_drawdown'), 2)}%</div>
            <div class="line">Plan Size Multiplier: {_fmt(p.get('broker_size_multiplier'), 2)}x</div>
            <div class="line">Expected Slippage: {_esc(p.get('expected_slippage_band') or '-')}</div>
            <div class="line">Plan Validity: {_esc(p.get('plan_validity_window') or '-')}</div>
            <div class="line">Veto Reasons: {veto_preview}</div>
          </div>
          <div class="detail-block">
            <h4>Broker Flow (Top 3 Brokers)</h4>
            <div class="line">Buy Amount: {_fmt_money(p.get('broker_buy_amt'))}</div>
            <div class="line">Sell Amount: {_fmt_money(p.get('broker_sell_amt'))}</div>
            <div class="line">Buy/Sell Ratio: {ratio_text}</div>
            <div class="line">Intensity: {_fmt_money(p.get('broker_flow_intensity'))}</div>
            <div class="line">Lifecycle State: {_esc(broker_state)}</div>
            <div class="line">Signal: {_esc(broker_signal_bias)} ({_esc(broker_signal_strength)})</div>
            <div class="line">Trust / Maturity: {_esc(broker_trust)} / {_esc(broker_maturity)}</div>
            <div class="line">Convergence Marker: {convergence_badge} (HT {high_trust_accum} | MED+ {medium_plus_accum})</div>
            <div class="line">Formal Broker EXIT Marker: {formal_exit_badge}</div>
            <div class="line">Top Buyers: {buy_brokers_text}</div>
            <div class="line">Top Sellers: {sell_brokers_text}</div>
          </div>
        </div>
      </article>
"""

    return f"""
  <div class="detail-wrap">
    <h3>Why These Stocks</h3>
    <p class="muted" style="margin-top:0;margin-bottom:10px">Use View to inspect each stock's full reasoning and broker-flow context.</p>
    <div style="overflow-x:auto">
      <table class="table detail-index-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Sector</th>
            <th style="text-align:center">Action</th>
            <th style="text-align:center">Score</th>
            <th style="text-align:right">Buy Amt</th>
            <th style="text-align:right">Sell Amt</th>
            <th style="text-align:center">B/S Ratio</th>
            <th style="text-align:center">Flow</th>
            <th>Criteria Snapshot</th>
            <th style="text-align:center">Details</th>
          </tr>
        </thead>
        <tbody>{index_rows}</tbody>
      </table>
    </div>
    <div class="detail-stack">{cards}</div>
  </div>
"""


def _build_ranking_detail_payload(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows, start=1):
        key = f"rk-{i}"
        flags = row.get("bucket_flags") or {}
        reasons = row.get("bucket_reasons") or {}
        raw_entry_zone = row.get("entry_zone")
        entry_zone: list[Any] = []
        if isinstance(raw_entry_zone, (list, tuple)) and len(raw_entry_zone) >= 2:
            entry_zone = [raw_entry_zone[0], raw_entry_zone[1]]

        payload[key] = {
            "symbol": str(row.get("symbol") or "-"),
            "company_name": str(row.get("company_name") or ""),
            "sector": str(row.get("sector") or "Other"),
            "price": row.get("price"),
            "entry_zone": entry_zone,
            "atr": row.get("atr"),
            "stop_loss": row.get("stop_loss"),
            "target_1": row.get("target_1"),
            "target_2": row.get("target_2"),
            "score": row.get("score"),
            "fused_score": row.get("fused_score"),
            "priority_tier": row.get("priority_tier"),
            "execution_confidence": row.get("execution_confidence"),
            "data_quality_grade": row.get("data_quality_grade"),
            "broker_alignment_flag": row.get("broker_alignment_flag"),
            "veto_reasons": [str(item) for item in (row.get("veto_reasons") or [])],
            "fused_score_breakdown": row.get("fused_score_breakdown") or {},
            "action_label": str(row.get("action_label") or "WATCH"),
            "tier": f"{row.get('tier_icon', '')} {row.get('tier_name', '-') }".strip(),
            "setup_type": str(row.get("setup_type") or "-"),
            "bucket_flags": {
                "short": bool(flags.get("short")),
                "swing": bool(flags.get("swing")),
                "long": bool(flags.get("long")),
                "hotlist": bool(flags.get("hotlist")),
            },
            "bucket_reasons": {
                name: [str(item) for item in (reasons.get(name) or [])]
                for name in ("short", "swing", "long", "hotlist")
            },
            "setup_reasoning": [str(item) for item in (row.get("setup_reasoning") or [])],
            "strengths": [str(item) for item in (row.get("strengths") or [])],
            "weaknesses": [str(item) for item in (row.get("weaknesses") or [])],
            "rr_ratio": row.get("rr_ratio"),
            "sector_rank": row.get("sector_rank"),
            "sector_size": row.get("sector_size"),
            "broker_asym": row.get("broker_asym"),
            "rs_delta": row.get("rs_delta"),
            "vol_20d": row.get("vol_20d"),
            "max_drawdown": row.get("max_drawdown"),
            "broker_buy_amt": row.get("broker_buy_amt"),
            "broker_sell_amt": row.get("broker_sell_amt"),
            "broker_buy_sell_ratio": row.get("broker_buy_sell_ratio"),
            "broker_flow_signal": str(row.get("broker_flow_signal") or "NO_FLOW"),
            "broker_flow_intensity": row.get("broker_flow_intensity"),
            "broker_state": str(row.get("broker_state") or "-"),
            "broker_signal_bias": str(row.get("broker_signal_bias") or "WATCH"),
            "broker_signal_strength": str(row.get("broker_signal_strength") or "WEAK"),
            "broker_trust_label": str(row.get("broker_trust_label") or "UNRATED"),
            "broker_data_maturity": str(row.get("broker_data_maturity") or "LOW"),
            "broker_size_multiplier": row.get("broker_size_multiplier"),
            "top_buy_brokers": [str(item) for item in (row.get("top_buy_brokers") or [])],
            "top_sell_brokers": [str(item) for item in (row.get("top_sell_brokers") or [])],
        }

    return payload


def _build_ranking_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No ranking rows available.</p>"

    body = ""
    for i, r in enumerate(rows, start=1):
        detail_key = f"rk-{i}"
        sec_rank = r.get("sector_rank")
        sec_size = r.get("sector_size")
        sec_rank_text = "-" if sec_rank is None else f"{int(sec_rank)}/{int(sec_size or 0)}"
        tier_text = _esc(f"{r.get('tier_icon', '')} {r.get('tier_name', '-') }").strip()
        flow_ratio = _fmt_ratio(r.get("broker_buy_sell_ratio"))

        body += (
            "<tr>"
            f"<td style='text-align:center'>{i}</td>"
            f"<td>{_esc(r.get('symbol', '-'))}</td>"
            f"<td>{_esc(r.get('sector', '-'))}</td>"
            f"<td style='text-align:right'>{_fmt_price(r.get('price'))}</td>"
            f"<td style='text-align:center'>{_fmt(r.get('score'), 1)}</td>"
            f"<td style='text-align:center'>{_fmt(r.get('fused_score'), 1)}</td>"
            f"<td style='text-align:center'>{_esc(r.get('priority_tier') or '-')}</td>"
            f"<td style='text-align:center'>{_fmt(r.get('execution_confidence'), 0)}</td>"
            f"<td style='text-align:center'>{_esc(r.get('data_quality_grade') or '-')}</td>"
            f"<td style='text-align:center'>{_esc(r.get('broker_alignment_flag') or '-')}</td>"
            f"<td style='text-align:center'>{_action_badge(r.get('action_label'))}</td>"
            f"<td style='text-align:center'>{tier_text}</td>"
            f"<td>{_esc(r.get('setup_type') or '-')}</td>"
            f"<td style='text-align:center'>{sec_rank_text}</td>"
            f"<td style='text-align:center'>{r.get('sector_rsi_pct') if r.get('sector_rsi_pct') is not None else '-'}</td>"
            f"<td style='text-align:center'>{r.get('scrip_rank_turnover') if r.get('scrip_rank_turnover') is not None else '-'}</td>"
            f"<td style='text-align:center'>{_fmt(r.get('vol_ratio'), 2)}x</td>"
            f"<td style='text-align:center'>{_fmt(r.get('broker_asym'), 1)}</td>"
            f"<td style='text-align:right'>{_fmt_money(r.get('broker_buy_amt'))}</td>"
            f"<td style='text-align:right'>{_fmt_money(r.get('broker_sell_amt'))}</td>"
            f"<td style='text-align:center'>{flow_ratio}</td>"
            f"<td style='text-align:center'>{_flow_badge(r.get('broker_flow_signal'))}</td>"
            f"<td style='text-align:center'><button class='view-btn' type='button' onclick=\"openRankingDetail('{detail_key}')\">View</button></td>"
            "</tr>"
        )

    return (
          "<p class='muted' style='margin:0 0 10px 0'>Use View to inspect full explainability for any ranked symbol.</p>"
        "<div style='overflow-x:auto'>"
        "<table class='table'>"
        "<thead><tr>"
        "<th style='text-align:center'>#</th>"
        "<th>Symbol</th>"
        "<th>Sector</th>"
        "<th style='text-align:right'>Price</th>"
        "<th style='text-align:center'>Score</th>"
        "<th style='text-align:center'>Fused</th>"
        "<th style='text-align:center'>Prio</th>"
        "<th style='text-align:center'>Exec</th>"
        "<th style='text-align:center'>Data Q</th>"
        "<th style='text-align:center'>Alignment</th>"
        "<th style='text-align:center'>Action</th>"
        "<th style='text-align:center'>Tier</th>"
        "<th>Setup</th>"
        "<th style='text-align:center'>Sector Rank</th>"
        "<th style='text-align:center'>Sector RSI%</th>"
        "<th style='text-align:center'>Turnover Rank</th>"
        "<th style='text-align:center'>Vol Ratio</th>"
        "<th style='text-align:center'>Broker Asym</th>"
        "<th style='text-align:right'>Buy Amt</th>"
        "<th style='text-align:right'>Sell Amt</th>"
        "<th style='text-align:center'>B/S Ratio</th>"
        "<th style='text-align:center'>Flow Bias</th>"
        "<th style='text-align:center'>Details</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
        "</div>"
      )


def _default_data_sources() -> list[dict[str, str]]:
    return [
        {"table": "daily_ohlcv", "purpose": "Primary OHLCV history for each symbol/day."},
        {"table": "daily_prices", "purpose": "Fallback rows when daily_ohlcv misses a symbol/day."},
        {"table": "live_market_snapshots", "purpose": "Live price bridge and intraday context."},
        {"table": "floorsheet_transactions", "purpose": "Broker flow and buy/sell pressure."},
        {"table": "market_summary", "purpose": "Breadth and turnover market regime."},
        {"table": "nepse_sub_indices", "purpose": "Sector leadership and laggard context."},
        {"table": "scrip_rankings", "purpose": "Turnover rank for liquidity scoring."},
        {"table": "company_details", "purpose": "Sector and company profile metadata."},
        {"table": "company_fundamentals", "purpose": "Valuation and fundamental scoring context."},
        {"table": "securities", "purpose": "Instrument-type filtering (equity focus)."},
    ]


def _data_sources_health_section(data: dict[str, Any]) -> str:
    meta = data.get("meta") or {}
    health = meta.get("data_health") or {}
    validation = meta.get("validation_summary") or {}
    ranking = data.get("ranking") or []

    def to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def to_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except Exception:
            return default

    exec_values: list[float] = []
    grade_ab = 0
    hard_veto_count = 0
    for row in ranking:
        exec_val = to_float(row.get("execution_confidence"), default=-1.0)
        if exec_val >= 0:
            exec_values.append(exec_val)
        if str(row.get("data_quality_grade") or "").upper() in {"A", "B"}:
            grade_ab += 1
        if row.get("veto_reasons"):
            hard_veto_count += 1

    ranked_count = len(ranking)
    avg_exec = sum(exec_values) / len(exec_values) if exec_values else 0.0
    grade_ab_rate = (grade_ab / ranked_count) if ranked_count else 0.0
    readiness_proxy = round(((avg_exec / 100.0) * 0.6 + (grade_ab_rate * 0.4)) * 100.0, 1)

    accuracy_score = to_float(health.get("accuracy_score"), readiness_proxy)
    equity_rows = to_int(health.get("equity_rows"))
    equity_zero_rows = to_int(health.get("equity_zero_volume_rows"))
    missing_equity_rows = to_int(health.get("missing_equity_rows_vs_daily_prices"))
    bad_close_rows = to_int(health.get("latest_bad_close_rows"))
    open_zero_rows = to_int(health.get("latest_open_zero_rows"))
    latest_ohlcv_rows = to_int(health.get("latest_ohlcv_rows"))

    processed = to_int(validation.get("processed"))
    total_symbols = to_int(validation.get("total_symbols"), ranked_count)
    stale_data = bool(meta.get("stale_data"))
    stale_label = "STALE" if stale_data else "FRESH"
    data_date = _esc(meta.get("data_date") or health.get("as_of_date") or "-")

    data_sources = meta.get("data_sources") or _default_data_sources()
    source_rows = ""
    for src in data_sources:
        source_rows += (
            "<tr>"
            f"<td><strong>{_esc(src.get('table', '-'))}</strong></td>"
            f"<td class='muted'>{_esc(src.get('purpose', '-'))}</td>"
            "</tr>"
        )

    return f"""
  <section class="card">
    <h2>Data Sources And Accuracy</h2>
    <p class="muted" style="margin-top:0">This report reads directly from these database tables and shows run-level data quality before decisioning.</p>
    <div class="grid4">
      <div class="kpi"><div class="label">Accuracy Score</div><div class="value">{_fmt(accuracy_score, 1)} / 100</div></div>
      <div class="kpi"><div class="label">Data Freshness</div><div class="value">{stale_label} ({data_date})</div></div>
      <div class="kpi"><div class="label">Equity Zero Volume</div><div class="value">{equity_zero_rows} / {equity_rows}</div></div>
      <div class="kpi"><div class="label">Missing vs daily_prices</div><div class="value">{missing_equity_rows}</div></div>
      <div class="kpi"><div class="label">Bad Close Rows</div><div class="value">{bad_close_rows} / {latest_ohlcv_rows}</div></div>
      <div class="kpi"><div class="label">Processed Symbols</div><div class="value">{processed} / {total_symbols}</div></div>
      <div class="kpi"><div class="label">Avg Execution Confidence</div><div class="value">{_fmt(avg_exec, 1)}</div></div>
      <div class="kpi"><div class="label">A/B Data Grade Share</div><div class="value">{_fmt(grade_ab_rate * 100.0, 1)}%</div></div>
    </div>
    <div class="muted" style="margin-top:10px;font-size:0.82rem">Hard veto flagged symbols: {hard_veto_count}. Raw OHLCV rows with open_price <= 0 on data date: {open_zero_rows}.</div>
    <div style="margin-top:12px;overflow-x:auto">
      <table class="table">
        <thead><tr><th>Database Table</th><th>Usage In Report</th></tr></thead>
        <tbody>{source_rows}</tbody>
      </table>
    </div>
  </section>
"""


def _market_section(data: dict[str, Any]) -> str:
    market = data.get("market", {})
    regime = _esc((market.get("regime") or {}).get("regime", "NEUTRAL"))
    regime_chg = (market.get("regime") or {}).get("chg", 0)
    summary = market.get("summary", {})
    breadth = market.get("breadth", {})
    sub = market.get("sub_indices", [])

    sub_rows = ""
    for r in sub[:8]:
        chg = float(r.get("percent_change") or 0)
        color = "#00e676" if chg > 0 else "#ff5252" if chg < 0 else "#b0bec5"
        sub_rows += (
            "<tr>"
            f"<td>{_esc(r.get('index_name','-'))}</td>"
            f"<td style='text-align:right'>{_fmt(r.get('current_value'),2)}</td>"
            f"<td style='text-align:right;color:{color}'>{_fmt_pct(chg)}</td>"
            "</tr>"
        )

    return f"""
  <section class="card">
    <h2>Market Dashboard</h2>
    <div class="grid4">
      <div class="kpi"><div class="label">Regime</div><div class="value">{regime} ({_fmt_pct(regime_chg)})</div></div>
      <div class="kpi"><div class="label">Turnover</div><div class="value">{_fmt(summary.get('total_turnover'),2)}</div></div>
      <div class="kpi"><div class="label">Adv / Dec</div><div class="value">{breadth.get('advances',0)} / {breadth.get('declines',0)}</div></div>
      <div class="kpi"><div class="label">Transactions</div><div class="value">{_fmt(summary.get('total_transactions'),0)}</div></div>
    </div>
    <div style="margin-top:14px;overflow-x:auto">
      <table class="table">
        <thead><tr><th>Sector Sub-Index</th><th style="text-align:right">Value</th><th style="text-align:right">Change</th></tr></thead>
        <tbody>{sub_rows}</tbody>
      </table>
    </div>
  </section>
"""


def _hotlist_section(data: dict[str, Any]) -> str:
    hotlist = data.get("hotlist", [])
    if not hotlist:
        return """
  <section class="card"><h2>Hotlist (max 5)</h2><p>No symbols met all hotlist conditions today.</p></section>
"""

    cards = ""
    for h in hotlist:
        tf = " ".join(_bucket_badge(t) for t in h.get("timeframes", [])) or "-"
        ratio_text = _fmt_ratio(h.get("broker_buy_sell_ratio"))
        flow_signal = _flow_badge(h.get("broker_flow_signal"))
        high_trust_accum = int(float(h.get("high_trust_accum_brokers") or 0))
        medium_plus_accum = int(float(h.get("medium_plus_accum_brokers") or 0))
        convergence_badge = _convergence_badge(h.get("broker_convergence_flag"))
        formal_exit_badge = _formal_exit_badge(
            h.get("broker_formal_exit"),
            h.get("broker_signal_bias"),
            h.get("broker_trust_label"),
        )
        veto_reasons = h.get("veto_reasons") or []
        veto_html = ""
        if veto_reasons:
          veto_text = ", ".join(str(v) for v in veto_reasons[:2])
          veto_html = f"<div class='warn'>Veto watch: {_esc(veto_text)}</div>"
        book = h.get("book_closure_warning")
        book_html = ""
        if book:
            book_html = (
                f"<div class='warn'>Book closure in {book.get('days_to_close')} days "
                f"(est. drop {book.get('est_drop_pct', 0):.2f}%)</div>"
            )

        cards += f"""
      <div class="hotcard">
        <div class="hothead">
          <div>
            <div class="sym">{_esc(h.get('symbol','-'))}</div>
            <div class="muted">{_esc(h.get('company_name',''))}</div>
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px">
            <div class="score">{h.get('score',0):.0f}</div>
            {_action_badge(h.get('action_label'))}
          </div>
        </div>
        <div class="muted" style="margin-bottom:8px">{_esc(h.get('sector','Other'))} | setup: {_esc(h.get('setup_type') or '-')}</div>
        <div class="muted">Fused {_fmt(h.get('fused_score'),1)} | Tier {_esc(h.get('priority_tier') or '-')} | Exec {_fmt(h.get('execution_confidence'),0)} | Data {_esc(h.get('data_quality_grade') or '-')}</div>
        <div class="muted">Broker: {_esc(h.get('broker_state') or '-')} / {_esc(h.get('broker_signal_bias') or '-')} | Trust {_esc(h.get('broker_trust_label') or '-')} | {_esc(h.get('broker_alignment_flag') or '-')}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">{convergence_badge}{formal_exit_badge}</div>
        <div class="muted">Convergence counts: HT {high_trust_accum} | MED+ {medium_plus_accum}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">{tf}</div>
        <div class="muted">WABR support: {_fmt_price(h.get('wabr_support')) if h.get('wabr_support') else '-'}</div>
        <div class="muted">Broker flow: Buy {_fmt_money(h.get('broker_buy_amt'))} | Sell {_fmt_money(h.get('broker_sell_amt'))} | B/S {ratio_text}</div>
        <div style="margin-top:8px">{flow_signal}</div>
        {veto_html}
        {book_html}
      </div>
"""

    return f"""
  <section class="card">
    <h2>Hotlist (max 5)</h2>
    <div class="hotgrid">{cards}</div>
  </section>
"""


def _broker_flow_section(data: dict[str, Any]) -> str:
    broker_flow = data.get("broker_flow") or {}
    top_acc = broker_flow.get("top_accumulation") or []
    top_dist = broker_flow.get("top_distribution") or []
    top_activity = broker_flow.get("top_activity") or []

    if not top_acc and not top_dist and not top_activity:
        return """
  <section class=\"card\">
    <h2>Broker Heavy Buy/Sell Flow</h2>
    <p class=\"muted\">No recent floorsheet flow summary is available.</p>
  </section>
"""

    window_start = broker_flow.get("window_start")
    window_end = broker_flow.get("window_end")
    sessions_used = int(broker_flow.get("sessions_used") or 0)
    if window_start and window_end:
        window_text = f"Window: {_esc(window_start)} to {_esc(window_end)}"
    else:
        window_text = "Window: recent sessions"

    def build_rows(rows: list[dict[str, Any]], max_rows: int = 8) -> str:
        body = ""
        for i, row in enumerate(rows[:max_rows], start=1):
            ratio_text = _fmt_ratio(row.get("buy_sell_ratio"))
            top_buy = ", ".join(_esc(v) for v in row.get("top_buy_brokers", [])[:2]) or "-"
            top_sell = ", ".join(_esc(v) for v in row.get("top_sell_brokers", [])[:2]) or "-"
            body += f"""
          <tr>
            <td style='text-align:center'>{i}</td>
            <td><strong>{_esc(row.get('symbol', '-'))}</strong></td>
            <td style='text-align:right'>{_fmt_money(row.get('buy_amt'))}</td>
            <td style='text-align:right'>{_fmt_money(row.get('sell_amt'))}</td>
            <td style='text-align:center'>{ratio_text}</td>
            <td style='text-align:center'>{_flow_badge(row.get('flow_signal'))}</td>
            <td class='muted' style='font-size:0.78rem'>B: {top_buy}<br>S: {top_sell}</td>
          </tr>
"""
        return body

    activity_rows = ""
    for i, row in enumerate(top_activity[:8], start=1):
        activity_rows += f"""
      <tr>
        <td style='text-align:center'>{i}</td>
        <td><strong>{_esc(row.get('symbol', '-'))}</strong></td>
        <td style='text-align:right'>{_fmt_money(row.get('flow_intensity'))}</td>
        <td style='text-align:right'>{_fmt_money(row.get('flow_dominance'))}</td>
        <td style='text-align:center'>{_flow_badge(row.get('flow_signal'))}</td>
      </tr>
"""

    return f"""
  <section class="card">
    <h2>Broker Heavy Buy/Sell Flow</h2>
    <p class="muted" style="margin-top:0">{window_text} | Sessions: {sessions_used}</p>
    <div class="flow-grid">
      <div class="flow-card">
        <h3>Top Accumulation (Buy Side)</h3>
        <div style="overflow-x:auto">
          <table class="table">
            <thead>
              <tr>
                <th style="text-align:center">#</th>
                <th>Symbol</th>
                <th style="text-align:right">Buy Amt</th>
                <th style="text-align:right">Sell Amt</th>
                <th style="text-align:center">B/S Ratio</th>
                <th style="text-align:center">Signal</th>
                <th>Top Brokers</th>
              </tr>
            </thead>
            <tbody>{build_rows(top_acc)}</tbody>
          </table>
        </div>
      </div>
      <div class="flow-card">
        <h3>Top Distribution (Sell Side)</h3>
        <div style="overflow-x:auto">
          <table class="table">
            <thead>
              <tr>
                <th style="text-align:center">#</th>
                <th>Symbol</th>
                <th style="text-align:right">Buy Amt</th>
                <th style="text-align:right">Sell Amt</th>
                <th style="text-align:center">B/S Ratio</th>
                <th style="text-align:center">Signal</th>
                <th>Top Brokers</th>
              </tr>
            </thead>
            <tbody>{build_rows(top_dist)}</tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="flow-card" style="margin-top:10px">
      <h3>Most Active Broker Flow</h3>
      <div style="overflow-x:auto">
        <table class="table">
          <thead>
            <tr>
              <th style="text-align:center">#</th>
              <th>Symbol</th>
              <th style="text-align:right">Flow Intensity</th>
              <th style="text-align:right">Buy - Sell</th>
              <th style="text-align:center">Signal</th>
            </tr>
          </thead>
          <tbody>{activity_rows}</tbody>
        </table>
      </div>
    </div>
  </section>
"""


def _plan_section(title: str, plans: list[dict[str, Any]], *, trading_mode: bool, section_key: str) -> str:
    if not plans:
        return f"<section class='card'><h2>{title}</h2><p>No qualifying candidates.</p></section>"

    rows = ""
    for p in plans:
        exits = "<br>".join(_esc(item) for item in p.get("exit_conditions", [])[:3])
        criteria_preview = "<br>".join(_esc(item) for item in p.get("bucket_criteria", [])[:3]) or "-"
        setup = _esc(p.get("setup_type") or "-")
        warning = ""
        book = p.get("book_closure_warning")
        if book:
            warning = (
                f"<div class='warn' style='margin-top:6px'>Book closure in {book.get('days_to_close')} days"
                f" (est. drop {book.get('est_drop_pct', 0):.2f}%)</div>"
            )

        size_cell = ""
        if trading_mode:
            size_cell = f"<td style='text-align:right'>{_fmt(p.get('position_size'),0)}</td>"

        flow_ratio = _fmt_ratio(p.get("broker_buy_sell_ratio"))
        flow_cell = (
            f"<td style='text-align:center'>{_flow_badge(p.get('broker_flow_signal'))}"
            f"<div class='muted' style='font-size:0.76rem;margin-top:3px'>{flow_ratio}</div></td>"
        )

        rows += f"""
      <tr>
        <td>
          <div style="font-weight:700">{_esc(p.get('symbol','-'))}</div>
          <div class="muted" style="font-size:0.8em">{_esc(p.get('sector','Other'))}</div>
          <div class="muted" style="font-size:0.8em">score {p.get('score',0):.1f} | fused {_fmt(p.get('fused_score'),1)} | setup {setup}</div>
          <div class="muted" style="font-size:0.8em">tier {_esc(p.get('priority_tier') or '-')} | exec {_fmt(p.get('execution_confidence'),0)} | data {_esc(p.get('data_quality_grade') or '-')} | {_esc(p.get('broker_alignment_flag') or '-')}</div>
          <div style="margin-top:6px">{_action_badge(p.get('action_label'))}</div>
          {warning}
        </td>
        <td style="text-align:right">{_fmt_price(p.get('entry_zone',[None,None])[0])} - {_fmt_price(p.get('entry_zone',[None,None])[1])}</td>
        <td style="text-align:right">{_fmt_price(p.get('stop_loss'))}</td>
        <td style="text-align:right">{_fmt_price(p.get('target_1'))}</td>
        <td style="text-align:right">{_fmt_price(p.get('target_2'))}</td>
        <td style="text-align:right">{_fmt_price(p.get('target_3'))}</td>
        <td style="text-align:center">{p.get('rr_ratio',0):.2f}</td>
        {flow_cell}
        {size_cell}
        <td>{_esc(p.get('hold_window','-'))}</td>
        <td class="muted" style="font-size:0.85em">{criteria_preview}</td>
        <td class="muted" style="font-size:0.85em">{exits}</td>
      </tr>
"""

    size_header = '<th style="text-align:right">Size</th>' if trading_mode else ''
    detail_cards = _plan_detail_cards(plans, section_key)

    return f"""
  <section class="card">
    <h2>{title}</h2>
    <div style="overflow-x:auto">
      <table class="table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th style="text-align:right">Entry Zone</th>
            <th style="text-align:right">Stop</th>
            <th style="text-align:right">T1</th>
            <th style="text-align:right">T2</th>
            <th style="text-align:right">T3</th>
            <th style="text-align:center">R:R</th>
            <th style="text-align:center">Broker Flow</th>
            {size_header}
            <th>Hold</th>
            <th>Why Included</th>
            <th>Exit Plan</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    {detail_cards}
  </section>
"""


def _tracker_section(data: dict[str, Any]) -> str:
    tracked = data.get("tracked", [])
    if not tracked:
        return ""

    rows = ""
    for t in tracked:
        verdict = t.get("verdict", "HOLD")
        if verdict == "HOLD":
            color = "#00e676"
        elif verdict == "TRIM":
            color = "#ffd740"
        elif verdict == "DATA_UNAVAILABLE":
            color = "#90a4ae"
        else:
            color = "#ff5252"
        recent_flow = t.get("broker_recent")
        prior_flow = t.get("broker_prior")
        flow_cell = "-"
        if recent_flow is not None and prior_flow is not None:
            flow_cell = f"{float(recent_flow):.1f} / {float(prior_flow):.1f}"
        high_trust_accum = int(float(t.get("high_trust_accum_brokers") or 0))
        medium_plus_accum = int(float(t.get("medium_plus_accum_brokers") or 0))
        convergence_badge = _convergence_badge(t.get("broker_convergence_flag"))
        formal_exit_badge = _formal_exit_badge(
          t.get("broker_formal_exit"),
          t.get("broker_signal_bias"),
          t.get("broker_trust_label"),
        )
        confidence_decay = t.get("confidence_decay")
        confidence_decay_text = "-" if confidence_decay is None else f"{float(confidence_decay):.1f}"
        state_shift = _esc(t.get("broker_state_shift_since_entry") or "-")
        if t.get("hard_exit_triggered"):
          exit_meta = "HARD EXIT"
        elif t.get("trim_reason_category"):
          exit_meta = str(t.get("trim_reason_category") or "-").upper()
        else:
          exit_meta = "-"
        bucket_label = str(t.get("bucket") or "-").upper()
        rows += f"""
      <tr>
        <td>{_esc(t.get('symbol','-'))}</td>
        <td style="text-align:center">{_esc(bucket_label)}</td>
        <td style="text-align:center;color:{color};font-weight:700">{_esc(verdict)}</td>
        <td style="text-align:center">{flow_cell}</td>
        <td style="text-align:center">{confidence_decay_text}</td>
        <td style="text-align:center">{state_shift}</td>
        <td style="text-align:center">{convergence_badge}<div class='muted' style='font-size:0.74rem;margin-top:3px'>HT {high_trust_accum} | MED+ {medium_plus_accum}</div></td>
        <td style="text-align:center">{formal_exit_badge}</td>
        <td style="text-align:center">{_esc(exit_meta)}</td>
        <td>{_esc(t.get('status_note','-'))}</td>
      </tr>
"""

    return f"""
  <section class="card">
    <h2>Exit Signal Tracker</h2>
    <div style="overflow-x:auto">
      <table class="table">
        <thead><tr><th>Symbol</th><th style="text-align:center">Bucket</th><th style="text-align:center">Verdict</th><th style="text-align:center">Broker Flow (Recent/Prior)</th><th style="text-align:center">Conf Decay</th><th style="text-align:center">State Shift</th><th style="text-align:center">Convergence</th><th style="text-align:center">Formal Broker EXIT</th><th style="text-align:center">Exit Meta</th><th>Trigger Notes</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </section>
"""


def build_master_html(data: dict[str, Any]) -> str:
    generated_at = _esc(data.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    meta = data.get("meta", {})
    trading_mode = bool(data.get("trading_mode"))
    mode_label = "TRADING" if trading_mode else "SCREENING"
    equity_meta = ""
    if trading_mode and data.get("equity") is not None:
        equity_meta = f"<span>Equity: {_fmt(data.get('equity'), 0)}</span>"

    mode_text = (
        "Actionable trade plans with risk-based position sizing."
        if trading_mode
        else "Screening intelligence mode with entries, stops, targets, and strategy rationale."
    )

    ranking_data = data.get("ranking", [])
    ranking_detail_payload = _build_ranking_detail_payload(ranking_data)
    ranking_detail_json = json.dumps(ranking_detail_payload, ensure_ascii=True).replace("</", "<\\/")
    ranking_block = _build_ranking_table(ranking_data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NEPSE Master Trader</title>
  <style>
    :root {{
      --bg: #071019;
      --bg-soft: #111b25;
      --border: #243242;
      --text: #e6edf3;
      --muted: #9bb0c3;
      --cyan: #00e5ff;
      --green: #00e676;
      --amber: #ffd740;
      --red: #ff5252;
    }}
    body {{
      margin: 0;
      color: var(--text);
      background: radial-gradient(1200px 500px at 20% -10%, rgba(0,229,255,0.12), transparent),
                  radial-gradient(900px 400px at 90% -20%, rgba(0,230,118,0.10), transparent),
                  var(--bg);
      font-family: "Segoe UI", Tahoma, sans-serif;
    }}
    .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
    .hero {{
      border: 1px solid var(--border);
      background: linear-gradient(135deg, rgba(0,229,255,0.06), rgba(0,230,118,0.05));
      border-radius: 14px;
      padding: 18px;
      margin-bottom: 18px;
    }}
    .hero h1 {{ margin: 0 0 8px 0; font-size: 2rem; }}
    .hero p {{ margin: 0; color: var(--muted); }}
    .meta {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 12px; color: var(--muted); font-size: 0.9rem; }}
    .card {{ border: 1px solid var(--border); background: var(--bg-soft); border-radius: 12px; padding: 14px; margin-bottom: 14px; }}
    .card h2 {{ margin: 0 0 10px 0; font-size: 1.2rem; }}
    .grid4 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }}
    .kpi {{ border: 1px solid var(--border); background: rgba(7,16,25,0.6); border-radius: 10px; padding: 10px; }}
    .kpi .label {{ color: var(--muted); font-size: 0.85rem; }}
    .kpi .value {{ font-size: 1.1rem; font-weight: 700; margin-top: 2px; }}
    .table {{ width: 100%; border-collapse: collapse; }}
    .table th, .table td {{ border-bottom: 1px solid rgba(255,255,255,0.08); padding: 8px; vertical-align: top; }}
    .table th {{ color: var(--muted); font-weight: 600; text-align: left; font-size: 0.86rem; }}
    .muted {{ color: var(--muted); }}
    .warn {{ color: var(--amber); font-size: 0.82rem; }}
    .hotgrid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }}
    .hotcard {{ border: 1px solid var(--border); border-radius: 10px; padding: 10px; background: rgba(7,16,25,0.7); }}
    .hothead {{ display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 6px; }}
    .sym {{ font-weight: 800; font-size: 1.1rem; }}
    .score {{ font-weight: 800; color: var(--green); font-size: 1.2rem; }}
    .action-badge {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:0.74rem; font-weight:700; letter-spacing:0.03em; }}
    .action-buy {{ background: rgba(0,230,118,0.14); color: var(--green); border: 1px solid rgba(0,230,118,0.5); }}
    .action-watch {{ background: rgba(255,215,64,0.14); color: var(--amber); border: 1px solid rgba(255,215,64,0.5); }}
    .action-avoid {{ background: rgba(255,82,82,0.14); color: var(--red); border: 1px solid rgba(255,82,82,0.5); }}
    .flow-badge {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:0.7rem; font-weight:700; letter-spacing:0.02em; }}
    .flow-buy {{ background: rgba(0,230,118,0.14); color: var(--green); border: 1px solid rgba(0,230,118,0.45); }}
    .flow-sell {{ background: rgba(255,82,82,0.14); color: var(--red); border: 1px solid rgba(255,82,82,0.45); }}
    .flow-mixed {{ background: rgba(255,215,64,0.14); color: var(--amber); border: 1px solid rgba(255,215,64,0.45); }}
    .flow-neutral {{ background: rgba(155,176,195,0.10); color: var(--muted); border: 1px solid rgba(155,176,195,0.35); }}
    .flow-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 10px; }}
    .flow-card {{ border: 1px solid var(--border); border-radius: 10px; background: rgba(7,16,25,0.6); padding: 10px; }}
    .flow-card h3 {{ margin: 0 0 8px 0; font-size: 0.98rem; color: var(--muted); }}
    .detail-wrap {{ margin-top: 14px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 12px; }}
    .detail-wrap h3 {{ margin: 0 0 10px 0; font-size: 1rem; color: var(--muted); }}
    .detail-index-table {{ margin-bottom: 10px; }}
    .detail-stack {{ display: grid; grid-template-columns: 1fr; gap: 10px; }}
    .detail-card {{ border: 1px solid var(--border); border-radius: 10px; padding: 10px; background: rgba(7,16,25,0.6); }}
    .detail-head {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 10px; }}
    .detail-grid-two {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }}
    .detail-block {{ border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 8px; }}
    .detail-block h4 {{ margin: 0 0 8px 0; font-size: 0.88rem; color: var(--muted); }}
    .crit-item {{ display: flex; gap: 8px; align-items: flex-start; padding: 5px 6px; border-radius: 6px; margin-bottom: 6px; font-size: 0.82rem; }}
    .crit-tag {{ min-width: 34px; text-align: center; font-size: 0.7rem; font-weight: 700; border-radius: 999px; padding: 1px 5px; background: rgba(255,255,255,0.12); }}
    .crit-pass {{ border: 1px solid rgba(0,230,118,0.35); background: rgba(0,230,118,0.08); }}
    .crit-fail {{ border: 1px solid rgba(255,82,82,0.35); background: rgba(255,82,82,0.08); }}
    .crit-neutral {{ border: 1px solid rgba(155,176,195,0.25); background: rgba(155,176,195,0.08); }}
    .line {{ font-size: 0.82rem; margin-bottom: 6px; padding-left: 8px; border-left: 2px solid rgba(155,176,195,0.35); }}
    .line.strength {{ border-left-color: rgba(0,230,118,0.7); }}
    .line.weakness {{ border-left-color: rgba(255,82,82,0.7); }}
    .detail-risk .line {{ border-left-color: rgba(0,229,255,0.6); }}
    .view-btn, .detail-close {{
      border: 1px solid rgba(0,229,255,0.5);
      background: transparent;
      color: var(--cyan);
      border-radius: 6px;
      padding: 5px 10px;
      font-size: 0.78rem;
      cursor: pointer;
      transition: all 0.2s ease;
    }}
    .view-btn:hover, .detail-close:hover {{
      background: rgba(0,229,255,0.12);
      border-color: rgba(0,229,255,0.8);
    }}
    .ranking-modal-overlay {{
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 14px;
      background: rgba(3,9,15,0.78);
      z-index: 2000;
    }}
    .ranking-modal {{
      width: min(1120px, 100%);
      max-height: 92vh;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: var(--bg-soft);
      box-shadow: 0 20px 70px rgba(0,0,0,0.45);
      overflow: hidden;
    }}
    .ranking-modal-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }}
    .ranking-modal-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .ranking-modal-body {{
      padding: 12px;
      overflow-y: auto;
      max-height: calc(92vh - 72px);
    }}
    .footer {{ color: var(--muted); font-size: 0.85rem; text-align: center; margin: 16px 0; }}
    @media (max-width: 768px) {{
      .container {{ padding: 12px; }}
      .hero h1 {{ font-size: 1.5rem; }}
      .table th, .table td {{ padding: 6px; font-size: 0.84rem; }}
      .ranking-modal-overlay {{ padding: 8px; }}
      .ranking-modal-head {{ flex-direction: column; align-items: flex-start; }}
      .ranking-modal-actions {{ justify-content: flex-start; }}
      .ranking-modal-body {{ max-height: calc(92vh - 120px); }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header class="hero">
      <h1>NEPSE Master Trader</h1>
      <p>{mode_text}</p>
      <div class="meta">
        <span>Generated: {generated_at}</span>
        <span>Mode: {mode_label}</span>
        {equity_meta}
        <span>Universe: {meta.get('universe', 0)}</span>
        <span>Short: {meta.get('short_count', 0)}</span>
        <span>Swing: {meta.get('swing_count', 0)}</span>
        <span>Long: {meta.get('long_count', 0)}</span>
        <span>Hotlist: {meta.get('hotlist_count', 0)}</span>
      </div>
    </header>

    {_data_sources_health_section(data)}
    {_market_section(data)}
    {_hotlist_section(data)}
    {_broker_flow_section(data)}
  {_plan_section('Short-Term Plays (1-5 days)', data.get('short_plans', []), trading_mode=trading_mode, section_key='short')}
  {_plan_section('Swing Trades (1-2 months)', data.get('swing_plans', []), trading_mode=trading_mode, section_key='swing')}
  {_plan_section('Long-Term Accumulation (6+ months)', data.get('long_plans', []), trading_mode=trading_mode, section_key='long')}
    {_tracker_section(data)}

    <section class="card">
      <h2>Full Universe Ranking</h2>
      {ranking_block}
    </section>

    <div id="ranking-modal-overlay" class="ranking-modal-overlay" onclick="if (event.target === this) closeRankingDetail();">
      <div class="ranking-modal" role="dialog" aria-modal="true" aria-labelledby="ranking-modal-symbol">
        <div class="ranking-modal-head">
          <div>
            <div class="sym" id="ranking-modal-symbol">-</div>
            <div class="muted" id="ranking-modal-subtitle">-</div>
          </div>
          <div class="ranking-modal-actions">
            <span id="ranking-modal-flow"></span>
            <span id="ranking-modal-action"></span>
            <span class="muted" id="ranking-modal-score">score -</span>
            <button class="detail-close" type="button" onclick="closeRankingDetail()">Close</button>
          </div>
        </div>
        <div class="ranking-modal-body">
          <div class="detail-grid-two" id="ranking-modal-grid"></div>
        </div>
      </div>
    </div>

    <div class="footer">
      NEPSE Master Trader coordinator report
    </div>
  </div>
  <script>
    const rankingDetailData = {ranking_detail_json};

    function showPlanDetail(detailId) {{
      document.querySelectorAll('.stock-detail-card').forEach((node) => {{
        node.style.display = 'none';
      }});
      const detail = document.getElementById(detailId);
      if (detail) {{
        detail.style.display = 'block';
        detail.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}
    }}

    function hidePlanDetail(detailId) {{
      const detail = document.getElementById(detailId);
      if (detail) {{
        detail.style.display = 'none';
      }}
    }}

    function escapeHtml(value) {{
      return String(value ?? "-")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }}

    function fmtCompact(value, decimals = 2) {{
      const n = Number(value);
      if (!Number.isFinite(n)) {{
        return "-";
      }}
      const absN = Math.abs(n);
      if (absN >= 1e9) {{
        return (n / 1e9).toFixed(decimals) + "B";
      }}
      if (absN >= 1e6) {{
        return (n / 1e6).toFixed(decimals) + "M";
      }}
      if (absN >= 1e3) {{
        return (n / 1e3).toFixed(decimals) + "K";
      }}
      return n.toLocaleString(undefined, {{ minimumFractionDigits: decimals, maximumFractionDigits: decimals }});
    }}

    function fmtMoney(value) {{
      const text = fmtCompact(value, 2);
      return text === "-" ? "-" : "Rs " + text;
    }}

    function fmtRatio(value) {{
      const n = Number(value);
      return Number.isFinite(n) ? n.toFixed(2) + "x" : "-";
    }}

    function fmtPct(value) {{
      const n = Number(value);
      if (!Number.isFinite(n)) {{
        return "-";
      }}
      return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
    }}

    function toNum(value) {{
      const n = Number(value);
      return Number.isFinite(n) ? n : null;
    }}

    function fmtPrice(value, decimals = 2) {{
      const n = toNum(value);
      if (n === null) {{
        return "-";
      }}
      return "Rs " + n.toLocaleString(undefined, {{
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }});
    }}

    function centerRange(value, atr, pctBand, atrMult) {{
      const center = toNum(value);
      if (center === null) {{
        return null;
      }}

      const pct = toNum(pctBand);
      const atrM = toNum(atrMult);
      const atrValue = toNum(atr);

      const pctWidth = Math.abs(center) * (pct !== null && pct > 0 ? pct : 0);
      const atrWidth = atrValue !== null ? Math.abs(atrValue) * (atrM !== null && atrM > 0 ? atrM : 0) : 0;
      const floorWidth = Math.abs(center) * 0.002;
      const width = Math.max(pctWidth, atrWidth, floorWidth);

      return [center - width, center + width];
    }}

    function deriveEntryRange(detail) {{
      const zone = Array.isArray(detail.entry_zone) ? detail.entry_zone : [];
      if (zone.length >= 2) {{
        const low = toNum(zone[0]);
        const high = toNum(zone[1]);
        if (low !== null && high !== null) {{
          return low <= high ? [low, high] : [high, low];
        }}
      }}
      return centerRange(detail.price, detail.atr, 0.01, 0.35);
    }}

    function formatPriceRange(rangeVals, fallback = "No range available") {{
      if (!Array.isArray(rangeVals) || rangeVals.length < 2) {{
        return fallback;
      }}
      const lowRaw = toNum(rangeVals[0]);
      const highRaw = toNum(rangeVals[1]);
      if (lowRaw === null || highRaw === null) {{
        return fallback;
      }}
      const low = Math.min(lowRaw, highRaw);
      const high = Math.max(lowRaw, highRaw);
      return fmtPrice(low) + " - " + fmtPrice(high);
    }}

    function actionBadgeHtml(action) {{
      const label = String(action || "WATCH").toUpperCase();
      const clsMap = {{ BUY: "action-buy", WATCH: "action-watch", AVOID: "action-avoid" }};
      const cls = clsMap[label] || "action-watch";
      return '<span class="action-badge ' + cls + '">' + escapeHtml(label) + "</span>";
    }}

    function flowBadgeHtml(signal) {{
      const raw = String(signal || "NO_FLOW").toUpperCase();
      const clsMap = {{
        BUY_HEAVY: "flow-buy",
        SELL_HEAVY: "flow-sell",
        TWO_WAY: "flow-mixed",
        NO_FLOW: "flow-neutral",
      }};
      const labelMap = {{
        BUY_HEAVY: "BUY HEAVY",
        SELL_HEAVY: "SELL HEAVY",
        TWO_WAY: "TWO-WAY",
        NO_FLOW: "NO FLOW",
      }};
      const cls = clsMap[raw] || "flow-neutral";
      const label = labelMap[raw] || raw.replace(/_/g, " ");
      return "<span class='flow-badge " + cls + "'>" + escapeHtml(label) + "</span>";
    }}

    function criterionItemHtml(text) {{
      const raw = String(text || "-");
      const upper = raw.toUpperCase();
      let cls = "crit-neutral";
      let tag = "INFO";
      if (upper.startsWith("PASS:")) {{
        cls = "crit-pass";
        tag = "PASS";
      }} else if (upper.startsWith("FAIL:")) {{
        cls = "crit-fail";
        tag = "FAIL";
      }}
      return "<div class='crit-item " + cls + "'><span class='crit-tag'>" + tag + "</span><span>" + escapeHtml(raw) + "</span></div>";
    }}

    function renderBulletLines(items, emptyText, cssClass) {{
      if (!Array.isArray(items) || !items.length) {{
        return "<div class='muted'>" + escapeHtml(emptyText) + "</div>";
      }}
      return items.slice(0, 5).map(function (item) {{
        return "<div class='" + cssClass + "'>" + escapeHtml(item) + "</div>";
      }}).join("");
    }}

    function renderCriteria(detail) {{
      const reasons = detail.bucket_reasons || {{}};
      const flags = detail.bucket_flags || {{}};
      const order = [["short", "Short"], ["swing", "Swing"], ["long", "Long"], ["hotlist", "Hotlist"]];
      let html = "";

      order.forEach(function (pair) {{
        const key = pair[0];
        const label = pair[1];
        const entries = Array.isArray(reasons[key]) ? reasons[key].slice(0, 6) : [];
        html += "<div class='line'><strong>" + label + "</strong> <span class='muted'>(" + (flags[key] ? "ACTIVE" : "WATCH") + ")</span></div>";
        if (!entries.length) {{
          html += "<div class='muted' style='margin-bottom:8px'>No criteria captured.</div>";
          return;
        }}
        entries.forEach(function (entry) {{
          html += criterionItemHtml(entry);
        }});
      }});

      return html || "<div class='muted'>No criteria captured.</div>";
    }}

    function openRankingDetail(detailKey) {{
      const detail = rankingDetailData[detailKey];
      const overlay = document.getElementById("ranking-modal-overlay");
      if (!detail || !overlay) {{
        return;
      }}

      const flags = detail.bucket_flags || {{}};
      const activeBuckets = [];
      ["short", "swing", "long", "hotlist"].forEach(function (bucket) {{
        if (flags[bucket]) {{
          activeBuckets.push(bucket.toUpperCase());
        }}
      }});

      const sectorRankText = detail.sector_rank != null
        ? String(detail.sector_rank) + "/" + String(detail.sector_size || 0)
        : "-";
      const topBuy = Array.isArray(detail.top_buy_brokers) && detail.top_buy_brokers.length
        ? detail.top_buy_brokers.slice(0, 3).map(function (item) {{ return escapeHtml(item); }}).join(", ")
        : "-";
      const topSell = Array.isArray(detail.top_sell_brokers) && detail.top_sell_brokers.length
        ? detail.top_sell_brokers.slice(0, 3).map(function (item) {{ return escapeHtml(item); }}).join(", ")
        : "-";
      const vetoReasons = Array.isArray(detail.veto_reasons) && detail.veto_reasons.length
        ? detail.veto_reasons.slice(0, 4).map(function (item) {{ return escapeHtml(item); }}).join(", ")
        : "none";
      const breakdown = detail.fused_score_breakdown || {{}};
      const components = breakdown.components || {{}};
      const entryRange = deriveEntryRange(detail);
      const stopRange = centerRange(detail.stop_loss, detail.atr, 0.007, 0.25);
      const target1Range = centerRange(detail.target_1, detail.atr, 0.010, 0.35);
      const target2Range = centerRange(detail.target_2, detail.atr, 0.012, 0.45);

      document.getElementById("ranking-modal-symbol").textContent = detail.symbol || "-";
      const companyPrefix = detail.company_name ? detail.company_name + " | " : "";
      document.getElementById("ranking-modal-subtitle").textContent =
        companyPrefix + (detail.sector || "Other") + " | setup: " + (detail.setup_type || "-") + " | price " + fmtMoney(detail.price);
      document.getElementById("ranking-modal-flow").innerHTML = flowBadgeHtml(detail.broker_flow_signal);
      document.getElementById("ranking-modal-action").innerHTML = actionBadgeHtml(detail.action_label);
      document.getElementById("ranking-modal-score").textContent =
        "score " + fmtCompact(detail.score, 1) +
        " | fused " + fmtCompact(detail.fused_score, 1) +
        " | prio " + String(detail.priority_tier || "-") +
        " | " + (detail.tier || "-");

      const blocks = [];
      blocks.push("<div class='detail-block'><h4>Selection Criteria</h4>" + renderCriteria(detail) + "</div>");
      blocks.push("<div class='detail-block'><h4>Setup Reasoning</h4>" + renderBulletLines(detail.setup_reasoning, "No setup reasoning available for this symbol.", "line") + "</div>");
      blocks.push("<div class='detail-block'><h4>Why Buy</h4>" + renderBulletLines(detail.strengths, "No major strengths captured (quick mode or weak signal).", "line strength") + "</div>");
      blocks.push("<div class='detail-block'><h4>Why Sell Or Trim Risk</h4>" + renderBulletLines(detail.weaknesses, "No major weaknesses captured (quick mode or limited signal).", "line weakness") + "</div>");
      blocks.push(
        "<div class='detail-block'><h4>Decision Intelligence</h4>" +
        "<div class='line'>Fused Score: " + fmtCompact(detail.fused_score, 2) + "</div>" +
        "<div class='line'>Opportunity Score: " + fmtCompact(breakdown.opportunity_score, 2) + "</div>" +
        "<div class='line'>Safety Multiplier: " + fmtCompact(breakdown.safety_multiplier, 3) + "</div>" +
        "<div class='line'>Explicit Penalties: " + fmtCompact(breakdown.explicit_penalties, 2) + "</div>" +
        "<div class='line'>Priority Tier: " + escapeHtml(detail.priority_tier || "-") + "</div>" +
        "<div class='line'>Execution Confidence: " + fmtCompact(detail.execution_confidence, 1) + "</div>" +
        "<div class='line'>Data Quality Grade: " + escapeHtml(detail.data_quality_grade || "-") + "</div>" +
        "<div class='line'>Broker Alignment: " + escapeHtml(detail.broker_alignment_flag || "-") + "</div>" +
        "<div class='line'>Veto Reasons: " + vetoReasons + "</div>" +
        "<div class='line'>Components: setup/trend " + fmtCompact(components.swing_setup_trend, 1) +
        " | conviction " + fmtCompact(components.single_conviction, 1) +
        " | rs/sector " + fmtCompact(components.relative_strength_sector, 1) +
        " | broker " + fmtCompact(components.broker_behavior_quality, 1) +
        " | volume " + fmtCompact(components.volume_turnover, 1) +
        " | market " + fmtCompact(components.market_alignment, 1) + "</div>" +
        "</div>"
      );
      blocks.push(
        "<div class='detail-block detail-risk'><h4>Risk Snapshot</h4>" +
        "<div class='line'>Active Buckets: " + escapeHtml(activeBuckets.length ? activeBuckets.join(", ") : "NONE") + "</div>" +
        "<div class='line'>R:R: " + fmtCompact(detail.rr_ratio, 2) + "</div>" +
        "<div class='line'>Best Entry Range: " + formatPriceRange(entryRange) + "</div>" +
        "<div class='line'>Stop Range: " + formatPriceRange(stopRange) + "</div>" +
        "<div class='line'>Target 1 Range: " + formatPriceRange(target1Range) + "</div>" +
        "<div class='line'>Target 2 Range: " + formatPriceRange(target2Range) + "</div>" +
        "<div class='line'>Sector Rank: " + escapeHtml(sectorRankText) + "</div>" +
        "<div class='line'>Broker Asym: " + fmtCompact(detail.broker_asym, 1) + "</div>" +
        "<div class='line'>RS Delta: " + fmtPct(detail.rs_delta) + "</div>" +
        "<div class='line'>Volatility 20D: " + fmtCompact(detail.vol_20d, 2) + "%</div>" +
        "<div class='line'>Max Drawdown: " + fmtCompact(detail.max_drawdown, 2) + "%</div>" +
        "</div>"
      );
      blocks.push(
        "<div class='detail-block'><h4>Broker Flow (Top 3 Brokers)</h4>" +
        "<div class='line'>Buy Amount: " + fmtMoney(detail.broker_buy_amt) + "</div>" +
        "<div class='line'>Sell Amount: " + fmtMoney(detail.broker_sell_amt) + "</div>" +
        "<div class='line'>Buy/Sell Ratio: " + fmtRatio(detail.broker_buy_sell_ratio) + "</div>" +
        "<div class='line'>Intensity: " + fmtMoney(detail.broker_flow_intensity) + "</div>" +
        "<div class='line'>Lifecycle State: " + escapeHtml(detail.broker_state || "-") + "</div>" +
        "<div class='line'>Signal: " + escapeHtml(detail.broker_signal_bias || "-") + " (" + escapeHtml(detail.broker_signal_strength || "-") + ")</div>" +
        "<div class='line'>Trust / Maturity: " + escapeHtml(detail.broker_trust_label || "-") + " / " + escapeHtml(detail.broker_data_maturity || "-") + "</div>" +
        "<div class='line'>Size Multiplier: " + fmtRatio(detail.broker_size_multiplier) + "</div>" +
        "<div class='line'>Top Buyers: " + topBuy + "</div>" +
        "<div class='line'>Top Sellers: " + topSell + "</div>" +
        "</div>"
      );

      document.getElementById("ranking-modal-grid").innerHTML = blocks.join("");
      overlay.style.display = "flex";
      document.body.style.overflow = "hidden";
    }}

    function closeRankingDetail() {{
      const overlay = document.getElementById("ranking-modal-overlay");
      if (overlay) {{
        overlay.style.display = "none";
      }}
      document.body.style.overflow = "";
    }}

    document.addEventListener("keydown", function (evt) {{
      if (evt.key === "Escape") {{
        closeRankingDetail();
      }}
    }});
  </script>
</body>
</html>
"""


def write_master_report(html: str, output_dir: str | None = None) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"master_trader_report_{date_str}.html"
    if output_dir:
        filepath = os.path.join(output_dir, filename)
    else:
        filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return os.path.abspath(filepath)
