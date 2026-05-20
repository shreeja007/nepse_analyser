"""
analysor_stores.store — Persists analyzer output into nepsego_analysis database.

Three entry points:
  save_full_analysis(data, report_path, elapsed)     — from `python -m analysor`
  save_single_analysis(symbol, data, report_path)    — from `python -m single_analyser NABIL`
  save_batch_single_analysis(all_data, report_path)  — from `python -m single_analyser --all`

All functions are non-fatal: exceptions are caught and printed as warnings
so the HTML report is always saved regardless of DB issues.
"""

from __future__ import annotations

import traceback
from datetime import date, datetime

from analysor_stores.config import ensure_database, get_conn, get_source_conn


# ═══════════════════════════════════════════════════════════════════════
#  SIGNAL → NUMERIC MAPPING
# ═══════════════════════════════════════════════════════════════════════

SIGNAL_MAP = {
    "STRONG SELL": -2,
    "SELL":        -1,
    "HOLD":         0,
    "BUY":          1,
    "STRONG BUY":   2,
}


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _safe(val, default=None):
    """Return val if it's a real number, else default."""
    if val is None:
        return default
    try:
        f = float(val)
        if f != f:  # NaN check
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_bool(val):
    """Convert bool/truthy to 1/0/None for MySQL TINYINT."""
    if val is None:
        return None
    return 1 if val else 0


def _pct_vs(price, sma):
    """Compute (price - sma) / sma * 100, or None."""
    p = _safe(price)
    s = _safe(sma)
    if p is None or s is None or s == 0:
        return None
    return round((p - s) / s * 100, 4)


# Module-level cache for analysis date (reset each process, valid per day)
_cached_analysis_date: date | None = None


def _detect_analysis_date() -> date:
    """
    Detect the most recent trading date from the main nepsego database.
    Cached per-process so only one DB connection is opened regardless
    of how many save_*() functions are called.
    """
    global _cached_analysis_date
    if _cached_analysis_date is not None:
        return _cached_analysis_date

    conn = get_source_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(trading_date) AS d FROM daily_ohlcv WHERE close_price > 0"
            )
            row = cur.fetchone()
            if row and row.get("d"):
                d = row["d"]
                _cached_analysis_date = d if isinstance(d, date) else date.today()
            else:
                _cached_analysis_date = date.today()
        return _cached_analysis_date
    finally:
        conn.close()


def _extract_pivots(pivots: dict | None, key: str):
    """Safely extract a value from the pivots dict."""
    if not pivots or not isinstance(pivots, dict):
        return None
    return _safe(pivots.get(key))


def _extract_fib(fib: dict | None, key: str):
    """Safely extract a value from the fib dict."""
    if not fib or not isinstance(fib, dict):
        return None
    return _safe(fib.get(key))


# ═══════════════════════════════════════════════════════════════════════
#  SNAPSHOT ROW BUILDER
# ═══════════════════════════════════════════════════════════════════════

