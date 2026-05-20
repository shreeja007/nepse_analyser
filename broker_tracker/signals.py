"""broker_tracker.signals

BUY / WATCH / EXIT signal generation based on broker-stock lifecycle states.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import pandas as pd

from broker_tracker.config import (
    ABSENCE_EXIT_SESSIONS,
    ACCUMULATION_ASYMMETRY_THRESHOLD,
    BUY_CD_ROLLING_WINDOW,
    BUY_CD_SLOPE_WINDOW,
    BUY_MIN_BCR,
    BUY_MIN_BROKER_POWER_SCORE,
    BUY_MIN_VOLUME_RATIO,
    BUY_WABR_PROXIMITY_PCT,
    DISTRIBUTION_ASYMMETRY_THRESHOLD,
    MARKUP_EXHAUSTION_PCT,
    MIN_ACTIVITY_THRESHOLD,
    OPPOSING_BROKER_POWER_THRESHOLD,
    CIRCUIT_DAILY_MOVE_THRESHOLD_PCT,
    STOP_STRUCTURAL_PCT,
    STOP_TIME_MIN_APPRECIATION_PCT,
    STOP_TIME_SESSIONS,
)
from broker_tracker.sizing import compute_position_size


def _signal_strength(
    trust_score: float | None,
    trust_label: str,
    asymmetry: float,
    sessions_accumulating: int,
    power_score: float | None = None,
) -> str:
    trust = float(trust_score) if trust_score is not None else None
    power = float(power_score) if power_score is not None else None

    if trust is None and power is None:
        effective_score = None
    elif trust is None:
        effective_score = power
    elif power is None:
        effective_score = trust
    else:
        effective_score = (0.6 * power) + (0.4 * trust)

    if effective_score is not None and effective_score >= 70 and asymmetry >= 75 and sessions_accumulating >= 3:
        return "STRONG"
    if trust_label == "HIGH" and asymmetry >= 75 and sessions_accumulating >= 4:
        return "STRONG"
    if trust is not None and trust >= 70 and asymmetry >= 70:
        return "STRONG"
    if power is not None and power >= 75 and asymmetry >= 70:
        return "STRONG"
    if asymmetry >= 80 and sessions_accumulating >= 3:
        return "STRONG"

    if effective_score is not None and effective_score >= 55 and asymmetry >= 65:
        return "MODERATE"
    if trust_label in ("MEDIUM", "HIGH") and asymmetry >= 65:
        return "MODERATE"
    if trust is not None and trust >= 50:
        return "MODERATE"
    if power is not None and power >= 50:
        return "MODERATE"
    if asymmetry >= 70:
        return "MODERATE"

    return "WEAK"


def _build_symbol_market_context(activity_df: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if activity_df is None or activity_df.empty:
        return {}

    ctx: dict[str, dict[str, Any]] = {}
    for symbol, g in activity_df.groupby("symbol", dropna=False):
        sym = str(symbol or "")
        if not sym:
            continue

        day_qty = (
            g.groupby("trading_date", dropna=False)["total_qty"]
            .sum()
            .sort_index()
        )
        if day_qty.empty:
            continue

        latest_day = day_qty.index[-1]
        latest_volume = float(day_qty.iloc[-1])
        avg20_volume = float(day_qty.tail(20).mean()) if len(day_qty) > 0 else 0.0
        volume_ratio = (latest_volume / avg20_volume) if avg20_volume > 0 else None

        day_rows = g.loc[g["trading_date"] == latest_day]
        buy_by_broker = (
            day_rows.groupby("broker_id", dropna=False)["bought_value"]
            .sum()
            .sort_values(ascending=False)
        )
        sell_by_broker = (
            day_rows.groupby("broker_id", dropna=False)["sold_value"]
            .sum()
            .sort_values(ascending=False)
        )
        total_buy_turnover = float(buy_by_broker.sum()) if not buy_by_broker.empty else 0.0
        total_sell_turnover = float(sell_by_broker.sum()) if not sell_by_broker.empty else 0.0
        total_turnover = total_buy_turnover + total_sell_turnover
        top3_buy_turnover = float(buy_by_broker.head(3).sum()) if not buy_by_broker.empty else 0.0
        bcr = (top3_buy_turnover / total_turnover) if total_turnover > 0 else None
        dominant_broker_id = int(buy_by_broker.index[0]) if not buy_by_broker.empty else None
        dominant_seller_id = int(sell_by_broker.index[0]) if not sell_by_broker.empty else None

        ctx[sym] = {
            "latest_trading_date": latest_day,
            "latest_volume": latest_volume,
            "avg20_volume": avg20_volume,
            "volume_ratio": volume_ratio,
            "bcr": bcr,
            "dominant_broker_id": dominant_broker_id,
            "dominant_seller_id": dominant_seller_id,
        }

    return ctx


def _is_recent_circuit_move(
    symbol: str,
    price_history_by_symbol: dict[str, list[tuple[Any, float]]] | None,
) -> bool:
    series = (price_history_by_symbol or {}).get(symbol) or []
    if len(series) < 2:
        return False
    try:
        prev_close = float(series[-2][1])
        curr_close = float(series[-1][1])
    except Exception:
        return False
    if prev_close <= 0:
        return False
    move_pct = abs((curr_close - prev_close) / prev_close) * 100.0
    return move_pct >= CIRCUIT_DAILY_MOVE_THRESHOLD_PCT


def _get_current_price(symbol: str, latest_prices: dict[str, dict[str, Any]] | None) -> float | None:
    latest_prices = latest_prices or {}
    r = latest_prices.get(symbol)
    if not r:
        return None
    v = r.get("close_price")
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _last_trade_rows(group: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    if group is None or group.empty:
        return group
    g = group.loc[(~group["is_synthetic"]) & (group["total_qty"] > 0)].sort_values("trading_date")
    if g.empty:
        return g
    return g.tail(n)


def _current_cycle_start_idx(group: pd.DataFrame) -> int:
    """Index into group (sorted by date) of the row after the last FLAT."""
    g = group.sort_values("trading_date").reset_index(drop=True)
    flat_idx = g.index[g["session_state"] == "FLAT"].tolist()
    if not flat_idx:
        return 0
    return flat_idx[-1] + 1 if flat_idx[-1] + 1 < len(g) else len(g) - 1


def _entry_price_for_cycle(group: pd.DataFrame) -> float | None:
    g = group.sort_values("trading_date").reset_index(drop=True)
    start = _current_cycle_start_idx(g)
    seg = g.iloc[start:]
    if seg.empty:
        return None

    for _, r in seg.iterrows():
        v = r.get("avg_buy_price")
        if v is not None and not pd.isna(v):
            try:
                return float(v)
            except Exception:
                pass
        v = r.get("cumulative_avg_cost")
        if v is not None and not pd.isna(v):
            try:
                return float(v)
            except Exception:
                pass
    return None


def _current_cycle_rows(group: pd.DataFrame) -> pd.DataFrame:
    if group is None or group.empty:
        return group
    g = group.sort_values("trading_date").reset_index(drop=True)
    start = _current_cycle_start_idx(g)
    if start < 0:
        return g
    return g.iloc[start:].copy()


def compute_stop_levels(
    wabr_price: float | None,
    current_price: float | None,
    avg_hold_sessions: float,
    sessions_held: int,
) -> dict[str, Any]:
    """Compute structural and time-stop signals for an open broker cycle."""
    structural_stop = (wabr_price * (1.0 - STOP_STRUCTURAL_PCT)) if wabr_price else None

    structural_triggered = (
        current_price is not None
        and structural_stop is not None
        and current_price < structural_stop
    )

    time_stop_triggered = (
        sessions_held >= STOP_TIME_SESSIONS
        and current_price is not None
        and wabr_price is not None
        and current_price < (wabr_price * (1.0 + (STOP_TIME_MIN_APPRECIATION_PCT / 100.0)))
    )

    return {
        "structural_stop_price": structural_stop,
        "structural_stop_triggered": bool(structural_triggered),
        "time_stop_triggered": bool(time_stop_triggered),
        "sessions_held": int(sessions_held),
        "avg_hold_sessions": float(avg_hold_sessions or 0.0),
    }


def _recent_sessions_payload(group: pd.DataFrame, n: int = 3) -> list[dict[str, Any]]:
    """Compact trailing trade-session snapshot used in signal explainability."""
    if group is None or group.empty:
        return []

    tail = _last_trade_rows(group, n=n)
    if tail is None or tail.empty:
        return []

    out: list[dict[str, Any]] = []
    for _, row in tail.iterrows():
        out.append(
            {
                "trading_date": str(row.get("trading_date") or ""),
                "session_state": str(row.get("session_state") or ""),
                "net_qty": int(row.get("net_qty") or 0),
                "cumulative_net_qty": int(row.get("cumulative_net_qty") or 0),
                "asymmetry": float(row.get("asymmetry") or 50.0),
                "total_qty": int(row.get("total_qty") or 0),
            }
        )
    return out


def generate_signals(
    positions_sessions_df: pd.DataFrame,
    positions_summary_df: pd.DataFrame,
    broker_profiles: dict[int, dict[str, Any]],
    latest_prices: dict[str, dict[str, Any]] | None = None,
    activity_df: pd.DataFrame | None = None,
    price_history_by_symbol: dict[str, list[tuple[Any, float]]] | None = None,
    atr_by_symbol: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (buy_signals, watch_signals, exit_signals)."""
    latest_prices = latest_prices or {}

    if positions_summary_df is None or positions_summary_df.empty:
        return [], [], []

    sessions = positions_sessions_df if positions_sessions_df is not None else pd.DataFrame()

    buy_signals: list[dict[str, Any]] = []
    watch_signals: list[dict[str, Any]] = []
    exit_signals: list[dict[str, Any]] = []

    symbol_market_ctx = _build_symbol_market_context(activity_df)

    # Pre-group session history for quick lookups
    grouped = {}
    if sessions is not None and not sessions.empty:
        for key, g in sessions.groupby(["broker_id", "symbol"], dropna=False):
            grouped[key] = g.sort_values("trading_date")

    for r in positions_summary_df.to_dict("records"):
        broker_id = int(r.get("broker_id") or 0)
        symbol = str(r.get("symbol") or "")
        broker_name = str(r.get("broker_name") or "")
        state = str(r.get("session_state") or "")

        profile = broker_profiles.get(broker_id, {})
        trust_score = profile.get("trust_score")
        trust_label = profile.get("trust_label") or "UNRATED"
        power_score = float(profile.get("broker_power_score") or 0.0)
        avg_hold_sessions = float(profile.get("avg_hold_sessions") or 0.0)

        current_price = _get_current_price(symbol, latest_prices)
        symbol_ctx = symbol_market_ctx.get(symbol, {})
        bcr = symbol_ctx.get("bcr")
        dominant_broker_id = symbol_ctx.get("dominant_broker_id")
        dominant_seller_id = symbol_ctx.get("dominant_seller_id")
        volume_ratio = symbol_ctx.get("volume_ratio")
        circuit_active = _is_recent_circuit_move(symbol, price_history_by_symbol)

        g = grouped.get((broker_id, symbol))
        latest_trade = None
        if g is not None and not g.empty:
            trade_tail = _last_trade_rows(g, n=3)
            if not trade_tail.empty:
                latest_trade = trade_tail.tail(1).to_dict("records")[0]

        latest_asym = None
        avg_buy_price = None
        latest_matching_qty = 0
        latest_bought_qty = 0
        latest_sold_qty = 0
        latest_net_qty = 0
        cumulative_net_qty = int(r.get("cumulative_net_qty") or 0)
        wabr_price = None
        try:
            v_wabr = r.get("cumulative_avg_cost")
            if v_wabr is not None and not pd.isna(v_wabr):
                wabr_price = float(v_wabr)
        except Exception:
            wabr_price = None

        if latest_trade:
            latest_asym = float(latest_trade.get("asymmetry") or 50.0)
            v = latest_trade.get("avg_buy_price")
            if v is not None and not pd.isna(v):
                avg_buy_price = float(v)
            latest_matching_qty = int(latest_trade.get("matching_qty") or 0)
            latest_bought_qty = int(latest_trade.get("bought_qty") or 0)
            latest_sold_qty = int(latest_trade.get("sold_qty") or 0)
            latest_net_qty = int(latest_trade.get("net_qty") or 0)

        effective_wabr = wabr_price
        if effective_wabr is None and avg_buy_price is not None:
            effective_wabr = avg_buy_price

        # Sessions accumulating: trailing ACCUMULATING streak
        sessions_accumulating = 0
        if g is not None and not g.empty:
            tail = g.loc[(~g["is_synthetic"]) & (g["total_qty"] > 0)].sort_values("trading_date")
            if not tail.empty:
                for st in reversed(tail["session_state"].tolist()):
                    if st == "ACCUMULATING":
                        sessions_accumulating += 1
                    else:
                        break

        sessions_traded = int(r.get("sessions_traded") or 0)
        cycle_rows = _current_cycle_rows(g) if g is not None and not g.empty else pd.DataFrame()
        sessions_held = 0
        if cycle_rows is not None and not cycle_rows.empty:
            if "is_synthetic" in cycle_rows.columns:
                sessions_held = int((cycle_rows["is_synthetic"] == False).sum())
            else:
                sessions_held = int(len(cycle_rows))

        absent_sessions = 0
        if g is not None and not g.empty:
            g_sorted = g.sort_values("trading_date")
            for row in reversed(g_sorted.to_dict("records")):
                if bool(row.get("is_synthetic")) or int(row.get("net_qty") or 0) <= 0:
                    absent_sessions += 1
                else:
                    break

        entry_price = _entry_price_for_cycle(g) if g is not None and not g.empty else None
        price_move_since_entry_pct = None
        if entry_price and current_price and entry_price > 0:
            price_move_since_entry_pct = ((current_price / entry_price) - 1.0) * 100.0

        # Growing cumulative (not plateauing): latest cumulative vs previous trade session
        cumulative_growing = None
        cumulative_prev = None
        cumulative_curr = None
        cd_slope_positive = None
        cd_prev = None
        cd_curr = None
        if g is not None and not g.empty:
            trade_tail = _last_trade_rows(g, n=2)
            if len(trade_tail) >= 2:
                a = int(trade_tail.iloc[-2].get("cumulative_net_qty") or 0)
                b = int(trade_tail.iloc[-1].get("cumulative_net_qty") or 0)
                cumulative_growing = b > a
                cumulative_prev = a
                cumulative_curr = b

            if f"rolling_cd_{BUY_CD_ROLLING_WINDOW}" in g.columns:
                latest_real = _last_trade_rows(g, n=1)
                if not latest_real.empty:
                    cd_col = f"rolling_cd_{BUY_CD_ROLLING_WINDOW}"
                    cd_curr_raw = latest_real.iloc[-1].get(cd_col)
                    if cd_curr_raw is not None and not pd.isna(cd_curr_raw):
                        cd_curr = float(cd_curr_raw)

                    slope_col = f"rolling_cd_slope_{BUY_CD_SLOPE_WINDOW}"
                    if slope_col not in g.columns and "rolling_cd_slope_5" in g.columns:
                        slope_col = "rolling_cd_slope_5"
                    slope_raw = latest_real.iloc[-1].get(slope_col)
                    if slope_raw is not None and not pd.isna(slope_raw):
                        slope_val = float(slope_raw)
                        cd_slope_positive = slope_val > 0
                        if cd_curr is not None:
                            cd_prev = cd_curr - slope_val

        if cd_slope_positive is None:
            cd_slope_positive = cumulative_growing

        wabr_proximity_pct = None
        if current_price is not None and effective_wabr is not None and effective_wabr > 0:
            wabr_proximity_pct = abs((current_price - effective_wabr) / effective_wabr) * 100.0

        stop_levels = compute_stop_levels(
            wabr_price=effective_wabr,
            current_price=current_price,
            avg_hold_sessions=avg_hold_sessions,
            sessions_held=sessions_held,
        )
        structural_stop_triggered = bool(stop_levels.get("structural_stop_triggered"))
        time_stop_triggered = bool(stop_levels.get("time_stop_triggered"))

        atr_14 = None
        if atr_by_symbol:
            try:
                atr_14 = float(atr_by_symbol.get(symbol)) if atr_by_symbol.get(symbol) is not None else None
            except Exception:
                atr_14 = None
        position_size = compute_position_size(
            current_price=current_price,
            atr_14=atr_14,
            broker_power_score=power_score,
            broker_daily_net_qty=(latest_net_qty if latest_net_qty > 0 else cumulative_net_qty),
        )

        recent_sessions = _recent_sessions_payload(g, n=3) if g is not None and not g.empty else []

        # ── BUY ────────────────────────────────────────────────────────
        if (
            state == "ACCUMULATING"
            and latest_asym is not None
            and latest_asym > ACCUMULATION_ASYMMETRY_THRESHOLD
            and cd_slope_positive is True
            and cumulative_curr is not None
            and cumulative_curr > 0
            and power_score >= BUY_MIN_BROKER_POWER_SCORE
            and bcr is not None
            and float(bcr) >= BUY_MIN_BCR
            and dominant_broker_id == broker_id
            and wabr_proximity_pct is not None
            and wabr_proximity_pct <= BUY_WABR_PROXIMITY_PCT
            and volume_ratio is not None
            and float(volume_ratio) > BUY_MIN_VOLUME_RATIO
            and not circuit_active
            and not structural_stop_triggered
            and sessions_traded >= MIN_ACTIVITY_THRESHOLD
        ):
            strength = _signal_strength(
                trust_score,
                trust_label,
                float(latest_asym),
                sessions_accumulating,
                power_score=power_score,
            )
            trust_text = (
                f"{trust_label} ({float(trust_score):.1f})"
                if trust_score is not None
                else f"{trust_label}"
            )
            why_points = [
                "Session state is ACCUMULATING.",
                f"Latest asymmetry is {float(latest_asym):.1f}% (> {ACCUMULATION_ASYMMETRY_THRESHOLD}%).",
                f"Broker power score is {power_score:.1f} (min {BUY_MIN_BROKER_POWER_SCORE:.1f}).",
                f"Market concentration BCR is {float(bcr):.2f} (min {BUY_MIN_BCR:.2f}) and broker {broker_id} is dominant buyer.",
                f"Rolling CD slope is positive ({int(cd_prev or 0):,} -> {int(cd_curr or 0):,} over {BUY_CD_SLOPE_WINDOW} sessions).",
                f"Current price is {float(wabr_proximity_pct):.2f}% away from WABR (max {BUY_WABR_PROXIMITY_PCT:.1f}%).",
                f"Volume ratio is {float(volume_ratio):.2f}x (min > {BUY_MIN_VOLUME_RATIO:.1f}x).",
                "No near-circuit move detected in the latest session.",
                f"Structural stop is set at {float(stop_levels.get('structural_stop_price') or 0.0):.2f}.",
                f"Suggested size: {int(position_size.get('recommended_qty') or 0):,} shares (~Rs {float(position_size.get('recommended_notional_rs') or 0.0):,.0f}).",
                f"Activity gate passed with {sessions_traded} traded sessions (min {MIN_ACTIVITY_THRESHOLD}).",
                f"Broker trust context: {trust_text}.",
                f"Signal strength computed as {strength}.",
            ]
            if latest_matching_qty > 0:
                why_points.append(f"Cross-trade warning: matching volume {latest_matching_qty:,} shares detected.")
            buy_signals.append(
                {
                    "signal_type": "BUY",
                    "symbol": symbol,
                    "broker_id": broker_id,
                    "broker_name": broker_name,
                    "broker_trust_score": trust_score,
                    "broker_trust_label": trust_label,
                    "broker_power_score": power_score,
                    "current_state": state,
                    "sessions_accumulating": sessions_accumulating,
                    "cumulative_net_qty": cumulative_net_qty,
                    "avg_buy_price": avg_buy_price,
                    "wabr_price": effective_wabr,
                    "raw_wabr_price": wabr_price,
                    "current_price": current_price,
                    "price_move_since_entry_pct": price_move_since_entry_pct,
                    "wabr_proximity_pct": wabr_proximity_pct,
                    "rolling_cd_prev": cd_prev,
                    "rolling_cd_curr": cd_curr,
                    "rolling_cd_slope_positive": bool(cd_slope_positive),
                    "bcr": bcr,
                    "dominant_broker_id": dominant_broker_id,
                    "volume_ratio": volume_ratio,
                    "circuit_active": circuit_active,
                    "matching_qty": latest_matching_qty,
                    "atr_14": atr_14,
                    "position_size": position_size,
                    "structural_stop_price": stop_levels.get("structural_stop_price"),
                    "structural_stop_triggered": structural_stop_triggered,
                    "time_stop_triggered": time_stop_triggered,
                    "sessions_held": sessions_held,
                    "latest_asymmetry": latest_asym,
                    "signal_strength": strength,
                    "signal_date": date.today(),
                    "why_summary": "Accumulation passed broker-quality, dominance, flow-slope, WABR, and liquidity gates.",
                    "why_points": why_points,
                    "recent_sessions": recent_sessions,
                }
            )
            continue

        # ── WATCH ──────────────────────────────────────────────────────
        if (
            state == "ENTERING"
            and latest_asym is not None
            and float(latest_asym) > 60.0
            and sessions_traded >= MIN_ACTIVITY_THRESHOLD
            and cumulative_net_qty > 0
            and (
                (trust_score is not None and float(trust_score) > 50.0)
                or trust_label == "UNRATED"
            )
        ):
            strength = _signal_strength(
                trust_score,
                trust_label,
                float(latest_asym),
                sessions_accumulating,
                power_score=power_score,
            )
            if trust_score is not None:
                trust_gate = f"Trust score {float(trust_score):.1f} > 50.0"
            else:
                trust_gate = "Broker is UNRATED, which is allowed for WATCH signals"

            why_points = [
                "Session state is ENTERING (early accumulation phase).",
                f"Latest asymmetry is {float(latest_asym):.1f}% (> 60.0%).",
                f"Activity gate passed with {sessions_traded} traded sessions (min {MIN_ACTIVITY_THRESHOLD}).",
                f"Net position is positive ({cumulative_net_qty:,}), not just short covering.",
                trust_gate + ".",
                f"Trailing accumulating streak is {sessions_accumulating} sessions.",
                f"Signal strength computed as {strength}.",
            ]
            watch_signals.append(
                {
                    "signal_type": "WATCH",
                    "symbol": symbol,
                    "broker_id": broker_id,
                    "broker_name": broker_name,
                    "broker_trust_score": trust_score,
                    "broker_trust_label": trust_label,
                    "broker_power_score": power_score,
                    "current_state": state,
                    "sessions_accumulating": sessions_accumulating,
                    "cumulative_net_qty": cumulative_net_qty,
                    "avg_buy_price": avg_buy_price,
                    "wabr_price": effective_wabr,
                    "raw_wabr_price": wabr_price,
                    "current_price": current_price,
                    "price_move_since_entry_pct": price_move_since_entry_pct,
                    "bcr": bcr,
                    "volume_ratio": volume_ratio,
                    "circuit_active": circuit_active,
                    "matching_qty": latest_matching_qty,
                    "atr_14": atr_14,
                    "position_size": position_size,
                    "structural_stop_price": stop_levels.get("structural_stop_price"),
                    "structural_stop_triggered": structural_stop_triggered,
                    "time_stop_triggered": time_stop_triggered,
                    "sessions_held": sessions_held,
                    "latest_asymmetry": latest_asym,
                    "signal_strength": strength,
                    "signal_date": date.today(),
                    "why_summary": "Broker is entering a likely accumulation cycle.",
                    "why_points": why_points,
                    "recent_sessions": recent_sessions,
                }
            )
            continue

        # ── EXIT ───────────────────────────────────────────────────────
        state_changed = False
        asym_drop = False
        qty_drop = False
        markup_exhaustion = False
        opposing_broker_exit = False
        broker_abandoned = False
        stop_loss_triggered = False
        prev_state = None
        curr_state = None
        prev_asym = None
        curr_asym = None
        two_ago = None
        curr = None

        if g is not None and not g.empty:
            g_sorted = g.sort_values("trading_date")
            if len(g_sorted) >= 2:
                prev_state = str(g_sorted.iloc[-2].get("session_state") or "")
                curr_state = str(g_sorted.iloc[-1].get("session_state") or "")
                if curr_state in ("DISTRIBUTING", "EXITING") and prev_state not in ("DISTRIBUTING", "EXITING"):
                    state_changed = True

            trade_tail = _last_trade_rows(g, n=3)
            if len(trade_tail) >= 2:
                prev_asym = float(trade_tail.iloc[-2].get("asymmetry") or 50.0)
                curr_asym = float(trade_tail.iloc[-1].get("asymmetry") or 50.0)
                if prev_asym > ACCUMULATION_ASYMMETRY_THRESHOLD and curr_asym < DISTRIBUTION_ASYMMETRY_THRESHOLD:
                    asym_drop = True

            if len(trade_tail) >= 3:
                two_ago = float(trade_tail.iloc[-3].get("cumulative_net_qty") or 0)
                curr = float(trade_tail.iloc[-1].get("cumulative_net_qty") or 0)
                if two_ago > 0 and curr < two_ago * 0.70:
                    qty_drop = True

        if (
            effective_wabr is not None
            and current_price is not None
            and effective_wabr > 0
            and current_price > effective_wabr * (1.0 + (MARKUP_EXHAUSTION_PCT / 100.0))
            and latest_sold_qty > latest_bought_qty
        ):
            markup_exhaustion = True

        dominant_seller_profile = broker_profiles.get(int(dominant_seller_id or 0), {}) if dominant_seller_id is not None else {}
        dominant_seller_power = float(dominant_seller_profile.get("broker_power_score") or 0.0)
        if (
            dominant_seller_id is not None
            and int(dominant_seller_id) != broker_id
            and dominant_seller_power >= OPPOSING_BROKER_POWER_THRESHOLD
            and cumulative_net_qty > 0
        ):
            opposing_broker_exit = True

        if absent_sessions >= ABSENCE_EXIT_SESSIONS and state == "HOLDING" and cumulative_net_qty > 0:
            broker_abandoned = True

        stop_loss_triggered = structural_stop_triggered or time_stop_triggered

        state_machine_triggered = state_changed or asym_drop or qty_drop
        protective_triggered = stop_loss_triggered or markup_exhaustion or opposing_broker_exit or broker_abandoned

        state_machine_exit = (
            state_machine_triggered
            and cumulative_net_qty > 0
            and state in ("DISTRIBUTING", "EXITING")
        )
        protective_exit = (
            protective_triggered
            and cumulative_net_qty > 0
            and state not in ("FLAT", "INACTIVE")
        )

        if state_machine_exit or protective_exit:
            exit_category = "PROTECTIVE" if protective_exit and not state_machine_exit else "DISTRIBUTION"
            strength = _signal_strength(
                trust_score,
                trust_label,
                float(latest_asym or 50.0),
                sessions_accumulating,
                power_score=power_score,
            )
            pnl_if_held = None
            if avg_buy_price and current_price and cumulative_net_qty:
                pnl_if_held = (current_price - avg_buy_price) * cumulative_net_qty

            exit_triggers: list[str] = []
            if state_changed:
                exit_triggers.append(f"State changed from {prev_state or 'UNKNOWN'} to {curr_state or state}.")
            if asym_drop:
                exit_triggers.append(
                    f"Asymmetry dropped from {float(prev_asym or 0.0):.1f}% to {float(curr_asym or 0.0):.1f}% "
                    f"({ACCUMULATION_ASYMMETRY_THRESHOLD}% -> {DISTRIBUTION_ASYMMETRY_THRESHOLD}% band break)."
                )
            if qty_drop:
                exit_triggers.append(
                    f"Cumulative position shrank sharply ({int(two_ago or 0):,} -> {int(curr or 0):,}, over 30% drawdown)."
                )
            if markup_exhaustion:
                exit_triggers.append(
                    f"Markup exhaustion: price exceeded WABR by {MARKUP_EXHAUSTION_PCT:.1f}% while sell flow overtook buy flow."
                )
            if opposing_broker_exit:
                exit_triggers.append(
                    f"Opposing dominant seller {int(dominant_seller_id or 0)} has power {dominant_seller_power:.1f} (>= {OPPOSING_BROKER_POWER_THRESHOLD:.1f})."
                )
            if broker_abandoned:
                exit_triggers.append(
                    f"Broker buy-side absence detected for {absent_sessions} consecutive sessions (threshold {ABSENCE_EXIT_SESSIONS})."
                )
            if stop_loss_triggered:
                stop_note = ""
                if structural_stop_triggered:
                    stop_note = f"Structural stop breached below {float(stop_levels.get('structural_stop_price') or 0.0):.2f}."
                elif time_stop_triggered:
                    stop_note = (
                        f"Time stop triggered after {sessions_held} sessions with insufficient appreciation "
                        f"(< {STOP_TIME_MIN_APPRECIATION_PCT:.1f}%)."
                    )
                exit_triggers.append(stop_note)
            if not exit_triggers:
                exit_triggers.append("Exit conditions were met by distribution behavior.")

            why_points = [
                f"Current session state is {state}.",
                f"Exit category: {exit_category}.",
                "Trigger(s): " + " ".join(exit_triggers),
                f"Remaining cumulative quantity is {cumulative_net_qty:,}.",
                f"Signal strength computed as {strength}.",
            ]

            exit_signals.append(
                {
                    "signal_type": "EXIT",
                    "symbol": symbol,
                    "broker_id": broker_id,
                    "broker_name": broker_name,
                    "broker_trust_score": trust_score,
                    "broker_trust_label": trust_label,
                    "broker_power_score": power_score,
                    "current_state": state,
                    "state_machine_exit": state_machine_exit,
                    "protective_exit": protective_exit,
                    "exit_category": exit_category,
                    "state_changed": state_changed,
                    "cumulative_net_qty": cumulative_net_qty,
                    "avg_buy_price": avg_buy_price,
                    "wabr_price": effective_wabr,
                    "raw_wabr_price": wabr_price,
                    "current_price": current_price,
                    "pnl_if_held": pnl_if_held,
                    "bcr": bcr,
                    "dominant_seller_id": dominant_seller_id,
                    "opposing_seller_power": dominant_seller_power if dominant_seller_id is not None else None,
                    "volume_ratio": volume_ratio,
                    "circuit_active": circuit_active,
                    "matching_qty": latest_matching_qty,
                    "atr_14": atr_14,
                    "position_size": position_size,
                    "sessions_held": sessions_held,
                    "consecutive_absent_sessions": absent_sessions,
                    "broker_abandoned": broker_abandoned,
                    "markup_exhaustion": markup_exhaustion,
                    "opposing_broker_exit": opposing_broker_exit,
                    "structural_stop_price": stop_levels.get("structural_stop_price"),
                    "structural_stop_triggered": structural_stop_triggered,
                    "time_stop_triggered": time_stop_triggered,
                    "latest_asymmetry": latest_asym,
                    "signal_strength": strength,
                    "signal_date": date.today(),
                    "asym_drop": asym_drop,
                    "qty_drop": qty_drop,
                    "why_summary": "Protective or distribution exit behavior detected in the broker lifecycle.",
                    "why_points": why_points,
                    "recent_sessions": recent_sessions,
                }
            )

    # Sort: strongest first
    strength_rank = {"STRONG": 0, "MODERATE": 1, "WEAK": 2}

    def _sort_key(s: dict[str, Any]):
        return (
            strength_rank.get(s.get("signal_strength"), 9),
            -(float(s.get("broker_power_score") or 0.0)),
            -(float(s.get("broker_trust_score") or 0.0)),
            -(float(s.get("latest_asymmetry") or 0.0)),
        )

    buy_signals.sort(key=_sort_key)
    watch_signals.sort(key=_sort_key)

    # EXIT: EXITING first, then state_changed/asym_drop/qty_drop implied
    def _exit_key(s: dict[str, Any]):
        st = s.get("current_state")
        return (
            0 if st == "EXITING" else 1,
            0 if s.get("state_changed") else 1,
            strength_rank.get(s.get("signal_strength"), 9),
        )

    exit_signals.sort(key=_exit_key)

    return buy_signals, watch_signals, exit_signals


