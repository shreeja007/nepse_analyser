"""
NEPSE Stock Analytics Report Generator — v2.0 (Audited & Improved)
Applies all 14 fixes from the Code Audit & Improvement Plan.

Fix summary:
 1  Corporate action price adjustment (adjusted closes)
 2  RSI / technical minimum data threshold raised to 100 bars
 3  EMA seeded with SMA of first `period` values (not values[0])
 4  Batch OHLCV fetch — eliminates N+1 query pattern
 5  Broker concentration microstructure score integrated into strong_picks
 6  ATR + support/resistance levels added to technical_signals
 7  Stochastic Oscillator (%K/%D) added to momentum_analysis
 8  On-Balance Volume (OBV) trend added to momentum_analysis
 9  Market-wide regime (BULLISH/NEUTRAL/BEARISH) affects composite score
10  52-week breakout detection in technical_signals
11  Seasonality factor (Ashad/Shrawan bonus) applied to composite score
12  Fundamental recency fixed: ORDER BY fiscal_year DESC, quarter DESC
13  Continuous tech score replaces coarse 3-value mapping
14  Dividend yield & ROE added to fundamental_analysis
"""

import os, sys, math, json
from datetime import datetime, timedelta
from collections import defaultdict
import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_CFG = {
    "host":     os.getenv("DB_HOST", "127.0.0.1"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "db":       os.getenv("DB_DATABASE", "nepsego"),
    "user":     os.getenv("DB_USERNAME", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "charset":  "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

def get_conn():
    return pymysql.connect(**DB_CFG)

def q(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()

def qone(conn, sql, params=None):
    rows = q(conn, sql, params)
    return rows[0] if rows else {}

# ═══════════════════════════════════════════════════════════════════════
#  BATCH DATA FETCHERS  (Issue 4 — eliminates N+1 query pattern)
# ═══════════════════════════════════════════════════════════════════════

def fetch_all_ohlcv(conn):
    """Single query for ALL symbols.  Returns dict: symbol → [candles ASC]."""
    print("  [pre] Batch-fetching OHLCV data...")
    rows = q(conn, """
        SELECT symbol, trading_date, open_price, high_price, low_price,
               close_price, volume
        FROM daily_ohlcv
        WHERE close_price > 0 AND close_price IS NOT NULL
        ORDER BY symbol, trading_date ASC
    """)
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)

def fetch_all_corp_actions(conn):
    """Returns dict: symbol → [actions]."""
    rows = q(conn, """
        SELECT symbol, action_type, ratio, book_close_date
        FROM corporate_actions
        ORDER BY book_close_date ASC
    """)
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)

def fetch_all_dividends(conn):
    """Returns dict: symbol → [dividends ASC by book_close_date]."""
    rows = q(conn, """
        SELECT symbol, bonus_share_percent, cash_dividend_percent, book_close_date
        FROM dividends
        ORDER BY book_close_date ASC
    """)
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)

def fetch_all_company_details(conn):
    """Returns dict: symbol → company_details row."""
    rows = q(conn, """
        SELECT symbol, fifty_two_week_high, fifty_two_week_low,
               market_capitalization, stock_listed_shares
        FROM company_details
    """)
    return {r["symbol"]: r for r in rows}

# ═══════════════════════════════════════════════════════════════════════
#  PRICE ADJUSTMENT  (Issue 1)
# ═══════════════════════════════════════════════════════════════════════

def _is_dup_adjustment(adjustments, bcd, factor, day_window=45):
    """Round-2 fix: date-proximity de-duplication.
    Two adjustments are considered duplicates if they fall within `day_window`
    days of each other AND have similar factors.  This is more robust than
    exact date match because the same corporate event can be recorded with
    slightly different book_close_dates in the dividends vs corporate_actions
    tables."""
    try:
        bcd_dt = datetime.strptime(str(bcd)[:10], "%Y-%m-%d")
    except ValueError:
        # Fallback: exact match only
        return any(a[0] == bcd and abs(a[1] - factor) < 0.02 for a in adjustments)
    for a_date, a_factor in adjustments:
        try:
            a_dt = datetime.strptime(str(a_date)[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if abs((bcd_dt - a_dt).days) <= day_window and abs(a_factor - factor) < 0.02:
            return True
    return False


def get_adjusted_series(candles, corp_actions, dividends):
    """
    Backward-adjust an OHLCV candle list for corporate actions and dividends.

    Adjustment factors (applied to all prices BEFORE the event date):
      Cash dividend:  factor = (P_cum − DPS) / P_cum   where DPS = cash_div_pct (face=100)
      Bonus share:    factor = 1 / (1 + bonus_ratio)   where bonus_ratio = bonus_pct / 100
      Rights issue:   factor = TERP / P_cum             (Section 2.2.3 of research paper)
    """
    if not candles:
        return candles

    adjustments = []   # list of (event_date_str, factor)

    # ── from dividends table ──
    for div in dividends:
        bcd = str(div.get("book_close_date") or "")
        if not bcd:
            continue
        bonus = float(div.get("bonus_share_percent") or 0)
        cash  = float(div.get("cash_dividend_percent") or 0)

        if bonus > 0:
            bonus_ratio = bonus / 100.0
            factor = 1.0 / (1.0 + bonus_ratio)
            adjustments.append((bcd, factor))

        if cash > 0:
            # Find the cum-price: last close strictly before book_close_date
            cum_price = None
            for c in candles:
                if str(c["trading_date"]) < bcd:
                    cum_price = float(c["close_price"])
                else:
                    break
            if cum_price and cum_price > 0:
                dps = cash   # face value = 100 → DPS = cash_div_pct rupees
                factor = (cum_price - dps) / cum_price
                if 0 < factor < 1:
                    adjustments.append((bcd, factor))

    # ── from corporate_actions table ──
    # Round-2 fix (Issues 1 & 2):
    #  - Rights issues now use TERP formula (Section 2.2.3 of research paper)
    #    instead of bonus formula 1/(1+r).  The bonus formula assumes free shares;
    #    rights involve a subscription at par value (Rs 100), so the correct
    #    adjustment is factor = TERP / P_cum where
    #    TERP = (P_cum + R_sub × ratio) / (1 + ratio).
    #  - Bonus entries in corporate_actions stored as "X%" were silently skipped
    #    because the code only parsed "X:Y" format.  Now both formats are handled.
    #  - De-duplication now uses date proximity (±45 days) instead of exact date
    #    match, because the same event can have different book_close_dates in
    #    the dividends vs corporate_actions tables.
    for action in corp_actions:
        bcd = str(action.get("book_close_date") or "")
        if not bcd:
            continue
        atype = (action.get("action_type") or "").lower()
        ratio_str = (action.get("ratio") or "").strip()

        if "right" in atype:
            # ── Rights issue: TERP formula (Section 2.2.3) ──
            try:
                parts = ratio_str.split(":")
                if len(parts) == 2:
                    rights_shares = float(parts[0])
                    base_shares   = float(parts[1])
                    rights_ratio  = rights_shares / base_shares
                    # Need cum-price (last close before book_close_date)
                    cum_price = None
                    for c in candles:
                        if str(c["trading_date"]) < bcd:
                            cum_price = float(c["close_price"])
                        else:
                            break
                    if cum_price and cum_price > 0:
                        sub_price = 100.0   # NEPSE par value
                        terp = (cum_price + sub_price * rights_ratio) / (1.0 + rights_ratio)
                        factor = terp / cum_price
                        if 0 < factor < 1:
                            if not _is_dup_adjustment(adjustments, bcd, factor):
                                adjustments.append((bcd, factor))
            except (ValueError, ZeroDivisionError):
                pass

        elif "bonus" in atype or "split" in atype:
            # ── Bonus / Split: factor = 1/(1+ratio) ──
            try:
                factor = None
                if ":" in ratio_str:
                    parts = ratio_str.split(":")
                    if len(parts) == 2:
                        bonus_ratio = float(parts[0]) / float(parts[1])
                        factor = 1.0 / (1.0 + bonus_ratio)
                elif ratio_str.endswith("%"):
                    pct = float(ratio_str.rstrip("%"))
                    if pct > 0:
                        factor = 1.0 / (1.0 + pct / 100.0)
                if factor is not None and 0 < factor < 1:
                    if not _is_dup_adjustment(adjustments, bcd, factor):
                        adjustments.append((bcd, factor))
            except (ValueError, ZeroDivisionError):
                pass

    if not adjustments:
        return candles

    # ── backward pass: multiply all prices BEFORE each event date ──
    adjustments.sort(key=lambda x: x[0])   # ascending so inner loop can break early

    # Build mutable price arrays
    dates  = [str(c["trading_date"]) for c in candles]
    closes = [float(c["close_price"])                           for c in candles]
    opens  = [float(c.get("open_price")  or c["close_price"])  for c in candles]
    highs  = [float(c.get("high_price")  or c["close_price"])  for c in candles]
    lows   = [float(c.get("low_price")   or c["close_price"])  for c in candles]

    for event_date, factor in adjustments:
        for i, d in enumerate(dates):
            if d < event_date:
                closes[i] *= factor
                opens[i]  *= factor
                highs[i]  *= factor
                lows[i]   *= factor

    adj = []
    for i, c in enumerate(candles):
        row = dict(c)
        row["close_price"] = closes[i]
        row["open_price"]  = opens[i]
        row["high_price"]  = highs[i]
        row["low_price"]   = lows[i]
        adj.append(row)
    return adj

# ═══════════════════════════════════════════════════════════════════════
#  INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════

def calc_rsi(closes, period=14):
    """Wilder's RSI. Requires Issue 2 threshold (≥100 bars) already enforced upstream."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 2)


def calc_ema(values, period):
    """
    Issue 3 fix: seed with SMA of first `period` values, then apply EMA.
    Returns a list of length  max(0, len(values) - period + 1).
    """
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    ema = [seed]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_macd(closes):
    """
    Returns (macd_val, signal_val, histogram, macd_line_series).
    All None/[] if insufficient data.
    """
    ema12 = calc_ema(closes, 12)   # length = n - 11
    ema26 = calc_ema(closes, 26)   # length = n - 25
    if len(ema12) < 15 or not ema26:
        return None, None, None, []
    # Align: ema12 starts at closes[11], ema26 at closes[25]
    # Offset = 26 - 12 = 14  → ema12[14:] aligns with ema26
    macd_line = [ema12[14 + i] - ema26[i] for i in range(len(ema26))]
    signal_line = calc_ema(macd_line, 9)
    if not signal_line:
        return macd_line[-1], None, None, macd_line
    macd_val  = macd_line[-1]
    sig_val   = signal_line[-1]
    histogram = macd_val - sig_val
    return (round(macd_val, 2), round(sig_val, 2),
            round(histogram, 2), macd_line)


def calc_atr(candles, period=14):
    """Issue 6: Average True Range via Wilder smoothing."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        hi  = float(candles[i]["high_price"])
        lo  = float(candles[i]["low_price"])
        pc  = float(candles[i - 1]["close_price"])
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 2)


def calc_stochastic(candles, k_period=14, d_period=3):
    """Issue 7: Stochastic Oscillator %K and %D."""
    if len(candles) < k_period:
        return None, None
    k_vals = []
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1: i + 1]
        highest = max(float(c["high_price"])  for c in window)
        lowest  = min(float(c["low_price"])   for c in window)
        close   = float(candles[i]["close_price"])
        if highest != lowest:
            k_vals.append((close - lowest) / (highest - lowest) * 100)
        else:
            k_vals.append(50.0)
    stoch_k = round(k_vals[-1], 1)
    stoch_d = round(sum(k_vals[-d_period:]) / min(len(k_vals), d_period), 1)
    return stoch_k, stoch_d


def calc_obv_trend(closes, volumes, lookback=10):
    """Issue 8: OBV slope direction over last `lookback` sessions."""
    if len(closes) < 2:
        return "FLAT"
    obv, obv_series = 0, [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
        obv_series.append(obv)
    if len(obv_series) >= lookback:
        slope = obv_series[-1] - obv_series[-lookback]
        if slope > 0:   return "RISING"
        if slope < 0:   return "FALLING"
    return "FLAT"

# ═══════════════════════════════════════════════════════════════════════
#  MARKET CONTEXT  (Issues 9 & 11)
# ═══════════════════════════════════════════════════════════════════════

def get_market_regime(conn):
    """Issue 9: Classify NEPSE as BULLISH / NEUTRAL / BEARISH."""
    idx = qone(conn, """
        SELECT change_percent FROM market_indices
        WHERE index_name = 'NEPSE'
        ORDER BY date DESC LIMIT 1
    """)
    chg = float(idx.get("change_percent") or 0)
    if chg > 1.0:
        return {"regime": "BULLISH",  "factor": 1.1,  "chg": chg}
    if chg < -1.0:
        return {"regime": "BEARISH",  "factor": 0.9,  "chg": chg}
    return {"regime": "NEUTRAL",  "factor": 1.0,  "chg": chg}


def seasonality_bonus():
    """Issue 11: +5 points during Ashad/Shrawan (≈ June–July) bullish window."""
    return 5 if datetime.now().month in (6, 7) else 0

# ═══════════════════════════════════════════════════════════════════════
#  BROKER CONCENTRATION  (Issue 5)
# ═══════════════════════════════════════════════════════════════════════

def calc_broker_concentration(conn):
    """
    Round-2 fix (Issue 5 — microstructure signal):
    The original function measured only buy-side broker concentration (top-3
    buyers' share of total buy volume).  But in any matched order book, total
    buy volume == total sell volume for every symbol.  High buy-side
    concentration alone doesn't distinguish accumulation from distribution.

    Per Section 5 of the research paper, the informative signal is the
    ASYMMETRY between buy-side and sell-side concentration:
      - High buy concentration + low sell concentration = accumulation
        (few institutions absorbing many small sellers — bullish)
      - High sell concentration + low buy concentration = distribution
        (institutions offloading to many small buyers — bearish)

    The score is normalised to 0–100 with 50 = neutral (symmetric),
    >50 = net accumulation, <50 = net distribution.
    """
    print("  [pre] Computing broker concentration (buy/sell asymmetry)...")

    # ── Buy-side: top-3 buyers' share of total buy amount per symbol ──
    buy_total_rows = q(conn, """
        SELECT symbol, SUM(amount) AS total_buy
        FROM floorsheet_transactions
        WHERE trading_date >= DATE_SUB(
            (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 30 DAY)
        GROUP BY symbol
    """)
    buy_total_map = {r["symbol"]: float(r["total_buy"] or 0) for r in buy_total_rows}

    buy_broker_rows = q(conn, """
        SELECT symbol, buyer_broker_id, SUM(amount) AS buy_amt
        FROM floorsheet_transactions
        WHERE trading_date >= DATE_SUB(
            (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 30 DAY)
        GROUP BY symbol, buyer_broker_id
    """)
    sym_buy = defaultdict(list)
    for r in buy_broker_rows:
        sym_buy[r["symbol"]].append(float(r["buy_amt"] or 0))

    # ── Sell-side: top-3 sellers' share of total sell amount per symbol ──
    sell_broker_rows = q(conn, """
        SELECT symbol, seller_broker_id, SUM(amount) AS sell_amt
        FROM floorsheet_transactions
        WHERE trading_date >= DATE_SUB(
            (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 30 DAY)
        GROUP BY symbol, seller_broker_id
    """)
    sym_sell = defaultdict(list)
    for r in sell_broker_rows:
        sym_sell[r["symbol"]].append(float(r["sell_amt"] or 0))

    # ── Compute asymmetry score per symbol ──
    scores = {}
    all_syms = set(sym_buy) | set(sym_sell)
    for sym in all_syms:
        total = buy_total_map.get(sym, 0)
        if total <= 0:
            scores[sym] = 50       # neutral if no data
            continue

        buy_amts = sorted(sym_buy.get(sym, []), reverse=True)
        buy_conc = sum(buy_amts[:3]) / total * 100 if buy_amts else 0

        sell_amts = sorted(sym_sell.get(sym, []), reverse=True)
        sell_conc = sum(sell_amts[:3]) / total * 100 if sell_amts else 0

        # Asymmetry: positive = accumulation (buy concentrated, sell dispersed)
        #            negative = distribution (sell concentrated, buy dispersed)
        raw_asym = buy_conc - sell_conc          # range roughly −100 to +100

        # Normalise to 0–100 with 50 = neutral
        scores[sym] = max(0, min(100, round(50 + raw_asym / 2, 1)))

    return scores

# ═══════════════════════════════════════════════════════════════════════
#  1. MARKET OVERVIEW
# ═══════════════════════════════════════════════════════════════════════

def market_overview(conn):
    print("  [1/12] Market Overview...")
    summary = qone(conn, "SELECT * FROM market_summary ORDER BY trading_date DESC LIMIT 1")
    indices = q(conn, "SELECT * FROM market_indices ORDER BY date DESC, index_name")
    latest_date = None
    if indices:
        latest_date = indices[0].get("date")
        indices = [i for i in indices if i.get("date") == latest_date]
    subs = q(conn, "SELECT * FROM nepse_sub_indices ORDER BY percent_change DESC")
    return {"summary": summary, "indices": indices, "sub_indices": subs, "date": latest_date}

# ═══════════════════════════════════════════════════════════════════════
#  2. MOMENTUM ANALYSIS  (Issues 1, 2, 3, 4, 7, 8)
# ═══════════════════════════════════════════════════════════════════════

def momentum_analysis(all_ohlcv, all_corps, all_divs):
    print("  [2/12] Momentum Analysis...")
    results = []
    for sym, raw_candles in all_ohlcv.items():
        # Issue 1: adjust prices
        candles = get_adjusted_series(
            raw_candles,
            all_corps.get(sym, []),
            all_divs.get(sym, [])
        )
        # Issue 2: minimum 100 bars
        if len(candles) < 100:
            continue

        closes  = [float(c["close_price"]) for c in candles]
        volumes = [int(c["volume"] or 0)    for c in candles]

        rsi = calc_rsi(closes)

        # Issue 3: fixed EMA → MACD
        macd_val, sig_val, macd_hist, _ = calc_macd(closes)

        price    = closes[-1]
        price_5d  = closes[-6]  if len(closes) >= 6  else closes[0]
        price_20d = closes[-21] if len(closes) >= 21 else closes[0]
        roc_5  = round((price - price_5d)  / price_5d  * 100, 2) if price_5d  else 0
        roc_20 = round((price - price_20d) / price_20d * 100, 2) if price_20d else 0

        vol_avg   = sum(volumes[-20:]) / min(len(volumes), 20) if volumes else 0
        vol_ratio = round(volumes[-1] / vol_avg, 2) if vol_avg > 0 else 0

        # Issue 7: Stochastic
        stoch_k, stoch_d = calc_stochastic(candles)

        # Issue 8: OBV
        obv_trend = calc_obv_trend(closes, volumes)

        # Momentum score — 5 equal components (20% each) + OBV bonus
        rsi_score   = min(max((rsi or 50) - 30, 0), 40) / 40 * 20
        stoch_score = min(max((stoch_k or 50) - 20, 0), 60) / 60 * 20
        roc5_score  = min(max(roc_5,  -10), 10) / 10 * 20
        roc20_score = min(max(roc_20, -20), 20) / 20 * 20
        vol_score   = min(max(vol_ratio - 0.5, 0), 2) / 2 * 20
        obv_bonus   = 5 if obv_trend == "RISING" else (-5 if obv_trend == "FALLING" else 0)
        mom_score   = min(100, max(0, round(
            rsi_score + stoch_score + roc5_score + roc20_score + vol_score + obv_bonus, 2)))

        results.append({
            "symbol": sym, "price": price, "rsi": rsi,
            "macd": macd_val, "macd_hist": macd_hist,
            "roc_5d": roc_5, "roc_20d": roc_20, "vol_ratio": vol_ratio,
            "stoch_k": stoch_k, "stoch_d": stoch_d,
            "obv_trend": obv_trend,
            "momentum_score": mom_score,
        })
    results.sort(key=lambda x: x["momentum_score"], reverse=True)
    return results

# ═══════════════════════════════════════════════════════════════════════
#  3. FUNDAMENTAL ANALYSIS  (Issues 12, 14)
# ═══════════════════════════════════════════════════════════════════════

def fundamental_analysis(conn):
    print("  [3/12] Fundamental Analysis...")

    # Round-2 fix (Issue 4 — recency):
    # The original query sorted by fiscal_year DESC, quarter DESC to find the
    # latest record.  fiscal_year (VARCHAR '2025-2026') sorts alphabetically OK,
    # but quarter (VARCHAR 'First Quar', 'Second Qua', etc.) does NOT:
    #   Alphabetical DESC: Third > Second > Fourth > First
    #   Chronological DESC: Fourth > Third > Second > First
    # So "Third Quarter" was chosen over "Fourth Quarter" — wrong.
    # Fix: use published_date (DATE column) which sorts chronologically by design.
    raw_rows = q(conn, """
        SELECT cf.symbol, cf.eps, cf.pe_ratio, cf.book_value, cf.net_profit,
               cf.fiscal_year, cf.quarter,
               cd.sector_name, cd.fifty_two_week_high, cd.fifty_two_week_low,
               cd.market_capitalization, cd.stock_listed_shares
        FROM company_fundamentals cf
        JOIN company_details cd ON cf.symbol = cd.symbol
        ORDER BY cf.symbol, cf.published_date DESC
    """)
    # Keep only the first (latest) row per symbol
    seen, rows = set(), []
    for r in raw_rows:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            rows.append(r)

    # Round-2 fix (Issue 4 — dividend recency):
    # Original used MAX(id) to pick the "latest" dividend, but IDs in this
    # dataset are NOT monotonically aligned with time (for NABIL, id=1 is the
    # most recent FY while id=5 is the oldest).  MAX(id) therefore returned the
    # OLDEST entry.  Fix: use MAX(book_close_date) which is a DATE column.
    div_rows = q(conn, """
        SELECT d.symbol, d.cash_dividend_percent
        FROM dividends d
        WHERE d.book_close_date = (
            SELECT MAX(d2.book_close_date) FROM dividends d2
            WHERE d2.symbol = d.symbol AND d2.cash_dividend_percent > 0
        )
    """)
    div_map = {r["symbol"]: float(r["cash_dividend_percent"] or 0) for r in div_rows}

    results = []
    for r in rows:
        eps   = float(r["eps"]          or 0)
        pe    = float(r["pe_ratio"]     or 0)
        bv    = float(r["book_value"]   or 0)
        mcap  = float(r["market_capitalization"] or 0)
        hi52  = float(r["fifty_two_week_high"]   or 0)
        lo52  = float(r["fifty_two_week_low"]    or 0)
        shares= float(r["stock_listed_shares"]   or 0)

        price_approx = eps * pe if eps and pe else 0
        pbv   = round(price_approx / bv, 2) if bv > 0 else None

        # Issue 14: ROE = EPS / Book Value * 100 (per-share equivalent)
        roe   = round(eps / bv * 100, 1) if bv > 0 and eps > 0 else 0

        # Issue 14: Dividend Yield — face value = Rs 100; DPS = cash_div_pct
        dps   = div_map.get(r["symbol"], 0)
        div_yield = round(dps / price_approx * 100, 2) if price_approx > 0 and dps > 0 else 0

        # Fundamental score
        score = 0
        if 0 < pe <= 15:    score += 25
        elif 15 < pe <= 25: score += 18
        elif 25 < pe <= 40: score += 10

        if eps > 30:        score += 20
        elif eps > 15:      score += 16
        elif eps > 5:       score += 12
        elif eps > 0:       score += 8

        if pbv and pbv < 1.5: score += 15
        elif pbv and pbv < 3: score += 8

        if lo52 > 0 and price_approx > 0 and hi52 != lo52:
            prox = (price_approx - lo52) / (hi52 - lo52) * 100
            if prox < 30:   score += 20
            elif prox < 50: score += 12

        # Issue 14: bonus for dividend yield & ROE
        if div_yield > 5:   score += 10
        elif div_yield > 2: score += 5
        if roe > 20:        score += 10
        elif roe > 10:      score += 5

        results.append({
            "symbol": r["symbol"], "sector": r["sector_name"],
            "eps": eps, "pe_ratio": pe, "book_value": bv, "pbv": pbv,
            "net_profit": float(r["net_profit"] or 0),
            "fiscal_year": r["fiscal_year"], "quarter": r["quarter"],
            "hi52": hi52, "lo52": lo52, "mcap": mcap,
            "roe": roe, "div_yield": div_yield,
            "fund_score": score,
        })
    results.sort(key=lambda x: x["fund_score"], reverse=True)
    return results

# ═══════════════════════════════════════════════════════════════════════
#  4. TECHNICAL SIGNALS  (Issues 1, 2, 3, 6, 10)
# ═══════════════════════════════════════════════════════════════════════

def technical_signals(all_ohlcv, all_corps, all_divs, all_company_details):
    print("  [4/12] Technical Signals...")
    results = []
    for sym, raw_candles in all_ohlcv.items():
        # Issue 1: price adjustment
        candles = get_adjusted_series(
            raw_candles,
            all_corps.get(sym, []),
            all_divs.get(sym, [])
        )
        # Issue 2: raise minimum to 100 bars
        if len(candles) < 100:
            continue

        closes  = [float(c["close_price"]) for c in candles]
        volumes = [int(c["volume"] or 0)    for c in candles]
        price   = closes[-1]

        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / 50
        std20 = (sum((c - sma20)**2 for c in closes[-20:]) / 20) ** 0.5
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        bb_pct   = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1) \
                   if bb_upper != bb_lower else 50

        det = all_company_details.get(sym, {})
        hi52 = float(det.get("fifty_two_week_high") or 0) or \
               (max(closes[-252:]) if len(closes) >= 252 else max(closes))
        lo52 = float(det.get("fifty_two_week_low")  or 0) or \
               (min(closes[-252:]) if len(closes) >= 252 else min(closes))
        range_pct = round((price - lo52) / (hi52 - lo52) * 100, 1) \
                    if hi52 != lo52 else 50

        # Moving average crossover
        prev_sma20 = sum(closes[-21:-1]) / 20 if len(closes) >= 21 else sma20
        prev_sma50 = sum(closes[-51:-1]) / 50 if len(closes) >= 51 else sma50
        if sma20 > sma50 and prev_sma20 <= prev_sma50:
            cross = "GOLDEN"
        elif sma20 < sma50 and prev_sma20 >= prev_sma50:
            cross = "DEATH"
        elif sma20 > sma50:
            cross = "BULLISH"
        else:
            cross = "BEARISH"

        signal = ("BUY"  if cross in ("GOLDEN", "BULLISH") and bb_pct < 40 else
                  "SELL" if cross in ("DEATH",  "BEARISH") and bb_pct > 80 else
                  "HOLD")

        # Issue 6: ATR + Support / Resistance
        atr = calc_atr(candles)
        if atr:
            support    = round(price - 1.5 * atr, 2)
            resistance = round(price + 1.5 * atr, 2)
        else:
            support = resistance = None

        # Issue 10: 52-week breakout detection
        vol_avg   = sum(volumes[-20:]) / min(len(volumes), 20) if volumes else 0
        vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 0
        if price >= hi52 and vol_ratio > 1.2:
            breakout = "52W_HIGH"
        elif price <= lo52:
            breakout = "52W_LOW"
        else:
            breakout = None

        results.append({
            "symbol": sym, "price": price,
            "sma20": round(sma20, 2), "sma50": round(sma50, 2),
            "bb_upper": round(bb_upper, 2), "bb_lower": round(bb_lower, 2),
            "bb_pct": bb_pct, "hi52": hi52, "lo52": lo52, "range_pct": range_pct,
            "cross": cross, "signal": signal,
            "atr": atr, "support": support, "resistance": resistance,
            "breakout": breakout,
        })
    results.sort(key=lambda x: 0 if x["signal"] == "BUY" else
                              (1 if x["signal"] == "HOLD" else 2))
    return results

# ═══════════════════════════════════════════════════════════════════════
#  5. SECTOR BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════

def sector_breakdown(conn):
    print("  [5/12] Sector Breakdown...")
    subs = q(conn, "SELECT * FROM nepse_sub_indices ORDER BY percent_change DESC")
    sector_data = q(conn, """
        SELECT sector, SUM(turnover) as total_turnover, SUM(volume) as total_volume,
               SUM(transaction_count) as total_txns, COUNT(*) as stock_count,
               AVG(percent_change) as avg_change
        FROM daily_trade_turnover_transaction_subindices
        WHERE sector IS NOT NULL
        GROUP BY sector ORDER BY total_turnover DESC
    """)
    return {"sub_indices": subs, "sectors": sector_data}

# ═══════════════════════════════════════════════════════════════════════
#  6. RISK OVERVIEW  (Issues 1, 4)
# ═══════════════════════════════════════════════════════════════════════

def risk_overview(all_ohlcv, all_corps, all_divs, all_company_details):
    print("  [6/12] Risk Overview...")
    results = []
    for sym, raw_candles in all_ohlcv.items():
        candles = get_adjusted_series(
            raw_candles,
            all_corps.get(sym, []),
            all_divs.get(sym, [])
        )
        if len(candles) < 20:
            continue
        closes  = [float(c["close_price"]) for c in candles]
        returns = [(closes[i] - closes[i-1]) / closes[i-1] * 100
                   for i in range(1, len(closes)) if closes[i-1] > 0]
        if len(returns) < 20:
            continue
        mu    = sum(returns[-20:]) / 20
        vol20 = round((sum((r - mu)**2 for r in returns[-20:]) / 20) ** 0.5, 2)

        peak, max_dd = closes[0], 0
        for c in closes:
            if c > peak: peak = c
            dd = (peak - c) / peak * 100
            if dd > max_dd: max_dd = dd

        det = all_company_details.get(sym, {})
        hi52 = float(det.get("fifty_two_week_high") or 0) or max(closes)
        lo52 = float(det.get("fifty_two_week_low")  or 0) or min(closes)
        rng  = round((hi52 - lo52) / lo52 * 100, 1) if lo52 > 0 else 0
        risk = "HIGH" if vol20 > 3 else ("MEDIUM" if vol20 > 1.5 else "LOW")

        results.append({
            "symbol": sym, "price": closes[-1], "volatility_20d": vol20,
            "max_drawdown": round(max_dd, 1), "range_52w": rng,
            "hi52": hi52, "lo52": lo52, "risk_level": risk,
        })
    results.sort(key=lambda x: x["volatility_20d"], reverse=True)
    return results

# ═══════════════════════════════════════════════════════════════════════
#  7–10.  UNCHANGED DATA FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def top_gainers_losers(conn):
    print("  [7/12] Top Gainers & Losers...")
    gainers = q(conn, """
        SELECT * FROM top_movers WHERE mover_type='gainer'
        AND trading_date = (SELECT MAX(trading_date) FROM top_movers)
        ORDER BY percent_change DESC LIMIT 20
    """)
    losers = q(conn, """
        SELECT * FROM top_movers WHERE mover_type='loser'
        AND trading_date = (SELECT MAX(trading_date) FROM top_movers)
        ORDER BY percent_change ASC LIMIT 20
    """)
    return {"gainers": gainers, "losers": losers}

def dividend_actions(conn):
    print("  [8/12] Dividends & Corporate Actions...")
    divs = q(conn, """
        SELECT d.*, cd.sector_name FROM dividends d
        LEFT JOIN company_details cd ON d.symbol = cd.symbol
        ORDER BY d.book_close_date DESC LIMIT 50
    """)
    actions = q(conn, """
        SELECT ca.*, cd.sector_name FROM corporate_actions ca
        LEFT JOIN company_details cd ON ca.symbol = cd.symbol
        ORDER BY ca.book_close_date DESC LIMIT 50
    """)
    return {"dividends": divs, "actions": actions}

def floorsheet_forensics(conn):
    print("  [9/12] Floorsheet Forensics...")
    top_buyers = q(conn, """
        SELECT buyer_broker_name as broker, COUNT(*) as trades,
               SUM(quantity) as total_qty, SUM(amount) as total_amt,
               COUNT(DISTINCT symbol) as symbols_traded
        FROM floorsheet_transactions
        WHERE trading_date = (SELECT MAX(trading_date) FROM floorsheet_transactions)
        GROUP BY buyer_broker_id, buyer_broker_name
        ORDER BY total_amt DESC LIMIT 15
    """)
    top_sellers = q(conn, """
        SELECT seller_broker_name as broker, COUNT(*) as trades,
               SUM(quantity) as total_qty, SUM(amount) as total_amt,
               COUNT(DISTINCT symbol) as symbols_traded
        FROM floorsheet_transactions
        WHERE trading_date = (SELECT MAX(trading_date) FROM floorsheet_transactions)
        GROUP BY seller_broker_id, seller_broker_name
        ORDER BY total_amt DESC LIMIT 15
    """)
    most_traded = q(conn, """
        SELECT symbol, COUNT(*) as trades, SUM(quantity) as total_qty,
               SUM(amount) as total_amt, MIN(rate) as min_rate,
               MAX(rate) as max_rate, AVG(rate) as avg_rate
        FROM floorsheet_transactions
        WHERE trading_date = (SELECT MAX(trading_date) FROM floorsheet_transactions)
        GROUP BY symbol ORDER BY total_amt DESC LIMIT 20
    """)
    return {"top_buyers": top_buyers, "top_sellers": top_sellers, "most_traded": most_traded}

def scrip_rankings(conn):
    print("  [10/12] Scrip Rankings...")
    by_trade = q(conn, """
        SELECT * FROM scrip_rankings
        WHERE category='trade'
          AND trading_date=(SELECT MAX(trading_date) FROM scrip_rankings)
        ORDER BY rank LIMIT 10
    """)
    by_turnover = q(conn, """
        SELECT * FROM scrip_rankings
        WHERE category='turnover'
          AND trading_date=(SELECT MAX(trading_date) FROM scrip_rankings)
        ORDER BY rank LIMIT 10
    """)
    by_txn = q(conn, """
        SELECT * FROM scrip_rankings
        WHERE category='transaction'
          AND trading_date=(SELECT MAX(trading_date) FROM scrip_rankings)
        ORDER BY rank LIMIT 10
    """)
    return {"by_trade": by_trade, "by_turnover": by_turnover, "by_transaction": by_txn}

# ═══════════════════════════════════════════════════════════════════════
#  11. STRONG BUY / SELL  (Issues 5, 9, 11, 13)
# ═══════════════════════════════════════════════════════════════════════

def strong_picks(momentum, fundamentals, technicals, risk_data,
                 broker_scores=None, market_factor=1.0, season_bonus=0):
    """
    Composite weights (v2):
      20% momentum + 25% fundamental + 20% technical + 15% risk
      + 10% microstructure + 10% market-context
    """
    print("  [11/12] Computing Strong Buy/Sell...")
    mom_map    = {r["symbol"]: r for r in momentum}
    fund_map   = {r["symbol"]: r for r in fundamentals}
    tech_map   = {r["symbol"]: r for r in technicals}
    risk_map   = {r["symbol"]: r for r in risk_data}
    broker_scores = broker_scores or {}
    all_syms   = set(mom_map) & set(fund_map) & set(tech_map)

    scored = []
    for sym in all_syms:
        m = mom_map[sym]
        f = fund_map[sym]
        t = tech_map[sym]
        r = risk_map.get(sym, {})

        ms = m.get("momentum_score", 0)
        fs = f.get("fund_score", 0)

        # Issue 13: Continuous tech score
        ts = 50.0
        sig   = t.get("signal", "HOLD")
        cross = t.get("cross", "")
        if sig   == "BUY":     ts += 15
        elif sig == "SELL":    ts -= 15
        if cross == "GOLDEN":  ts += 15
        elif cross == "DEATH": ts -= 15
        bb_pct    = t.get("bb_pct", 50)
        range_pct = t.get("range_pct", 50)
        ts += (50 - bb_pct) * 0.2          # lower BB% → more bullish → +bonus
        if range_pct < 30:    ts += 5      # near 52W low (value)
        elif range_pct > 90:  ts -= 5      # near 52W high (extended)
        breakout = t.get("breakout")
        if breakout == "52W_HIGH": ts += 10
        elif breakout == "52W_LOW":ts -= 5
        ts = max(0, min(100, round(ts, 1)))

        vol  = r.get("volatility_20d", 2)
        rs   = max(0, 100 - vol * 15)
        micro = broker_scores.get(sym, 50)
        # Round-2 fix (Issue 3): market_factor was applied TWICE — once inside
        # mkt_ctx (50 * market_factor) and again as an outer multiplier on the
        # entire weighted sum.  This caused double-scaling: the mkt_ctx component
        # was scaled by market_factor², while all other components were scaled
        # by market_factor¹.  Fix: set mkt_ctx to a constant 50-point base so
        # market_factor is applied exactly once via the outer multiplier.
        mkt_ctx = 50                        # constant base; regime applied once below

        composite = round(
            (ms * 0.20 + fs * 0.25 + ts * 0.20 + rs * 0.15
             + micro * 0.10 + mkt_ctx * 0.10) * market_factor
            + season_bonus,
            2
        )

        scored.append({
            "symbol": sym, "sector": f.get("sector", ""),
            "price": m["price"], "eps": f["eps"], "pe": f["pe_ratio"],
            "rsi": m["rsi"], "signal": sig,
            "momentum_score": ms, "fund_score": fs,
            "tech_score": ts, "risk_score": round(rs, 1),
            "micro_score": round(micro, 1),
            "composite": composite,
        })
    scored.sort(key=lambda x: x["composite"], reverse=True)
    return {"buy": scored[:15], "sell": scored[-15:][::-1]}

# ═══════════════════════════════════════════════════════════════════════
#  12. RESEARCH INSIGHTS  (static)
# ═══════════════════════════════════════════════════════════════════════

def research_insights():
    print("  [12/12] Research Insights...")
    return [
        {"title": "📅 The Ashad Effect — Seasonal NEPSE Anomaly",
         "body": "July (Ashad/Shrawan) is historically the most bullish month in NEPSE. "
                 "Government capital expenditure rushes, dividend anticipation, and tax "
                 "clearance cycles create predictable liquidity waves. The v2 scoring engine "
                 "automatically adds a +5-point seasonal bonus during this window."},
        {"title": "🧠 EMD-LSTM Hybrid Forecasting",
         "body": "Empirical Mode Decomposition combined with LSTM networks filters market "
                 "noise by decomposing price into trend and oscillatory components. Research "
                 "shows EMD-LSTM outperforms standalone LSTM and ARIMA models on NEPSE data."},
        {"title": "🔍 Microstructure Forensics — Smart Money Tracking",
         "body": "Broker-level floorsheet data reveals institutional accumulation patterns. "
                 "High buy-side broker concentration (top-3 brokers dominating purchases) "
                 "indicates stock transfer from retail to institutional hands — a bullish "
                 "precursor now integrated into the composite score (10% weight)."},
        {"title": "📊 Lead-Lag Sector Rotation",
         "body": "Banking and Hydropower sectors often lead broader NEPSE moves. "
                 "Cross-correlation analysis shows Banking Index movements can predict Hydro "
                 "Index moves with a 2-day lag."},
        {"title": "⚖️ Fusion Approach: Fundamentals + Technicals",
         "body": "Research shows that screening by fundamentals (low P/E, high EPS, high ROE, "
                 "attractive dividend yield) and timing entry with technicals (RSI < 30, "
                 "Stochastic oversold, OBV rising) significantly improves Sharpe Ratio. "
                 "Fundamentals decide WHAT; technicals decide WHEN."},
        {"title": "📈 Volume-Price Divergence & OBV",
         "body": "On-Balance Volume (OBV) reveals sustained buying or selling pressure. "
                 "A rising OBV alongside stable or rising prices confirms accumulation. "
                 "Price rising on falling OBV signals a hollow rally likely to reverse. "
                 "OBV trend is now displayed in the Momentum tab."},
        {"title": "🎯 ATR-Based Price Levels",
         "body": "Average True Range (ATR) provides context-aware support and resistance "
                 "levels: Support = Price − 1.5×ATR, Resistance = Price + 1.5×ATR. "
                 "These dynamic levels adapt to each stock's volatility and are now shown "
                 "in the Technicals tab alongside breakout detection."},
    ]

# ═══════════════════════════════════════════════════════════════════════
#  HTML GENERATION
# ═══════════════════════════════════════════════════════════════════════

def fmt_num(v, decimals=2):
    if v is None: return "—"
    try:
        v = float(v)
        if abs(v) >= 1e9: return f"{v/1e9:.{decimals}f}B"
        if abs(v) >= 1e6: return f"{v/1e6:.{decimals}f}M"
        if abs(v) >= 1e3: return f"{v/1e3:.{decimals}f}K"
        return f"{v:,.{decimals}f}"
    except: return str(v)

def color_val(v, invert=False):
    try:
        v = float(v)
        if invert: v = -v
        if v > 0: return "pos"
        if v < 0: return "neg"
    except: pass
    return "neu"

def build_html(data, market_regime=None):
    print("\n📝 Generating HTML report...")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ov  = data["overview"]
    sm  = ov.get("summary", {})
    nepse_idx = next((i for i in ov.get("indices", []) if i["index_name"] == "NEPSE"), {})
    regime = market_regime or {"regime": "NEUTRAL", "factor": 1.0, "chg": 0}

    # ── CSS ────────────────────────────────────────────────────────────
    css = """
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;--dim:#8b949e;
--green:#00c853;--red:#ff1744;--amber:#ffc107;--blue:#58a6ff;--purple:#bc8cff;
--hover:#1f2937;--font:'Segoe UI',system-ui,-apple-system,sans-serif}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.5;padding:0}
.header{background:linear-gradient(135deg,#0d1117 0%,#161b22 50%,#1a2332 100%);
padding:24px 32px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:24px;font-weight:700;letter-spacing:-0.5px}
.header h1 span{color:var(--green)}
.header .ts{color:var(--dim);font-size:13px;text-align:right}
.regime{display:inline-block;margin-top:4px;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:700}
.regime.bullish{background:rgba(0,200,83,.15);color:var(--green);border:1px solid rgba(0,200,83,.3)}
.regime.bearish{background:rgba(255,23,68,.15);color:var(--red);border:1px solid rgba(255,23,68,.3)}
.regime.neutral{background:rgba(255,193,7,.15);color:var(--amber);border:1px solid rgba(255,193,7,.3)}
.tabs{display:flex;gap:4px;padding:8px 16px;background:var(--card);border-bottom:1px solid var(--border);
overflow-x:auto;flex-wrap:nowrap;position:sticky;top:0;z-index:100}
.tab{padding:8px 14px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;
white-space:nowrap;color:var(--dim);border:1px solid transparent;transition:all .2s}
.tab:hover{color:var(--text);background:var(--hover)}
.tab.active{color:var(--green);background:rgba(0,200,83,.1);border-color:rgba(0,200,83,.3)}
.content{padding:16px 24px;max-width:1800px;margin:0 auto}
.section{display:none;animation:fadeIn .3s ease}.section.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.scorecard{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.sc-card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center}
.sc-card .label{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.sc-card .value{font-size:22px;font-weight:700}
.sc-card .change{font-size:13px;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px}
th{background:var(--card);color:var(--dim);font-weight:600;text-transform:uppercase;font-size:11px;
letter-spacing:.5px;padding:10px 12px;text-align:left;border-bottom:2px solid var(--border);
cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--text)}
th::after{content:'⇅';margin-left:4px;opacity:.3}
td{padding:8px 12px;border-bottom:1px solid var(--border);white-space:nowrap}
tr:hover{background:var(--hover)}
.pos{color:var(--green)}.neg{color:var(--red)}.neu{color:var(--amber)}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.badge.buy{background:rgba(0,200,83,.15);color:var(--green);border:1px solid rgba(0,200,83,.3)}
.badge.sell{background:rgba(255,23,68,.15);color:var(--red);border:1px solid rgba(255,23,68,.3)}
.badge.hold{background:rgba(255,193,7,.15);color:var(--amber);border:1px solid rgba(255,193,7,.3)}
.badge.high{background:rgba(255,23,68,.15);color:var(--red)}
.badge.medium{background:rgba(255,193,7,.15);color:var(--amber)}
.badge.low{background:rgba(0,200,83,.15);color:var(--green)}
.badge.rising{background:rgba(0,200,83,.15);color:var(--green)}
.badge.falling{background:rgba(255,23,68,.15);color:var(--red)}
.badge.flat{background:rgba(255,193,7,.15);color:var(--amber)}
.badge.52w_high{background:rgba(88,166,255,.15);color:var(--blue)}
.badge.52w_low{background:rgba(255,23,68,.15);color:var(--red)}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px;margin-bottom:16px}
.card h3{font-size:16px;margin-bottom:8px;color:var(--blue)}
.card p{color:var(--dim);font-size:14px;line-height:1.6}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
h2.sec-title{font-size:18px;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.subtitle{color:var(--dim);font-size:13px;margin-bottom:16px}
@media(max-width:900px){.grid-2{grid-template-columns:1fr}.content{padding:12px}}
"""

    # ── JS ─────────────────────────────────────────────────────────────
    js = """
function showTab(id){
document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
document.getElementById(id).classList.add('active');
document.querySelector('[data-tab="'+id+'"]').classList.add('active');}
function sortTable(th){
var table=th.closest('table'),tbody=table.querySelector('tbody'),
rows=Array.from(tbody.querySelectorAll('tr')),
idx=Array.from(th.parentNode.children).indexOf(th),
asc=th.dataset.sort!=='asc';th.parentNode.querySelectorAll('th').forEach(t=>delete t.dataset.sort);
th.dataset.sort=asc?'asc':'desc';
rows.sort(function(a,b){
var av=a.children[idx].textContent.trim().replace(/[,%BKMRS₨ ]/g,''),
bv=b.children[idx].textContent.trim().replace(/[,%BKMRS₨ ]/g,'');
var an=parseFloat(av),bn=parseFloat(bv);
if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
return asc?av.localeCompare(bv):bv.localeCompare(av);});
rows.forEach(r=>tbody.appendChild(r));}
document.addEventListener('DOMContentLoaded',function(){
document.querySelectorAll('th').forEach(th=>th.addEventListener('click',function(){sortTable(this)}));
showTab('overview');});
"""

    # ── TAB LIST ───────────────────────────────────────────────────────
    tab_list = [
        ("overview",     "📊 Overview"),
        ("buy",          "📈 Strong Buy"),
        ("sell",         "📉 Strong Sell"),
        ("momentum",     "🔥 Momentum"),
        ("fundamentals", "💼 Fundamentals"),
        ("technicals",   "📊 Technicals"),
        ("sectors",      "🌍 Sectors"),
        ("risk",         "⚠️ Risk"),
        ("gainers",      "🏆 Gainers/Losers"),
        ("dividends",    "💰 Dividends"),
        ("floorsheet",   "🏦 Floorsheet"),
        ("rankings",     "🏅 Rankings"),
        ("research",     "📰 Research"),
    ]
    tabs_html = ""
    for tid, label in tab_list:
        tabs_html += f'<div class="tab" data-tab="{tid}" onclick="showTab(\'{tid}\')">{label}</div>\n'

    sections_html = ""

    # ── OVERVIEW ───────────────────────────────────────────────────────
    idx_val = fmt_num(nepse_idx.get("current_value"), 2) if nepse_idx else "—"
    idx_chg = nepse_idx.get("change_points", 0)   if nepse_idx else 0
    idx_pct = nepse_idx.get("change_percent", 0)  if nepse_idx else 0
    r_cls   = regime["regime"].lower()
    r_lbl   = f"Market: {regime['regime']}  {'+' if regime['chg']>=0 else ''}{round(regime['chg'],2)}%"
    sections_html += f"""
<div id="overview" class="section active">
<h2 class="sec-title">📊 Market Overview</h2>
<div class="scorecard">
<div class="sc-card"><div class="label">NEPSE Index</div><div class="value">{idx_val}</div>
<div class="change {color_val(idx_chg)}">{'+' if float(idx_chg or 0)>0 else ''}{fmt_num(idx_chg)} ({'+' if float(idx_pct or 0)>0 else ''}{fmt_num(idx_pct)}%)</div></div>
<div class="sc-card"><div class="label">Total Turnover</div><div class="value">Rs {fmt_num(sm.get('total_turnover'))}</div></div>
<div class="sc-card"><div class="label">Traded Shares</div><div class="value">{fmt_num(sm.get('total_traded_shares'),0)}</div></div>
<div class="sc-card"><div class="label">Transactions</div><div class="value">{fmt_num(sm.get('total_transactions'),0)}</div></div>
<div class="sc-card"><div class="label">Scrips Traded</div><div class="value">{sm.get('total_scrips_traded','—')}</div></div>
<div class="sc-card"><div class="label">Market Cap</div><div class="value">Rs {fmt_num(sm.get('total_market_cap'))}</div></div>
</div>
<p style="margin-bottom:16px"><span class="regime {r_cls}">{r_lbl}</span>
&nbsp;<span style="color:var(--dim);font-size:12px">— composite scores are {'boosted ×1.1' if r_cls=='bullish' else ('reduced ×0.9' if r_cls=='bearish' else 'unmodified (×1.0)')}</span></p>
<h3 style="margin:16px 0 8px;font-size:15px;">Market Indices</h3>
<table><thead><tr><th>Index</th><th>Value</th><th>Change Pts</th><th>Change %</th></tr></thead><tbody>
"""
    for i in ov.get("indices", []):
        c = color_val(i.get("change_percent", 0))
        sections_html += f'<tr><td>{i["index_name"]}</td><td>{fmt_num(i.get("current_value"))}</td><td class="{c}">{fmt_num(i.get("change_points"))}</td><td class="{c}">{fmt_num(i.get("change_percent"))}%</td></tr>\n'
    sections_html += "</tbody></table>\n"
    sections_html += '<h3 style="margin:16px 0 8px;font-size:15px;">Sub-Indices</h3>\n<table><thead><tr><th>Index</th><th>Value</th><th>Change Pts</th><th>Change %</th></tr></thead><tbody>\n'
    for s in ov.get("sub_indices", []):
        c = color_val(s.get("percent_change", 0))
        sections_html += f'<tr><td>{s["index_name"]}</td><td>{fmt_num(s.get("current_value"))}</td><td class="{c}">{fmt_num(s.get("points_change"))}</td><td class="{c}">{fmt_num(s.get("percent_change"))}%</td></tr>\n'
    sections_html += "</tbody></table></div>\n"

    # ── STRONG BUY ─────────────────────────────────────────────────────
    picks = data["picks"]
    weight_desc = "Composite = 20% momentum + 25% fundamental + 20% technical + 15% risk + 10% microstructure + 10% market-context"
    sections_html += f'<div id="buy" class="section"><h2 class="sec-title">📈 Strong Buy Candidates</h2><p class="subtitle">{weight_desc}</p>\n<table><thead><tr><th>#</th><th>Symbol</th><th>Sector</th><th>Price</th><th>EPS</th><th>P/E</th><th>RSI</th><th>Signal</th><th>Mom</th><th>Fund</th><th>Tech</th><th>Risk</th><th>Micro</th><th>Composite</th></tr></thead><tbody>\n'
    for i, s in enumerate(picks["buy"], 1):
        sections_html += f'<tr><td>{i}</td><td><b>{s["symbol"]}</b></td><td>{s["sector"]}</td><td>{fmt_num(s["price"])}</td><td class="{color_val(s["eps"])}">{fmt_num(s["eps"])}</td><td>{fmt_num(s["pe"])}</td><td>{s["rsi"] or "—"}</td><td><span class="badge {s["signal"].lower()}">{s["signal"]}</span></td><td>{fmt_num(s["momentum_score"])}</td><td>{fmt_num(s["fund_score"],0)}</td><td>{fmt_num(s["tech_score"],0)}</td><td>{fmt_num(s["risk_score"])}</td><td>{fmt_num(s["micro_score"])}</td><td><b class="pos">{fmt_num(s["composite"])}</b></td></tr>\n'
    sections_html += "</tbody></table></div>\n"

    # ── STRONG SELL ────────────────────────────────────────────────────
    sections_html += f'<div id="sell" class="section"><h2 class="sec-title">📉 Strong Sell Candidates</h2><p class="subtitle">{weight_desc}</p>\n<table><thead><tr><th>#</th><th>Symbol</th><th>Sector</th><th>Price</th><th>EPS</th><th>P/E</th><th>RSI</th><th>Signal</th><th>Mom</th><th>Fund</th><th>Tech</th><th>Risk</th><th>Micro</th><th>Composite</th></tr></thead><tbody>\n'
    for i, s in enumerate(picks["sell"], 1):
        sections_html += f'<tr><td>{i}</td><td><b>{s["symbol"]}</b></td><td>{s["sector"]}</td><td>{fmt_num(s["price"])}</td><td class="{color_val(s["eps"])}">{fmt_num(s["eps"])}</td><td>{fmt_num(s["pe"])}</td><td>{s["rsi"] or "—"}</td><td><span class="badge {s["signal"].lower()}">{s["signal"]}</span></td><td>{fmt_num(s["momentum_score"])}</td><td>{fmt_num(s["fund_score"],0)}</td><td>{fmt_num(s["tech_score"],0)}</td><td>{fmt_num(s["risk_score"])}</td><td>{fmt_num(s["micro_score"])}</td><td><b class="neg">{fmt_num(s["composite"])}</b></td></tr>\n'
    sections_html += "</tbody></table></div>\n"

    # ── MOMENTUM  (Issues 7, 8 — new columns) ─────────────────────────
    mom = data["momentum"][:50]
    sections_html += '<div id="momentum" class="section"><h2 class="sec-title">🔥 Momentum Leaders</h2><p class="subtitle">Top 50 — RSI, MACD, Stochastic, OBV Trend, Rate of Change, Volume</p>\n<table><thead><tr><th>#</th><th>Symbol</th><th>Price</th><th>RSI(14)</th><th>MACD</th><th>MACD Hist</th><th>Stoch %K</th><th>Stoch %D</th><th>OBV Trend</th><th>ROC 5D</th><th>ROC 20D</th><th>Vol Ratio</th><th>Score</th></tr></thead><tbody>\n'
    for i, m in enumerate(mom, 1):
        obv_cls = (m["obv_trend"] or "flat").lower()
        sections_html += (
            f'<tr><td>{i}</td><td><b>{m["symbol"]}</b></td><td>{fmt_num(m["price"])}</td>'
            f'<td>{m["rsi"] or "—"}</td>'
            f'<td class="{color_val(m["macd"])}">{fmt_num(m["macd"])}</td>'
            f'<td class="{color_val(m["macd_hist"])}">{fmt_num(m["macd_hist"])}</td>'
            f'<td>{m["stoch_k"] or "—"}</td><td>{m["stoch_d"] or "—"}</td>'
            f'<td><span class="badge {obv_cls}">{m["obv_trend"]}</span></td>'
            f'<td class="{color_val(m["roc_5d"])}">{m["roc_5d"]}%</td>'
            f'<td class="{color_val(m["roc_20d"])}">{m["roc_20d"]}%</td>'
            f'<td>{m["vol_ratio"]}</td><td><b>{fmt_num(m["momentum_score"])}</b></td></tr>\n'
        )
    sections_html += "</tbody></table></div>\n"

    # ── FUNDAMENTALS  (Issue 14 — new columns) ────────────────────────
    fund = data["fundamentals"][:50]
    sections_html += '<div id="fundamentals" class="section"><h2 class="sec-title">💼 Fundamental Scores</h2><p class="subtitle">Top 50 — EPS, P/E, Book Value, ROE, Dividend Yield</p>\n<table><thead><tr><th>#</th><th>Symbol</th><th>Sector</th><th>EPS</th><th>P/E</th><th>Book Value</th><th>P/BV</th><th>ROE%</th><th>Div Yield%</th><th>Net Profit</th><th>FY / Qtr</th><th>Score</th></tr></thead><tbody>\n'
    for i, f in enumerate(fund, 1):
        sections_html += (
            f'<tr><td>{i}</td><td><b>{f["symbol"]}</b></td><td>{f["sector"] or "—"}</td>'
            f'<td class="{color_val(f["eps"])}">{fmt_num(f["eps"])}</td>'
            f'<td>{fmt_num(f["pe_ratio"])}</td><td>{fmt_num(f["book_value"])}</td>'
            f'<td>{fmt_num(f["pbv"])}</td>'
            f'<td class="{color_val(f["roe"])}">{fmt_num(f["roe"])}%</td>'
            f'<td class="{color_val(f["div_yield"])}">{fmt_num(f["div_yield"])}%</td>'
            f'<td>{fmt_num(f["net_profit"])}</td>'
            f'<td>{f["fiscal_year"]} {(f["quarter"] or "")[:10]}</td>'
            f'<td><b>{f["fund_score"]}</b></td></tr>\n'
        )
    sections_html += "</tbody></table></div>\n"

    # ── TECHNICALS  (Issues 6, 10 — new columns) ──────────────────────
    tech = data["technicals"][:60]
    sections_html += '<div id="technicals" class="section"><h2 class="sec-title">📊 Technical Signals</h2><p class="subtitle">SMA crossovers, Bollinger Bands, ATR price levels, 52-week breakout detection</p>\n<table><thead><tr><th>#</th><th>Symbol</th><th>Price</th><th>SMA20</th><th>SMA50</th><th>BB%</th><th>ATR</th><th>Support</th><th>Resistance</th><th>52W Range%</th><th>Breakout</th><th>Cross</th><th>Signal</th></tr></thead><tbody>\n'
    for i, t in enumerate(tech, 1):
        brk = t.get("breakout") or ""
        brk_badge = f'<span class="badge {brk.lower()}">{brk}</span>' if brk else "—"
        sections_html += (
            f'<tr><td>{i}</td><td><b>{t["symbol"]}</b></td><td>{fmt_num(t["price"])}</td>'
            f'<td>{fmt_num(t["sma20"])}</td><td>{fmt_num(t["sma50"])}</td>'
            f'<td>{t["bb_pct"]}%</td>'
            f'<td>{fmt_num(t["atr"])}</td>'
            f'<td class="neg">{fmt_num(t["support"])}</td>'
            f'<td class="pos">{fmt_num(t["resistance"])}</td>'
            f'<td>{t["range_pct"]}%</td>'
            f'<td>{brk_badge}</td>'
            f'<td>{t["cross"]}</td>'
            f'<td><span class="badge {t["signal"].lower()}">{t["signal"]}</span></td></tr>\n'
        )
    sections_html += "</tbody></table></div>\n"

    # ── SECTORS ────────────────────────────────────────────────────────
    sect = data["sectors"]
    sections_html += '<div id="sectors" class="section"><h2 class="sec-title">🌍 Sector Breakdown</h2>\n<div class="grid-2"><div>\n<h3 style="margin-bottom:8px;font-size:15px;">Sub-Index Performance</h3>\n<table><thead><tr><th>Index</th><th>Value</th><th>Change</th><th>%</th></tr></thead><tbody>\n'
    for s in sect.get("sub_indices", []):
        c = color_val(s.get("percent_change", 0))
        sections_html += f'<tr><td>{s["index_name"]}</td><td>{fmt_num(s.get("current_value"))}</td><td class="{c}">{fmt_num(s.get("points_change"))}</td><td class="{c}">{fmt_num(s.get("percent_change"))}%</td></tr>\n'
    sections_html += '</tbody></table></div><div>\n<h3 style="margin-bottom:8px;font-size:15px;">Sector Turnover</h3>\n<table><thead><tr><th>Sector</th><th>Turnover</th><th>Volume</th><th>Stocks</th><th>Avg Chg%</th></tr></thead><tbody>\n'
    for s in sect.get("sectors", []):
        c = color_val(s.get("avg_change", 0))
        sections_html += f'<tr><td>{s["sector"]}</td><td>Rs {fmt_num(s.get("total_turnover"))}</td><td>{fmt_num(s.get("total_volume"),0)}</td><td>{s["stock_count"]}</td><td class="{c}">{fmt_num(s.get("avg_change"))}%</td></tr>\n'
    sections_html += "</tbody></table></div></div></div>\n"

    # ── RISK ───────────────────────────────────────────────────────────
    risk = data["risk"][:50]
    sections_html += '<div id="risk" class="section"><h2 class="sec-title">⚠️ Risk Overview</h2><p class="subtitle">Top 50 most volatile — 20-day volatility, max drawdown, 52-week range (adjusted prices)</p>\n<table><thead><tr><th>#</th><th>Symbol</th><th>Price</th><th>Vol 20D</th><th>Max DD%</th><th>52W Range%</th><th>52W High</th><th>52W Low</th><th>Risk</th></tr></thead><tbody>\n'
    for i, r in enumerate(risk, 1):
        sections_html += f'<tr><td>{i}</td><td><b>{r["symbol"]}</b></td><td>{fmt_num(r["price"])}</td><td>{r["volatility_20d"]}</td><td class="neg">{r["max_drawdown"]}%</td><td>{r["range_52w"]}%</td><td>{fmt_num(r["hi52"])}</td><td>{fmt_num(r["lo52"])}</td><td><span class="badge {r["risk_level"].lower()}">{r["risk_level"]}</span></td></tr>\n'
    sections_html += "</tbody></table></div>\n"

    # ── GAINERS / LOSERS ───────────────────────────────────────────────
    gl = data["gainers_losers"]
    sections_html += '<div id="gainers" class="section"><h2 class="sec-title">🏆 Top Gainers & Losers</h2>\n<div class="grid-2"><div><h3 style="margin-bottom:8px;font-size:15px;color:var(--green)">🟢 Top Gainers</h3>\n<table><thead><tr><th>#</th><th>Symbol</th><th>LTP</th><th>Prev Close</th><th>Change</th><th>%</th></tr></thead><tbody>\n'
    for i, g in enumerate(gl.get("gainers", []), 1):
        sections_html += f'<tr><td>{i}</td><td><b>{g["symbol"]}</b></td><td>{fmt_num(g.get("ltp"))}</td><td>{fmt_num(g.get("previous_close"))}</td><td class="pos">{fmt_num(g.get("point_change"))}</td><td class="pos">{fmt_num(g.get("percent_change"))}%</td></tr>\n'
    sections_html += '</tbody></table></div><div><h3 style="margin-bottom:8px;font-size:15px;color:var(--red)">🔴 Top Losers</h3>\n<table><thead><tr><th>#</th><th>Symbol</th><th>LTP</th><th>Prev Close</th><th>Change</th><th>%</th></tr></thead><tbody>\n'
    for i, l in enumerate(gl.get("losers", []), 1):
        sections_html += f'<tr><td>{i}</td><td><b>{l["symbol"]}</b></td><td>{fmt_num(l.get("ltp"))}</td><td>{fmt_num(l.get("previous_close"))}</td><td class="neg">{fmt_num(l.get("point_change"))}</td><td class="neg">{fmt_num(l.get("percent_change"))}%</td></tr>\n'
    sections_html += "</tbody></table></div></div></div>\n"

    # ── DIVIDENDS ──────────────────────────────────────────────────────
    da = data["dividends_actions"]
    sections_html += '<div id="dividends" class="section"><h2 class="sec-title">💰 Dividends & Corporate Actions</h2>\n<div class="grid-2"><div><h3 style="margin-bottom:8px;font-size:15px;">Recent Dividends</h3>\n<table><thead><tr><th>Symbol</th><th>FY</th><th>Bonus%</th><th>Cash%</th><th>Book Close</th><th>Sector</th></tr></thead><tbody>\n'
    for d in da.get("dividends", [])[:25]:
        sections_html += f'<tr><td><b>{d["symbol"]}</b></td><td>{d.get("fiscal_year","—")}</td><td class="pos">{fmt_num(d.get("bonus_share_percent"))}%</td><td class="pos">{fmt_num(d.get("cash_dividend_percent"))}%</td><td>{d.get("book_close_date","—")}</td><td>{d.get("sector_name","—")}</td></tr>\n'
    sections_html += '</tbody></table></div><div><h3 style="margin-bottom:8px;font-size:15px;">Recent Corporate Actions</h3>\n<table><thead><tr><th>Symbol</th><th>Action</th><th>Ratio</th><th>Notify Date</th><th>Book Close</th></tr></thead><tbody>\n'
    for a in da.get("actions", [])[:25]:
        sections_html += f'<tr><td><b>{a["symbol"]}</b></td><td>{a.get("action_type","—")}</td><td>{a.get("ratio","—")}</td><td>{a.get("notify_date","—")}</td><td>{a.get("book_close_date","—")}</td></tr>\n'
    sections_html += "</tbody></table></div></div></div>\n"

    # ── FLOORSHEET ─────────────────────────────────────────────────────
    fl = data["floorsheet"]
    sections_html += '<div id="floorsheet" class="section"><h2 class="sec-title">🏦 Floorsheet Forensics</h2>\n<div class="grid-2"><div><h3 style="margin-bottom:8px;font-size:15px;color:var(--green)">Top Buyer Brokers</h3>\n<table><thead><tr><th>#</th><th>Broker</th><th>Trades</th><th>Qty</th><th>Amount</th><th>Symbols</th></tr></thead><tbody>\n'
    for i, b in enumerate(fl.get("top_buyers", []), 1):
        sections_html += f'<tr><td>{i}</td><td>{b["broker"]}</td><td>{fmt_num(b.get("trades"),0)}</td><td>{fmt_num(b.get("total_qty"),0)}</td><td>Rs {fmt_num(b.get("total_amt"))}</td><td>{b.get("symbols_traded","—")}</td></tr>\n'
    sections_html += '</tbody></table></div><div><h3 style="margin-bottom:8px;font-size:15px;color:var(--red)">Top Seller Brokers</h3>\n<table><thead><tr><th>#</th><th>Broker</th><th>Trades</th><th>Qty</th><th>Amount</th><th>Symbols</th></tr></thead><tbody>\n'
    for i, s in enumerate(fl.get("top_sellers", []), 1):
        sections_html += f'<tr><td>{i}</td><td>{s["broker"]}</td><td>{fmt_num(s.get("trades"),0)}</td><td>{fmt_num(s.get("total_qty"),0)}</td><td>Rs {fmt_num(s.get("total_amt"))}</td><td>{s.get("symbols_traded","—")}</td></tr>\n'
    sections_html += '</tbody></table></div></div>\n<h3 style="margin:16px 0 8px;font-size:15px;">Most Traded Securities</h3>\n<table><thead><tr><th>#</th><th>Symbol</th><th>Trades</th><th>Qty</th><th>Amount</th><th>Min Rate</th><th>Max Rate</th><th>Avg Rate</th></tr></thead><tbody>\n'
    for i, m in enumerate(fl.get("most_traded", []), 1):
        sections_html += f'<tr><td>{i}</td><td><b>{m["symbol"]}</b></td><td>{fmt_num(m.get("trades"),0)}</td><td>{fmt_num(m.get("total_qty"),0)}</td><td>Rs {fmt_num(m.get("total_amt"))}</td><td>{fmt_num(m.get("min_rate"))}</td><td>{fmt_num(m.get("max_rate"))}</td><td>{fmt_num(m.get("avg_rate"))}</td></tr>\n'
    sections_html += "</tbody></table></div>\n"

    # ── RANKINGS ───────────────────────────────────────────────────────
    rk = data["rankings"]
    sections_html += '<div id="rankings" class="section"><h2 class="sec-title">🏅 Scrip Rankings</h2>\n<div class="grid-2"><div><h3 style="margin-bottom:8px;font-size:15px;">By Shares Traded</h3>\n<table><thead><tr><th>Rank</th><th>Symbol</th><th>Shares</th><th>Close</th></tr></thead><tbody>\n'
    for r in rk.get("by_trade", []):
        sections_html += f'<tr><td>{r.get("rank","—")}</td><td><b>{r["symbol"]}</b></td><td>{fmt_num(r.get("metric_value"),0)}</td><td>{fmt_num(r.get("closing_price"))}</td></tr>\n'
    sections_html += '</tbody></table>\n<h3 style="margin:16px 0 8px;font-size:15px;">By Turnover</h3>\n<table><thead><tr><th>Rank</th><th>Symbol</th><th>Turnover</th><th>Close</th></tr></thead><tbody>\n'
    for r in rk.get("by_turnover", []):
        sections_html += f'<tr><td>{r.get("rank","—")}</td><td><b>{r["symbol"]}</b></td><td>Rs {fmt_num(r.get("metric_value"))}</td><td>{fmt_num(r.get("closing_price"))}</td></tr>\n'
    sections_html += '</tbody></table></div><div><h3 style="margin-bottom:8px;font-size:15px;">By Transaction Count</h3>\n<table><thead><tr><th>Rank</th><th>Symbol</th><th>Transactions</th><th>Close</th></tr></thead><tbody>\n'
    for r in rk.get("by_transaction", []):
        sections_html += f'<tr><td>{r.get("rank","—")}</td><td><b>{r["symbol"]}</b></td><td>{fmt_num(r.get("metric_value"),0)}</td><td>{fmt_num(r.get("closing_price"))}</td></tr>\n'
    sections_html += "</tbody></table></div></div></div>\n"

    # ── RESEARCH ───────────────────────────────────────────────────────
    sections_html += '<div id="research" class="section"><h2 class="sec-title">📰 Research Insights</h2><p class="subtitle">Key concepts from Strategic Equity Forecasting Architectures — applied in v2</p>\n'
    for r in data["research"]:
        sections_html += f'<div class="card"><h3>{r["title"]}</h3><p>{r["body"]}</p></div>\n'
    sections_html += "</div>\n"

    # ── ASSEMBLE ───────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEPSE Analytics Report v2 — {now}</title>
<style>{css}</style></head><body>
<div class="header">
  <h1>NEPSE <span>Analytics</span> Report <span style="font-size:14px;color:var(--dim)">v2</span></h1>
  <div class="ts">Generated: {now}<br>
    <span class="regime {r_cls}">{regime['regime']} MARKET</span>
  </div>
</div>
<div class="tabs">{tabs_html}</div>
<div class="content">{sections_html}</div>
<script>{js}</script></body></html>"""
    return html

# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("  NEPSE Stock Analytics Report Generator  — v2.0")
    print("=" * 65)
    conn = get_conn()
    try:
        print("\n🔌 Connected to database\n📊 Running analytics...\n")

        # ── Issue 4: single batch fetch for all OHLCV data ────────────
        all_ohlcv   = fetch_all_ohlcv(conn)
        all_corps   = fetch_all_corp_actions(conn)
        all_divs    = fetch_all_dividends(conn)
        all_details = fetch_all_company_details(conn)

        # ── Issue 9: market regime ─────────────────────────────────────
        regime = get_market_regime(conn)
        print(f"  Market regime: {regime['regime']}  (factor {regime['factor']})")

        # ── Issue 5: broker concentration ─────────────────────────────
        broker_scores = calc_broker_concentration(conn)

        # ── Issue 11: seasonality ──────────────────────────────────────
        s_bonus = seasonality_bonus()
        if s_bonus:
            print(f"  Seasonal bonus active: +{s_bonus} pts (Ashad/Shrawan window)")

        # ── Analytics ─────────────────────────────────────────────────
        ov   = market_overview(conn)
        mom  = momentum_analysis(all_ohlcv, all_corps, all_divs)
        fund = fundamental_analysis(conn)
        tech = technical_signals(all_ohlcv, all_corps, all_divs, all_details)
        sect = sector_breakdown(conn)
        risk = risk_overview(all_ohlcv, all_corps, all_divs, all_details)
        gl   = top_gainers_losers(conn)
        da   = dividend_actions(conn)
        fl   = floorsheet_forensics(conn)
        rk   = scrip_rankings(conn)
        picks = strong_picks(mom, fund, tech, risk,
                             broker_scores=broker_scores,
                             market_factor=regime["factor"],
                             season_bonus=s_bonus)
        research = research_insights()

        data = {
            "overview": ov, "momentum": mom, "fundamentals": fund,
            "technicals": tech, "sectors": sect, "risk": risk,
            "gainers_losers": gl, "dividends_actions": da,
            "floorsheet": fl, "rankings": rk, "picks": picks,
            "research": research,
        }

        html = build_html(data, market_regime=regime)
        out  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"\n✅ Report generated: {out}")
        print(f"   Open in browser to view the full analytics dashboard.")

    finally:
        conn.close()
        print("\n🔌 Database connection closed.")

if __name__ == "__main__":
    main()