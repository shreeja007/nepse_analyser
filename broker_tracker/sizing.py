"""broker_tracker.sizing

Position sizing helpers for BUY signal execution guidance.
"""

from __future__ import annotations

from math import floor
from typing import Any

from broker_tracker.config import (
    DEFAULT_PORTFOLIO_CAPITAL_RS,
    POSITION_FRONT_RUN_CAP_PCT,
    POSITION_MAX_CAPITAL_PCT,
    POSITION_MIN_NOTIONAL_RS,
    POSITION_RISK_BUDGET_PCT,
)


def compute_position_size(
    current_price: float | None,
    atr_14: float | None,
    broker_power_score: float | None,
    broker_daily_net_qty: int | None = None,
    portfolio_capital_rs: float = DEFAULT_PORTFOLIO_CAPITAL_RS,
) -> dict[str, Any]:
    """Return a practical, risk-budgeted quantity suggestion for a BUY setup."""
    if current_price is None or current_price <= 0:
        return {
            "recommended_qty": 0,
            "recommended_notional_rs": 0.0,
            "risk_budget_rs": 0.0,
            "per_share_risk": None,
            "atr_14": atr_14,
            "qty_by_risk": 0,
            "qty_by_capital": 0,
            "qty_by_front_run_cap": None,
            "broker_daily_net_qty": broker_daily_net_qty,
            "sizing_note": "Missing/invalid current price.",
        }

    power = float(broker_power_score or 0.0)

    # Research-aligned risk tiers by broker power.
    if power >= 85.0:
        risk_multiplier = 3.0
    elif power >= 70.0:
        risk_multiplier = 2.0
    else:
        risk_multiplier = 1.0
    risk_budget_rs = float(portfolio_capital_rs) * POSITION_RISK_BUDGET_PCT * risk_multiplier

    atr_val = None
    try:
        if atr_14 is not None:
            atr_val = float(atr_14)
    except Exception:
        atr_val = None

    # Use ATR when available; otherwise use a conservative 3% proxy.
    per_share_risk = atr_val if atr_val is not None and atr_val > 0 else (float(current_price) * 0.03)
    if per_share_risk <= 0:
        per_share_risk = float(current_price) * 0.03

    qty_by_risk = floor(risk_budget_rs / per_share_risk) if per_share_risk > 0 else 0
    max_capital_rs = float(portfolio_capital_rs) * POSITION_MAX_CAPITAL_PCT
    qty_by_capital = floor(max_capital_rs / float(current_price)) if current_price > 0 else 0
    qty_by_front_run_cap = (
        floor(int(broker_daily_net_qty) * POSITION_FRONT_RUN_CAP_PCT)
        if broker_daily_net_qty is not None and int(broker_daily_net_qty) > 0
        else None
    )

    cap_map: dict[str, int] = {
        "risk_budget": int(qty_by_risk),
        "capital_cap": int(qty_by_capital),
    }
    if qty_by_front_run_cap is not None:
        cap_map["front_run_cap"] = int(qty_by_front_run_cap)

    recommended_qty = int(max(0, min(cap_map.values())))
    recommended_notional = float(recommended_qty * float(current_price))

    binding_caps = [k for k, v in cap_map.items() if int(v) == recommended_qty]
    note = "Applied caps: " + ", ".join(binding_caps) + "."
    if recommended_notional > 0 and recommended_notional < POSITION_MIN_NOTIONAL_RS:
        recommended_qty = 0
        recommended_notional = 0.0
        note = "Suggested size below minimum notional threshold."

    return {
        "recommended_qty": recommended_qty,
        "recommended_notional_rs": round(recommended_notional, 2),
        "risk_budget_rs": round(risk_budget_rs, 2),
        "risk_multiplier": risk_multiplier,
        "per_share_risk": round(float(per_share_risk), 4),
        "atr_14": round(float(atr_val), 4) if atr_val is not None else None,
        "qty_by_risk": int(qty_by_risk),
        "qty_by_capital": int(qty_by_capital),
        "qty_by_front_run_cap": int(qty_by_front_run_cap) if qty_by_front_run_cap is not None else None,
        "broker_daily_net_qty": int(broker_daily_net_qty) if broker_daily_net_qty is not None else None,
        "sizing_note": note,
    }