def _build_snapshot_row(r: dict, run_id: int, analysis_date: date,
                        source: str, regime: str = None,
                        regime_factor: float = None) -> tuple:
    """
    Convert one per-symbol analysis dict into an INSERT tuple.
    Works for both analysor and single_analyser output dicts.
    """
    signal = str(r.get("signal", "HOLD"))
    signal_num = SIGNAL_MAP.get(signal, 0)
    price = _safe(r.get("price"))

    # Pivot / Fib extraction
    pivots = r.get("pivots")
    fib = r.get("fib")

    # Patterns list → comma-separated string
    patterns = r.get("patterns")
    if isinstance(patterns, list):
        patterns = ",".join(str(p) for p in patterns) if patterns else None
    elif isinstance(patterns, str):
        patterns = patterns or None
    else:
        patterns = None

    # Fund data (single_analyser nests it in fund_data dict)
    fund = r.get("fund_data", {}) if isinstance(r.get("fund_data"), dict) else {}

    return (
        run_id,
        analysis_date,
        source,
        # Identity
        str(r.get("symbol", "")),
        r.get("sector"),
        price,
        # Signal
        signal,
        signal_num,
        _safe(r.get("confidence")),
        # Composite
        _safe(r.get("composite")),
        _safe(r.get("pa_score")),
        _safe(r.get("mom_score")),
        _safe(r.get("vol_score")),
        _safe(r.get("sect_score")),
        _safe(r.get("risk_score")),
        _safe(r.get("momentum_score")),
        _safe(r.get("fund_score")),
        # MAs
        _safe(r.get("sma5")),
        _safe(r.get("sma10")),
        _safe(r.get("sma20")),
        _safe(r.get("sma50")),
        _safe(r.get("sma200")),
        _pct_vs(price, r.get("sma20")),
        _pct_vs(price, r.get("sma50")),
        _pct_vs(price, r.get("sma200")),
        r.get("cross"),
        # RSI
        _safe(r.get("rsi")),
        # MACD
        _safe(r.get("macd_val")),
        _safe(r.get("macd_hist")),
        _safe_bool(r.get("macd_just_bullish")),
        _safe_bool(r.get("macd_just_bearish")),
        # Stochastic
        _safe(r.get("stoch_k")),
        _safe(r.get("stoch_d")),
        # BB
        _safe(r.get("bb_upper")),
        _safe(r.get("bb_middle")),
        _safe(r.get("bb_lower")),
        _safe(r.get("bb_pct")),
        _safe_bool(r.get("bb_squeeze")),
        _safe_bool(r.get("bb_breakout")),
        # Volatility
        _safe(r.get("atr")),
        _safe(r.get("vol_20d")),
        _safe(r.get("max_drawdown")),
        # Volume
        _safe(r.get("vol_ratio")),
        _safe(r.get("vol_avg")),
        r.get("obv_trend"),
        _safe_bool(r.get("vpt_bearish_div")),
        # Momentum
        _safe(r.get("roc_20")),
        _safe(r.get("roc_60")),
        # 52W
        _safe(r.get("hi52")),
        _safe(r.get("lo52")),
        _safe(r.get("high_prox")),
        _safe(r.get("range_pct")),
        # Pivots
        _extract_pivots(pivots, "P"),
        _extract_pivots(pivots, "R1"),
        _extract_pivots(pivots, "S1"),
        _extract_fib(fib, "fib_382"),
        _extract_fib(fib, "fib_500"),
        _extract_fib(fib, "fib_618"),
        _safe_bool(r.get("fib_618_broken")),
        # Patterns
        patterns,
        # Trade plan
        _safe(r.get("stop_loss")),
        _safe(r.get("target1")),
        _safe(r.get("target2")),
        _safe(r.get("rr_ratio")),
        _safe(r.get("position_size")),
        # Broker
        _safe(r.get("asym_score")),
        _safe(r.get("sell_dist_pct")),
        # Flags
        _safe_bool(r.get("circuit_flag")),
        _safe_bool(r.get("liquidity_flag")),
        _safe_bool(r.get("breakout_52w")),
        _safe_bool(r.get("breakout_candidate")),
        # Fundamentals
        _safe(r.get("pe") or fund.get("pe_ratio")),
        _safe(r.get("eps") or fund.get("eps")),
        _safe(r.get("roe") or fund.get("roe")),
        _safe(r.get("div_yield") or fund.get("div_yield")),
        # Single-analyser-only
        _safe(r.get("mfi")),
        _safe(r.get("vwap")),
        _safe(r.get("tech_score")),
        _safe(r.get("bt_score")),
        r.get("trend"),
        r.get("risk_level"),
        _safe(r.get("eps_growth")),
        r.get("broker_activity"),
        # Reasons
        r.get("reasons"),
        # Market context (denormalized from run for ML direct access)
        regime,
        _safe(regime_factor),
    )


# ═══════════════════════════════════════════════════════════════════════
#  INSERT SQL
# ═══════════════════════════════════════════════════════════════════════

