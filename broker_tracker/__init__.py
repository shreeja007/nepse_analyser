"""NEPSE Broker Tracker — Package Entry Point

Usage:
    python -m broker_tracker

Generates a CLI summary + a self-contained HTML report.
"""

from __future__ import annotations

import os
import time
from datetime import datetime


def _fmt_asym(v) -> str:
    try:
        if v is None:
            return "—"
        return f"{float(v):.0f}%"
    except Exception:
        return "—"


def main():
    from broker_tracker.config import OUTPUT_DIR, TOP_N_SIGNALS
    from broker_tracker.data import (
        get_db_connection,
        get_total_transactions,
        get_broker_universe,
        get_all_broker_activity,
        aggregate_broker_activity,
        get_latest_prices,
        get_symbol_price_history,
        get_market_index_history,
        get_atr_14,
        build_sector_map,
    )
    from broker_tracker.positions import compute_broker_stock_positions, get_state_transitions
    from broker_tracker.intelligence import build_broker_profiles
    from broker_tracker.signals import generate_signals, aggregate_stock_signals
    from broker_tracker.html_report import build_html, write_report

    now = datetime.now()

    print("=" * 60)
    print(f"  NEPSE BROKER TRACKER — {now:%Y-%m-%d} {now:%H:%M}")
    print("=" * 60)

    t0 = time.time()

    conn = get_db_connection()
    try:
        total_transactions = get_total_transactions(conn)
        broker_universe = get_broker_universe(conn)
        raw_activity_rows = get_all_broker_activity(conn)
        latest_prices = get_latest_prices(conn)
        symbol_price_history = get_symbol_price_history(conn)
        market_index_history = get_market_index_history(conn, index_name="NEPSE")
        atr_by_symbol = get_atr_14(conn)
        sector_map = build_sector_map(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    activity_df = aggregate_broker_activity(raw_activity_rows)

    if activity_df.empty:
        print("\n  ⚠ No floorsheet activity found.")
        print("=" * 60)
        return None

    trading_sessions = int(activity_df["trading_date"].nunique())
    brokers_tracked = int(len(broker_universe))
    stocks_covered = int(activity_df["symbol"].nunique())

    min_date = activity_df["trading_date"].min()
    max_date = activity_df["trading_date"].max()

    print("\n📊 DATA SUMMARY")
    print(f"  Brokers tracked   : {brokers_tracked}")
    print(f"  Stocks covered    : {stocks_covered}")
    print(f"  Total transactions: {total_transactions:,}")
    print(f"  Date range        : {min_date} → {max_date}")

    if trading_sessions < 30:
        print("  ⚠ Data maturity   : LOW (< 30 days of history)")

    sessions_df, summary_df = compute_broker_stock_positions(activity_df, latest_prices)
    transitions = get_state_transitions(sessions_df)

    broker_profiles = build_broker_profiles(
        positions_sessions_df=sessions_df,
        positions_summary_df=summary_df,
        activity_df=activity_df,
        sector_map=sector_map,
        price_history_by_symbol=symbol_price_history,
        market_index_history=market_index_history,
    )

    buy_broker_signals, watch_broker_signals, exit_broker_signals = generate_signals(
        positions_sessions_df=sessions_df,
        positions_summary_df=summary_df,
        broker_profiles=broker_profiles,
        latest_prices=latest_prices,
        activity_df=activity_df,
        price_history_by_symbol=symbol_price_history,
        atr_by_symbol=atr_by_symbol,
    )
    buy_signals, watch_signals, exit_signals = aggregate_stock_signals(
        buy_broker_signals,
        watch_broker_signals,
        exit_broker_signals,
    )

    def _select_top_rows(rows: list[dict], top_n: int) -> list[dict]:
        if not rows:
            return []
        return rows[:top_n]

    def _print_signal_list(header: str, icon: str, rows: list[dict], kind: str):
        selected = _select_top_rows(rows, TOP_N_SIGNALS)
        print(f"\n{icon} {header} ({len(rows)} total, showing {len(selected)})")
        if not rows:
            return

        for s in selected:
            sym = str(s.get("symbol") or "")
            broker_count = int(s.get("broker_count") or 0)
            trust = str(s.get("broker_trust_label") or "UNRATED")
            score = float(s.get("stock_score") or 0.0)
            asym = _fmt_asym(s.get("latest_asymmetry"))

            if kind in ("BUY", "WATCH"):
                move = s.get("price_move_since_entry_pct")
                move_txt = f"{float(move):.1f}%" if move is not None else "—"
                print(
                    f"  {sym:<7} — {broker_count} brokers"
                    f"   | Score: {score:.1f} | Move: {move_txt} | Asym: {asym} | Trust: {trust}"
                )
            else:
                qty = int(s.get("cumulative_net_qty") or 0)
                stc = "YES" if s.get("state_changed") else "—"
                print(
                    f"  {sym:<7} — {broker_count} brokers"
                    f"   | Score: {score:.1f} | State Changed: {stc} | Qty: {qty:,} | Trust: {trust}"
                )

    _print_signal_list("BUY SIGNALS", "🚨", buy_signals, "BUY")
    _print_signal_list("WATCH SIGNALS", "👁", watch_signals, "WATCH")
    _print_signal_list("EXIT SIGNALS", "⚠", exit_signals, "EXIT")

    # Prepare ranked profiles for the report
    profiles_list = list(broker_profiles.values())

    def _profile_sort_key(p: dict):
        trust_score = p.get("trust_score")
        trade_value = float(p.get("total_value_bought") or 0.0) + float(p.get("total_value_sold") or 0.0)
        if trust_score is None:
            return (1, -trade_value)
        return (0, -float(trust_score), -float(p.get("completed_cycles") or 0), -trade_value)

    profiles_list.sort(key=_profile_sort_key)

    report = {
        "meta": {
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "brokers_tracked": brokers_tracked,
            "stocks_covered": stocks_covered,
            "total_transactions": total_transactions,
            "min_date": str(min_date),
            "max_date": str(max_date),
            "trading_sessions": trading_sessions,
        },
        "buy_signals": buy_signals,
        "watch_signals": watch_signals,
        "exit_signals": exit_signals,
        "buy_broker_signals": buy_broker_signals,
        "watch_broker_signals": watch_broker_signals,
        "exit_broker_signals": exit_broker_signals,
        "profiles": profiles_list,
        "sessions_df": sessions_df,
        "summary_df": summary_df,
        "transitions": transitions,
        "sector_map": sector_map,
        "latest_prices": latest_prices,
    }

    html = build_html(report)
    filepath = write_report(html)

    # Print relative path in the exact UX shown in the spec
    relpath = os.path.join(OUTPUT_DIR, os.path.basename(filepath))

    elapsed = time.time() - t0
    print(f"\n📄 HTML report saved: {relpath}")
    print(f"  ⏱️  Total time: {elapsed:.1f}s")
    print("=" * 60)

    return filepath


__all__ = ["main"]