def _strength_to_num(v: str | None) -> float:
    m = {"STRONG": 1.0, "MODERATE": 0.6, "WEAK": 0.3}
    return m.get(str(v or "").upper(), 0.3)


def _num_to_strength(v: float) -> str:
    if v >= 0.85:
        return "STRONG"
    if v >= 0.5:
        return "MODERATE"
    return "WEAK"


def _trust_label_from_score(v: float | None) -> str:
    if v is None:
        return "UNRATED"
    if v >= 70:
        return "HIGH"
    if v >= 40:
        return "MEDIUM"
    return "LOW"


def _mean_float(vals: list[float | None]) -> float | None:
    xs = [float(v) for v in vals if v is not None]
    if not xs:
        return None
    return sum(xs) / len(xs)


def _aggregate_stock_signal_rows(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    if not rows:
        return []

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sym = str(r.get("symbol") or "")
        if not sym:
            continue
        grouped[sym].append(r)

    out: list[dict[str, Any]] = []
    for symbol, group in grouped.items():
        brokers = sorted({int(x.get("broker_id") or 0) for x in group})
        broker_count = len(brokers)

        avg_trust = _mean_float([x.get("broker_trust_score") for x in group])
        trust_label = _trust_label_from_score(avg_trust)
        avg_asym = _mean_float([x.get("latest_asymmetry") for x in group]) or 50.0
        avg_move = _mean_float([x.get("price_move_since_entry_pct") for x in group])
        avg_buy = _mean_float([x.get("avg_buy_price") for x in group])
        current_price = _mean_float([x.get("current_price") for x in group])
        avg_strength_num = _mean_float([_strength_to_num(x.get("signal_strength")) for x in group]) or 0.3
        signal_strength = _num_to_strength(avg_strength_num)

        contributors: list[dict[str, Any]] = []
        for g in group:
            contributors.append(
                {
                    "broker_id": int(g.get("broker_id") or 0),
                    "broker_name": str(g.get("broker_name") or ""),
                    "broker_power_score": g.get("broker_power_score"),
                    "broker_trust_score": g.get("broker_trust_score"),
                    "broker_trust_label": str(g.get("broker_trust_label") or "UNRATED"),
                    "signal_strength": str(g.get("signal_strength") or "WEAK"),
                    "exit_category": str(g.get("exit_category") or ""),
                    "current_state": str(g.get("current_state") or ""),
                    "latest_asymmetry": g.get("latest_asymmetry"),
                    "price_move_since_entry_pct": g.get("price_move_since_entry_pct"),
                    "sessions_accumulating": int(g.get("sessions_accumulating") or 0),
                    "cumulative_net_qty": int(g.get("cumulative_net_qty") or 0),
                }
            )
        contributors.sort(
            key=lambda x: (
                -_strength_to_num(x.get("signal_strength")),
                -(float(x.get("broker_power_score") or 0.0)),
                -(float(x.get("broker_trust_score") or 0.0)),
                -(float(x.get("latest_asymmetry") or 0.0)),
            )
        )

        if kind in ("BUY", "WATCH"):
            score = (
                (avg_strength_num * 35.0)
                + (min(broker_count, 10) / 10.0 * 25.0)
                + ((avg_asym / 100.0) * 20.0)
                + (((avg_trust if avg_trust is not None else 50.0) / 100.0) * 20.0)
            )
            score = max(0.0, min(100.0, score))

            why_points = [
                f"{broker_count} brokers currently contribute to this {kind} signal cluster.",
                f"Average broker trust is {trust_label} ({float(avg_trust or 0.0):.1f}).",
                f"Average asymmetry is {float(avg_asym):.1f}%.",
                f"Consensus signal strength is {signal_strength}.",
            ]
            if avg_move is not None:
                why_points.append(f"Average move since cycle entry is {float(avg_move):.1f}%.")

            out.append(
                {
                    "signal_type": kind,
                    "symbol": symbol,
                    "broker_count": broker_count,
                    "broker_ids": brokers,
                    "contributors": contributors[:10],
                    "broker_trust_score": avg_trust,
                    "broker_trust_label": trust_label,
                    "avg_buy_price": avg_buy,
                    "current_price": current_price,
                    "price_move_since_entry_pct": avg_move,
                    "latest_asymmetry": avg_asym,
                    "signal_strength": signal_strength,
                    "stock_score": score,
                    "why_summary": f"{kind} ranked by stock-level broker consensus and conviction breadth.",
                    "why_points": why_points,
                    "recent_sessions": group[0].get("recent_sessions") if group else [],
                }
            )
            continue

        # EXIT
        total_qty_remaining = sum(max(0, int(x.get("cumulative_net_qty") or 0)) for x in group)
        total_pnl = sum(float(x.get("pnl_if_held") or 0.0) for x in group)
        protective_count = sum(1 for x in group if str(x.get("exit_category") or "") == "PROTECTIVE")
        distribution_count = sum(1 for x in group if str(x.get("exit_category") or "") == "DISTRIBUTION")
        any_state_changed = any(bool(x.get("state_changed")) for x in group)
        any_asym_drop = any(bool(x.get("asym_drop")) for x in group)
        any_qty_drop = any(bool(x.get("qty_drop")) for x in group)
        any_markup_exhaustion = any(bool(x.get("markup_exhaustion")) for x in group)
        any_opposing_broker_exit = any(bool(x.get("opposing_broker_exit")) for x in group)
        any_broker_abandoned = any(bool(x.get("broker_abandoned")) for x in group)
        any_structural_stop = any(bool(x.get("structural_stop_triggered")) for x in group)
        any_time_stop = any(bool(x.get("time_stop_triggered")) for x in group)
        trigger_count = (
            int(any_state_changed)
            + int(any_asym_drop)
            + int(any_qty_drop)
            + int(any_markup_exhaustion)
            + int(any_opposing_broker_exit)
            + int(any_broker_abandoned)
            + int(any_structural_stop)
            + int(any_time_stop)
        )
        trigger_max = 8

        score = (
            (avg_strength_num * 30.0)
            + (min(broker_count, 10) / 10.0 * 25.0)
            + (((100.0 - avg_asym) / 100.0) * 20.0)
            + ((trigger_count / float(trigger_max)) * 25.0)
        )
        score = max(0.0, min(100.0, score))

        why_points = [
            f"{broker_count} brokers are signaling distribution/exit behavior on this stock.",
            f"Average asymmetry is {float(avg_asym):.1f}% (lower implies stronger distribution).",
            f"Exit trigger consensus count is {trigger_count}/{trigger_max}.",
            f"Protective exits: {protective_count}, distribution exits: {distribution_count}.",
            f"Consensus signal strength is {signal_strength}.",
        ]

        out.append(
            {
                "signal_type": "EXIT",
                "symbol": symbol,
                "broker_count": broker_count,
                "broker_ids": brokers,
                "contributors": contributors[:10],
                "broker_trust_score": avg_trust,
                "broker_trust_label": trust_label,
                "protective_exit_count": protective_count,
                "distribution_exit_count": distribution_count,
                "state_changed": any_state_changed,
                "cumulative_net_qty": total_qty_remaining,
                "avg_buy_price": avg_buy,
                "current_price": current_price,
                "pnl_if_held": total_pnl,
                "latest_asymmetry": avg_asym,
                "signal_strength": signal_strength,
                "stock_score": score,
                "why_summary": "Stock-level exit pressure based on multi-broker distribution signals.",
                "why_points": why_points,
                "recent_sessions": group[0].get("recent_sessions") if group else [],
            }
        )

    # Highest conviction first. For EXIT ties, lower asymmetry implies stronger distribution.
    if kind == "EXIT":
        out.sort(
            key=lambda x: (
                -(float(x.get("stock_score") or 0.0)),
                -(int(x.get("broker_count") or 0)),
                float(x.get("latest_asymmetry") or 0.0),
            )
        )
    else:
        out.sort(
            key=lambda x: (
                -(float(x.get("stock_score") or 0.0)),
                -(int(x.get("broker_count") or 0)),
                -(float(x.get("latest_asymmetry") or 0.0)),
            )
        )
    return out


def aggregate_stock_signals(
    buy_signals: list[dict[str, Any]],
    watch_signals: list[dict[str, Any]],
    exit_signals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Aggregate broker-level signals into stock-level consensus rankings."""
    buy_stock = _aggregate_stock_signal_rows(buy_signals, "BUY")
    watch_stock = _aggregate_stock_signal_rows(watch_signals, "WATCH")
    exit_stock = _aggregate_stock_signal_rows(exit_signals, "EXIT")
    return buy_stock, watch_stock, exit_stock