_SNAPSHOT_SQL = """
INSERT INTO analysis_snapshots (
    run_id, analysis_date, source_type,
    symbol, sector, price,
    `signal`, signal_numeric, confidence,
    composite, pa_score, mom_score, vol_score, sect_score, risk_score,
    momentum_score, fund_score,
    sma5, sma10, sma20, sma50, sma200,
    price_vs_sma20_pct, price_vs_sma50_pct, price_vs_sma200_pct, ma_cross,
    rsi,
    macd_val, macd_hist, macd_just_bullish, macd_just_bearish,
    stoch_k, stoch_d,
    bb_upper, bb_middle, bb_lower, bb_pct, bb_squeeze, bb_breakout,
    atr, vol_20d, max_drawdown,
    vol_ratio, vol_avg, obv_trend, vpt_bearish_div,
    roc_20, roc_60,
    hi52, lo52, high_prox, range_pct,
    pivot_p, pivot_r1, pivot_s1,
    fib_382, fib_500, fib_618, fib_618_broken,
    patterns,
    stop_loss, target1, target2, rr_ratio, position_size,
    asym_score, sell_dist_pct,
    circuit_flag, liquidity_flag, breakout_52w, breakout_candidate,
    pe, eps, roe, div_yield,
    mfi, vwap, tech_score, bt_score, trend, risk_level, eps_growth,
    broker_activity,
    reasons,
    market_regime, regime_factor
) VALUES (
    %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s,
    %s,
    %s, %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s,
    %s,
    %s,
    %s, %s
)
ON DUPLICATE KEY UPDATE
    price             = VALUES(price),
    `signal`          = VALUES(`signal`),
    signal_numeric    = VALUES(signal_numeric),
    confidence        = VALUES(confidence),
    composite         = VALUES(composite),
    pa_score          = VALUES(pa_score),
    mom_score         = VALUES(mom_score),
    vol_score         = VALUES(vol_score),
    sect_score        = VALUES(sect_score),
    risk_score        = VALUES(risk_score),
    momentum_score    = VALUES(momentum_score),
    fund_score        = VALUES(fund_score),
    sma5              = VALUES(sma5),
    sma10             = VALUES(sma10),
    sma20             = VALUES(sma20),
    sma50             = VALUES(sma50),
    sma200            = VALUES(sma200),
    price_vs_sma20_pct  = VALUES(price_vs_sma20_pct),
    price_vs_sma50_pct  = VALUES(price_vs_sma50_pct),
    price_vs_sma200_pct = VALUES(price_vs_sma200_pct),
    ma_cross          = VALUES(ma_cross),
    rsi               = VALUES(rsi),
    macd_val          = VALUES(macd_val),
    macd_hist         = VALUES(macd_hist),
    macd_just_bullish = VALUES(macd_just_bullish),
    macd_just_bearish = VALUES(macd_just_bearish),
    stoch_k           = VALUES(stoch_k),
    stoch_d           = VALUES(stoch_d),
    bb_upper          = VALUES(bb_upper),
    bb_middle         = VALUES(bb_middle),
    bb_lower          = VALUES(bb_lower),
    bb_pct            = VALUES(bb_pct),
    bb_squeeze        = VALUES(bb_squeeze),
    bb_breakout       = VALUES(bb_breakout),
    atr               = VALUES(atr),
    vol_20d           = VALUES(vol_20d),
    max_drawdown      = VALUES(max_drawdown),
    vol_ratio         = VALUES(vol_ratio),
    vol_avg           = VALUES(vol_avg),
    obv_trend         = VALUES(obv_trend),
    vpt_bearish_div   = VALUES(vpt_bearish_div),
    roc_20            = VALUES(roc_20),
    roc_60            = VALUES(roc_60),
    hi52              = VALUES(hi52),
    lo52              = VALUES(lo52),
    high_prox         = VALUES(high_prox),
    range_pct         = VALUES(range_pct),
    pivot_p           = VALUES(pivot_p),
    pivot_r1          = VALUES(pivot_r1),
    pivot_s1          = VALUES(pivot_s1),
    fib_382           = VALUES(fib_382),
    fib_500           = VALUES(fib_500),
    fib_618           = VALUES(fib_618),
    fib_618_broken    = VALUES(fib_618_broken),
    patterns          = VALUES(patterns),
    stop_loss         = VALUES(stop_loss),
    target1           = VALUES(target1),
    target2           = VALUES(target2),
    rr_ratio          = VALUES(rr_ratio),
    position_size     = VALUES(position_size),
    asym_score        = VALUES(asym_score),
    sell_dist_pct     = VALUES(sell_dist_pct),
    circuit_flag      = VALUES(circuit_flag),
    liquidity_flag    = VALUES(liquidity_flag),
    breakout_52w      = VALUES(breakout_52w),
    breakout_candidate = VALUES(breakout_candidate),
    pe                = VALUES(pe),
    eps               = VALUES(eps),
    roe               = VALUES(roe),
    div_yield         = VALUES(div_yield),
    mfi               = VALUES(mfi),
    vwap              = VALUES(vwap),
    tech_score        = VALUES(tech_score),
    bt_score          = VALUES(bt_score),
    trend             = VALUES(trend),
    risk_level        = VALUES(risk_level),
    eps_growth        = VALUES(eps_growth),
    broker_activity   = VALUES(broker_activity),
    reasons           = VALUES(reasons),
    market_regime     = VALUES(market_regime),
    regime_factor     = VALUES(regime_factor)
"""

_RUN_SQL = """
INSERT INTO analysis_runs
    (run_timestamp, analysis_date, run_type, symbol, total_symbols,
     report_path, duration_seconds, market_regime, regime_factor,
     floorsheet_days, status)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_WATCHLIST_SQL = """
