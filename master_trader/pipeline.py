"""Coordinator pipeline for NEPSE Master Trader.

This module keeps existing analysers independent and reusable while building a
single, connected report pipeline:
  Layer 1: market context
  Layer 2: screening and ranking
  Layer 3: deep enrichment for top candidates
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import mean
from typing import Any

from broker_tracker.data import (
    aggregate_broker_activity,
    build_sector_map,
    get_all_broker_activity,
    get_atr_14,
    get_latest_prices,
    get_market_index_history,
    get_symbol_price_history,
)
from broker_tracker.intelligence import build_broker_profiles
from broker_tracker.positions import compute_broker_stock_positions
from broker_tracker.signals import generate_signals
from master_trader.classifier import classify_stock
from master_trader.trade_plan import build_bucket_plans
from single_analyser.logic import (
    build_strengths,
    build_weaknesses,
    calc_fibonacci_retracement,
    calc_fundamental_score,
    calc_mfi,
)
from swing_analyser.logic import (
    ATR_SL_MULT,
    ATR_T1_MULT,
    ATR_T2_MULT,
    CIRCUIT_LIMIT,
    LOW_LIQ_THRESH,
    MAX_CAPITAL_ALLOCATION_PCT,
    MAX_FORWARD_FILL_STREAK,
    MAX_POSITION_SHARE_OF_AVG_VOL,
    MIN_DATA_BARS,
    RISK_PCT,
    _compute_data_confidence,
    _calc_entry_zone,
    _detect_swing_setups,
    _est_hold_period,
    _is_fundamental_stale,
    bridge_live_candle,
    calc_adx,
    calc_atr,
    calc_bollinger_bands,
    calc_ema,
    calc_macd,
    calc_obv_trend,
    calc_roc,
    calc_rsi,
    calc_sma,
    calc_vpt,
    calc_stochastic,
    check_ma_crossover,
    check_macd_bullish_crossover,
    detect_candlestick_patterns,
    fetch_52w_from_snapshots,
    fetch_all_company_details,
    fetch_all_corp_actions,
    fetch_all_dividends,
    fetch_all_fundamentals,
    fetch_all_live_ltp,
    fetch_all_ohlcv,
    fetch_all_securities,
    fetch_broker_scores,
    get_market_regime,
    set_dynamic_rsi,
    forward_fill_zero_volume_days,
    get_adjusted_series,
    get_conn,
    is_bollinger_squeeze,
    is_circuit_volatile,
    is_low_liquidity,
    q,
    qone,
    resample_to_weekly,
)
from swing_analyser.scoring import calc_universal_score, classify_tier


DEFAULT_SHORT_LIMIT = 20
DEFAULT_SWING_LIMIT = 25
DEFAULT_LONG_LIMIT = 25
HOTLIST_LIMIT = 5
MAX_ALLOWED_FRESHNESS_DAYS = 3
_UNMATCHED_SECTOR_KEYS_LOGGED: set[str] = set()

DATA_SOURCE_TABLES: list[dict[str, str]] = [
    {"table": "daily_ohlcv", "purpose": "Primary historical OHLCV candles per symbol/day."},
    {"table": "daily_prices", "purpose": "Fallback when symbol-day is missing in daily_ohlcv."},
    {"table": "live_market_snapshots", "purpose": "Latest intraday bridge and live LTP context."},
    {"table": "floorsheet_transactions", "purpose": "Broker buy/sell flow, asymmetry, and conviction."},
    {"table": "market_summary", "purpose": "Daily market turnover and breadth regime context."},
    {"table": "nepse_sub_indices", "purpose": "Sector leadership and laggard context."},
    {"table": "market_indices", "purpose": "NEPSE index trend and momentum context."},
    {"table": "scrip_rankings", "purpose": "Turnover rank and short-term liquidity signal."},
    {"table": "top_movers", "purpose": "Recent mover streak bias for momentum filtering."},
    {"table": "daily_script_price_graph", "purpose": "Intraday VWAP and day-level execution context."},
    {"table": "company_details", "purpose": "Sector mapping and company profile metadata."},
    {"table": "company_fundamentals", "purpose": "Valuation context and sector-relative PE scoring."},
    {"table": "securities", "purpose": "Instrument type filtering (equity vs others)."},
    {"table": "dividends", "purpose": "Dividend and book-closure event risk adjustments."},
    {"table": "corporate_actions", "purpose": "Split/bonus adjustments for clean series."},
    {"table": "market_schedule", "purpose": "Trading calendar used by freshness guard."},
]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _max_forward_fill_streak(candles: list[dict[str, Any]]) -> int:
    streak = 0
    best = 0
    for row in candles:
        ff = _safe_int(row.get("is_forward_filled"))
        if ff:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def _grade_data_quality(
    *,
    data_confidence: int,
    freshness_days: int,
    max_fill_streak: int,
    has_synthetic_open: bool,
) -> str:
    if data_confidence >= 80 and freshness_days <= 1 and max_fill_streak <= 2 and not has_synthetic_open:
        return "A"
    if data_confidence >= 70 and freshness_days <= 2 and max_fill_streak <= MAX_FORWARD_FILL_STREAK:
        return "B"
    if data_confidence >= 60 and freshness_days <= MAX_ALLOWED_FRESHNESS_DAYS:
        return "C"
    return "D"


def _execution_confidence_from_grade(grade: str, broker_alignment: str) -> float:
    base = {
        "A": 85.0,
        "B": 75.0,
        "C": 62.0,
        "D": 45.0,
    }.get(grade, 50.0)
    if broker_alignment == "ALIGNED":
        base += 6.0
    elif broker_alignment == "CONFLICT":
        base -= 12.0
    return round(max(0.0, min(100.0, base)), 1)


def _priority_tier_from_score(fused_score: float, veto_reasons: list[str]) -> str:
    if veto_reasons:
        return "C"
    if fused_score >= 78:
        return "A"
    if fused_score >= 62:
        return "B"
    return "C"


def _broker_size_multiplier(
    trust_label: str,
    maturity_label: str,
    alignment: str,
    power_score: float | None = None,
) -> float:
    trust_key = (trust_label or "UNRATED").upper()
    maturity_key = (maturity_label or "LOW").upper()

    if trust_key == "HIGH" and maturity_key == "HIGH":
        mult = 1.10
    elif trust_key == "MEDIUM":
        mult = 0.95
    elif trust_key == "LOW":
        mult = 0.75
    else:
        mult = 0.65

    if alignment == "ALIGNED":
        mult += 0.05
    elif alignment == "CONFLICT":
        mult -= 0.20

    power = _safe_float(power_score, 0.0)
    if power >= 85:
        mult += 0.10
    elif power >= 70:
        mult += 0.05
    elif 0 < power < 40:
        mult -= 0.05

    return round(max(0.50, min(1.15, mult)), 2)


def _is_trading_mode(equity: int | None) -> bool:
    return equity is not None and equity > 0


def _derive_action_label(score: Any, *, bucket_flags: dict[str, bool] | None = None) -> str:
    stock_score = _safe_float(score)
    flags = bucket_flags or {}
    bucket_qualified = bool(flags.get("short") or flags.get("swing") or flags.get("long") or flags.get("hotlist"))

    if bucket_qualified and stock_score >= 65:
        return "BUY"
    if stock_score >= 55:
        return "WATCH"
    return "AVOID"


def _coerce_to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        text = str(value).strip()
        return datetime.fromisoformat(text).date() if text else None
    except Exception:
        return None


def _max_date_from_query(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> date | None:
    try:
        row = qone(conn, sql, params)
    except Exception:
        return None
    return _coerce_to_date((row or {}).get("dt"))


def _infer_expected_market_date(conn: Any, as_of: date) -> date:
    candidates: list[date] = []

    # Prefer exchange calendar when available and recent.
    sched_dt = _max_date_from_query(
        conn,
        """
        SELECT MAX(trading_date) AS dt
        FROM market_schedule
        WHERE is_trading_day = 1
          AND trading_date <= %s
        """,
        (as_of,),
    )
    if sched_dt is not None and (as_of - sched_dt).days <= 14:
        candidates.append(sched_dt)

    # Fallback signals from market-wide tables.
    observed_sources = [
        "SELECT MAX(trading_date) AS dt FROM daily_prices WHERE trading_date <= %s",
        "SELECT MAX(trading_date) AS dt FROM market_summary WHERE trading_date <= %s",
        "SELECT MAX(date) AS dt FROM market_indices WHERE date <= %s",
    ]
    for sql in observed_sources:
        dt_val = _max_date_from_query(conn, sql, (as_of,))
        if dt_val is not None:
            candidates.append(dt_val)

    return max(candidates) if candidates else as_of


def _assert_fresh_ohlcv_date(conn: Any, *, allow_stale: bool = False) -> date:
    row = qone(conn, "SELECT MAX(trading_date) AS max_dt FROM daily_ohlcv")
    latest = _coerce_to_date((row or {}).get("max_dt"))
    if latest is None:
        raise RuntimeError("Data freshness check failed: no rows found in daily_ohlcv.")

    expected = _infer_expected_market_date(conn, date.today())
    if latest < expected:
        if allow_stale:
            return latest
        raise RuntimeError(
            f"Data freshness check failed: latest daily_ohlcv date is {latest.isoformat()}, "
            f"expected at least {expected.isoformat()} (last trading day). "
            "Run collection jobs before generating report."
        )
    return latest


def _build_data_health_snapshot(conn: Any, data_date: date) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "as_of_date": data_date.isoformat(),
        "latest_ohlcv_rows": 0,
        "latest_close_positive_volume_zero_rows": 0,
        "latest_bad_close_rows": 0,
        "latest_open_zero_rows": 0,
        "equity_rows": 0,
        "equity_zero_volume_rows": 0,
        "missing_equity_rows_vs_daily_prices": 0,
        "equity_zero_volume_rate": 0.0,
        "missing_equity_rate": 0.0,
        "bad_close_rate": 0.0,
        "accuracy_score": 0.0,
    }

    try:
        row = qone(
            conn,
            """
            SELECT
              COUNT(*) AS total_rows,
              SUM(CASE WHEN close_price > 0 AND COALESCE(volume, 0) = 0 THEN 1 ELSE 0 END) AS close_pos_vol_zero_rows,
              SUM(CASE WHEN close_price <= 0 THEN 1 ELSE 0 END) AS bad_close_rows,
              SUM(CASE WHEN COALESCE(open_price, 0) <= 0 THEN 1 ELSE 0 END) AS open_zero_rows
            FROM daily_ohlcv
            WHERE trading_date = %s
            """,
            (data_date,),
        ) or {}
        snapshot["latest_ohlcv_rows"] = _safe_int(row.get("total_rows"))
        snapshot["latest_close_positive_volume_zero_rows"] = _safe_int(row.get("close_pos_vol_zero_rows"))
        snapshot["latest_bad_close_rows"] = _safe_int(row.get("bad_close_rows"))
        snapshot["latest_open_zero_rows"] = _safe_int(row.get("open_zero_rows"))
    except Exception:
        pass

    try:
        row = qone(
            conn,
            """
            SELECT
              COUNT(*) AS equity_rows,
              SUM(CASE WHEN do.close_price > 0 AND COALESCE(do.volume, 0) = 0 THEN 1 ELSE 0 END) AS equity_zero_vol_rows
            FROM daily_ohlcv do
            JOIN securities s ON s.symbol = do.symbol
            WHERE do.trading_date = %s
              AND s.instrument_type = 'Equity'
            """,
            (data_date,),
        ) or {}
        snapshot["equity_rows"] = _safe_int(row.get("equity_rows"))
        snapshot["equity_zero_volume_rows"] = _safe_int(row.get("equity_zero_vol_rows"))
    except Exception:
        pass

    try:
        row = qone(
            conn,
            """
            SELECT COUNT(*) AS missing_rows
            FROM daily_prices dp
            LEFT JOIN daily_ohlcv do
              ON do.symbol = dp.symbol
             AND do.trading_date = dp.trading_date
            JOIN securities s ON s.symbol = dp.symbol
            WHERE dp.trading_date = %s
              AND do.symbol IS NULL
              AND s.instrument_type = 'Equity'
              AND dp.close_price > 0
            """,
            (data_date,),
        ) or {}
        snapshot["missing_equity_rows_vs_daily_prices"] = _safe_int(row.get("missing_rows"))
    except Exception:
        pass

    latest_rows = max(1, _safe_int(snapshot.get("latest_ohlcv_rows")))
    equity_rows = max(1, _safe_int(snapshot.get("equity_rows")))
    equity_zero_rate = _safe_int(snapshot.get("equity_zero_volume_rows")) / equity_rows
    missing_rate = _safe_int(snapshot.get("missing_equity_rows_vs_daily_prices")) / equity_rows
    bad_close_rate = _safe_int(snapshot.get("latest_bad_close_rows")) / latest_rows
    penalty = (equity_zero_rate * 45.0) + (missing_rate * 35.0) + (bad_close_rate * 20.0)
    accuracy_score = max(0.0, 100.0 - (penalty * 100.0))

    snapshot["equity_zero_volume_rate"] = round(equity_zero_rate, 4)
    snapshot["missing_equity_rate"] = round(missing_rate, 4)
    snapshot["bad_close_rate"] = round(bad_close_rate, 4)
    snapshot["accuracy_score"] = round(accuracy_score, 1)
    return snapshot


def _window_return(values: list[float], n: int) -> float | None:
    if len(values) <= n or values[-n - 1] == 0:
        return None
    return (values[-1] - values[-n - 1]) / values[-n - 1] * 100.0


def _max_drawdown(closes: list[float]) -> float:
    if not closes:
        return 0.0
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak > 0:
            dd = (peak - c) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 2)


def _volatility_20d(closes: list[float]) -> float:
    if len(closes) < 21:
        return 0.0
    rets = []
    for i in range(-20, 0):
        prev = closes[i - 1]
        if prev > 0:
            rets.append((closes[i] - prev) / prev * 100.0)
    if not rets:
        return 0.0
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / len(rets)
    return round(var ** 0.5, 2)


def _calc_rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    if len(closes) < period + 1:
        return [None] * len(closes)
    rsis: list[float | None] = [None] * len(closes)
    for i in range(period, len(closes)):
        window = closes[i - period : i + 1]
        rsis[i] = calc_rsi(window, period=period)
    return rsis


def _detect_bearish_rsi_divergence(closes: list[float]) -> bool:
    if len(closes) < 45:
        return False
    rsis = _calc_rsi_series(closes)
    prev_slice = closes[-40:-20]
    curr_slice = closes[-20:]
    prev_high = max(prev_slice)
    curr_high = max(curr_slice)
    if curr_high <= prev_high:
        return False

    prev_idx = len(closes) - 40 + prev_slice.index(prev_high)
    curr_idx = len(closes) - 20 + curr_slice.index(curr_high)
    prev_rsi = rsis[prev_idx]
    curr_rsi = rsis[curr_idx]
    if prev_rsi is None or curr_rsi is None:
        return False
    return curr_rsi < prev_rsi


def _detect_vpt_bearish_divergence(closes: list[float], volumes: list[int], window: int = 20) -> bool:
    if len(closes) < window * 2 or len(volumes) < window * 2:
        return False
    vpt_series = calc_vpt(closes, volumes)
    if len(vpt_series) < window * 2:
        return False

    price_recent_high = max(closes[-window:])
    price_prev_high = max(closes[-window * 2 : -window])
    vpt_recent_high = max(vpt_series[-window:])
    vpt_prev_high = max(vpt_series[-window * 2 : -window])
    return price_recent_high > price_prev_high and vpt_recent_high < vpt_prev_high


def _calc_circuit_adjusted_atr(candles: list[dict[str, Any]], period: int = 14, circuit_weight: float = 0.35) -> float | None:
    """ATR with circuit-day TR down-weighting to avoid distorted stop sizing."""
    if len(candles) < period + 1:
        return None

    trs: list[float] = []
    for i in range(1, len(candles)):
        hi = _safe_float(candles[i].get("high_price"))
        lo = _safe_float(candles[i].get("low_price"))
        prev_close = _safe_float(candles[i - 1].get("close_price"))
        close_now = _safe_float(candles[i].get("close_price"))
        if prev_close <= 0:
            continue

        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        circuit_hit = abs(close_now - prev_close) / prev_close >= CIRCUIT_LIMIT
        if circuit_hit:
            tr *= circuit_weight
        trs.append(tr)

    if len(trs) < period:
        return None

    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 2)


def _detect_obv_flip(closes: list[float], volumes: list[int]) -> bool:
    n = min(len(closes), len(volumes))
    if n < 60:
        return False

    closes_tail = closes[-n:]
    volumes_tail = volumes[-n:]

    # Build cumulative OBV once on the full tail so adjacent windows keep continuity.
    obv: list[float] = [0.0]
    for i in range(1, n):
        vol_i = float(volumes_tail[i] or 0)
        if closes_tail[i] > closes_tail[i - 1]:
            obv.append(obv[-1] + vol_i)
        elif closes_tail[i] < closes_tail[i - 1]:
            obv.append(obv[-1] - vol_i)
        else:
            obv.append(obv[-1])

    prev_start = n - 60
    prev_end = n - 30
    curr_start = n - 30
    curr_end = n - 1

    prev_slope = obv[prev_end - 1] - obv[prev_start]
    curr_slope = obv[curr_end] - obv[curr_start]
    return prev_slope > 0 and curr_slope < 0


def _check_macd_bearish_crossover(macd_line: list[float]) -> bool:
    if not macd_line or len(macd_line) < 2:
        return False
    sig_ema = calc_ema(macd_line, 9)
    if len(sig_ema) < 2:
        return False
    prev_h = macd_line[-2] - sig_ema[-2]
    curr_h = macd_line[-1] - sig_ema[-1]
    return prev_h >= 0 and curr_h < 0


def _fetch_market_dashboard(conn: Any) -> dict[str, Any]:
    regime = get_market_regime(conn)
    set_dynamic_rsi(regime)
    summary = qone(conn, "SELECT * FROM market_summary ORDER BY trading_date DESC LIMIT 1")
    sub_indices = q(
        conn,
        """
        SELECT index_name, points_change, percent_change, current_value, created_at
        FROM nepse_sub_indices
        WHERE DATE(created_at) = (SELECT MAX(DATE(created_at)) FROM nepse_sub_indices)
        ORDER BY percent_change DESC
        """,
    )

    breadth = {"advances": 0, "declines": 0, "unchanged": 0}
    try:
        b = qone(
            conn,
            """
            SELECT
                SUM(CASE WHEN percent_change > 0 THEN 1 ELSE 0 END) AS advances,
                SUM(CASE WHEN percent_change < 0 THEN 1 ELSE 0 END) AS declines,
                SUM(CASE WHEN percent_change = 0 THEN 1 ELSE 0 END) AS unchanged
            FROM daily_prices
            WHERE trading_date = (SELECT MAX(trading_date) FROM daily_prices)
            """,
        )
        breadth = {
            "advances": int(b.get("advances") or 0),
            "declines": int(b.get("declines") or 0),
            "unchanged": int(b.get("unchanged") or 0),
        }
    except Exception:
        pass

    return {
        "regime": regime,
        "summary": summary,
        "sub_indices": sub_indices,
        "breadth": breadth,
    }


def _fetch_top_mover_streaks(conn: Any, lookback_days: int = 10) -> dict[str, int]:
    rows = q(
        conn,
        """
        SELECT symbol, trading_date
        FROM top_movers
        WHERE mover_type = 'gainer'
          AND trading_date >= DATE_SUB((SELECT MAX(trading_date) FROM top_movers), INTERVAL %s DAY)
        ORDER BY trading_date DESC
        """,
        (lookback_days,),
    )
    if not rows:
        return {}

    trade_dates = sorted({r["trading_date"] for r in rows}, reverse=True)
    by_symbol: dict[str, set[Any]] = defaultdict(set)
    for r in rows:
        by_symbol[r["symbol"]].add(r["trading_date"])

    streaks: dict[str, int] = {}
    for sym, dates in by_symbol.items():
        streak = 0
        for d in trade_dates:
            if d in dates:
                streak += 1
            elif streak > 0:
                break
        streaks[sym] = streak
    return streaks


def _fetch_intraday_vwap_map(conn: Any) -> dict[str, float]:
    try:
        rows = q(
            conn,
            """
            SELECT
                symbol,
                SUM(contract_rate * COALESCE(contract_quantity, 1))
                / NULLIF(SUM(COALESCE(contract_quantity, 1)), 0) AS vwap
            FROM daily_script_price_graph
            WHERE DATE(created_at) = (SELECT MAX(DATE(created_at)) FROM daily_script_price_graph)
            GROUP BY symbol
            """,
        )
        if not rows:
            print("  [warn] intraday VWAP map is empty for latest daily_script_price_graph date")
            return {}
        out = {r["symbol"]: round(_safe_float(r.get("vwap")), 2) for r in rows if r.get("symbol")}
        if not out:
            print("  [warn] intraday VWAP query returned rows but no usable symbol VWAP values")
        return out
    except Exception:
        print("  [warn] failed to fetch intraday VWAP map; continuing without VWAP floor context")
        return {}


def _fetch_sector_pe_averages(conn: Any) -> dict[str, float]:
    rows = q(
        conn,
        """
        SELECT cd.sector_name, AVG(cf.pe_ratio) AS avg_pe
        FROM company_fundamentals cf
        JOIN company_details cd ON cd.symbol = cf.symbol
        JOIN (
            SELECT symbol, MAX(published_date) AS latest_pub
            FROM company_fundamentals
            GROUP BY symbol
        ) latest ON latest.symbol = cf.symbol AND latest.latest_pub = cf.published_date
        WHERE cf.pe_ratio > 0
        GROUP BY cd.sector_name
        """,
    )
    return {r["sector_name"]: round(_safe_float(r.get("avg_pe")), 2) for r in rows if r.get("sector_name")}


def _fetch_scrip_turnover_ranks(conn: Any) -> dict[str, dict[str, float]]:
    try:
        rows = q(
            conn,
            """
            SELECT symbol, `rank`, metric_value
            FROM scrip_rankings
            WHERE category = 'turnover'
              AND trading_date = (
                  SELECT MAX(trading_date)
                  FROM scrip_rankings
                  WHERE category = 'turnover'
              )
            """,
        )
    except Exception:
        return {}

    result: dict[str, dict[str, float]] = {}
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue
        result[sym] = {
            "rank": float(r.get("rank") or 0),
            "metric_value": _safe_float(r.get("metric_value")),
        }
    return result


def _fetch_nepse_series(conn: Any) -> list[float]:
    rows = q(
        conn,
        """
        SELECT current_value
        FROM market_indices
        WHERE index_name = 'NEPSE'
        ORDER BY date ASC
        """,
    )
    return [_safe_float(r.get("current_value")) for r in rows if _safe_float(r.get("current_value")) > 0]


def _compute_rs_delta(closes: list[float], nepse_values: list[float]) -> tuple[float, int, float]:
    max_usable = min(len(closes), len(nepse_values)) - 1
    if max_usable < 1:
        return (0.0, 0, 50.0)

    windows = [w for w in (20, 50, 90) if w <= max_usable]
    if not windows and max_usable >= 5:
        # Fall back to the longest shared history when index history is short.
        windows = [max_usable]

    deltas = []
    for w in windows:
        s_ret = _window_return(closes, w)
        i_ret = _window_return(nepse_values, w)
        if s_ret is None or i_ret is None:
            continue
        deltas.append(s_ret - i_ret)

    if not deltas:
        return (0.0, 0, 50.0)
    avg_delta = mean(deltas)

    if avg_delta >= 8:
        bonus = 5
    elif avg_delta >= 4:
        bonus = 3
    elif avg_delta <= -8:
        bonus = -5
    elif avg_delta <= -4:
        bonus = -3
    else:
        bonus = 0

    # Use a bounded transform so outsized movers do not saturate score too early.
    rs_component = 45.0 * (avg_delta / (abs(avg_delta) + 12.0))
    rs_score = max(0.0, min(100.0, 50.0 + rs_component))
    return (round(avg_delta, 2), bonus, round(rs_score, 2))


def _fetch_sector_leadership(conn: Any) -> tuple[list[str], list[str]]:
    rows = q(
        conn,
        """
        SELECT index_name, percent_change
        FROM nepse_sub_indices
        WHERE DATE(created_at) = (SELECT MAX(DATE(created_at)) FROM nepse_sub_indices)
        ORDER BY percent_change DESC
        """,
    )
    if not rows:
        return ([], [])
    leaders = [str(r.get("index_name") or "") for r in rows[:3]]
    laggards = [str(r.get("index_name") or "") for r in rows[-3:]]
    return (leaders, laggards)


def _sector_key(sector_name: str) -> str:
    s = (sector_name or "").lower()
    mapping = [
        ("bank", "bank"),
        ("hydro", "hydro"),
        ("life", "life"),
        ("non life", "non life"),
        ("finance", "finance"),
        ("micro", "micro"),
        ("trading", "trading"),
        ("hotel", "hotel"),
        ("manufact", "manufacturing"),
        ("invest", "investment"),
    ]
    for needle, key in mapping:
        if needle in s:
            return key
    unresolved = s.strip() or "other"
    if unresolved not in {"", "other"} and unresolved not in _UNMATCHED_SECTOR_KEYS_LOGGED:
        print(f"  [warn] unmatched sector mapping: {sector_name!r} -> {unresolved!r}")
        _UNMATCHED_SECTOR_KEYS_LOGGED.add(unresolved)
    return unresolved


def _index_key(index_name: str) -> str:
    s = (index_name or "").lower()
    s = s.replace("subindex", "")
    s = s.replace("index", "")
    return _sector_key(s.strip())


def _sector_leadership_bonus(sector: str, leaders: list[str], laggards: list[str]) -> tuple[int, str]:
    sk = _sector_key(sector)
    leader_keys = [_index_key(i) for i in leaders]
    laggard_keys = [_index_key(i) for i in laggards]
    if sk and sk in leader_keys:
        return (3, "leader")
    if sk and sk in laggard_keys:
        return (-3, "laggard")
    return (0, "neutral")


def _fetch_book_closure_map(conn: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    today = date.today()

    divs = q(
        conn,
        """
                SELECT d.symbol, d.book_close_date, d.bonus_share_percent, d.cash_dividend_percent
                FROM dividends d
                JOIN (
                        SELECT symbol, MIN(book_close_date) AS next_book_close
                        FROM dividends
                        WHERE book_close_date IS NOT NULL
                            AND book_close_date >= CURDATE()
                        GROUP BY symbol
                ) nxt
                    ON nxt.symbol = d.symbol
                 AND nxt.next_book_close = d.book_close_date
                ORDER BY d.book_close_date ASC
        """,
    )
    for d in divs:
        sym = d.get("symbol")
        bcd = d.get("book_close_date")
        if not sym or not bcd:
            continue
        days = (bcd - today).days
        if days < 0:
            continue
        est_drop = _safe_float(d.get("cash_dividend_percent")) + _safe_float(d.get("bonus_share_percent"))
        result[sym] = {
            "book_close_date": str(bcd),
            "days_to_close": days,
            "est_drop_pct": round(est_drop, 2),
        }
    return result


def _fetch_wabr_map(conn: Any) -> dict[str, float]:
    max_date = qone(conn, "SELECT MAX(trading_date) AS max_dt FROM floorsheet_transactions").get("max_dt")
    if not max_date:
        return {}

    date_rows = q(
        conn,
        """
        SELECT DISTINCT trading_date
        FROM floorsheet_transactions
        WHERE trading_date <= %s
        ORDER BY trading_date DESC
        LIMIT 20
        """,
        (max_date,),
    )
    trading_dates = [r.get("trading_date") for r in date_rows if r.get("trading_date")]
    if not trading_dates:
        return {}
    start_dt = trading_dates[-1]
    session_rank = {d: i for i, d in enumerate(trading_dates)}

    rows = q(
        conn,
        """
        SELECT
            symbol,
            broker_id,
            trading_date,
            SUM(net_qty) AS net_qty,
            SUM(net_amt) AS net_amt
        FROM (
            SELECT
                symbol,
                buyer_broker_id AS broker_id,
                trading_date,
                SUM(quantity) AS net_qty,
                SUM(amount) AS net_amt
            FROM floorsheet_transactions
            WHERE trading_date >= %s
              AND trading_date <= %s
            GROUP BY symbol, buyer_broker_id, trading_date

            UNION ALL

            SELECT
                symbol,
                seller_broker_id AS broker_id,
                trading_date,
                -SUM(quantity) AS net_qty,
                -SUM(amount) AS net_amt
            FROM floorsheet_transactions
            WHERE trading_date >= %s
              AND trading_date <= %s
            GROUP BY symbol, seller_broker_id, trading_date
        ) flows
        GROUP BY symbol, broker_id, trading_date
        """,
        (start_dt, max_date, start_dt, max_date),
    )

    by_symbol: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for r in rows:
        sym = r.get("symbol")
        broker = r.get("broker_id")
        t_date = r.get("trading_date")
        if not sym or broker is None or t_date is None:
            continue
        b_key = str(broker)
        rank = session_rank.get(t_date, len(trading_dates) - 1)
        weight = 0.95 ** rank

        bucket = by_symbol[sym].setdefault(b_key, {"net_qty": 0.0, "net_amt": 0.0})
        bucket["net_qty"] += _safe_float(r.get("net_qty")) * weight
        bucket["net_amt"] += _safe_float(r.get("net_amt")) * weight

    out: dict[str, float] = {}
    for sym, broker_map in by_symbol.items():
        entries = [v for v in broker_map.values() if v["net_qty"] > 0 and v["net_amt"] > 0]
        top = sorted(entries, key=lambda x: x["net_amt"], reverse=True)[:3]
        qty = sum(e["net_qty"] for e in top)
        amt = sum(e["net_amt"] for e in top)
        if qty > 0:
            out[sym] = round(amt / qty, 2)
    return out


def _fetch_broker_consistency(conn: Any) -> tuple[dict[str, int], int]:
    date_rows = q(
        conn,
        """
        SELECT DISTINCT trading_date
        FROM floorsheet_transactions
        ORDER BY trading_date DESC
        LIMIT 10
        """,
    )
    trading_dates = [r.get("trading_date") for r in date_rows if r.get("trading_date")]
    floorsheet_days = len(trading_dates)
    if not trading_dates:
        return ({}, 0)
    start_dt = trading_dates[-1]
    end_dt = trading_dates[0]

    rows = q(
        conn,
        """
        SELECT symbol, buyer_broker_id, COUNT(DISTINCT trading_date) AS sessions, SUM(amount) AS total_amt
        FROM floorsheet_transactions
        WHERE trading_date >= %s
          AND trading_date <= %s
        GROUP BY symbol, buyer_broker_id
        ORDER BY symbol, total_amt DESC
        """,
        (start_dt, end_dt),
    )

    by_symbol: dict[str, list[dict[str, float]]] = defaultdict(list)
    for r in rows:
        by_symbol[r["symbol"]].append(
            {
                "sessions": int(r.get("sessions") or 0),
                "amt": _safe_float(r.get("total_amt")),
            }
        )

    consistency: dict[str, int] = {}
    for sym, values in by_symbol.items():
        top3 = sorted(values, key=lambda x: x["amt"], reverse=True)[:3]
        consistency[sym] = max((int(v["sessions"]) for v in top3), default=0)
    return consistency, floorsheet_days


def _broker_flow_signal(buy_amt: float, sell_amt: float, ratio: float | None) -> str:
    if buy_amt <= 0 and sell_amt <= 0:
        return "NO_FLOW"
    if ratio is None:
        return "BUY_HEAVY" if buy_amt > 0 else "SELL_HEAVY"
    if ratio >= 1.25:
        return "BUY_HEAVY"
    if ratio <= 0.80:
        return "SELL_HEAVY"
    return "TWO_WAY"


def _fetch_broker_flow_summary(
    conn: Any,
    *,
    lookback_sessions: int = 5,
    top_brokers_per_side: int = 3,
    top_symbols: int = 10,
) -> dict[str, Any]:
    date_rows = q(
        conn,
        """
        SELECT DISTINCT trading_date
        FROM floorsheet_transactions
        ORDER BY trading_date DESC
        LIMIT %s
        """,
        (max(1, lookback_sessions),),
    )
    trading_dates = [r.get("trading_date") for r in date_rows if r.get("trading_date")]
    if not trading_dates:
        return {
            "window_start": None,
            "window_end": None,
            "sessions_used": 0,
            "symbol_flow": {},
            "top_accumulation": [],
            "top_distribution": [],
            "top_activity": [],
        }

    start_dt = trading_dates[-1]
    end_dt = trading_dates[0]

    rows = q(
        conn,
        """
        SELECT symbol, broker_id, SUM(net_qty) AS net_qty, SUM(net_amt) AS net_amt
        FROM (
            SELECT
                symbol,
                buyer_broker_id AS broker_id,
                quantity AS net_qty,
                amount AS net_amt
            FROM floorsheet_transactions
            WHERE trading_date >= %s
              AND trading_date <= %s

            UNION ALL

            SELECT
                symbol,
                seller_broker_id AS broker_id,
                -quantity AS net_qty,
                -amount AS net_amt
            FROM floorsheet_transactions
            WHERE trading_date >= %s
              AND trading_date <= %s
        ) flows
        GROUP BY symbol, broker_id
        """,
        (start_dt, end_dt, start_dt, end_dt),
    )

    by_symbol: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    for r in rows:
        sym = r.get("symbol")
        broker_id = r.get("broker_id")
        if not sym or broker_id is None:
            continue
        by_symbol[sym].append(
            {
                "broker_id": str(broker_id),
                "net_qty": _safe_float(r.get("net_qty")),
                "net_amt": _safe_float(r.get("net_amt")),
            }
        )

    symbol_flow: dict[str, dict[str, Any]] = {}
    for sym, flows in by_symbol.items():
        buy_legs = sorted(
            [f for f in flows if _safe_float(f.get("net_amt")) > 0],
            key=lambda x: _safe_float(x.get("net_amt")),
            reverse=True,
        )
        sell_legs = sorted(
            [f for f in flows if _safe_float(f.get("net_amt")) < 0],
            key=lambda x: abs(_safe_float(x.get("net_amt"))),
            reverse=True,
        )

        top_buy = buy_legs[: max(1, top_brokers_per_side)]
        top_sell = sell_legs[: max(1, top_brokers_per_side)]

        buy_amt = sum(_safe_float(x.get("net_amt")) for x in top_buy)
        sell_amt = sum(abs(_safe_float(x.get("net_amt"))) for x in top_sell)
        buy_qty = sum(_safe_float(x.get("net_qty")) for x in top_buy)
        sell_qty = sum(abs(_safe_float(x.get("net_qty"))) for x in top_sell)
        if buy_amt <= 0 and sell_amt <= 0:
            continue

        ratio = round(buy_amt / sell_amt, 2) if sell_amt > 0 else None
        flow_intensity = buy_amt + sell_amt
        flow_dominance = buy_amt - sell_amt

        top_buy_brokers = [
            f"{_safe_float(x.get('broker_id')):.0f} ({_safe_float(x.get('net_amt')) / 1e6:.2f}M)"
            for x in top_buy
            if x.get("broker_id") is not None
        ]
        top_sell_brokers = [
            f"{_safe_float(x.get('broker_id')):.0f} ({abs(_safe_float(x.get('net_amt'))) / 1e6:.2f}M)"
            for x in top_sell
            if x.get("broker_id") is not None
        ]

        symbol_flow[sym] = {
            "symbol": sym,
            "buy_amt": round(buy_amt, 2),
            "sell_amt": round(sell_amt, 2),
            "buy_qty": round(buy_qty),
            "sell_qty": round(sell_qty),
            "flow_intensity": round(flow_intensity, 2),
            "flow_dominance": round(flow_dominance, 2),
            "buy_sell_ratio": ratio,
            "flow_signal": _broker_flow_signal(buy_amt, sell_amt, ratio),
            "top_buy_brokers": top_buy_brokers,
            "top_sell_brokers": top_sell_brokers,
        }

    all_rows = list(symbol_flow.values())
    top_accumulation = sorted(
        all_rows,
        key=lambda x: (
            _safe_float(x.get("buy_amt")),
            _safe_float(x.get("buy_sell_ratio"), 1.0),
            _safe_float(x.get("flow_intensity")),
        ),
        reverse=True,
    )[:top_symbols]
    top_distribution = sorted(
        all_rows,
        key=lambda x: (
            _safe_float(x.get("sell_amt")),
            _safe_float(x.get("flow_intensity")),
        ),
        reverse=True,
    )[:top_symbols]
    top_activity = sorted(all_rows, key=lambda x: _safe_float(x.get("flow_intensity")), reverse=True)[:top_symbols]

    return {
        "window_start": str(start_dt),
        "window_end": str(end_dt),
        "sessions_used": len(trading_dates),
        "symbol_flow": symbol_flow,
        "top_accumulation": top_accumulation,
        "top_distribution": top_distribution,
        "top_activity": top_activity,
    }


def _fetch_broker_intelligence_map(conn: Any, *, quick: bool = False) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Build per-symbol broker intelligence using broker_tracker lifecycle, trust, and signals."""
    try:
        rows = get_all_broker_activity(conn)
        activity_df = aggregate_broker_activity(rows)
        if activity_df is None or activity_df.empty:
            return {}, {"enabled": False, "reason": "no_floorsheet_activity"}

        latest_prices = get_latest_prices(conn)
        symbol_price_history = get_symbol_price_history(conn)
        market_index_history = get_market_index_history(conn, index_name="NEPSE")
        atr_by_symbol = get_atr_14(conn)
        sector_map = build_sector_map(conn)
        sessions_df, summary_df = compute_broker_stock_positions(activity_df, latest_prices)
        if summary_df is None or summary_df.empty:
            return {}, {"enabled": False, "reason": "no_broker_summary"}

        profiles = build_broker_profiles(
            positions_sessions_df=sessions_df,
            positions_summary_df=summary_df,
            activity_df=activity_df,
            sector_map=sector_map,
            price_history_by_symbol=symbol_price_history,
            market_index_history=market_index_history,
        )
        buy_signals, watch_signals, exit_signals = generate_signals(
            positions_sessions_df=sessions_df,
            positions_summary_df=summary_df,
            broker_profiles=profiles,
            latest_prices=latest_prices,
            activity_df=activity_df,
            price_history_by_symbol=symbol_price_history,
            atr_by_symbol=atr_by_symbol,
        )

        signal_rank = {"EXIT": 3, "BUY": 2, "WATCH": 1}
        strength_rank = {"STRONG": 3, "MODERATE": 2, "WEAK": 1}
        signal_map: dict[str, dict[str, Any]] = {}

        def _consume_signal(row: dict[str, Any]) -> None:
            sym = str(row.get("symbol") or "")
            if not sym:
                return
            signal_type = str(row.get("signal_type") or "WATCH").upper()
            candidate = {
                "broker_signal_bias": signal_type,
                "broker_signal_strength": str(row.get("signal_strength") or "WEAK").upper(),
                "signal_broker_id": _safe_int(row.get("broker_id")) or None,
                "signal_broker_name": row.get("broker_name"),
                "signal_power_score": row.get("broker_power_score"),
                "signal_sessions_accumulating": _safe_int(row.get("sessions_accumulating")),
                "signal_latest_asymmetry": _safe_float(row.get("latest_asymmetry"), 50.0),
                "signal_trust_score": row.get("broker_trust_score"),
                "signal_trust_label": row.get("broker_trust_label"),
                "signal_bcr": row.get("bcr"),
                "signal_volume_ratio": row.get("volume_ratio"),
                "signal_circuit_active": bool(row.get("circuit_active")),
                "signal_exit_category": row.get("exit_category"),
                "signal_protective_exit": bool(row.get("protective_exit")),
                "signal_structural_stop_triggered": bool(row.get("structural_stop_triggered")),
                "signal_time_stop_triggered": bool(row.get("time_stop_triggered")),
                "signal_position_size_qty": _safe_int((row.get("position_size") or {}).get("recommended_qty")),
            }
            existing = signal_map.get(sym)
            if existing is None:
                signal_map[sym] = candidate
                return
            curr_key = (
                signal_rank.get(candidate["broker_signal_bias"], 0),
                strength_rank.get(candidate["broker_signal_strength"], 0),
                _safe_float(candidate.get("signal_power_score"), 0.0),
                _safe_float(candidate.get("signal_trust_score"), 0.0),
            )
            prev_key = (
                signal_rank.get(existing.get("broker_signal_bias"), 0),
                strength_rank.get(existing.get("broker_signal_strength"), 0),
                _safe_float(existing.get("signal_power_score"), 0.0),
                _safe_float(existing.get("signal_trust_score"), 0.0),
            )
            if curr_key > prev_key:
                signal_map[sym] = candidate

        for row in exit_signals:
            _consume_signal(row)
        for row in buy_signals:
            _consume_signal(row)
        for row in watch_signals:
            _consume_signal(row)

        summary_rows = summary_df.to_dict("records")
        symbol_best: dict[str, dict[str, Any]] = {}
        high_trust_accum_count: dict[str, int] = defaultdict(int)
        medium_plus_accum_count: dict[str, int] = defaultdict(int)

        for row in summary_rows:
            sym = str(row.get("symbol") or "")
            broker_id = _safe_int(row.get("broker_id"))
            state = str(row.get("session_state") or "FLAT").upper()
            if not sym or broker_id <= 0 or state != "ACCUMULATING":
                continue
            profile = profiles.get(broker_id, {})
            trust_label = str(profile.get("trust_label") or "UNRATED").upper()
            if trust_label == "HIGH":
                high_trust_accum_count[sym] += 1
            if trust_label in {"HIGH", "MEDIUM"}:
                medium_plus_accum_count[sym] += 1

        for row in summary_rows:
            sym = str(row.get("symbol") or "")
            broker_id = _safe_int(row.get("broker_id"))
            if not sym or broker_id <= 0:
                continue
            profile = profiles.get(broker_id, {})
            trust_score = profile.get("trust_score")
            trust_score_num = _safe_float(trust_score, -1.0) if trust_score is not None else -1.0
            key = (
                trust_score_num,
                _safe_int(profile.get("completed_cycles")),
                abs(_safe_int(row.get("cumulative_net_qty"))),
            )
            prev = symbol_best.get(sym)
            prev_key = prev.get("_sort_key") if prev else None
            if prev_key is None or key > prev_key:
                symbol_best[sym] = {
                    "_sort_key": key,
                    "broker_id": broker_id,
                    "broker_name": row.get("broker_name"),
                    "broker_state": str(row.get("session_state") or "FLAT"),
                    "broker_cumulative_net_qty": _safe_int(row.get("cumulative_net_qty")),
                    "broker_sessions_traded": _safe_int(row.get("sessions_traded")),
                    "broker_asymmetry_latest": _safe_float(row.get("asymmetry"), 50.0),
                    "broker_trust_score": trust_score,
                    "broker_trust_label": str(profile.get("trust_label") or "UNRATED"),
                    "broker_power_score": profile.get("broker_power_score"),
                    "broker_tier": str(profile.get("broker_tier") or "UNRATED"),
                    "broker_data_maturity": str(profile.get("data_maturity") or "LOW"),
                    "broker_completed_cycles": _safe_int(profile.get("completed_cycles")),
                }

        out: dict[str, dict[str, Any]] = {}
        for sym, row in symbol_best.items():
            row.pop("_sort_key", None)
            sig = signal_map.get(sym, {})
            merged = dict(row)
            merged.update(sig)
            if not merged.get("broker_signal_bias"):
                state = str(merged.get("broker_state") or "FLAT")
                if state in {"DISTRIBUTING", "EXITING"}:
                    merged["broker_signal_bias"] = "EXIT"
                elif state in {"ENTERING", "ACCUMULATING"}:
                    merged["broker_signal_bias"] = "BUY"
                else:
                    merged["broker_signal_bias"] = "WATCH"
            if not merged.get("broker_signal_strength"):
                merged["broker_signal_strength"] = "WEAK"
            high_count = int(high_trust_accum_count.get(sym, 0))
            medium_plus_count = int(medium_plus_accum_count.get(sym, 0))
            if high_count >= 2:
                convergence_flag = "HIGH_TRUST_CONVERGENCE"
            elif medium_plus_count >= 2:
                convergence_flag = "MEDIUM_PLUS_CONVERGENCE"
            elif high_count == 1:
                convergence_flag = "SINGLE_HIGH_TRUST"
            else:
                convergence_flag = "NONE"
            merged["high_trust_accum_brokers"] = high_count
            merged["medium_plus_accum_brokers"] = medium_plus_count
            merged["broker_convergence_flag"] = convergence_flag
            out[sym] = merged

        return out, {
            "enabled": True,
            "quick_mode": quick,
            "symbols_with_intel": len(out),
            "buy_signals": len(buy_signals),
            "watch_signals": len(watch_signals),
            "exit_signals": len(exit_signals),
        }
    except Exception as e:
        print(f"  [warn] broker intelligence ingestion failed; continuing with flow-only context: {e}")
        return {}, {"enabled": False, "reason": "ingestion_failed"}


