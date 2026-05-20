"""Trade-plan generation for NEPSE Master Trader buckets."""

from __future__ import annotations

from typing import Any

from swing_analyser.logic import RISK_PCT


def _default_entry_zone(price: float, atr: float | None, width_atr: float = 0.3) -> tuple[float, float]:
    if atr and atr > 0:
        return (round(price - width_atr * atr, 2), round(price + width_atr * atr, 2))
    return (round(price * 0.99, 2), round(price * 1.01, 2))


def _position_size(
    entry_mid: float,
    stop_loss: float,
    equity: int | None,
    risk_pct: float = RISK_PCT,
    risk_multiplier: float = 1.0,
    avg_volume: float | None = None,
    max_trade_pct: float = 0.02,
    max_allocation_pct: float = 0.25,
) -> int | None:
    if equity is None or equity <= 0:
        return 0
    if entry_mid <= 0:
        return 0
    risk_per_share = abs(entry_mid - stop_loss)
    if risk_per_share <= 0:
        return 0
    adj_multiplier = max(0.50, min(1.20, float(risk_multiplier or 1.0)))
    raw_size = max(1, int((equity * risk_pct * adj_multiplier) / risk_per_share))
    max_by_capital = max(1, int(equity / entry_mid))
    max_by_allocation = max(1, int((equity * max_allocation_pct) / entry_mid))
    if avg_volume is not None and avg_volume > 0:
        max_by_liquidity = max(1, int(avg_volume * max_trade_pct))
    else:
        max_by_liquidity = raw_size
    return max(1, min(raw_size, max_by_capital, max_by_allocation, max_by_liquidity))


def _rr(entry_mid: float, stop_loss: float, target: float) -> float:
    risk = abs(entry_mid - stop_loss)
    if risk <= 0:
        return 0.0
    return round((target - entry_mid) / risk, 2)


def _plan_risk_multiplier(stock: dict[str, Any]) -> float:
    preset = stock.get("broker_size_multiplier")
    try:
        if preset is not None:
            preset_val = float(preset)
            return round(max(0.50, min(1.20, preset_val)), 2)
    except Exception:
        pass

    trust = str(stock.get("broker_trust_label") or "UNRATED").upper()
    maturity = str(stock.get("broker_data_maturity") or "LOW").upper()
    alignment = str(stock.get("broker_alignment_flag") or "NEUTRAL").upper()
    power = 0.0
    try:
        power = float(stock.get("signal_power_score") or stock.get("broker_power_score") or 0.0)
    except Exception:
        power = 0.0

    if trust == "HIGH" and maturity == "HIGH":
        mult = 1.10
    elif trust == "MEDIUM":
        mult = 0.95
    elif trust == "LOW":
        mult = 0.75
    else:
        mult = 0.65

    if alignment == "ALIGNED":
        mult += 0.05
    elif alignment == "CONFLICT":
        mult -= 0.20

    if power >= 85:
        mult += 0.10
    elif power >= 70:
        mult += 0.05
    elif 0 < power < 40:
        mult -= 0.05

    return round(max(0.50, min(1.15, mult)), 2)


def build_trade_plan(stock: dict[str, Any], bucket: str, equity: int | None) -> dict[str, Any]:
    """Create an explicit, checkable trade-plan card for one stock and bucket."""

    price = float(stock.get("price") or 0)
    atr = float(stock.get("atr") or 0) or None
    vwap = stock.get("vwap")
    avg_volume = float(stock.get("avg_volume") or 0)
    risk_multiplier = _plan_risk_multiplier(stock)

    entry_zone = stock.get("entry_zone")
    if not isinstance(entry_zone, (list, tuple)) or len(entry_zone) != 2:
        if bucket == "long":
            entry_zone = (round(price * 0.97, 2), round(price * 1.03, 2))
        else:
            entry_zone = _default_entry_zone(price, atr)
    entry_low, entry_high = float(entry_zone[0]), float(entry_zone[1])
    entry_mid = (entry_low + entry_high) / 2

    if bucket == "short":
        stop_loss = float(stock.get("stop_loss") or (price - (atr or price * 0.03) * 1.5))
        stop_loss = min(stop_loss, round(price * 0.97, 2))
        if vwap is not None:
            vwap_floor = float(vwap) * 0.999
            if vwap_floor < price:
                stop_loss = max(stop_loss, vwap_floor)
        target_1 = round(price + (atr or price * 0.03) * 1.0, 2)
        target_2 = round(price + (atr or price * 0.03) * 1.8, 2)
        target_3 = round(price + (atr or price * 0.03) * 2.5, 2)
        hold = "1-5 days"
        time_stop = "Hard 5 trading days"
        exits = [
            "Take profit at ATR T1 or if RSI > 80",
            "Hard time-stop after 5 sessions",
            "Exit if price closes below intraday VWAP",
        ]

    elif bucket == "swing":
        stop_loss = float(stock.get("stop_loss") or (price - (atr or price * 0.03) * 2.0))
        stop_loss = min(stop_loss, round(price * 0.97, 2))
        target_1 = float(stock.get("target_1") or round(price + (atr or price * 0.03) * 3.0, 2))
        target_2 = float(stock.get("target_2") or round(price + (atr or price * 0.03) * 5.0, 2))
        target_3 = round(target_2 + (atr or price * 0.03) * 1.5, 2)
        hold = "1-2 months"
        time_stop = "Hard 45 calendar days"
        exits = [
            "T1 hit: sell 50 percent and trail stop to entry",
            "T2 hit: exit remainder",
            "Exit on RSI divergence, OBV flip, or close below SMA20",
        ]

    else:  # long
        stop_loss = round(price - (atr or price * 0.03) * 3.0, 2)
        stop_loss = min(stop_loss, round(price * 0.95, 2))
        target_1 = round(price * 1.15, 2)
        target_2 = round(price * 1.30, 2)
        target_3 = round(price * 1.50, 2)
        hold = "6+ months"
        time_stop = "No fixed time-stop"
        exits = [
            "Exit if EPS turns negative",
            "Exit if P/E rises above 40 (overpricing)",
            "Warning if broker flow flips from net buyer to net seller",
        ]

    position_size = _position_size(
        entry_mid,
        stop_loss,
        equity,
        risk_multiplier=risk_multiplier,
        avg_volume=avg_volume,
    )

    atr_pct = ((atr / price) * 100.0) if atr and price > 0 else 0.0
    if atr_pct >= 5:
        expected_slippage_band = "HIGH"
    elif atr_pct >= 2.5:
        expected_slippage_band = "MEDIUM"
    else:
        expected_slippage_band = "LOW"

    if bucket == "short":
        plan_validity_window = "1 session"
    elif bucket == "swing":
        plan_validity_window = "3 sessions"
    else:
        plan_validity_window = "5 sessions"

    return {
        "symbol": stock.get("symbol"),
        "bucket": bucket,
        "entry_zone": (round(entry_low, 2), round(entry_high, 2)),
        "stop_loss": round(stop_loss, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2),
        "target_3": round(target_3, 2),
        "rr_ratio": _rr(entry_mid, stop_loss, target_1),
        "position_size": position_size,
        "broker_size_multiplier": risk_multiplier,
        "expected_slippage_band": expected_slippage_band,
        "plan_validity_window": plan_validity_window,
        "hold_window": hold,
        "time_stop": time_stop,
        "exit_conditions": exits,
    }


def build_bucket_plans(stocks: list[dict[str, Any]], bucket: str, equity: int | None) -> list[dict[str, Any]]:
    return [build_trade_plan(s, bucket=bucket, equity=equity) for s in stocks]
