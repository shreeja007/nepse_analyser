"""Convert Broker Tracker HTML report to Markdown.

Goal: keep the *data* (tables + per-broker payload JSON) and drop CSS/HTML tags
so the output is smaller and easier for AI agents to process.

Usage:
  python tools/broker_tracker_html_to_md.py \
    --input broker_tracker_reports/broker_tracker_2026-03-31.html \
    --output broker_tracker_reports/broker_tracker_2026-03-31.md

Notes:
- Uses only Python stdlib (no BeautifulSoup).
- Extracts:
  - Data maturity banner (if present)
  - Data Summary KV pairs
  - BUY/WATCH/EXIT signal tables
  - Broker Leaderboard table
  - Per-broker deep-dive summaries + embedded JSON payloads (positions + timelines)
  - Stock-Level Broker Activity table

If the HTML structure changes, adjust the extraction regexes accordingly.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
from pathlib import Path
from typing import Any, Iterable


WS_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(s: str) -> str:
    s = html_lib.unescape(s or "")
    s = TAG_RE.sub("", s)
    s = s.replace("\xa0", " ")
    s = WS_RE.sub(" ", s).strip()
    return s


def _extract_first(pattern: str, text: str, flags: int = re.S) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def _extract_banner(html: str) -> str | None:
    # Example: <div class="banner">⚠ Data maturity: LOW (&lt; 30 trading sessions ...)</div>
    banner = _extract_first(r"<div class=\"banner\">(.*?)</div>", html)
    return _clean_text(banner) if banner else None


def _extract_data_summary(html: str) -> dict[str, Any]:
    # Locate the Data Summary card and pull date range/generated + KV pairs.
    # The HTML contains nested <div> blocks, so matching a full "card" via regex is brittle.
    # Instead, take a window after the title and extract the fields from that window.
    title = "📊 Data Summary"
    idx = html.find(title)
    if idx < 0:
        return {}

    window = html[idx : idx + 10_000]

    date_range = _extract_first(r"Date range:\s*(.*?)</div>", window)
    generated = _extract_first(r"Generated:\s*(.*?)</div>", window)

    kv_pairs: dict[str, str] = {}
    for k, v in re.findall(r"<div><div class=\"k\">(.*?)</div><div class=\"v\">(.*?)</div></div>", window, re.S):
        kv_pairs[_clean_text(k)] = _clean_text(v)

    out: dict[str, Any] = {}
    if date_range:
        out["Date range"] = _clean_text(date_range)
    if generated:
        out["Generated"] = _clean_text(generated)
    out.update(kv_pairs)
    return out


def _extract_table_after_title(html: str, title_contains: str) -> str | None:
    # Find a card-title containing title_contains, then grab the first <table>...</table> after it.
    idx = html.find(title_contains)
    if idx < 0:
        return None
    tail = html[idx:]
    m = re.search(r"<table>(.*?)</table>", tail, re.S)
    if not m:
        # Some tables are <table><tr>... (still matches), but keep fallback
        m = re.search(r"<table[^>]*>(.*?)</table>", tail, re.S)
    if not m:
        return None
    return "<table>" + m.group(1) + "</table>"


def _parse_html_table(table_html: str) -> tuple[list[str], list[list[str]]]:
    # Returns (headers, rows) as plain text.
    row_htmls = re.findall(r"<tr>(.*?)</tr>", table_html, re.S)
    headers: list[str] = []
    rows: list[list[str]] = []

    for row_i, row_html in enumerate(row_htmls):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row_html, re.S)
        cells_txt = [_clean_text(c) for c in cells]
        if row_i == 0 and any("<th" in row_html for _ in [0]):
            headers = cells_txt
        else:
            if cells_txt:
                rows.append(cells_txt)

    # Sometimes header row is not first (unlikely here) — fallback
    if not headers and rows:
        headers = [f"col_{i+1}" for i in range(len(rows[0]))]

    return headers, rows


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    # GitHub-flavored markdown table.
    headers = [h or "—" for h in headers]

    def esc(cell: str) -> str:
        cell = cell.replace("|", "\\|")
        return cell

    out = []
    out.append("| " + " | ".join(esc(h) for h in headers) + " |")
    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for r in rows:
        # pad/truncate
        r = (r + [""] * len(headers))[: len(headers)]
        out.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(out)


def _md_kv_list(kv: dict[str, Any]) -> str:
    lines = []
    for k, v in kv.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def _extract_deep_dives(html: str) -> list[dict[str, Any]]:
    # Parse each broker deep dive section + its embedded JSON payload.
    dives: list[dict[str, Any]] = []

    # Find all broker toggle blocks.
    # Example: onclick="toggleBroker('broker_58', 58)"
    broker_ids = [int(x) for x in re.findall(r"toggleBroker\('broker_(\d+)'\s*,\s*(\d+)\)", html) for x in [x[1]]]
    # de-dup preserve order
    seen = set()
    broker_ids_unique = []
    for bid in broker_ids:
        if bid in seen:
            continue
        seen.add(bid)
        broker_ids_unique.append(bid)

    for bid in broker_ids_unique:
        # Block for this broker (hidden div)
        block = _extract_first(rf"<div id=\"broker_{bid}\" class=\"hidden\".*?>(.*?)<script type=\"application/json\" id=\"bt_data_{bid}\">(.*?)</script>", html)
        payload_raw = _extract_first(rf"<script type=\"application/json\" id=\"bt_data_{bid}\">(.*?)</script>", html)

        # Extract broker name and stocks-traded from toggle header
        toggle = _extract_first(
            rf"<div class=\"toggle\" onclick=\"toggleBroker\('broker_{bid}', {bid}\)\">(.*?)</div>\s*<div id=\"broker_{bid}\"",
            html,
        )
        toggle_txt = _clean_text(toggle or "")

        # Pull name from the toggle text: "Broker 58 — Name (375 stocks)"
        name = ""
        stocks_traded = ""
        m = re.search(rf"Broker {bid}\s+—\s+(.*?)(?:\((\d+[\d,]*)\s+stocks\))?", toggle_txt)
        if m:
            name = (m.group(1) or "").strip()
            stocks_traded = (m.group(2) or "").strip()

        # Parse cards inside block (summary, preferred sectors, current focus)
        summary = {}
        preferred_sectors = ""
        current_focus = {"Accumulating": "", "Distributing": ""}

        if block:
            block_txt = block
            # Summary card fields
            for label in [
                "Completed cycles",
                "Win rate",
                "Avg hold (sessions)",
                "Avg buy size",
            ]:
                v = _extract_first(rf"{re.escape(label)}:\s*<b>(.*?)</b>", block_txt)
                if v:
                    summary[label] = _clean_text(v)

            # Preferred sectors
            ps = _extract_first(r"<div class=\"card-title\">Preferred Sectors</div>.*?<div class=\"small\">(.*?)</div>", block_txt)
            if ps:
                preferred_sectors = _clean_text(ps)

            # Current focus
            cf = _extract_first(r"<div class=\"card-title\">Current Focus</div>.*?<div class=\"small\">(.*?)</div>", block_txt)
            if cf:
                cf_txt = html_lib.unescape(cf)
                # Accumulating: ...<br> Distributing: ...
                acc = _extract_first(r"Accumulating:\s*(.*?)(?:<br>|$)", cf_txt)
                dist = _extract_first(r"Distributing:\s*(.*?)(?:<br>|$)", cf_txt)
                current_focus["Accumulating"] = _clean_text(acc or "")
                current_focus["Distributing"] = _clean_text(dist or "")

        payload: dict[str, Any] = {}
        if payload_raw:
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}

        dives.append(
            {
                "broker_id": bid,
                "broker_name": name,
                "stocks_traded": stocks_traded,
                "summary": summary,
                "preferred_sectors": preferred_sectors,
                "current_focus": current_focus,
                "payload": payload,
                "toggle_text": toggle_txt,
            }
        )

    return dives


def _csv_escape(v: Any) -> str:
    if v is None:
        return ""
    s = str(v)
    if any(ch in s for ch in [",", "\n", '"']):
        s = s.replace('"', '""')
        return f'"{s}"'
    return s


def _payload_positions_to_csv(rows: list[list[Any]]) -> str:
    headers = [
        "Date",
        "Symbol",
        "Sector",
        "Bought",
        "Sold",
        "Net",
        "Cumulative",
        "AvgBuy",
        "AvgSell",
        "Asym",
        "State",
        "UnrealizedPnL",
    ]
    out = [",".join(headers)]
    for r in rows or []:
        r = (r + [None] * len(headers))[: len(headers)]
        out.append(",".join(_csv_escape(x) for x in r))
    return "\n".join(out)


def convert(html_text: str) -> str:
    lines: list[str] = []

    lines.append("# NEPSE Broker Tracker — Markdown Export")

    banner = _extract_banner(html_text)
    if banner:
        lines.append("")
        lines.append(f"**Banner**: {banner}")

    # Data summary
    data_summary = _extract_data_summary(html_text)
    if data_summary:
        lines.append("")
        lines.append("## Data Summary")
        lines.append(_md_kv_list(data_summary))

    # Signals
    def add_table_section(md_title: str, title_contains: str):
        table_html = _extract_table_after_title(html_text, title_contains)
        if not table_html:
            return
        headers, rows = _parse_html_table(table_html)
        lines.append("")
        lines.append(f"## {md_title}")
        lines.append(_md_table(headers, rows))

    add_table_section("BUY Signals", "BUY Signals")
    add_table_section("WATCH Signals", "WATCH Signals")
    add_table_section("EXIT Signals", "EXIT Signals")

    # Leaderboard
    table_html = _extract_table_after_title(html_text, "Broker Leaderboard")
    if table_html:
        headers, rows = _parse_html_table(table_html)
        lines.append("")
        lines.append("## Broker Leaderboard")
        lines.append(_md_table(headers, rows))

    # Deep dives
    dives = _extract_deep_dives(html_text)
    if dives:
        lines.append("")
        lines.append("## Per-Broker Deep Dives")

        for d in dives:
            bid = d.get("broker_id")
            name = d.get("broker_name") or ""
            stocks = d.get("stocks_traded") or ""

            lines.append("")
            title = f"### Broker {bid}" + (f" — {name}" if name else "")
            lines.append(title)
            if stocks:
                lines.append(f"- Stocks traded (unique symbols): {stocks}")

            summary = d.get("summary") or {}
            if summary:
                lines.append("- Summary:")
                for k, v in summary.items():
                    lines.append(f"  - {k}: {v}")

            ps = d.get("preferred_sectors")
            if ps:
                lines.append(f"- Preferred sectors: {ps}")

            cf = d.get("current_focus") or {}
            acc = cf.get("Accumulating")
            dist = cf.get("Distributing")
            if acc or dist:
                lines.append("- Current focus:")
                if acc:
                    lines.append(f"  - Accumulating: {acc}")
                if dist:
                    lines.append(f"  - Distributing: {dist}")

            payload = d.get("payload") or {}
            rows = payload.get("rows") or []
            timeline = payload.get("timeline") or {}

            if rows:
                lines.append("")
                lines.append("#### Position History (trades only) — CSV")
                lines.append("```csv")
                lines.append(_payload_positions_to_csv(rows))
                lines.append("```")

            if timeline:
                lines.append("")
                lines.append("#### State Transition Timeline — JSON")
                lines.append("```json")
                lines.append(json.dumps(timeline, ensure_ascii=False, separators=(",", ":")))
                lines.append("```")

    # Stock level activity
    table_html = _extract_table_after_title(html_text, "Stock-Level Broker Activity")
    if table_html:
        headers, rows = _parse_html_table(table_html)
        lines.append("")
        lines.append("## Stock-Level Broker Activity")
        # Usually large; emit as CSV inside markdown for easier parsing.
        lines.append("```csv")
        lines.append(",".join(headers))
        for r in rows:
            r = (r + [""] * len(headers))[: len(headers)]
            lines.append(",".join(_csv_escape(x) for x in r))
        lines.append("```")

    lines.append("")
    lines.append("---")
    lines.append("Generated by tools/broker_tracker_html_to_md.py")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to broker_tracker_YYYY-MM-DD.html")
    ap.add_argument("--output", required=True, help="Path to output .md")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    html_text = in_path.read_text(encoding="utf-8", errors="replace")
    md = convert(html_text)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