def _apply_sector_rsi_context(rows: list[dict[str, Any]]) -> None:
    by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_sector[row.get("sector") or "Other"].append(row)

    for items in by_sector.values():
        rsi_values = sorted(float(r["rsi"]) for r in items if r.get("rsi") is not None)
        n = len(rsi_values)
        for row in items:
            rsi_val = row.get("rsi")
            pct: float | None = None
            bonus = 0
            state = "neutral"
            if rsi_val is not None and n >= 3:
                rsi_float = float(rsi_val)
                le_count = sum(1 for v in rsi_values if v <= rsi_float)
                pct = le_count / n * 100.0

                if pct >= 75:
                    bonus = 2
                    state = "leading"
                elif pct >= 60:
                    bonus = 1
                    state = "strong"
                elif pct <= 25:
                    bonus = -2
                    state = "lagging"
                elif pct <= 40:
                    bonus = -1
                    state = "weak"

            row["sector_rsi_pct"] = round(pct, 1) if pct is not None else None
            row["sector_rsi_bonus"] = bonus
            row["sector_rsi_state"] = state

            if bonus:
                adjusted = max(0.0, min(100.0, _safe_float(row.get("score")) + bonus))
                row["score"] = round(adjusted, 2)
                row["universal_score"] = row["score"]
                if isinstance(row.get("fused_score_breakdown"), dict):
                    row["fused_score_breakdown"]["final_score"] = row["score"]
                tier_name, tier_icon, tier_color = classify_tier(adjusted)
                row["tier_name"] = tier_name
                row["tier_icon"] = tier_icon
                row["tier_color"] = tier_color