INSERT INTO watchlist_snapshots
    (run_id, analysis_date, symbol, rank_in_watchlist,
     composite_score, `signal`, confidence, rr_ratio,
     price, stop_loss, target1, target2,
     entry_zone_low, entry_zone_high, atr)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    rank_in_watchlist  = VALUES(rank_in_watchlist),
    composite_score    = VALUES(composite_score),
    `signal`           = VALUES(`signal`),
    confidence         = VALUES(confidence),
    rr_ratio           = VALUES(rr_ratio),
    price              = VALUES(price),
    stop_loss          = VALUES(stop_loss),
    target1            = VALUES(target1),
    target2            = VALUES(target2),
    entry_zone_low     = VALUES(entry_zone_low),
    entry_zone_high    = VALUES(entry_zone_high),
    atr                = VALUES(atr)
"""

_BOOM_SQL = """
INSERT INTO boom_stock_snapshots
    (run_id, analysis_date, symbol, asym_score, vol_ratio,
     rsi, price, `signal`, confidence, floorsheet_days)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    asym_score      = VALUES(asym_score),
    vol_ratio       = VALUES(vol_ratio),
    rsi             = VALUES(rsi),
    price           = VALUES(price),
    `signal`        = VALUES(`signal`),
    confidence      = VALUES(confidence),
    floorsheet_days = VALUES(floorsheet_days)
