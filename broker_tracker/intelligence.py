"""broker_tracker.intelligence

Broker profiles and trust scores.

Builds per-broker summaries, completed lifecycle cycles, and trust scoring.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from broker_tracker.config import (
    MIN_SESSIONS_FOR_TRUST_SCORE,
    PROFILE_V2_HORIZONS,
    BROKER_POWER_WEIGHT_WIN,
    BROKER_POWER_WEIGHT_ALPHA,
    BROKER_POWER_WEIGHT_STEALTH,
    BROKER_POWER_WEIGHT_CONCENTRATION,
    BROKER_POWER_MIN_CYCLES_FOR_TIER,
    BROKER_TIER_A_MIN,
    BROKER_TIER_B_MIN,
    CAPM_BETA_WINDOW,
    CAPM_RISK_FREE_ANNUAL,
)


def get_data_maturity(completed_cycles: int) -> str:
    if completed_cycles < 3:
        return "LOW"
    if completed_cycles < 10:
        return "MEDIUM"
    return "HIGH"


def _label_trust(trust: float) -> str:
    if trust < 40:
        return "LOW"
    if trust < 70:
        return "MEDIUM"
    return "HIGH"


def _coerce_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        text = str(v).strip()
        if not text:
            return None
        return datetime.fromisoformat(text).date()
    except Exception:
        return None


@dataclass
class CycleResult:
    broker_id: int
    broker_name: str
    symbol: str
    entry_date: Any
    exit_date: Any
    entry_price: float | None
    exit_price: float | None
    is_win: bool | None
    hold_sessions: int | None


def _prepare_series(points: list[tuple[Any, float]] | None) -> tuple[list[date], list[float], dict[date, int]]:
    parsed: list[tuple[date, float]] = []
    for dt_raw, value_raw in points or []:
        dt = _coerce_date(dt_raw)
        if dt is None:
            continue
        try:
            value = float(value_raw)
        except Exception:
            continue
        if value <= 0:
            continue
        parsed.append((dt, value))

    parsed.sort(key=lambda x: x[0])
    dates = [d for d, _ in parsed]
    values = [v for _, v in parsed]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    return dates, values, date_to_idx


def _find_anchor_index(dates: list[date], date_to_idx: dict[date, int], target: date) -> int | None:
    exact = date_to_idx.get(target)
    if exact is not None:
        return exact
    pos = bisect_left(dates, target)
    if 0 <= pos < len(dates):
        return pos
    return None


def _forward_return(
    dates: list[date],
    values: list[float],
    date_to_idx: dict[date, int],
    anchor_date: date,
    horizon: int,
) -> float | None:
    if not dates or not values or horizon <= 0:
        return None
    anchor_idx = _find_anchor_index(dates, date_to_idx, anchor_date)
    if anchor_idx is None:
        return None
    end_idx = anchor_idx + horizon
    if end_idx >= len(values):
        return None
    entry_px = values[anchor_idx]
    exit_px = values[end_idx]
    if entry_px <= 0:
        return None
    return (exit_px - entry_px) / entry_px


def _build_return_map(dates: list[date], values: list[float]) -> dict[date, float]:
    out: dict[date, float] = {}
    if len(dates) < 2 or len(values) < 2:
        return out
    for i in range(1, min(len(dates), len(values))):
        prev_px = values[i - 1]
        curr_px = values[i]
        if prev_px <= 0:
            continue
        out[dates[i]] = (curr_px - prev_px) / prev_px
    return out


def _rolling_beta(
    stock_ret_map: dict[date, float],
    index_ret_map: dict[date, float],
    anchor_date: date,
    window: int,
) -> float | None:
    common = sorted(d for d in stock_ret_map if d <= anchor_date and d in index_ret_map)
    if len(common) < max(10, window // 3):
        return None
    tail = common[-window:]
    x = [float(index_ret_map[d]) for d in tail]
    y = [float(stock_ret_map[d]) for d in tail]
    if not x or not y:
        return None

    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    var_x = sum((v - mean_x) ** 2 for v in x) / len(x)
    if var_x <= 0:
        return None
    cov_xy = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x))) / len(x)
    beta = cov_xy / var_x
    return float(beta)


def _compute_cycle_horizon_metrics(
    cycles: list[CycleResult],
    symbol_series_map: dict[str, tuple[list[date], list[float], dict[date, int]]],
    index_series: tuple[list[date], list[float], dict[date, int]] | None,
    horizons: tuple[int, ...],
    risk_free_annual: float = CAPM_RISK_FREE_ANNUAL,
    beta_window: int = CAPM_BETA_WINDOW,
) -> dict[str, dict[int, float | int | None]]:
    win_hits = {h: 0 for h in horizons}
    win_total = {h: 0 for h in horizons}
    alpha_sum = {h: 0.0 for h in horizons}
    alpha_total = {h: 0 for h in horizons}
    beta_sum = {h: 0.0 for h in horizons}
    beta_total = {h: 0 for h in horizons}

    index_dates: list[date] = []
    index_values: list[float] = []
    index_idx_map: dict[date, int] = {}
    if index_series is not None:
        index_dates, index_values, index_idx_map = index_series
    index_ret_map = _build_return_map(index_dates, index_values) if index_series is not None else {}
    rf_daily = (1.0 + max(0.0, float(risk_free_annual))) ** (1.0 / 252.0) - 1.0

    for c in cycles:
        entry_dt = _coerce_date(c.entry_date)
        if entry_dt is None:
            continue
        sym = str(c.symbol or "")
        sym_series = symbol_series_map.get(sym)
        if sym_series is None:
            continue
        sym_dates, sym_values, sym_idx_map = sym_series
        sym_ret_map = _build_return_map(sym_dates, sym_values)

        for h in horizons:
            stock_ret = _forward_return(sym_dates, sym_values, sym_idx_map, entry_dt, h)
            if stock_ret is None:
                continue
            win_total[h] += 1
            if stock_ret > 0:
                win_hits[h] += 1

            if index_series is not None:
                index_ret = _forward_return(index_dates, index_values, index_idx_map, entry_dt, h)
                if index_ret is not None:
                    beta = _rolling_beta(
                        stock_ret_map=sym_ret_map,
                        index_ret_map=index_ret_map,
                        anchor_date=entry_dt,
                        window=beta_window,
                    )
                    if beta is None:
                        beta = 1.0
                    rf_h = (1.0 + rf_daily) ** h - 1.0
                    expected_capm = rf_h + (beta * (index_ret - rf_h))
                    alpha_sum[h] += stock_ret - expected_capm
                    alpha_total[h] += 1
                    beta_sum[h] += float(beta)
                    beta_total[h] += 1

    win_rate = {
        h: (win_hits[h] / win_total[h]) if win_total[h] > 0 else None
        for h in horizons
    }
    alpha = {
        h: (alpha_sum[h] / alpha_total[h]) if alpha_total[h] > 0 else None
        for h in horizons
    }
    beta = {
        h: (beta_sum[h] / beta_total[h]) if beta_total[h] > 0 else None
        for h in horizons
    }

    return {
        "win_rate": win_rate,
        "alpha": alpha,
        "beta": beta,
        "win_samples": win_total,
        "alpha_samples": alpha_total,
        "beta_samples": beta_total,
    }


def _compute_broker_beta_avg(
    cycles: list[CycleResult],
    symbol_series_map: dict[str, tuple[list[date], list[float], dict[date, int]]],
    index_series: tuple[list[date], list[float], dict[date, int]] | None,
    beta_window: int = CAPM_BETA_WINDOW,
) -> tuple[float | None, int]:
    if index_series is None or not cycles:
        return None, 0

    index_dates, index_values, _ = index_series
    index_ret_map = _build_return_map(index_dates, index_values)
    if not index_ret_map:
        return None, 0

    betas: list[float] = []
    for c in cycles:
        entry_dt = _coerce_date(c.entry_date)
        if entry_dt is None:
            continue

        sym = str(c.symbol or "")
        sym_series = symbol_series_map.get(sym)
        if sym_series is None:
            continue

        sym_dates, sym_values, _ = sym_series
        sym_ret_map = _build_return_map(sym_dates, sym_values)
        if not sym_ret_map:
            continue

        beta_val = _rolling_beta(
            stock_ret_map=sym_ret_map,
            index_ret_map=index_ret_map,
            anchor_date=entry_dt,
            window=beta_window,
        )
        if beta_val is not None:
            betas.append(float(beta_val))

    if not betas:
        return None, 0
    return (sum(betas) / len(betas)), len(betas)


def _compute_portfolio_concentration_ratio(g: pd.DataFrame) -> float:
    if g is None or g.empty:
        return 0.0
    by_symbol = (
        g.groupby("symbol", dropna=False)["trade_value"]
        .sum()
        .sort_values(ascending=False)
    )
    total = float(by_symbol.sum())
    if total <= 0:
        return 0.0
    top3 = float(by_symbol.head(3).sum())
    return top3 / total


def _compute_concentration_ratio(g: pd.DataFrame) -> float:
    """Backward-compatible alias; this is broker portfolio concentration, not market BCR."""
    return _compute_portfolio_concentration_ratio(g)


def _compute_stealth_proxy(g: pd.DataFrame) -> float:
    if g is None or g.empty:
        return 0.0

    if "session_state" in g.columns:
        accum = g.loc[g["session_state"].isin(["ENTERING", "ACCUMULATING"])].copy()
        if not accum.empty:
            g = accum

    total_qty = pd.to_numeric(g["total_qty"], errors="coerce").fillna(0.0)
    trade_value = pd.to_numeric(g["trade_value"], errors="coerce").fillna(0.0)

    active = g.loc[total_qty > 0].copy()
    if active.empty:
        return 0.0

    active_qty = pd.to_numeric(active["total_qty"], errors="coerce").fillna(0.0)
    qty_sum = float(active_qty.sum())
    if qty_sum <= 0:
        return 0.0

    shares = active_qty / qty_sum
    hhi = float((shares * shares).sum())
    split_score = max(0.0, 1.0 - hhi)

    active_trade_value = pd.to_numeric(active["trade_value"], errors="coerce").fillna(0.0)
    exec_px = (active_trade_value / active_qty.replace(0, pd.NA)).dropna()
    if exec_px.empty:
        price_stability = 0.0
    else:
        mean_px = float(exec_px.mean())
        std_px = float(exec_px.std())
        if mean_px <= 0:
            price_stability = 0.0
        else:
            cv = std_px / mean_px
            price_stability = 1.0 / (1.0 + max(0.0, cv))

    return max(0.0, min(1.0, split_score * price_stability))


def _normalize_minmax(metric_by_broker: dict[int, float]) -> dict[int, float]:
    if not metric_by_broker:
        return {}
    vals = list(metric_by_broker.values())
    lo = min(vals)
    hi = max(vals)
    if hi <= lo:
        return {k: 0.5 for k in metric_by_broker}
    return {k: (v - lo) / (hi - lo) for k, v in metric_by_broker.items()}


def _compute_broker_tier(score: float | None, completed_cycles: int) -> str:
    if score is None or completed_cycles < BROKER_POWER_MIN_CYCLES_FOR_TIER:
        return "UNRATED"
    if score >= BROKER_TIER_A_MIN:
        return "A"
    if score >= BROKER_TIER_B_MIN:
        return "B"
    return "C"


def _extract_cycles_for_broker_symbol(g: pd.DataFrame) -> list[CycleResult]:
    """Detect cycles for one broker-symbol timeline.

    Cycle definition (spec): hit ACCUMULATING at least once, then later reach FLAT.
    """
    if g is None or g.empty:
        return []

    g = g.sort_values("trading_date", ascending=True)
    rows = g.to_dict("records")

    broker_id = int(rows[0].get("broker_id") or 0)
    broker_name = str(rows[0].get("broker_name") or "")
    symbol = str(rows[0].get("symbol") or "")

    cycles: list[CycleResult] = []

    in_position = False
    saw_accum = False
    cycle_entry_idx = None

    for i, r in enumerate(rows):
        st = r.get("session_state")

        if not in_position:
            if st and st != "FLAT":
                in_position = True
                saw_accum = st == "ACCUMULATING"
                cycle_entry_idx = i
        else:
            if st == "ACCUMULATING":
                saw_accum = True

            if st == "FLAT":
                if saw_accum and cycle_entry_idx is not None:
                    seg = rows[cycle_entry_idx : i + 1]

                    entry_price = None
                    for rr in seg:
                        v = rr.get("avg_buy_price")
                        if v is not None and not pd.isna(v):
                            entry_price = float(v)
                            break
                        v = rr.get("cumulative_avg_cost")
                        if v is not None and not pd.isna(v):
                            entry_price = float(v)
                            break

                    exit_price = None
                    for rr in reversed(seg):
                        v = rr.get("avg_sell_price")
                        if v is not None and not pd.isna(v):
                            exit_price = float(v)
                            break

                    is_win = None
                    if entry_price is not None and exit_price is not None:
                        is_win = exit_price > entry_price

                    hold_sessions = None
                    # avg sessions from ENTERING to DISTRIBUTING/EXITING
                    entering_idx = None
                    dist_idx = None
                    for j, rr in enumerate(seg):
                        if entering_idx is None and rr.get("session_state") in ("ENTERING", "ACCUMULATING"):
                            entering_idx = j
                        if dist_idx is None and rr.get("session_state") in ("DISTRIBUTING", "EXITING"):
                            dist_idx = j
                            break
                    if entering_idx is not None and dist_idx is not None and dist_idx >= entering_idx:
                        hold_sessions = dist_idx - entering_idx

                    cycles.append(
                        CycleResult(
                            broker_id=broker_id,
                            broker_name=broker_name,
                            symbol=symbol,
                            entry_date=seg[0].get("trading_date"),
                            exit_date=seg[-1].get("trading_date"),
                            entry_price=entry_price,
                            exit_price=exit_price,
                            is_win=is_win,
                            hold_sessions=hold_sessions,
                        )
                    )

                # reset after flat
                in_position = False
                saw_accum = False
                cycle_entry_idx = None

    return cycles


def compute_trust_score(
    completed_cycles: int,
    win_rate: float | None,
    recent_cycle_wins: list[bool | None],
) -> tuple[float | None, str]:
    if completed_cycles < MIN_SESSIONS_FOR_TRUST_SCORE:
        return None, "UNRATED"

    wr = float(win_rate or 0.0)
    recent = [w for w in recent_cycle_wins if w is not None]
    recent_win_rate = (sum(1 for w in recent if w) / len(recent)) if recent else 0.0

    win_rate_score = wr * 100.0 * 0.40
    consistency_score = min(completed_cycles / 20.0, 1.0) * 100.0 * 0.30
    sample_score = min(completed_cycles / 50.0, 1.0) * 100.0 * 0.20
    recency_score = recent_win_rate * 100.0 * 0.10

    trust = win_rate_score + consistency_score + sample_score + recency_score
    return round(trust, 1), _label_trust(trust)


def build_broker_profiles(
    positions_sessions_df: pd.DataFrame,
    positions_summary_df: pd.DataFrame,
    activity_df: pd.DataFrame,
    sector_map: dict[str, dict[str, Any]] | None = None,
    price_history_by_symbol: dict[str, list[tuple[Any, float]]] | None = None,
    market_index_history: list[tuple[Any, float]] | None = None,
) -> dict[int, dict[str, Any]]:
    sector_map = sector_map or {}

    if activity_df is None or activity_df.empty:
        return {}

    profiles: dict[int, dict[str, Any]] = {}
    raw_metrics: dict[int, dict[str, float | int]] = {}

    symbol_series_map = {
        sym: _prepare_series(points)
        for sym, points in (price_history_by_symbol or {}).items()
    }
    symbol_series_map = {
        sym: series
        for sym, series in symbol_series_map.items()
        if series[0] and series[1]
    }

    index_series = _prepare_series(market_index_history) if market_index_history else None
    if index_series is not None and (not index_series[0] or not index_series[1]):
        index_series = None

    # Precompute cycles per broker-symbol
    cycles_by_broker: dict[int, list[CycleResult]] = {}
    if positions_sessions_df is not None and not positions_sessions_df.empty:
        for (broker_id, symbol), g in positions_sessions_df.groupby(["broker_id", "symbol"], dropna=False):
            broker_id_int = int(broker_id)
            cycles = _extract_cycles_for_broker_symbol(g)
            if cycles:
                cycles_by_broker.setdefault(broker_id_int, []).extend(cycles)

    # Activity merged with sector
    act = activity_df.copy()
    act["sector_name"] = act["symbol"].map(lambda s: (sector_map.get(s) or {}).get("sector_name"))
    act["trade_value"] = (
        pd.to_numeric(act["bought_value"], errors="coerce").fillna(0.0)
        + pd.to_numeric(act["sold_value"], errors="coerce").fillna(0.0)
    )
    act["total_qty"] = (
        pd.to_numeric(act["bought_qty"], errors="coerce").fillna(0.0)
        + pd.to_numeric(act["sold_qty"], errors="coerce").fillna(0.0)
    )

    stealth_activity_by_broker: dict[int, pd.DataFrame] = {}
    if positions_sessions_df is not None and not positions_sessions_df.empty:
        ss = positions_sessions_df.copy()
        ss = ss.loc[(~ss["is_synthetic"]) & ss["session_state"].isin(["ENTERING", "ACCUMULATING"])].copy()
        if not ss.empty:
            ss["trade_value"] = (
                pd.to_numeric(ss["bought_value"], errors="coerce").fillna(0.0)
                + pd.to_numeric(ss["sold_value"], errors="coerce").fillna(0.0)
            )
            ss["total_qty"] = (
                pd.to_numeric(ss["bought_qty"], errors="coerce").fillna(0.0)
                + pd.to_numeric(ss["sold_qty"], errors="coerce").fillna(0.0)
            )
            for bid, ssg in ss.groupby("broker_id", dropna=False):
                stealth_activity_by_broker[int(bid)] = ssg

    for broker_id, g in act.groupby("broker_id", dropna=False):
        broker_id_int = int(broker_id)
        broker_name = str(g["broker_name"].dropna().iloc[0]) if g["broker_name"].notna().any() else ""

        total_stocks_traded = int(g["symbol"].nunique())
        total_volume_bought = int(pd.to_numeric(g["bought_qty"], errors="coerce").fillna(0).sum())
        total_volume_sold = int(pd.to_numeric(g["sold_qty"], errors="coerce").fillna(0).sum())
        total_value_bought = float(pd.to_numeric(g["bought_value"], errors="coerce").fillna(0.0).sum())
        total_value_sold = float(pd.to_numeric(g["sold_value"], errors="coerce").fillna(0.0).sum())

        # Preferred sectors by traded value
        sec = (
            g.groupby("sector_name", dropna=False)["trade_value"].sum().sort_values(ascending=False)
        )
        preferred_sectors = [str(s) for s in sec.index.tolist()[:3] if s and not pd.isna(s)]

        buys = g.loc[pd.to_numeric(g["bought_qty"], errors="coerce").fillna(0) > 0]
        avg_position_size_rs = float(pd.to_numeric(buys["bought_value"], errors="coerce").fillna(0.0).mean()) if not buys.empty else 0.0

        # Latest-state lists
        currently_accumulating: list[str] = []
        currently_distributing: list[str] = []
        if positions_summary_df is not None and not positions_summary_df.empty:
            s = positions_summary_df.loc[positions_summary_df["broker_id"] == broker_id]
            if not s.empty:
                currently_accumulating = sorted(
                    [str(x) for x in s.loc[s["session_state"] == "ACCUMULATING", "symbol"].tolist()]
                )
                currently_distributing = sorted(
                    [str(x) for x in s.loc[s["session_state"].isin(["DISTRIBUTING", "EXITING"]), "symbol"].tolist()]
                )

        cycles = cycles_by_broker.get(broker_id_int, [])
        completed_cycles = len(cycles)
        known_cycles = [c for c in cycles if c.is_win is not None]
        known_cycle_count = len(known_cycles)
        win_cycles = sum(1 for c in known_cycles if c.is_win)

        win_rate = None
        if known_cycle_count > 0:
            win_rate = win_cycles / known_cycle_count
        if known_cycle_count < MIN_SESSIONS_FOR_TRUST_SCORE:
            win_rate_display = None
        else:
            win_rate_display = win_rate

        hold_sessions_vals = [c.hold_sessions for c in cycles if c.hold_sessions is not None]
        avg_hold_sessions = float(sum(hold_sessions_vals) / len(hold_sessions_vals)) if hold_sessions_vals else 0.0

        data_maturity = get_data_maturity(completed_cycles)

        # Recency: last 3 cycles
        cycles_sorted = sorted(
            cycles,
            key=lambda c: (_coerce_date(c.exit_date) or date.min),
        )
        recent_wins = [c.is_win for c in cycles_sorted[-3:]]

        trust_score, trust_label = compute_trust_score(
            completed_cycles=completed_cycles,
            win_rate=win_rate_display,
            recent_cycle_wins=recent_wins,
        )

        horizon_metrics = _compute_cycle_horizon_metrics(
            cycles=cycles,
            symbol_series_map=symbol_series_map,
            index_series=index_series,
            horizons=PROFILE_V2_HORIZONS,
        )

        win_rate_1d = horizon_metrics["win_rate"].get(1)
        win_rate_5d = horizon_metrics["win_rate"].get(5)
        win_rate_10d = horizon_metrics["win_rate"].get(10)

        alpha_1d = horizon_metrics["alpha"].get(1)
        alpha_5d = horizon_metrics["alpha"].get(5)
        alpha_10d = horizon_metrics["alpha"].get(10)
        beta_1d = horizon_metrics["beta"].get(1)
        beta_5d = horizon_metrics["beta"].get(5)
        beta_10d = horizon_metrics["beta"].get(10)
        beta_60d, beta_60d_samples = _compute_broker_beta_avg(
            cycles=cycles,
            symbol_series_map=symbol_series_map,
            index_series=index_series,
            beta_window=CAPM_BETA_WINDOW,
        )

        portfolio_concentration_ratio = _compute_portfolio_concentration_ratio(g)
        stealth_source = stealth_activity_by_broker.get(broker_id_int, g)
        stealth_proxy = _compute_stealth_proxy(stealth_source)

        raw_win = float(
            win_rate_5d
            if win_rate_5d is not None
            else (win_rate_display if win_rate_display is not None else 0.0)
        )
        raw_alpha = float(alpha_5d if alpha_5d is not None else 0.0)

        profile = {
            "broker_id": broker_id_int,
            "broker_name": broker_name,
            "total_stocks_traded": total_stocks_traded,
            "total_volume_bought": total_volume_bought,
            "total_volume_sold": total_volume_sold,
            "total_value_bought": total_value_bought,
            "total_value_sold": total_value_sold,
            "preferred_sectors": preferred_sectors,
            "avg_position_size_rs": avg_position_size_rs,
            "completed_cycles": completed_cycles,
            "known_outcome_cycles": known_cycle_count,
            "win_cycles": int(win_cycles),
            "win_rate": win_rate_display,
            "avg_hold_sessions": avg_hold_sessions,
            "data_maturity": data_maturity,
            "currently_accumulating": currently_accumulating,
            "currently_distributing": currently_distributing,
            "trust_score": trust_score,
            "trust_label": trust_label,
            "win_rate_1d": win_rate_1d,
            "win_rate_5d": win_rate_5d,
            "win_rate_10d": win_rate_10d,
            "alpha_1d": alpha_1d,
            "alpha_5d": alpha_5d,
            "alpha_10d": alpha_10d,
            "beta_1d": beta_1d,
            "beta_5d": beta_5d,
            "beta_10d": beta_10d,
            "beta_60d": beta_60d,
            "win_samples_1d": int(horizon_metrics["win_samples"].get(1) or 0),
            "win_samples_5d": int(horizon_metrics["win_samples"].get(5) or 0),
            "win_samples_10d": int(horizon_metrics["win_samples"].get(10) or 0),
            "alpha_samples_1d": int(horizon_metrics["alpha_samples"].get(1) or 0),
            "alpha_samples_5d": int(horizon_metrics["alpha_samples"].get(5) or 0),
            "alpha_samples_10d": int(horizon_metrics["alpha_samples"].get(10) or 0),
            "beta_samples_1d": int(horizon_metrics["beta_samples"].get(1) or 0),
            "beta_samples_5d": int(horizon_metrics["beta_samples"].get(5) or 0),
            "beta_samples_10d": int(horizon_metrics["beta_samples"].get(10) or 0),
            "beta_samples_60d": int(beta_60d_samples or 0),
            "portfolio_concentration_ratio": portfolio_concentration_ratio,
            "concentration_ratio": portfolio_concentration_ratio,
            "stealth_proxy": stealth_proxy,
            "broker_power_score": None,
            "broker_tier": "UNRATED",
            "broker_power_components": {
                "win": 0.0,
                "alpha": 0.0,
                "stealth": 0.0,
                "concentration": 0.0,
            },
        }

        profiles[broker_id_int] = profile
        raw_metrics[broker_id_int] = {
            "win": raw_win,
            "alpha": raw_alpha,
            "stealth": float(stealth_proxy),
            "concentration": float(portfolio_concentration_ratio),
            "completed_cycles": int(completed_cycles),
        }

    if raw_metrics:
        win_norm = _normalize_minmax({bid: float(v["win"]) for bid, v in raw_metrics.items()})
        alpha_norm = _normalize_minmax({bid: float(v["alpha"]) for bid, v in raw_metrics.items()})
        stealth_norm = _normalize_minmax({bid: float(v["stealth"]) for bid, v in raw_metrics.items()})
        concentration_norm = _normalize_minmax({bid: float(v["concentration"]) for bid, v in raw_metrics.items()})

        for bid, m in raw_metrics.items():
            n_win = float(win_norm.get(bid, 0.0))
            n_alpha = float(alpha_norm.get(bid, 0.0))
            n_stealth = float(stealth_norm.get(bid, 0.0))
            n_concentration = float(concentration_norm.get(bid, 0.0))

            score = 100.0 * (
                (BROKER_POWER_WEIGHT_WIN * n_win)
                + (BROKER_POWER_WEIGHT_ALPHA * n_alpha)
                + (BROKER_POWER_WEIGHT_STEALTH * n_stealth)
                + (BROKER_POWER_WEIGHT_CONCENTRATION * n_concentration)
            )

            profiles[bid]["broker_power_score"] = round(score, 1)
            profiles[bid]["broker_tier"] = _compute_broker_tier(
                score=score,
                completed_cycles=int(m["completed_cycles"]),
            )
            profiles[bid]["broker_power_components"] = {
                "win": round(n_win, 4),
                "alpha": round(n_alpha, 4),
                "stealth": round(n_stealth, 4),
                "concentration": round(n_concentration, 4),
            }

    return profiles