import concurrent.futures
import multiprocessing
import concurrent.futures
import multiprocessing

_worker_state = {}

def _init_worker(
    all_corps, all_divs, all_details, all_securities, all_52w, all_live, all_fund,
    broker_scores, vwap_map, turnover_rank_map, top_mover_streaks, sector_pe_avg,
    nepse_values, leaders, laggards, book_closure_map, wabr_map, broker_flow_map,
    broker_intel_map, broker_consistency, floorsheet_days, market_regime_factor,
    data_date, equity, quick
):
    global _worker_state
    _worker_state = {
        'corps': all_corps, 'divs': all_divs, 'details': all_details, 'securities': all_securities,
        'snapshots': all_52w, 'live': all_live, 'fund': all_fund, 'broker_scores': broker_scores,
        'vwap_map': vwap_map, 'turnover_rank_map': turnover_rank_map, 'top_mover_streaks': top_mover_streaks,
        'sector_pe_avg': sector_pe_avg, 'nepse_values': nepse_values, 'leaders': leaders,
        'laggards': laggards, 'book_closure_map': book_closure_map, 'wabr_map': wabr_map,
        'broker_flow_map': broker_flow_map, 'broker_intel_map': broker_intel_map,
        'broker_consistency': broker_consistency, 'floorsheet_days': floorsheet_days,
        'market_regime_factor': market_regime_factor, 'data_date': data_date,
        'equity': equity, 'quick': quick
    }

