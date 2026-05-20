"""broker_tracker.positions

Lifecycle state machine per broker-stock.

Reconstructs broker positions from net quantities (buy - sell) aggregated per session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from broker_tracker.config import (
    EXIT_CONFIRMATION_SESSIONS,
    FLAT_QTY_THRESHOLD,
    HOLDING_GAP_SESSIONS,
    MIN_SESSIONS_FOR_ACCUMULATION,
)


STATES = {
    "INACTIVE": "INACTIVE",
    "ENTERING": "ENTERING",
    "ACCUMULATING": "ACCUMULATING",
    "HOLDING": "HOLDING",
    "DISTRIBUTING": "DISTRIBUTING",
    "EXITING": "EXITING",
    "FLAT": "FLAT",
}


@dataclass
class CycleCtx:
    consec_buy: int = 0
    consec_sell: int = 0
    buy_qty_sum: int = 0
    buy_value_sum: float = 0.0
    cumulative_net_qty: int = 0


def _safe_float(v):
    try:
        if v is None:
            return None
        if pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def _compute_session_state(
    net_qty: int,
    cumulative_net_qty: int,
    consec_buy: int,
    consec_sell: int,
    sessions_since_last_trade: int,
) -> str:
    # FLAT takes priority once position is near zero
    if abs(int(cumulative_net_qty or 0)) < FLAT_QTY_THRESHOLD:
        return STATES["FLAT"]

    if net_qty > 0:
        if consec_buy >= MIN_SESSIONS_FOR_ACCUMULATION:
            return STATES["ACCUMULATING"]
        return STATES["ENTERING"]

    # net_qty <= 0
    if cumulative_net_qty > 0:
        if sessions_since_last_trade >= HOLDING_GAP_SESSIONS and net_qty == 0:
            return STATES["HOLDING"]
        if consec_sell >= EXIT_CONFIRMATION_SESSIONS and net_qty < 0:
            return STATES["EXITING"]
        return STATES["DISTRIBUTING"]

    return STATES["FLAT"]


def compute_broker_stock_positions(
    activity_df: pd.DataFrame,
    latest_prices: dict[str, dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute session-level lifecycle + a latest-state summary per broker-stock."""
    latest_prices = latest_prices or {}

    if activity_df is None or activity_df.empty:
        empty = pd.DataFrame()
        return empty, empty

    df = activity_df.copy()

    # Global session calendar (floorsheet trading sessions)
    all_dates = sorted(df["trading_date"].dropna().unique().tolist())
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    required_cols = [
        "trading_date",
        "symbol",
        "security_name",
        "broker_id",
        "broker_name",
        "bought_qty",
        "bought_value",
        "sold_qty",
        "sold_value",
        "net_qty",
        "total_qty",
        "asymmetry",
        "avg_buy_price",
        "avg_sell_price",
    ]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"activity_df missing required column: {c}")

    out_rows: list[dict[str, Any]] = []

    group_cols = ["broker_id", "symbol"]
    for (broker_id, symbol), g in df.groupby(group_cols, dropna=False):
        g = g.sort_values("trading_date", ascending=True)
        rows = g.to_dict("records")

        # Insert at most one synthetic HOLDING row per gap (to show quiet periods)
        timeline: list[dict[str, Any]] = []
        prev_idx = None
        for r in rows:
            d = r.get("trading_date")
            idx = date_to_idx.get(d)
            if prev_idx is not None and idx is not None:
                gap = idx - prev_idx - 1
                if gap >= HOLDING_GAP_SESSIONS:
                    hold_date = all_dates[prev_idx + HOLDING_GAP_SESSIONS]
                    synthetic = {
                        "trading_date": hold_date,
                        "symbol": r.get("symbol"),
                        "security_name": r.get("security_name"),
                        "broker_id": r.get("broker_id"),
                        "broker_name": r.get("broker_name"),
                        "bought_qty": 0,
                        "bought_value": 0.0,
                        "sold_qty": 0,
                        "sold_value": 0.0,
                        "matching_qty": 0,
                        "net_qty": 0,
                        "total_qty": 0,
                        "asymmetry": 50.0,
                        "avg_buy_price": pd.NA,
                        "avg_sell_price": pd.NA,
                        "is_synthetic": True,
                        "sessions_since_last_trade": HOLDING_GAP_SESSIONS,
                    }
                    timeline.append(synthetic)
            timeline.append({**r, "is_synthetic": False})
            prev_idx = idx

        ctx = CycleCtx()

        prev_trade_idx = None
        for r in timeline:
            d = r.get("trading_date")
            idx = date_to_idx.get(d)

            # sessions_since_last_trade: only meaningful on synthetic rows
            sessions_since_last_trade = int(r.get("sessions_since_last_trade") or 0)
            if not r.get("is_synthetic"):
                sessions_since_last_trade = 0
                prev_trade_idx = idx
            else:
                # For synthetic, idx is the holding trigger date, so since last trade is threshold
                if prev_trade_idx is not None and idx is not None:
                    sessions_since_last_trade = max(sessions_since_last_trade, idx - prev_trade_idx)

            net_qty = int(r.get("net_qty") or 0)

            if net_qty > 0:
                ctx.consec_buy += 1
                ctx.consec_sell = 0
            elif net_qty < 0:
                ctx.consec_sell += 1
                ctx.consec_buy = 0
            else:
                # flat session in terms of net activity
                ctx.consec_buy = 0
                ctx.consec_sell = 0

            bought_qty = int(r.get("bought_qty") or 0)
            bought_value = float(r.get("bought_value") or 0.0)
            if bought_qty > 0 and bought_value > 0:
                ctx.buy_qty_sum += bought_qty
                ctx.buy_value_sum += bought_value

            ctx.cumulative_net_qty += net_qty

            state = _compute_session_state(
                net_qty=net_qty,
                cumulative_net_qty=ctx.cumulative_net_qty,
                consec_buy=ctx.consec_buy,
                consec_sell=ctx.consec_sell,
                sessions_since_last_trade=sessions_since_last_trade,
            )

            # Prevent cross-cycle WABR contamination once a cycle is FLAT.
            if state == STATES["FLAT"]:
                if abs(int(ctx.cumulative_net_qty or 0)) < FLAT_QTY_THRESHOLD:
                    ctx.cumulative_net_qty = 0
                ctx.buy_qty_sum = 0
                ctx.buy_value_sum = 0.0

            cumulative_avg_cost = None
            if ctx.buy_qty_sum > 0:
                cumulative_avg_cost = ctx.buy_value_sum / ctx.buy_qty_sum

            price_row = latest_prices.get(symbol) if symbol else None
            current_price = None
            if price_row:
                current_price = price_row.get("close_price")
                try:
                    current_price = float(current_price) if current_price is not None else None
                except Exception:
                    current_price = None

            unrealized_pnl = None
            unrealized_pnl_pct = None
            if (
                current_price is not None
                and cumulative_avg_cost is not None
                and ctx.cumulative_net_qty is not None
                and ctx.cumulative_net_qty > 0
                and cumulative_avg_cost > 0
            ):
                unrealized_pnl = (current_price - cumulative_avg_cost) * ctx.cumulative_net_qty
                unrealized_pnl_pct = ((current_price / cumulative_avg_cost) - 1.0) * 100.0

            out_rows.append(
                {
                    **r,
                    "consecutive_net_buy_sessions": ctx.consec_buy,
                    "consecutive_net_sell_sessions": ctx.consec_sell,
                    "sessions_since_last_trade": sessions_since_last_trade,
                    "cumulative_net_qty": ctx.cumulative_net_qty,
                    "cumulative_avg_cost": cumulative_avg_cost,
                    "session_state": state,
                    "matching_qty": int(r.get("matching_qty") or 0),
                    "current_price": current_price,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                }
            )

    sessions_df = pd.DataFrame(out_rows)
    if sessions_df.empty:
        empty = pd.DataFrame()
        return empty, empty

    sessions_df = sessions_df.sort_values(
        ["broker_id", "symbol", "trading_date"], ascending=True
    ).reset_index(drop=True)

    # Rolling cumulative-delta windows for trend persistence checks.
    for window in (10, 20):
        sessions_df[f"rolling_cd_{window}"] = (
            sessions_df.groupby(["broker_id", "symbol"], dropna=False)["net_qty"]
            .transform(lambda x: x.rolling(window, min_periods=1).sum())
        )
    sessions_df["rolling_cd_slope_5"] = (
        sessions_df.groupby(["broker_id", "symbol"], dropna=False)["rolling_cd_10"]
        .transform(lambda x: x - x.shift(5))
    )

    # Summary: last row per broker-symbol
    summary_df = (
        sessions_df.sort_values("trading_date")
        .groupby(["broker_id", "symbol"], as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )

    # Sessions traded: count of real trade sessions (exclude synthetic + zero-qty rows)
    trade_counts = (
        sessions_df.loc[(~sessions_df["is_synthetic"]) & (sessions_df["total_qty"] > 0)]
        .groupby(["broker_id", "symbol"])
        .size()
        .rename("sessions_traded")
        .reset_index()
    )
    summary_df = summary_df.merge(trade_counts, on=["broker_id", "symbol"], how="left")
    summary_df["sessions_traded"] = summary_df["sessions_traded"].fillna(0).astype(int)

    return sessions_df, summary_df


def get_state_transitions(positions_sessions_df: pd.DataFrame) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """Extract state transitions per (broker_id, symbol)."""
    if positions_sessions_df is None or positions_sessions_df.empty:
        return {}

    out: dict[tuple[int, str], list[dict[str, Any]]] = {}

    for (broker_id, symbol), g in positions_sessions_df.groupby(["broker_id", "symbol"], dropna=False):
        g = g.sort_values("trading_date", ascending=True)
        last_state = None
        transitions: list[dict[str, Any]] = []

        for r in g.to_dict("records"):
            st = r.get("session_state")
            if st != last_state:
                note_parts = []
                bq = int(r.get("bought_qty") or 0)
                sq = int(r.get("sold_qty") or 0)
                if bq > 0:
                    note_parts.append(f"bought {bq}")
                if sq > 0:
                    note_parts.append(f"sold {sq}")
                abp = _safe_float(r.get("avg_buy_price"))
                if abp is not None and bq > 0:
                    note_parts.append(f"@ {abp:.2f}")

                transitions.append(
                    {
                        "trading_date": r.get("trading_date"),
                        "state": st,
                        "note": " ".join(note_parts) if note_parts else "",
                    }
                )
                last_state = st

        out[(int(broker_id), str(symbol))] = transitions

    return out