"""


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API — save_full_analysis
# ═══════════════════════════════════════════════════════════════════════

def save_full_analysis(data: dict, report_path: str = None,
                       elapsed: float = None) -> int | None:
    """
    Persist a full analysor run (all symbols) into nepsego_analysis.

    Args:
        data:        The dict returned by run_full_analysis()
        report_path: File path of the generated HTML report
        elapsed:     Total analysis time in seconds

    Returns:
        The run_id on success, None on failure.
    """
    try:
        ensure_database()

        all_analysis = data.get("all_analysis", {})
        if not all_analysis:
            print("  ⚠️  analysor_stores: No analysis data to store")
            return None

        analysis_date = _detect_analysis_date()
        regime = data.get("regime", {})

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # ── 1. Insert run ──
                cur.execute(_RUN_SQL, (
                    datetime.now(),
                    analysis_date,
                    "full",
                    None,                               # no single symbol
                    len(all_analysis),
                    report_path,
                    round(elapsed, 2) if elapsed else None,
                    regime.get("regime"),
                    _safe(regime.get("factor")),
                    data.get("floorsheet_days"),
                    "completed",
                ))
                run_id = cur.lastrowid

                # ── 2. Bulk-insert snapshots ──
                rows = []
                for sym, r in all_analysis.items():
                    if not isinstance(r, dict):
                        continue
                    rows.append(
                        _build_snapshot_row(r, run_id, analysis_date, "analysor",
                                           regime=regime.get("regime"),
                                           regime_factor=regime.get("factor"))
                    )

                if rows:
                    cur.executemany(_SNAPSHOT_SQL, rows)

                # ── 3. Watchlist snapshots ──
                wl = data.get("watchlist", [])
                wl_rows = []
                for rank, w in enumerate(wl, 1):
                    sym = w.get("symbol", "")
                    price_w = _safe(w.get("price"))
                    atr_w = _safe(w.get("atr"))
                    # Entry zone: price ± 0.5 × ATR  (mirrors html_extractor.py L481)
                    if price_w and atr_w and atr_w > 0:
                        ez_lo = round(price_w - 0.5 * atr_w, 2)
                        ez_hi = round(price_w + 0.5 * atr_w, 2)
                    elif price_w:
                        ez_lo = round(price_w * 0.995, 2)
                        ez_hi = round(price_w * 1.005, 2)
                    else:
                        ez_lo = ez_hi = None
                    wl_rows.append((
                        run_id, analysis_date, sym, rank,
                        _safe(w.get("composite")),
                        w.get("signal"),
                        _safe(w.get("confidence")),
                        _safe(w.get("rr_ratio")),
                        price_w,
                        _safe(w.get("stop_loss")),
                        _safe(w.get("target1")),
                        _safe(w.get("target2")),
                        ez_lo,
                        ez_hi,
                        atr_w,
                    ))
                if wl_rows:
                    cur.executemany(_WATCHLIST_SQL, wl_rows)

                # ── 4. Boom stock snapshots ──
                boom = data.get("boom_stocks", [])
                fl_days = data.get("floorsheet_days")  # same value as stored in run
                boom_rows = []
                for b in boom:
                    sym = b.get("symbol", "")
                    # Look up full analysis for extra fields
                    full = all_analysis.get(sym, {})
                    boom_rows.append((
                        run_id, analysis_date, sym,
                        _safe(b.get("asym_score") or full.get("asym_score")),
                        _safe(b.get("vol_ratio") or full.get("vol_ratio")),
                        _safe(b.get("rsi") or full.get("rsi")),
                        _safe(b.get("price") or full.get("price")),
                        full.get("signal"),
                        _safe(full.get("confidence")),
                        fl_days,
                    ))
                if boom_rows:
                    cur.executemany(_BOOM_SQL, boom_rows)

            conn.commit()

            print(f"  💾 Stored {len(rows)} snapshots + "
                  f"{len(wl_rows)} watchlist + {len(boom_rows)} boom → "
                  f"nepsego_analysis (run #{run_id})")
            return run_id

        finally:
            conn.close()

    except Exception as e:
        print(f"  ⚠️  analysor_stores: DB save failed (non-fatal): {e}")
        traceback.print_exc()
        return None


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API — save_single_analysis
# ═══════════════════════════════════════════════════════════════════════

def save_single_analysis(symbol: str, data: dict,
                         report_path: str = None,
                         elapsed: float = None) -> int | None:
    """
    Persist a single-stock analysis into nepsego_analysis.

    Args:
        symbol:      The stock symbol (e.g., 'NABIL')
        data:        The dict returned by analyze_single_stock()
        report_path: File path of the generated HTML report
        elapsed:     Total analysis time in seconds

    Returns:
        The run_id on success, None on failure.
    """
    if data is None:
        return None

    try:
        ensure_database()

        analysis_date = _detect_analysis_date()

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # ── 1. Insert run ──
                cur.execute(_RUN_SQL, (
                    datetime.now(),
                    analysis_date,
                    "single",
                    symbol,
                    1,
                    report_path,
                    round(elapsed, 2) if elapsed else None,
                    None,      # no market regime for single
                    None,
                    None,      # no floorsheet_days for single
                    "completed",
                ))
                run_id = cur.lastrowid

                # ── 2. Insert snapshot ──
                row = _build_snapshot_row(
                    data, run_id, analysis_date, "single_analyser"
                )
                cur.execute(_SNAPSHOT_SQL, row)

            conn.commit()

            sig = data.get("signal", "HOLD")
            score = _safe(data.get("composite"), 0)
            print(f"  💾 Stored {symbol} ({sig}, score={score:.1f}) → "
                  f"nepsego_analysis (run #{run_id})")
            return run_id

        finally:
            conn.close()

    except Exception as e:
        print(f"  ⚠️  analysor_stores: DB save failed (non-fatal): {e}")
        traceback.print_exc()
        return None


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API — save_batch_single_analysis
# ═══════════════════════════════════════════════════════════════════════

def save_batch_single_analysis(all_data: list[dict],
                               report_path: str = None,
                               elapsed: float = None) -> int | None:
    """
    Persist a batch of single-stock analyses (--all mode) into nepsego_analysis.

    Args:
        all_data:    List of dicts returned by analyze_single_stock() for each symbol
        report_path: File path of the combined HTML report
        elapsed:     Total analysis time in seconds

    Returns:
        The run_id on success, None on failure.
    """
    if not all_data:
        return None

    try:
        ensure_database()

        analysis_date = _detect_analysis_date()

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # ── 1. Insert run ──
                cur.execute(_RUN_SQL, (
                    datetime.now(),
                    analysis_date,
                    "batch_single",
                    None,
                    len(all_data),
                    report_path,
                    round(elapsed, 2) if elapsed else None,
                    None,
                    None,
                    None,      # no floorsheet_days for batch_single
                    "completed",
                ))
                run_id = cur.lastrowid

                # ── 2. Bulk-insert snapshots ──
                rows = []
                for r in all_data:
                    if not isinstance(r, dict):
                        continue
                    rows.append(
                        _build_snapshot_row(
                            r, run_id, analysis_date, "single_analyser"
                        )
                    )

                if rows:
                    cur.executemany(_SNAPSHOT_SQL, rows)

            conn.commit()

            print(f"  💾 Stored {len(rows)} single-analyser snapshots → "
                  f"nepsego_analysis (run #{run_id})")
            return run_id

        finally:
            conn.close()

    except Exception as e:
        print(f"  ⚠️  analysor_stores: DB save failed (non-fatal): {e}")
        traceback.print_exc()
        return None