def _process_single_symbol(sym, raw_candles):
    global _worker_state
    all_corps = _worker_state['corps']
    all_divs = _worker_state['divs']
    all_details = _worker_state['details']
    all_securities = _worker_state['securities']
    all_52w = _worker_state['snapshots']
    all_live = _worker_state['live']
    all_fund = _worker_state['fund']
    broker_scores = _worker_state['broker_scores']
    vwap_map = _worker_state['vwap_map']
    turnover_rank_map = _worker_state['turnover_rank_map']
    top_mover_streaks = _worker_state['top_mover_streaks']
    sector_pe_avg = _worker_state['sector_pe_avg']
    nepse_values = _worker_state['nepse_values']
    leaders = _worker_state['leaders']
    laggards = _worker_state['laggards']
    book_closure_map = _worker_state['book_closure_map']
    wabr_map = _worker_state['wabr_map']
    broker_flow_map = _worker_state['broker_flow_map']
    broker_intel_map = _worker_state['broker_intel_map']
    broker_consistency = _worker_state['broker_consistency']
    floorsheet_days = _worker_state['floorsheet_days']
    market_regime_factor = _worker_state['market_regime_factor']
    data_date = _worker_state['data_date']
    equity = _worker_state['equity']
    quick = _worker_state['quick']

    has_consistency_window = floorsheet_days >= 4
    min_sessions = max(2, (floorsheet_days + 1) // 2) if has_consistency_window else 2
    normalized_market_regime_factor = max(0.85, min(1.15, _safe_float(market_regime_factor, 1.0)))
    trading_mode = _is_trading_mode(equity)

    skip_stats = {
        "skipped_short_history": 0,
        "skipped_bad_price": 0,
        "skipped_low_liquidity": 0,
        "skipped_circuit_volatile": 0,
        "skipped_errors": 0,
    }

    try:
        live_row = all_live.get(sym)
        bridged = bridge_live_candle(raw_candles, live_row)
        candles = get_adjusted_series(bridged, all_corps.get(sym, []), all_divs.get(sym, []))
        candles = forward_fill_zero_volume_days(candles)
        if len(candles) < MIN_DATA_BARS:
            skip_stats["skipped_short_history"] += 1
            return sym, None, skip_stats, None

        closes = [_safe_float(c["close_price"]) for c in candles]
        volumes = [int(c.get("volume") or 0) for c in candles]
        has_live_price = bool(live_row and _safe_float(live_row.get("last_traded_price")) > 0)
        if has_live_price:
            price = _safe_float(live_row.get("last_traded_price"))
        else:
            price = closes[-1]
        if price <= 0:
            skip_stats["skipped_bad_price"] += 1
            return sym, None, skip_stats, None

        vol_window = volumes[-20:]
        avg_volume = sum(vol_window) / len(vol_window) if vol_window else 0
        if avg_volume < LOW_LIQ_THRESH:
            skip_stats["skipped_low_liquidity"] += 1
            return sym, None, skip_stats, None

        sma20 = calc_sma(closes, 20)
        sma50 = calc_sma(closes, 50)
        sma200 = calc_sma(closes, 200)
        rsi = calc_rsi(closes)
        macd_val, sig_val, macd_hist, macd_line = calc_macd(closes)
        macd_just_bullish = check_macd_bullish_crossover(macd_line)
        macd_just_bearish = _check_macd_bearish_crossover(macd_line)
        circuit_volatile = bool(is_circuit_volatile(candles))
        if circuit_volatile:
            skip_stats["skipped_circuit_volatile"] += 1
            return sym, None, skip_stats, None
        atr = _calc_circuit_adjusted_atr(candles)
        if atr is None:
            atr = calc_atr(candles)
        stoch_k, stoch_d = calc_stochastic(candles)
        obv_trend = calc_obv_trend(closes, volumes)
        vpt_bearish_div = _detect_vpt_bearish_divergence(closes, volumes, window=20)
        bb_upper, bb_middle, bb_lower = calc_bollinger_bands(closes)
        bb_squeeze = is_bollinger_squeeze(bb_upper, bb_middle, bb_lower)
        adx = calc_adx(candles)
        roc_20 = calc_roc(closes, 20)
        roc_60 = calc_roc(closes, 60) if len(closes) > 61 else None
        patterns = detect_candlestick_patterns(candles)
        cross = check_ma_crossover(closes, sma20, sma50)
        weekly = resample_to_weekly(candles)
        w_closes = [_safe_float(w["close_price"]) for w in weekly]
        w_sma10 = calc_sma(w_closes, 10) if len(w_closes) >= 10 else None
        weekly_uptrend = bool(w_sma10 is not None and price > w_sma10)
        w_rsi = calc_rsi(w_closes) if len(w_closes) >= 15 else None

        det = all_details.get(sym, {})
        sec = all_securities.get(sym, {})
        snap52 = all_52w.get(sym, {})
        hi52 = (
            _safe_float(snap52.get("hi52"))
            or _safe_float(det.get("fifty_two_week_high"))
            or max(closes[-252:] if len(closes) >= 252 else closes)
        )
        lo52 = (
            _safe_float(snap52.get("lo52"))
            or _safe_float(det.get("fifty_two_week_low"))
            or min(closes[-252:] if len(closes) >= 252 else closes)
        )
        high_prox = round((hi52 - price) / hi52 * 100.0, 2) if hi52 > 0 else 100.0

        vol_ratio = round(volumes[-1] / avg_volume, 2) if avg_volume > 0 else 0.0
        bb_pct = None
        if bb_upper and bb_lower and bb_upper != bb_lower:
            bb_pct = round((price - bb_lower) / (bb_upper - bb_lower) * 100.0, 1)

        sector = det.get("sector_name") or sec.get("sector_name") or "Other"
        broker_asym = _safe_float(broker_scores.get(sym, 50))
        flow = broker_flow_map.get(sym, {})
        broker_intel = broker_intel_map.get(sym, {})
        fund = all_fund.get(sym, {})
        fundamental_stale = _is_fundamental_stale(fund)
        max_fill_streak = _max_forward_fill_streak(candles)
        excessive_forward_fill = max_fill_streak > MAX_FORWARD_FILL_STREAK
        has_synthetic_open = any(_safe_int(c.get("is_synthetic_open")) > 0 for c in candles[-3:])
        latest_symbol_date = _coerce_to_date(candles[-1].get("trading_date"))
        freshness_days = (data_date - latest_symbol_date).days if latest_symbol_date else MAX_ALLOWED_FRESHNESS_DAYS + 1
        freshness_days = max(0, freshness_days)
        data_confidence = _compute_data_confidence(
            bars=len(candles),
            avg_volume=avg_volume,
            circuit_volatile=circuit_volatile,
            fundamental_stale=fundamental_stale,
            has_live_price=has_live_price,
            excessive_forward_fill=excessive_forward_fill,
        )
        setups = _detect_swing_setups(
            price=price,
            candles=candles,
            weekly_uptrend=weekly_uptrend,
            w_rsi=w_rsi,
            sma20=sma20,
            sma50=sma50,
            rsi=rsi,
            macd_hist=macd_hist,
            macd_just_bullish=macd_just_bullish,
            adx=adx,
            bb_squeeze=bb_squeeze,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
            obv_trend=obv_trend,
            vol_ratio=vol_ratio,
            lo52=lo52,
            patterns=patterns,
            broker_asym=broker_asym,
            cross=cross,
        )
        best_setup = max(setups, key=lambda s: s["confidence"]) if setups else None

        scores = calc_universal_score(
            price=price, sma20=sma20, sma50=sma50, sma200=sma200, rsi=rsi, macd_hist=macd_hist,
            macd_just_bullish=macd_just_bullish, vol_ratio=vol_ratio, obv_trend=obv_trend,
            adx=adx, cross=cross, bb_pct=bb_pct, atr=atr, hi52=hi52, lo52=lo52, high_prox=high_prox,
            broker_asym=broker_asym, fund=fund, fundamental_stale=fundamental_stale,
            weekly_uptrend=weekly_uptrend, w_rsi=w_rsi, roc_20=roc_20, roc_60=roc_60,
            setup_conf=best_setup["confidence"] if best_setup else 0, has_setup=bool(best_setup),
            avg_volume=avg_volume, circuit_volatile=circuit_volatile,
        )

        rs_delta, rs_bonus, rs_score = _compute_rs_delta(closes, nepse_values)
        sector_bonus, sector_state = _sector_leadership_bonus(sector, leaders, laggards)
        turnover_info = turnover_rank_map.get(sym, {})
        turnover_rank = int(turnover_info.get("rank") or 0) or None
        turnover_metric = _safe_float(turnover_info.get("metric_value"))
        if turnover_rank is None:
            turnover_bonus = 0
        elif turnover_rank <= 10:
            turnover_bonus = 3
        elif turnover_rank <= 25:
            turnover_bonus = 2
        elif turnover_rank <= 50:
            turnover_bonus = 1
        else:
            turnover_bonus = 0

        opportunity_score = max(0.0, min(100.0, _safe_float(scores.get("universal_score")) + rs_bonus + sector_bonus + turnover_bonus))

        broker_state = str(broker_intel.get("broker_state") or "FLAT").upper()
        broker_trust_label = str(broker_intel.get("broker_trust_label") or "UNRATED").upper()
        broker_data_maturity = str(broker_intel.get("broker_data_maturity") or "LOW").upper()
        broker_signal_bias = str(broker_intel.get("broker_signal_bias") or "WATCH").upper()
        broker_signal_strength = str(broker_intel.get("broker_signal_strength") or "WEAK").upper()
        broker_trust_score = broker_intel.get("broker_trust_score")
        broker_power_score = _safe_float(broker_intel.get("broker_power_score"), 0.0)
        signal_power_score = _safe_float(broker_intel.get("signal_power_score"), broker_power_score)
        high_trust_accum_brokers = _safe_int(broker_intel.get("high_trust_accum_brokers"))
        medium_plus_accum_brokers = _safe_int(broker_intel.get("medium_plus_accum_brokers"))
        broker_convergence_flag = str(broker_intel.get("broker_convergence_flag") or "NONE")

        trend_component = _safe_float(scores.get("trend_score"), 50.0)
        momentum_component = _safe_float(scores.get("momentum_score"), 50.0)
        volume_component = _safe_float(scores.get("volume_score"), 50.0)
        setup_component = _safe_float(scores.get("setup_score"), 25.0)

        stop_loss = round(price - (ATR_SL_MULT * atr), 2) if atr else round(price * 0.92, 2)
        target_1 = round(price + (ATR_T1_MULT * atr), 2) if atr else round(price * 1.08, 2)
        target_2 = round(price + (ATR_T2_MULT * atr), 2) if atr else round(price * 1.15, 2)
        stop_loss = max(0.01, stop_loss)
        risk_per_share = abs(price - stop_loss)
        rr_ratio = round((target_1 - price) / risk_per_share, 2) if risk_per_share > 0 else 0.0
        if trading_mode and risk_per_share > 0:
            raw_size = max(1, int((float(equity) * RISK_PCT) / risk_per_share))
            max_by_capital = max(1, int(float(equity) / price)) if price > 0 else raw_size
            max_by_liquidity = max(1, int(avg_volume * MAX_POSITION_SHARE_OF_AVG_VOL)) if avg_volume > 0 else raw_size
            max_by_allocation = max(1, int((float(equity) * MAX_CAPITAL_ALLOCATION_PCT) / price)) if price > 0 else raw_size
            position_size = max(1, min(raw_size, max_by_capital, max_by_liquidity, max_by_allocation))
        elif trading_mode:
            position_size = 0
        else:
            position_size = None

        setup_type = best_setup["setup_type"] if best_setup else None
        entry_zone = _calc_entry_zone(price, atr, setup_type or "TREND_CONTINUATION")
        hold_period = _est_hold_period(setup_type or "TREND_CONTINUATION")

        eps = _safe_float(fund.get("eps"))
        pe = _safe_float(fund.get("pe_ratio"))
        book_value = _safe_float(fund.get("book_value"))
        pb_ratio = round(price / book_value, 2) if book_value > 0 else None

        divs = all_divs.get(sym, [])
        has_dividend_history = any((_safe_float(d.get("bonus_share_percent")) > 0 or _safe_float(d.get("cash_dividend_percent")) > 0) for d in divs)
        latest_cash = 0.0
        if divs:
            latest_div = max(divs, key=lambda d: _coerce_to_date(d.get("book_close_date")) or date.min)
            latest_cash = _safe_float(latest_div.get("cash_dividend_percent"))
        div_yield = round(latest_cash, 2) if latest_cash > 0 else 0.0
        roe = round((eps / book_value) * 100.0, 2) if book_value > 0 and eps > 0 else 0.0
        fund_for_score = {"eps": eps, "pe_ratio": pe, "book_value": book_value, "div_yield": div_yield, "roe": roe}
        fundamental_score = float(calc_fundamental_score(fund_for_score))

        single_conviction_component = max(0.0, min(100.0, (fundamental_score * 0.55) + (trend_component * 0.25) + (momentum_component * 0.20)))
        relative_strength_component = max(0.0, min(100.0, (rs_score * 0.75) + (50.0 + (sector_bonus * 8.0)) * 0.25))
        volume_turnover_component = max(0.0, min(100.0, (volume_component * 0.70) + (50.0 + turnover_bonus * 12.0) * 0.30))
        market_regime_component = max(0.0, min(100.0, (50.0 + (rs_bonus * 6.0) + (sector_bonus * 6.0)) * normalized_market_regime_factor))

        trust_base = 30.0 if broker_trust_score is None else _safe_float(broker_trust_score, 30.0)
        state_bonus = {"ACCUMULATING": 12.0, "HOLDING": 6.0, "ENTERING": 4.0, "DISTRIBUTING": -12.0, "EXITING": -18.0, "FLAT": 0.0}.get(broker_state, 0.0)
        signal_bonus = {"BUY": 8.0, "WATCH": 2.0, "EXIT": -15.0}.get(broker_signal_bias, 0.0)
        strength_bonus = {"STRONG": 5.0, "MODERATE": 2.0, "WEAK": 0.0}.get(broker_signal_strength, 0.0)
        convergence_bonus = 0.0
        if high_trust_accum_brokers >= 2: convergence_bonus = 8.0
        elif medium_plus_accum_brokers >= 2: convergence_bonus = 4.0
        power_bonus = 0.0
        if signal_power_score > 0: power_bonus = max(-4.0, min(10.0, (signal_power_score - 55.0) / 4.0))
        broker_behavior_component = max(0.0, min(100.0, trust_base + state_bonus + signal_bonus + strength_bonus + convergence_bonus + power_bonus))

        model_opportunity_score = max(0.0, min(100.0, ((setup_component + trend_component) / 2.0) * 0.30 + single_conviction_component * 0.20 + relative_strength_component * 0.15 + broker_behavior_component * 0.15 + volume_turnover_component * 0.10 + market_regime_component * 0.10))
        opportunity_score = round((opportunity_score * 0.35) + (model_opportunity_score * 0.65), 2)

        bullish_candidate = bool(best_setup) or opportunity_score >= 65
        if bullish_candidate and (broker_state in {"ACCUMULATING", "HOLDING", "ENTERING"}) and broker_signal_bias != "EXIT":
            broker_alignment_flag = "ALIGNED"
        elif bullish_candidate and (broker_state in {"DISTRIBUTING", "EXITING"} or broker_signal_bias == "EXIT"):
            broker_alignment_flag = "CONFLICT"
        elif (not bullish_candidate) and broker_signal_bias == "BUY":
            broker_alignment_flag = "EARLY_ACCUMULATION"
        else:
            broker_alignment_flag = "NEUTRAL"

        data_quality_grade = _grade_data_quality(data_confidence=data_confidence, freshness_days=freshness_days, max_fill_streak=max_fill_streak, has_synthetic_open=has_synthetic_open)

        safety_multiplier = {"A": 1.00, "B": 0.94, "C": 0.86, "D": 0.72}.get(data_quality_grade, 0.80)
        safety_multiplier *= {"HIGH": 1.00, "MEDIUM": 0.97, "LOW": 0.92}.get(broker_data_maturity, 0.92)

        if broker_alignment_flag == "ALIGNED": safety_multiplier *= 1.05
        elif broker_alignment_flag == "CONFLICT": safety_multiplier *= 0.78

        veto_reasons: list[str] = []
        if freshness_days > MAX_ALLOWED_FRESHNESS_DAYS: veto_reasons.append(f"stale_data_{freshness_days}d")
        if excessive_forward_fill: veto_reasons.append(f"forward_fill_streak_{max_fill_streak}")
        if has_synthetic_open and freshness_days > 1: veto_reasons.append("synthetic_open_with_stale_context")
        if rr_ratio < 2.0: veto_reasons.append("rr_below_minimum")
        if data_confidence < 60: veto_reasons.append("data_confidence_below_floor")
        if bullish_candidate and broker_signal_bias == "EXIT" and broker_trust_label in {"MEDIUM", "HIGH"}: veto_reasons.append("trusted_broker_exit_bias")
        if bullish_candidate and broker_state == "EXITING" and broker_trust_label == "HIGH": veto_reasons.append("high_trust_broker_exiting")

        explicit_penalties = float(len(veto_reasons) * 7)
        if broker_alignment_flag == "CONFLICT": explicit_penalties += 6.0

        fused_score = max(0.0, min(100.0, (opportunity_score * safety_multiplier) - explicit_penalties))
        hard_veto = len(veto_reasons) > 0
        final_score = min(fused_score, 59.0) if hard_veto else fused_score
        priority_tier = _priority_tier_from_score(final_score, veto_reasons)
        execution_confidence = _execution_confidence_from_grade(data_quality_grade, broker_alignment_flag)
        broker_size_multiplier = _broker_size_multiplier(broker_trust_label, broker_data_maturity, broker_alignment_flag, power_score=signal_power_score)

        if trading_mode and position_size is not None and position_size > 0:
            position_size = max(1, int(position_size * broker_size_multiplier))

        tier_name, tier_icon, tier_color = classify_tier(final_score)
        fused_score_breakdown = {
            "opportunity_score": round(opportunity_score, 2),
            "components": {
                "swing_setup_trend": round((setup_component + trend_component) / 2.0, 2),
                "single_conviction": round(single_conviction_component, 2),
                "relative_strength_sector": round(relative_strength_component, 2),
                "broker_behavior_quality": round(broker_behavior_component, 2),
                "volume_turnover": round(volume_turnover_component, 2),
                "market_alignment": round(market_regime_component, 2),
            },
            "safety_multiplier": round(safety_multiplier, 3),
            "explicit_penalties": round(explicit_penalties, 2),
            "market_regime_factor": round(normalized_market_regime_factor, 3),
            "fused_score": round(fused_score, 2),
            "final_score": round(final_score, 2),
        }

        mfi = calc_mfi(candles)
        vol_20d = _volatility_20d(closes)
        max_dd = _max_drawdown(closes)
        consistency_sessions = int(broker_consistency.get(sym, 0))
        boom_flag = bool(has_consistency_window and broker_asym > 65 and consistency_sessions >= min_sessions and vol_ratio >= 1.3 and rsi is not None and 40 <= float(rsi) <= 80 and sma20 is not None and price >= float(sma20))

        fib_618_broken = False
        if hi52 > lo52 > 0:
            try:
                fib_levels = calc_fibonacci_retracement(lo52, hi52)
                fib_618_broken = price < _safe_float((fib_levels or {}).get("fib_618"))
            except Exception:
                pass

        book_warning = book_closure_map.get(sym)
        if book_warning and int(book_warning.get("days_to_close", 999)) > 30: book_warning = None
        sell_dist_pct = high_prox

        a_for_story = {
            "price": price, "sma20": sma20, "sma50": sma50, "sma200": sma200, "cross": cross,
            "rsi": rsi, "macd_hist": macd_hist, "macd_just_bullish": macd_just_bullish, "macd_just_bearish": macd_just_bearish,
            "vol_ratio": vol_ratio, "obv_trend": obv_trend, "asym_score": broker_asym, "high_prox": high_prox,
            "bb_squeeze": bb_squeeze, "bb_breakout": bool(bb_upper is not None and price > bb_upper and vol_ratio >= 1.5),
            "patterns": patterns, "rr_ratio": rr_ratio, "fib_618_broken": fib_618_broken, "circuit_flag": circuit_volatile,
            "liquidity_flag": bool(is_low_liquidity(candles, LOW_LIQ_THRESH)), "data_bars": len(candles),
            "vol_20d": vol_20d, "max_drawdown": max_dd, "sell_dist_pct": sell_dist_pct, "vpt_bearish_div": vpt_bearish_div,
        }

        strengths = []
        weaknesses = []
        if not quick:
            strengths = build_strengths(a_for_story, fund_for_score)
            weaknesses = build_weaknesses(a_for_story, fund_for_score)

        stock = {
            "symbol": sym, "company_name": det.get("security_name") or sym, "sector": sector,
            "price": round(price, 2), "score": round(final_score, 2), "universal_score": round(final_score, 2),
            "fused_score": round(fused_score, 2), "opportunity_score": round(opportunity_score, 2),
            "fused_score_breakdown": fused_score_breakdown, "veto_reasons": veto_reasons, "hard_veto": hard_veto,
            "broker_alignment_flag": broker_alignment_flag, "data_quality_grade": data_quality_grade,
            "priority_tier": priority_tier, "execution_confidence": execution_confidence,
            "base_universal_score": _safe_float(scores.get("universal_score")),
            "tier_name": tier_name, "tier_icon": tier_icon, "tier_color": tier_color,
            "setup_type": setup_type, "setup_reasoning": best_setup.get("reasoning", []) if best_setup else [],
            "all_setups": setups, "confidence": best_setup.get("confidence", 0) if best_setup else 0,
            "entry_zone": entry_zone, "hold_period": hold_period, "stop_loss": stop_loss,
            "target_1": target_1, "target_2": target_2, "rr_ratio": rr_ratio, "position_size": position_size,
            "sma20": sma20, "sma50": sma50, "sma200": sma200, "rsi": rsi, "macd_val": macd_val, "macd_hist": macd_hist,
            "macd_just_bullish": macd_just_bullish, "atr": atr, "stoch_k": stoch_k, "stoch_d": stoch_d,
            "obv_trend": obv_trend, "vol_ratio": vol_ratio, "avg_volume": round(avg_volume), "data_bars": len(candles),
            "data_confidence": data_confidence, "freshness_days": freshness_days, "max_forward_fill_streak": max_fill_streak,
            "excessive_forward_fill": excessive_forward_fill, "is_synthetic_open": has_synthetic_open, "fundamental_stale": fundamental_stale,
            "mfi": mfi, "vwap": vwap_map.get(sym), "hi52": hi52, "lo52": lo52, "high_prox": high_prox,
            "weekly_uptrend": weekly_uptrend, "broker_asym": broker_asym, "boom_flag": boom_flag,
            "top_mover_streak": int(top_mover_streaks.get(sym, 0)), "scrip_rank_turnover": turnover_rank,
            "scrip_turnover_value": turnover_metric, "turnover_bonus": turnover_bonus, "fundamental_score": fundamental_score,
            "eps": eps, "pe": pe, "book_value": book_value, "pb_ratio": pb_ratio, "div_yield": div_yield,
            "has_dividend_history": has_dividend_history, "vol_20d": vol_20d, "max_drawdown": max_dd,
            "strengths": strengths, "weaknesses": weaknesses, "sector_avg_pe": sector_pe_avg.get(sector),
            "sector_leadership": sector_state, "sector_bonus": sector_bonus, "sector_rsi_pct": None,
            "sector_rsi_bonus": 0, "sector_rsi_state": "neutral", "rs_delta": rs_delta, "rs_bonus": rs_bonus,
            "rs_score": rs_score, "book_closure_warning": book_warning, "wabr_support": wabr_map.get(sym),
            "broker_buy_amt": _safe_float(flow.get("buy_amt")), "broker_sell_amt": _safe_float(flow.get("sell_amt")),
            "broker_buy_qty": _safe_float(flow.get("buy_qty")), "broker_sell_qty": _safe_float(flow.get("sell_qty")),
            "broker_buy_sell_ratio": flow.get("buy_sell_ratio"), "broker_flow_intensity": _safe_float(flow.get("flow_intensity")),
            "broker_flow_dominance": _safe_float(flow.get("flow_dominance")), "broker_flow_signal": flow.get("flow_signal", "NO_FLOW"),
            "broker_state": broker_state, "broker_trust_score": broker_trust_score, "broker_trust_label": broker_trust_label,
            "broker_power_score": broker_power_score, "signal_power_score": signal_power_score, "broker_tier": broker_intel.get("broker_tier"),
            "broker_data_maturity": broker_data_maturity, "broker_signal_bias": broker_signal_bias, "broker_signal_strength": broker_signal_strength,
            "signal_bcr": broker_intel.get("signal_bcr"), "signal_volume_ratio": broker_intel.get("signal_volume_ratio"),
            "signal_circuit_active": bool(broker_intel.get("signal_circuit_active")), "signal_exit_category": broker_intel.get("signal_exit_category"),
            "signal_protective_exit": bool(broker_intel.get("signal_protective_exit")), "signal_structural_stop_triggered": bool(broker_intel.get("signal_structural_stop_triggered")),
            "signal_time_stop_triggered": bool(broker_intel.get("signal_time_stop_triggered")), "signal_position_size_qty": _safe_int(broker_intel.get("signal_position_size_qty")),
            "high_trust_accum_brokers": high_trust_accum_brokers, "medium_plus_accum_brokers": medium_plus_accum_brokers,
            "broker_convergence_flag": broker_convergence_flag, "broker_size_multiplier": broker_size_multiplier,
            "top_buy_brokers": flow.get("top_buy_brokers", []), "top_sell_brokers": flow.get("top_sell_brokers", []),
            "circuit_volatile": circuit_volatile, "vpt_bearish_div": vpt_bearish_div, "close_series": closes, "volume_series": volumes,
        }
        return sym, stock, skip_stats, None

    except Exception as e:
        return sym, None, skip_stats, str(e)


def _build_universe(
    *,
    all_ohlcv: dict[str, list[dict[str, Any]]],
    all_corps: dict[str, list[dict[str, Any]]],
    all_divs: dict[str, list[dict[str, Any]]],
    all_details: dict[str, dict[str, Any]],
    all_securities: dict[str, dict[str, Any]],
    all_52w: dict[str, dict[str, Any]],
    all_live: dict[str, dict[str, Any]],
    all_fund: dict[str, dict[str, Any]],
    broker_scores: dict[str, float],
    vwap_map: dict[str, float],
    turnover_rank_map: dict[str, dict[str, float]],
    top_mover_streaks: dict[str, int],
    sector_pe_avg: dict[str, float],
    nepse_values: list[float],
    leaders: list[str],
    laggards: list[str],
    book_closure_map: dict[str, dict[str, Any]],
    wabr_map: dict[str, float],
    broker_flow_map: dict[str, dict[str, Any]],
    broker_intel_map: dict[str, dict[str, Any]],
    broker_consistency: dict[str, int],
    floorsheet_days: int,
    market_regime_factor: float,
    data_date: date,
    equity: int | None,
    quick: bool,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    ranked: list[dict[str, Any]] = []
    diagnostics = {
        "total_symbols": len(all_ohlcv),
        "processed": 0,
        "ranked": 0,
        "skipped_short_history": 0,
        "skipped_bad_price": 0,
        "skipped_low_liquidity": 0,
        "skipped_circuit_volatile": 0,
        "skipped_errors": 0,
    }

    max_workers = max(1, multiprocessing.cpu_count() // 5)
    init_args = (
        all_corps, all_divs, all_details, all_securities, all_52w, all_live, all_fund,
        broker_scores, vwap_map, turnover_rank_map, top_mover_streaks, sector_pe_avg,
        nepse_values, leaders, laggards, book_closure_map, wabr_map, broker_flow_map,
        broker_intel_map, broker_consistency, floorsheet_days, market_regime_factor,
        data_date, equity, quick
    )

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker, initargs=init_args) as executor:
        futures = {
            executor.submit(_process_single_symbol, sym, raw_candles): sym
            for sym, raw_candles in all_ohlcv.items()
        }
        
        for future in concurrent.futures.as_completed(futures):
            try:
                sym, stock, skips, err = future.result()
                
                for k, v in skips.items():
                    diagnostics[k] += v
                
                if err:
                    diagnostics["skipped_errors"] += 1
                    print(f"  [warn] skipped {sym} during universe build: {err}")
                
                if stock:
                    ranked.append(stock)
                    diagnostics["processed"] += 1
            except Exception as e:
                diagnostics["skipped_errors"] += 1
                print(f"  [warn] executor error on symbol {futures[future]}: {e}")

    _apply_sector_rsi_context(ranked)

    ranked.sort(key=lambda s: s.get("score", 0), reverse=True)
    diagnostics["ranked"] = len(ranked)
    by_symbol = {s["symbol"]: s for s in ranked}

    by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in ranked:
        by_sector[s.get("sector") or "Other"].append(s)
    for sec, items in by_sector.items():
        ordered = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
        size = len(ordered)
        for i, row in enumerate(ordered, start=1):
            row["sector_rank"] = i
            row["sector_size"] = size
            if not quick:
                row["sector_peers"] = [p["symbol"] for p in ordered[:6] if p["symbol"] != row["symbol"]][:4]
            else:
                row["sector_peers"] = []

    return ranked, by_symbol, diagnostics


def _classify_buckets(
    ranked: list[dict[str, Any]],
    sector_pe_avg: dict[str, float],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    buckets = {"short": [], "swing": [], "long": [], "hotlist": []}
    by_symbol: dict[str, dict[str, Any]] = {}
    tier_rank = {"A": 3, "B": 2, "C": 1}

    for s in ranked:
        cls = classify_stock(s, sector_pe_avg.get(s.get("sector", "")))
        s["bucket_flags"] = {
            "short": cls["short"],
            "swing": cls["swing"],
            "long": cls["long"],
            "hotlist": cls["hotlist"],
        }
        s["bucket_reasons"] = cls["reasons"]
        s["action_label"] = _derive_action_label(s.get("score"), bucket_flags=s["bucket_flags"])
        by_symbol[s["symbol"]] = s
        for name in ("short", "swing", "long", "hotlist"):
            if cls[name]:
                buckets[name].append(s)

    buckets["short"].sort(
        key=lambda x: (
            tier_rank.get(str(x.get("priority_tier") or "C"), 1),
            x.get("execution_confidence", 0),
            x.get("top_mover_streak", 0),
            max(0, 200 - int(x.get("scrip_rank_turnover") or 10_000)),
            x.get("vol_ratio", 0),
            x.get("score", 0),
        ),
        reverse=True,
    )
    buckets["swing"].sort(
        key=lambda x: (
            tier_rank.get(str(x.get("priority_tier") or "C"), 1),
            x.get("execution_confidence", 0),
            x.get("score", 0),
        ),
        reverse=True,
    )
    buckets["long"].sort(
        key=lambda x: (
            tier_rank.get(str(x.get("priority_tier") or "C"), 1),
            x.get("execution_confidence", 0),
            x.get("fundamental_score", 0),
            -_safe_float(x.get("pb_ratio"), default=999),
            x.get("score", 0),
        ),
        reverse=True,
    )
    buckets["hotlist"].sort(
        key=lambda x: (
            tier_rank.get(str(x.get("priority_tier") or "C"), 1),
            x.get("execution_confidence", 0),
            x.get("score", 0),
        ),
        reverse=True,
    )
    buckets["hotlist"] = buckets["hotlist"][:HOTLIST_LIMIT]

    return buckets, by_symbol


def _enrich_plans(
    plans: list[dict[str, Any]],
    stock_map: dict[str, dict[str, Any]],
    bucket: str,
) -> list[dict[str, Any]]:
    enriched = []
    for p in plans:
        sym = p.get("symbol")
        s = stock_map.get(sym, {})
        bucket_criteria = s.get("bucket_reasons", {}).get(bucket, [])
        row = dict(p)
        row.update(
            {
                "company_name": s.get("company_name", sym),
                "sector": s.get("sector", "Other"),
                "price": s.get("price"),
                "score": s.get("score"),
                "action_label": s.get("action_label", "WATCH"),
                "fused_score": s.get("fused_score"),
                "priority_tier": s.get("priority_tier"),
                "execution_confidence": s.get("execution_confidence"),
                "data_quality_grade": s.get("data_quality_grade"),
                "broker_alignment_flag": s.get("broker_alignment_flag"),
                "veto_reasons": s.get("veto_reasons", []),
                "fused_score_breakdown": s.get("fused_score_breakdown", {}),
                "setup_type": s.get("setup_type"),
                "weekly_uptrend": s.get("weekly_uptrend"),
                "rsi": s.get("rsi"),
                "mfi": s.get("mfi"),
                "vwap": s.get("vwap"),
                "obv_trend": s.get("obv_trend"),
                "broker_asym": s.get("broker_asym"),
                "pb_ratio": s.get("pb_ratio"),
                "pe": s.get("pe"),
                "eps": s.get("eps"),
                "fundamental_score": s.get("fundamental_score"),
                "book_closure_warning": s.get("book_closure_warning"),
                "wabr_support": s.get("wabr_support"),
                "broker_buy_amt": s.get("broker_buy_amt"),
                "broker_sell_amt": s.get("broker_sell_amt"),
                "broker_buy_qty": s.get("broker_buy_qty"),
                "broker_sell_qty": s.get("broker_sell_qty"),
                "broker_buy_sell_ratio": s.get("broker_buy_sell_ratio"),
                "broker_flow_intensity": s.get("broker_flow_intensity"),
                "broker_flow_dominance": s.get("broker_flow_dominance"),
                "broker_flow_signal": s.get("broker_flow_signal"),
                "broker_state": s.get("broker_state"),
                "broker_signal_bias": s.get("broker_signal_bias"),
                "broker_signal_strength": s.get("broker_signal_strength"),
                "broker_trust_score": s.get("broker_trust_score"),
                "broker_trust_label": s.get("broker_trust_label"),
                "broker_power_score": s.get("broker_power_score"),
                "signal_power_score": s.get("signal_power_score"),
                "broker_tier": s.get("broker_tier"),
                "broker_data_maturity": s.get("broker_data_maturity"),
                "signal_bcr": s.get("signal_bcr"),
                "signal_volume_ratio": s.get("signal_volume_ratio"),
                "signal_circuit_active": s.get("signal_circuit_active"),
                "signal_exit_category": s.get("signal_exit_category"),
                "signal_protective_exit": s.get("signal_protective_exit"),
                "signal_structural_stop_triggered": s.get("signal_structural_stop_triggered"),
                "signal_time_stop_triggered": s.get("signal_time_stop_triggered"),
                "signal_position_size_qty": s.get("signal_position_size_qty"),
                "high_trust_accum_brokers": s.get("high_trust_accum_brokers", 0),
                "medium_plus_accum_brokers": s.get("medium_plus_accum_brokers", 0),
                "broker_convergence_flag": s.get("broker_convergence_flag", "NONE"),
                "broker_size_multiplier": s.get("broker_size_multiplier"),
                "top_buy_brokers": s.get("top_buy_brokers", []),
                "top_sell_brokers": s.get("top_sell_brokers", []),
                "scrip_rank_turnover": s.get("scrip_rank_turnover"),
                "sector_rsi_pct": s.get("sector_rsi_pct"),
                "sector_rank": s.get("sector_rank"),
                "sector_size": s.get("sector_size"),
                "rs_delta": s.get("rs_delta"),
                "vol_20d": s.get("vol_20d"),
                "max_drawdown": s.get("max_drawdown"),
                "strengths": s.get("strengths", []),
                "weaknesses": s.get("weaknesses", []),
                "setup_reasoning": s.get("setup_reasoning", []),
                "sector_peers": s.get("sector_peers", [])[:4],
                "bucket_criteria": bucket_criteria,
                "reasons": bucket_criteria[:3],
            }
        )
        enriched.append(row)
    return enriched


def _calc_broker_asym_for_range(conn: Any, symbol: str, max_dt: Any, from_days: int, to_days: int) -> float:
    """Compute asym score in [from_days, to_days] lookback window from max date.

    Example:
        from_days=0,to_days=4 => last 5 sessions
        from_days=5,to_days=9 => previous 5 sessions
    """

    if not max_dt:
        return 50.0

    session_count = max(1, int(to_days) + 1)
    date_rows = q(
        conn,
        """
        SELECT DISTINCT trading_date
        FROM floorsheet_transactions
        WHERE symbol = %s
          AND trading_date <= %s
        ORDER BY trading_date DESC
        LIMIT %s
        """,
        (symbol, max_dt, session_count),
    )
    if not date_rows or len(date_rows) <= from_days:
        return 50.0

    window = date_rows[from_days : to_days + 1]
    if not window:
        return 50.0

    start_dt = window[-1].get("trading_date")
    end_dt = window[0].get("trading_date")

    buy_rows = q(
        conn,
        """
        SELECT buyer_broker_id, SUM(amount) AS buy_amt
        FROM floorsheet_transactions
        WHERE symbol = %s
          AND trading_date >= %s
          AND trading_date <= %s
        GROUP BY buyer_broker_id
        """,
        (symbol, start_dt, end_dt),
    )
    sell_rows = q(
        conn,
        """
        SELECT seller_broker_id, SUM(amount) AS sell_amt
        FROM floorsheet_transactions
        WHERE symbol = %s
          AND trading_date >= %s
          AND trading_date <= %s
        GROUP BY seller_broker_id
        """,
        (symbol, start_dt, end_dt),
    )

    buy_amts = sorted([_safe_float(r.get("buy_amt")) for r in buy_rows], reverse=True)
    sell_amts = sorted([_safe_float(r.get("sell_amt")) for r in sell_rows], reverse=True)
    total_buy = sum(buy_amts)
    if total_buy <= 0:
        return 50.0

    buy_conc = sum(buy_amts[:3]) / total_buy * 100.0 if buy_amts else 0.0
    sell_conc = sum(sell_amts[:3]) / total_buy * 100.0 if sell_amts else 0.0
    return max(0.0, min(100.0, 50.0 + (buy_conc - sell_conc) / 2.0))


def _build_track_verdicts(
    conn: Any,
    tracked_symbols: list[str],
    stock_map: dict[str, dict[str, Any]],
    plan_lookup: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not tracked_symbols:
        return []

    max_dt = qone(conn, "SELECT MAX(trading_date) AS max_dt FROM floorsheet_transactions").get("max_dt")
    out: list[dict[str, Any]] = []

    for raw_sym in tracked_symbols:
        sym = raw_sym.upper().strip()
        stock = stock_map.get(sym)
        if not stock:
            out.append(
                {
                    "symbol": sym,
                    "bucket": "none",
                    "verdict": "DATA_UNAVAILABLE",
                    "status_note": "Not present in screened universe (insufficient candles/liquidity or fetch skip)",
                    "signal_deteriorated": None,
                    "confidence_decay": None,
                    "broker_state_shift_since_entry": None,
                    "hard_exit_triggered": None,
                    "trim_reason_category": None,
                }
            )
            continue

        plans = plan_lookup.get(sym, {})
        active_bucket = "short" if "short" in plans else "swing" if "swing" in plans else "long" if "long" in plans else "none"
        ref_plan = plans.get(active_bucket) if active_bucket != "none" else None

        price = _safe_float(stock.get("price"))
        stop_loss = _safe_float((ref_plan or {}).get("stop_loss"), _safe_float(stock.get("stop_loss"), price * 0.92))
        target_1 = _safe_float((ref_plan or {}).get("target_1"), _safe_float(stock.get("target_1"), price * 1.08))
        stop_touched = price <= stop_loss
        t1_reached = price >= target_1
        rsi_div = _detect_bearish_rsi_divergence(stock.get("close_series", []))
        obv_flip = _detect_obv_flip(stock.get("close_series", []), stock.get("volume_series", []))
        vpt_div = _detect_vpt_bearish_divergence(
            stock.get("close_series", []),
            stock.get("volume_series", []),
            window=20,
        )
        close_below_sma20 = stock.get("sma20") is not None and price < _safe_float(stock.get("sma20"))

        broker_recent = _calc_broker_asym_for_range(conn, sym, max_dt, from_days=0, to_days=4) if max_dt else 50.0
        broker_prior = _calc_broker_asym_for_range(conn, sym, max_dt, from_days=5, to_days=9) if max_dt else 50.0
        broker_flip = broker_prior > 55 and broker_recent < 45
        broker_signal_bias = str(stock.get("broker_signal_bias") or "WATCH").upper()
        broker_trust_label = str(stock.get("broker_trust_label") or "UNRATED").upper()
        high_trust_accum_brokers = _safe_int(stock.get("high_trust_accum_brokers"))
        medium_plus_accum_brokers = _safe_int(stock.get("medium_plus_accum_brokers"))
        broker_convergence_flag = str(stock.get("broker_convergence_flag") or "NONE").upper()
        broker_formal_exit = broker_signal_bias == "EXIT" and broker_trust_label in {"HIGH", "MEDIUM"}

        current_any_bucket = bool(
            stock.get("bucket_flags", {}).get("short")
            or stock.get("bucket_flags", {}).get("swing")
            or stock.get("bucket_flags", {}).get("long")
        )
        signal_deteriorated = not current_any_bucket

        eps_negative = _safe_float(stock.get("eps")) <= 0
        pe_overpriced = _safe_float(stock.get("pe")) > 40
        fundamental_exit = active_bucket == "long" and (eps_negative or pe_overpriced)
        execution_confidence = _safe_float(stock.get("execution_confidence"), 50.0)
        confidence_decay = round(max(0.0, 85.0 - execution_confidence), 1)

        current_broker_state = str(stock.get("broker_state") or "FLAT").upper()
        if broker_prior >= 60:
            inferred_prior_state = "ACCUMULATING"
        elif broker_prior <= 40:
            inferred_prior_state = "DISTRIBUTING"
        else:
            inferred_prior_state = "HOLDING"
        broker_state_shift_since_entry = (
            "STABLE" if inferred_prior_state == current_broker_state else f"{inferred_prior_state}->{current_broker_state}"
        )

        verdict = "HOLD"
        notes = []

        if stop_touched or fundamental_exit or broker_formal_exit:
            verdict = "EXIT"
        elif active_bucket in ("short", "swing") and (rsi_div or obv_flip or vpt_div or close_below_sma20):
            verdict = "EXIT"
        elif t1_reached or rsi_div or obv_flip or vpt_div or broker_flip or signal_deteriorated:
            verdict = "TRIM"

        if stop_touched:
            notes.append("stop-loss touched")
        if t1_reached:
            notes.append("T1 reached")
        if rsi_div:
            notes.append("RSI divergence")
        if obv_flip:
            notes.append("OBV flipped down")
        if vpt_div:
            notes.append("VPT bearish divergence")
        if broker_flip:
            notes.append("broker flow flipped")
        if broker_formal_exit:
            notes.append("trusted broker formal EXIT signal")
        if close_below_sma20:
            notes.append("close below SMA20")
        if active_bucket == "long" and eps_negative:
            notes.append("EPS turned negative")
        if active_bucket == "long" and pe_overpriced:
            notes.append("PE above 40")
        if signal_deteriorated:
            notes.append("entry signal deteriorated")

        hard_exit_triggered = verdict == "EXIT" and bool(
            stop_touched
            or fundamental_exit
            or broker_formal_exit
            or close_below_sma20
            or broker_flip
            or (active_bucket in ("short", "swing") and (rsi_div or obv_flip or vpt_div))
        )
        trim_reason_category = None
        if verdict == "TRIM":
            if t1_reached:
                trim_reason_category = "profit_lock"
            elif broker_flip:
                trim_reason_category = "broker_flow_deterioration"
            elif signal_deteriorated:
                trim_reason_category = "signal_quality_drop"
            elif rsi_div or obv_flip or vpt_div:
                trim_reason_category = "technical_deterioration"
            else:
                trim_reason_category = "risk_rebalance"

        out.append(
            {
                "symbol": sym,
                "bucket": active_bucket,
                "price": price,
                "stop_touched": stop_touched,
                "target1_reached": t1_reached,
                "rsi_divergence": rsi_div,
                "obv_flip": obv_flip,
                "vpt_bearish_divergence": vpt_div,
                "broker_flip": broker_flip,
                "close_below_sma20": close_below_sma20,
                "signal_deteriorated": signal_deteriorated,
                "broker_recent": round(broker_recent, 1),
                "broker_prior": round(broker_prior, 1),
                "broker_state": current_broker_state,
                "broker_state_shift_since_entry": broker_state_shift_since_entry,
                "broker_signal_bias": broker_signal_bias,
                "broker_trust_label": broker_trust_label,
                "high_trust_accum_brokers": high_trust_accum_brokers,
                "medium_plus_accum_brokers": medium_plus_accum_brokers,
                "broker_convergence_flag": broker_convergence_flag,
                "broker_formal_exit": broker_formal_exit,
                "execution_confidence": execution_confidence,
                "confidence_decay": confidence_decay,
                "hard_exit_triggered": hard_exit_triggered,
                "trim_reason_category": trim_reason_category,
                "verdict": verdict,
                "status_note": ", ".join(notes) if notes else "No active exit trigger",
            }
        )

    return out


def run_master_pipeline(
    *,
    equity: int | None = None,
    quick: bool = False,
    allow_stale_data: bool = False,
    tracked_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full NEPSE Master Trader coordinator pipeline."""

    tracked_symbols = tracked_symbols or []
    trading_mode = _is_trading_mode(equity)
    conn = get_conn()
    try:
        data_date = _assert_fresh_ohlcv_date(conn, allow_stale=allow_stale_data)

        # Shared one-pass fetch set for layer 1 + 2 + most of 3.
        all_ohlcv = fetch_all_ohlcv(conn)
        all_corps = fetch_all_corp_actions(conn)
        all_divs = fetch_all_dividends(conn)
        all_details = fetch_all_company_details(conn)
        all_securities = fetch_all_securities(conn)
        all_52w = fetch_52w_from_snapshots(conn)
        all_live = fetch_all_live_ltp(conn)
        all_fund = fetch_all_fundamentals(conn)
        broker_scores = fetch_broker_scores(conn)

        market = _fetch_market_dashboard(conn)
        market_regime_factor = _safe_float((market.get("regime") or {}).get("factor"), 1.0)
        top_mover_streaks = _fetch_top_mover_streaks(conn)
        vwap_map = _fetch_intraday_vwap_map(conn)
        turnover_rank_map = _fetch_scrip_turnover_ranks(conn)
        sector_pe_avg = _fetch_sector_pe_averages(conn)
        nepse_values = _fetch_nepse_series(conn)
        leaders, laggards = _fetch_sector_leadership(conn)
        book_closure_map = _fetch_book_closure_map(conn) if not quick else {}
        wabr_map = _fetch_wabr_map(conn) if not quick else {}
        broker_flow = _fetch_broker_flow_summary(conn, lookback_sessions=3 if quick else 5)
        broker_flow_map = broker_flow.get("symbol_flow", {})
        broker_intel_map, broker_intel_meta = _fetch_broker_intelligence_map(conn, quick=quick)
        broker_consistency, floorsheet_days = _fetch_broker_consistency(conn)
        data_health = _build_data_health_snapshot(conn, data_date)

        ranking, _, validation_summary = _build_universe(
            all_ohlcv=all_ohlcv,
            all_corps=all_corps,
            all_divs=all_divs,
            all_details=all_details,
            all_securities=all_securities,
            all_52w=all_52w,
            all_live=all_live,
            all_fund=all_fund,
            broker_scores=broker_scores,
            vwap_map=vwap_map,
            turnover_rank_map=turnover_rank_map,
            top_mover_streaks=top_mover_streaks,
            sector_pe_avg=sector_pe_avg,
            nepse_values=nepse_values,
            leaders=leaders,
            laggards=laggards,
            book_closure_map=book_closure_map,
            wabr_map=wabr_map,
            broker_flow_map=broker_flow_map,
            broker_intel_map=broker_intel_map,
            broker_consistency=broker_consistency,
            floorsheet_days=floorsheet_days,
            market_regime_factor=market_regime_factor,
            data_date=data_date,
            equity=equity,
            quick=quick,
        )

        buckets, classified_stock_map = _classify_buckets(ranking, sector_pe_avg)

        short_candidates = buckets["short"][:DEFAULT_SHORT_LIMIT]
        swing_candidates = buckets["swing"][:DEFAULT_SWING_LIMIT]
        long_candidates = buckets["long"][:DEFAULT_LONG_LIMIT]
        hotlist_candidates = buckets["hotlist"][:HOTLIST_LIMIT]

        short_plans = _enrich_plans(build_bucket_plans(short_candidates, "short", equity), classified_stock_map, "short")
        swing_plans = _enrich_plans(build_bucket_plans(swing_candidates, "swing", equity), classified_stock_map, "swing")
        long_plans = _enrich_plans(build_bucket_plans(long_candidates, "long", equity), classified_stock_map, "long")

        # Fast lookups for tracker/hotlist perspective.
        plan_lookup: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in short_plans:
            plan_lookup[row["symbol"]]["short"] = row
        for row in swing_plans:
            plan_lookup[row["symbol"]]["swing"] = row
        for row in long_plans:
            plan_lookup[row["symbol"]]["long"] = row

        hotlist = []
        for s in hotlist_candidates:
            sym = s["symbol"]
            symbol_plans = plan_lookup.get(sym, {})
            available_timeframes = [name for name in ("short", "swing", "long") if symbol_plans.get(name)]
            hotlist.append(
                {
                    "symbol": sym,
                    "company_name": s.get("company_name", sym),
                    "sector": s.get("sector", "Other"),
                    "score": s.get("score", 0),
                    "fused_score": s.get("fused_score"),
                    "priority_tier": s.get("priority_tier"),
                    "execution_confidence": s.get("execution_confidence"),
                    "data_quality_grade": s.get("data_quality_grade"),
                    "broker_alignment_flag": s.get("broker_alignment_flag"),
                    "veto_reasons": s.get("veto_reasons", []),
                    "action_label": s.get("action_label", "WATCH"),
                    "setup_type": s.get("setup_type"),
                    "boom_flag": s.get("boom_flag", False),
                    "timeframes": available_timeframes,
                    "short_plan": symbol_plans.get("short"),
                    "swing_plan": symbol_plans.get("swing"),
                    "long_plan": symbol_plans.get("long"),
                    "reasons": s.get("bucket_reasons", {}).get("hotlist", []),
                    "book_closure_warning": s.get("book_closure_warning"),
                    "wabr_support": s.get("wabr_support"),
                    "broker_buy_amt": s.get("broker_buy_amt"),
                    "broker_sell_amt": s.get("broker_sell_amt"),
                    "broker_buy_sell_ratio": s.get("broker_buy_sell_ratio"),
                    "broker_flow_signal": s.get("broker_flow_signal"),
                    "broker_flow_intensity": s.get("broker_flow_intensity"),
                    "broker_state": s.get("broker_state"),
                    "broker_signal_bias": s.get("broker_signal_bias"),
                    "broker_trust_label": s.get("broker_trust_label"),
                    "high_trust_accum_brokers": s.get("high_trust_accum_brokers", 0),
                    "medium_plus_accum_brokers": s.get("medium_plus_accum_brokers", 0),
                    "broker_convergence_flag": s.get("broker_convergence_flag", "NONE"),
                    "broker_formal_exit": (
                        str(s.get("broker_signal_bias") or "WATCH").upper() == "EXIT"
                        and str(s.get("broker_trust_label") or "UNRATED").upper() in {"HIGH", "MEDIUM"}
                    ),
                }
            )

        tracked = _build_track_verdicts(conn, tracked_symbols, classified_stock_map, plan_lookup)

        # Tracker consumes raw series; strip them before packaging report payload.
        for s in ranking:
            s.pop("close_series", None)
            s.pop("volume_series", None)

        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "trading" if trading_mode else "screening",
            "trading_mode": trading_mode,
            "equity": equity if trading_mode else None,
            "quick": quick,
            "market": market,
            "broker_flow": broker_flow,
            "meta": {
                "mode": "trading" if trading_mode else "screening",
                "universe": len(ranking),
                "short_count": len(short_candidates),
                "swing_count": len(swing_candidates),
                "long_count": len(long_candidates),
                "hotlist_count": len(hotlist),
                "data_date": data_date.isoformat(),
                "stale_data": data_date != date.today(),
                "validation_summary": validation_summary,
                "broker_intelligence": broker_intel_meta,
                "data_sources": DATA_SOURCE_TABLES,
                "data_health": data_health,
            },
            "hotlist": hotlist,
            "short_plans": short_plans,
            "swing_plans": swing_plans,
            "long_plans": long_plans,
            "ranking": ranking,
            "tracked": tracked,
        }

    finally:
        conn.close()
