"""
NEPSE Single-Stock Deep Analysis Engine — Logic Module (v1.0)

Analyzes a single stock in depth: fetches its OHLCV, company info, fundamentals,
floorsheet, intraday data, and computes all technical indicators, score breakdowns,
strengths/weaknesses, and comparisons against market/sector.

Reuses indicator functions from the main analysor where possible, but adds
single-stock-specific features:
  - Intraday price chart data (from daily_script_price_graph)
  - VWAP from intraday ticks
  - Historical price series for charting
  - Full score breakdown (Technical, Fundamental, Volume, Backtest)
  - Detailed strengths & weaknesses lists
  - Sector peer comparison
  - Broker activity detail for this symbol
"""

import os, math
from datetime import datetime, timedelta
from collections import defaultdict

import pymysql
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════
#  CONSTANTS (same as analysor)
# ═══════════════════════════════════════════════════════════════════════

ACCOUNT_EQUITY = 100_000
RISK_PCT       = 0.015
ATR_SL_MULT    = 1.5
ATR_T1_MULT    = 2.0
ATR_T2_MULT    = 3.5
RSI_OVERBOUGHT = 80
RSI_OVERSOLD   = 20
MIN_BARS_RSI   = 100
MIN_BARS_MACD  = 35
MIN_BARS_BB    = 20
MIN_BARS_ATR   = 15
MIN_BARS_STOCH = 14
MIN_BARS_ROC60 = 61
MIN_BARS_SMA200= 200
LOW_LIQ_THRESH = 5000
CIRCUIT_LIMIT  = 0.10
MIN_RR_RATIO   = 2.0
FUNDAMENTAL_STALE_DAYS = 540
MIN_INTRADAY_TICKS_FOR_VWAP = 30
MIN_INTRADAY_SESSION_MINUTES = 120
MAX_POSITION_SHARE_OF_AVG_VOL = 0.02
MAX_CAPITAL_ALLOCATION_PCT = 0.25
MIN_BROKER_PARTICIPANTS = 5
MIN_BROKER_TOTAL_VALUE = 5_000_000
MAX_FORWARD_FILL_STREAK = 5
LIVE_CANDLE_DEVIATION_BUFFER = 0.02

# ═══════════════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════════════

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
#  SINGLE-STOCK DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════

def fetch_ohlcv(conn, symbol):
    """Fetch OHLCV for a single symbol with open_price fix.
    Appends rows from daily_prices when a date is missing in daily_ohlcv."""
    rows = q(conn, """
        SELECT
            do.symbol, do.trading_date,
            COALESCE(NULLIF(dp.open_price, 0), NULLIF(do.open_price, 0), do.close_price) AS open_price,
            CASE
                WHEN COALESCE(NULLIF(dp.open_price, 0), NULLIF(do.open_price, 0)) IS NULL THEN 1
                ELSE 0
            END AS is_synthetic_open,
            do.high_price, do.low_price, do.close_price, do.volume
        FROM daily_ohlcv do
        LEFT JOIN daily_prices dp
            ON do.symbol = dp.symbol AND do.trading_date = dp.trading_date
        WHERE do.symbol = %s AND do.close_price > 0

        UNION ALL

        SELECT
            dp.symbol, dp.trading_date,
            COALESCE(NULLIF(dp.open_price, 0), dp.close_price) AS open_price,
            CASE WHEN NULLIF(dp.open_price, 0) IS NULL THEN 1 ELSE 0 END AS is_synthetic_open,
            dp.high_price, dp.low_price, dp.close_price, dp.volume
        FROM daily_prices dp
        LEFT JOIN daily_ohlcv do
            ON do.symbol = dp.symbol AND do.trading_date = dp.trading_date
        WHERE dp.symbol = %s
          AND do.symbol IS NULL
          AND dp.close_price > 0
          AND dp.trading_date < CURDATE()

        ORDER BY trading_date ASC
    """, (symbol, symbol))
    return rows


def fetch_company_details(conn, symbol):
    """Fetch company details for a single symbol."""
    return qone(conn, """
        SELECT * FROM company_details WHERE symbol = %s
    """, (symbol,))


def fetch_security_info(conn, symbol):
    """Fetch from securities table."""
    return qone(conn, """
        SELECT * FROM securities WHERE symbol = %s
    """, (symbol,))


def fetch_fundamentals(conn, symbol):
    """Fetch all quarterly fundamentals for this symbol."""
    rows = q(conn, """
        SELECT * FROM company_fundamentals
        WHERE symbol = %s
        ORDER BY published_date DESC
    """, (symbol,))
    return rows


def fetch_dividends(conn, symbol):
    """Fetch dividend history."""
    return q(conn, """
        SELECT * FROM dividends WHERE symbol = %s
        ORDER BY book_close_date DESC
    """, (symbol,))


def fetch_corp_actions(conn, symbol):
    """Fetch corporate actions."""
    return q(conn, """
        SELECT * FROM corporate_actions WHERE symbol = %s
        ORDER BY book_close_date ASC
    """, (symbol,))


def fetch_52w_snapshot(conn, symbol):
    """52W high/low from live_market_snapshots."""
    return qone(conn, """
        SELECT MAX(fifty_two_week_high) as hi52,
               MIN(fifty_two_week_low)  as lo52
        FROM live_market_snapshots
        WHERE symbol = %s AND fifty_two_week_high > 0 AND fifty_two_week_low > 0
    """, (symbol,))


def fetch_live_ltp(conn, symbol):
    """Fetch real-time LTP from live_market_snapshots for a single symbol.
    This matches the official NEPSE website price."""
    return qone(conn, """
        SELECT l.last_traded_price, l.percent_change,
               l.open_price, l.high_price, l.low_price,
               l.total_traded_quantity AS volume, l.trading_date
        FROM live_market_snapshots l
        INNER JOIN (
            SELECT MAX(snapshot_timestamp) AS max_ts
            FROM live_market_snapshots
            WHERE symbol = %s
              AND trading_date = (SELECT MAX(trading_date) FROM live_market_snapshots WHERE symbol = %s)
        ) latest ON l.snapshot_timestamp = latest.max_ts
        WHERE l.symbol = %s AND l.last_traded_price > 0
        LIMIT 1
    """, (symbol, symbol, symbol))


def bridge_live_candle(ohlcv_candles, live_row):
    """Append a synthetic candle from live_market_snapshots if daily_ohlcv
    doesn't have data for the live trading date yet (data lag bridge)."""
    if not live_row or not ohlcv_candles:
        return ohlcv_candles
    live_date = str(live_row.get("trading_date") or "")[:10]
    last_ohlcv_date = str(ohlcv_candles[-1].get("trading_date") or "")[:10]
    today_iso = datetime.now().date().isoformat()
    if live_date and live_date > last_ohlcv_date and live_date < today_iso:
        last_traded = float(live_row["last_traded_price"])
        prev_close = float(ohlcv_candles[-1].get("close_price") or 0)
        if prev_close > 0:
            jump = abs(last_traded - prev_close) / prev_close
            if jump > CIRCUIT_LIMIT + LIVE_CANDLE_DEVIATION_BUFFER:
                return ohlcv_candles
        open_price = float(live_row.get("open_price") or last_traded)
        high_price = float(live_row.get("high_price") or last_traded)
        low_price = float(live_row.get("low_price") or last_traded)
        high_price = max(high_price, open_price, last_traded)
        low_price = min(low_price, open_price, last_traded)
        if high_price < low_price or min(open_price, high_price, low_price, last_traded) <= 0:
            return ohlcv_candles
        synthetic = {
            "symbol": ohlcv_candles[-1].get("symbol", ""),
            "trading_date": live_row["trading_date"],
            "open_price": open_price,
            "high_price": high_price,
            "low_price": low_price,
            "close_price": last_traded,
            "volume": int(live_row.get("volume") or 0),
            "is_synthetic_open": 0,
            "is_live_bridge": 1,
        }
        return ohlcv_candles + [synthetic]
    return ohlcv_candles


def fetch_intraday_ticks(conn, symbol):
    """Fetch intraday price ticks from daily_script_price_graph (latest day)."""
    return q(conn, """
        SELECT unix_time, contract_rate, contract_quantity, created_at
        FROM daily_script_price_graph
        WHERE symbol = %s
          AND DATE(created_at) = (
              SELECT COALESCE(
                  MAX(CASE WHEN DATE(created_at) < CURDATE() THEN DATE(created_at) END),
                  MAX(DATE(created_at))
              )
              FROM daily_script_price_graph
              WHERE symbol = %s
          )
        ORDER BY unix_time ASC
    """, (symbol, symbol))


def fetch_floorsheet(conn, symbol):
    """Fetch floorsheet transactions for this symbol (last 10 days)."""
    return q(conn, """
        SELECT * FROM floorsheet_transactions
        WHERE symbol = %s
          AND trading_date >= DATE_SUB(
              (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 10 DAY)
        ORDER BY trading_date DESC, amount DESC
    """, (symbol,))


def fetch_broker_summary(conn, symbol):
    """Aggregate buyer/seller brokers for this symbol."""
    buyers = q(conn, """
        SELECT buyer_broker_id, buyer_broker_name as broker_name,
               COUNT(*) as trades, SUM(quantity) as total_qty,
               SUM(amount) as total_amt,
               COUNT(DISTINCT trading_date) as sessions
        FROM floorsheet_transactions
        WHERE symbol = %s
          AND trading_date >= DATE_SUB(
              (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 10 DAY)
        GROUP BY buyer_broker_id, buyer_broker_name
        ORDER BY total_amt DESC LIMIT 10
    """, (symbol,))

    sellers = q(conn, """
        SELECT seller_broker_id, seller_broker_name as broker_name,
               COUNT(*) as trades, SUM(quantity) as total_qty,
               SUM(amount) as total_amt,
               COUNT(DISTINCT trading_date) as sessions
        FROM floorsheet_transactions
        WHERE symbol = %s
          AND trading_date >= DATE_SUB(
              (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 10 DAY)
        GROUP BY seller_broker_id, seller_broker_name
        ORDER BY total_amt DESC LIMIT 10
    """, (symbol,))

    return {"buyers": buyers, "sellers": sellers}


def fetch_sector_peers(conn, sector, current_symbol):
    """Fetch peer symbols in the same sector.
    Uses securities table (753 rows) with company_details fallback (384 rows)
    so peers aren't missed for partially-covered sectors."""
    if not sector:
        return []
    rows = q(conn, """
        SELECT peer.symbol,
               latest.close_price AS price
        FROM (
            SELECT symbol FROM securities WHERE sector_name = %s AND symbol != %s
            UNION
            SELECT symbol FROM company_details WHERE sector_name = %s AND symbol != %s
        ) peer
        LEFT JOIN (
            SELECT do.symbol, do.close_price
            FROM daily_ohlcv do
            INNER JOIN (
                SELECT symbol, MAX(trading_date) AS max_date
                FROM daily_ohlcv WHERE close_price > 0
                GROUP BY symbol
            ) latest_date ON do.symbol = latest_date.symbol AND do.trading_date = latest_date.max_date
        ) latest ON peer.symbol = latest.symbol
        WHERE latest.close_price IS NOT NULL
        ORDER BY peer.symbol
        LIMIT 20
    """, (sector, current_symbol, sector, current_symbol))
    return rows


def fetch_market_context(conn):
    """Get market regime and summary."""
    idx = qone(conn, """
        SELECT * FROM market_indices WHERE index_name = 'NEPSE'
        ORDER BY date DESC LIMIT 1
    """)
    summary = qone(conn, "SELECT * FROM market_summary ORDER BY trading_date DESC LIMIT 1")
    return {"index": idx, "summary": summary}


def fetch_scrip_ranking(conn, symbol):
    """Get this symbol's ranking position."""
    rows = q(conn, """
        SELECT category, `rank`, metric_value, closing_price
        FROM scrip_rankings
        WHERE symbol = %s
          AND trading_date = (SELECT MAX(trading_date) FROM scrip_rankings)
    """, (symbol,))
    return {r["category"]: r for r in rows}


# ═══════════════════════════════════════════════════════════════════════
#  PRICE ADJUSTMENT (same as analysor)
# ═══════════════════════════════════════════════════════════════════════

def _is_dup_adjustment(adjustments, bcd, factor, day_window=45):
    try:
        bcd_dt = datetime.strptime(str(bcd)[:10], "%Y-%m-%d")
    except ValueError:
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
    """Backward-adjust OHLCV for corporate actions and dividends."""
    if not candles:
        return candles

    adjustments = []

    for div in dividends:
        bcd = str(div.get("book_close_date") or "")
        if not bcd:
            continue
        bonus = float(div.get("bonus_share_percent") or 0)
        cash  = float(div.get("cash_dividend_percent") or 0)
        if bonus > 0:
            factor = 1.0 / (1.0 + bonus / 100.0)
            adjustments.append((bcd, factor))
        if cash > 0:
            cum_price = None
            for c in candles:
                if str(c["trading_date"]) < bcd:
                    cum_price = float(c["close_price"])
                else:
                    break
            if cum_price and cum_price > 0:
                dps = cash
                factor = (cum_price - dps) / cum_price
                if 0 < factor < 1:
                    adjustments.append((bcd, factor))

    for action in corp_actions:
        bcd = str(action.get("book_close_date") or "")
        if not bcd:
            continue
        atype = (action.get("action_type") or "").lower()
        ratio_str = (action.get("ratio") or "").strip()

        if "right" in atype:
            try:
                parts = ratio_str.split(":")
                if len(parts) == 2:
                    rights_ratio = float(parts[0]) / float(parts[1])
                    cum_price = None
                    for c in candles:
                        if str(c["trading_date"]) < bcd:
                            cum_price = float(c["close_price"])
                        else:
                            break
                    if cum_price and cum_price > 0:
                        sub_price = 100.0
                        terp = (cum_price + sub_price * rights_ratio) / (1.0 + rights_ratio)
                        factor = terp / cum_price
                        if 0 < factor < 1:
                            if not _is_dup_adjustment(adjustments, bcd, factor):
                                adjustments.append((bcd, factor))
            except (ValueError, ZeroDivisionError):
                pass
        elif "bonus" in atype or "split" in atype:
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

    adjustments.sort(key=lambda x: x[0])
    dates  = [str(c["trading_date"]) for c in candles]
    closes = [float(c["close_price"])                          for c in candles]
    opens  = [float(c.get("open_price")  or c["close_price"]) for c in candles]
    highs  = [float(c.get("high_price")  or c["close_price"]) for c in candles]
    lows   = [float(c.get("low_price")   or c["close_price"]) for c in candles]

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
#  DATA QUALITY
# ═══════════════════════════════════════════════════════════════════════

def forward_fill_zero_volume_days(candles):
    if not candles:
        return candles
    filled = []
    last_active_close = None
    zero_streak = 0
    for c in candles:
        row = dict(c)
        vol = int(row.get("volume") or 0)
        if vol == 0 and last_active_close is not None:
            zero_streak += 1
            row["open_price"]  = last_active_close
            row["high_price"]  = last_active_close
            row["low_price"]   = last_active_close
            row["close_price"] = last_active_close
            row["is_forward_filled"] = 1
        else:
            zero_streak = 0
            row["is_forward_filled"] = 0
            last_active_close = float(row["close_price"])
        row["forward_fill_streak"] = zero_streak
        row["forward_fill_limit_exceeded"] = int(zero_streak > MAX_FORWARD_FILL_STREAK)
        filled.append(row)
    return filled


def _max_forward_fill_streak(candles):
    max_streak = 0
    for c in candles:
        max_streak = max(max_streak, int(c.get("forward_fill_streak") or 0))
    return max_streak


def is_circuit_volatile(candles, lookback=5, threshold=2):
    if len(candles) < 2:
        return False
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    circuit_days = 0
    for i in range(1, len(recent)):
        prev_close = float(recent[i-1]["close_price"])
        curr_close = float(recent[i]["close_price"])
        if prev_close > 0:
            if abs(curr_close - prev_close) / prev_close >= CIRCUIT_LIMIT:
                circuit_days += 1
    return circuit_days > threshold


def is_low_liquidity(candles, min_avg_volume=None):
    if min_avg_volume is None:
        min_avg_volume = LOW_LIQ_THRESH
    if len(candles) < 5:
        return True
    vols = [int(c.get("volume") or 0) for c in candles[-20:]]
    avg_vol = sum(vols) / len(vols) if vols else 0
    return avg_vol < min_avg_volume

# ═══════════════════════════════════════════════════════════════════════
#  INDICATOR CALCULATIONS (same formulas as analysor)
# ═══════════════════════════════════════════════════════════════════════

def calc_sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def calc_ema(values, period):
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    ema = [seed]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def calc_rsi(closes, period=14):
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

def calc_macd(closes):
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if len(ema12) < 15 or not ema26:
        return None, None, None, []
    macd_line = [ema12[14 + i] - ema26[i] for i in range(len(ema26))]
    signal_line = calc_ema(macd_line, 9)
    if not signal_line:
        return macd_line[-1] if macd_line else None, None, None, macd_line
    macd_val = macd_line[-1]
    sig_val = signal_line[-1]
    histogram = macd_val - sig_val
    return (round(macd_val, 2), round(sig_val, 2), round(histogram, 2), macd_line)

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        hi = float(candles[i]["high_price"])
        lo = float(candles[i]["low_price"])
        pc = float(candles[i - 1]["close_price"])
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 2)


def calc_circuit_adjusted_atr(candles, period=14, circuit_weight=0.35):
    """ATR with circuit-day TR down-weighting to reduce circuit distortion."""
    if len(candles) < period + 1:
        return None

    trs = []
    for i in range(1, len(candles)):
        hi = float(candles[i]["high_price"])
        lo = float(candles[i]["low_price"])
        prev_close = float(candles[i - 1]["close_price"])
        close_now = float(candles[i]["close_price"])
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

def calc_stochastic(candles, k_period=14, d_period=3):
    if len(candles) < k_period:
        return None, None
    k_vals = []
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1: i + 1]
        highest = max(float(c["high_price"]) for c in window)
        lowest  = min(float(c["low_price"])  for c in window)
        close   = float(candles[i]["close_price"])
        if highest != lowest:
            k_vals.append((close - lowest) / (highest - lowest) * 100)
        else:
            k_vals.append(50.0)
    stoch_k = round(k_vals[-1], 1)
    stoch_d = round(sum(k_vals[-d_period:]) / min(len(k_vals), d_period), 1)
    return stoch_k, stoch_d

def calc_obv(closes, volumes):
    if len(closes) < 2:
        return [0]
    obv = [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv

def calc_obv_trend(closes, volumes, lookback=10):
    obv_series = calc_obv(closes, volumes)
    if len(obv_series) >= lookback:
        slope = obv_series[-1] - obv_series[-lookback]
        if slope > 0: return "RISING"
        if slope < 0: return "FALLING"
    return "FLAT"

def calc_vpt(closes, volumes):
    if len(closes) < 2:
        return [0]
    vpt = [0]
    for i in range(1, len(closes)):
        if closes[i - 1] != 0:
            vpt.append(vpt[-1] + volumes[i] * (closes[i] - closes[i-1]) / closes[i-1])
        else:
            vpt.append(vpt[-1])
    return vpt

def calc_roc(closes, n):
    if len(closes) <= n or closes[-n-1] == 0:
        return None
    return round((closes[-1] - closes[-n-1]) / closes[-n-1] * 100, 2)

def calc_bollinger_bands(closes, period=20, std_dev=2):
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((c - middle)**2 for c in window) / period
    sigma = variance ** 0.5
    upper = middle + std_dev * sigma
    lower = middle - std_dev * sigma
    return round(upper, 2), round(middle, 2), round(lower, 2)

def is_bollinger_squeeze(upper, middle, lower):
    if upper is None or middle is None or lower is None or middle == 0:
        return False
    return (upper - lower) / middle < 0.04

def is_bollinger_breakout(close, upper, vol_ratio):
    if upper is None:
        return False
    return close > upper and vol_ratio >= 1.5

def calc_pivot_points(h_prev, l_prev, c_prev):
    p = (h_prev + l_prev + c_prev) / 3
    r1 = (2 * p) - l_prev
    s1 = (2 * p) - h_prev
    hl = h_prev - l_prev
    return {
        "P": round(p, 2), "R1": round(r1, 2), "S1": round(s1, 2),
        "R1_fib": round(p + 0.382 * hl, 2), "S1_fib": round(p - 0.382 * hl, 2),
        "R2_fib": round(p + 0.618 * hl, 2), "S2_fib": round(p - 0.618 * hl, 2),
    }

def calc_fibonacci_retracement(swing_low, swing_high):
    diff = swing_high - swing_low
    return {
        "fib_382": round(swing_high - 0.382 * diff, 2),
        "fib_500": round(swing_high - 0.500 * diff, 2),
        "fib_618": round(swing_high - 0.618 * diff, 2),
    }

def detect_candlestick_patterns(candles):
    if len(candles) < 2:
        return []
    patterns = []
    c = candles[-1]
    p = candles[-2]
    if any(int(x.get("is_synthetic_open") or 0) for x in (c, p)):
        return []
    if any(int(x.get("forward_fill_limit_exceeded") or 0) for x in (c, p)):
        return []
    o  = float(c["open_price"])
    h  = float(c["high_price"])
    l  = float(c["low_price"])
    cl = float(c["close_price"])
    hl = h - l
    body = abs(o - cl)
    if hl <= 0:
        return []
    if body <= 0.05 * hl:
        patterns.append("Doji")
    closes_20 = [float(candles[i]["close_price"]) for i in range(max(0, len(candles)-20), len(candles))]
    sma20 = sum(closes_20) / len(closes_20) if closes_20 else cl
    prev_close = float(p["close_price"])
    if prev_close < sma20:
        if (body <= 0.3 * hl and min(o, cl) - l >= 2 * body and h - max(o, cl) <= 0.1 * hl):
            patterns.append("Hammer")
    po = float(p["open_price"])
    pc = float(p["close_price"])
    if pc < po and cl > o and o < pc and cl > po:
        patterns.append("Bullish Engulfing")
    return patterns

def calc_stop_loss(entry_price, atr, multiplier=None):
    if multiplier is None:
        multiplier = ATR_SL_MULT
    if atr is None or atr <= 0:
        return round(entry_price * 0.95, 2)
    return round(entry_price - multiplier * atr, 2)

def calc_targets(entry_price, atr):
    if atr is None or atr <= 0:
        return round(entry_price * 1.05, 2), round(entry_price * 1.10, 2)
    t1 = round(entry_price + ATR_T1_MULT * atr, 2)
    t2 = round(entry_price + ATR_T2_MULT * atr, 2)
    return t1, t2

def calc_position_size(entry_price, stop_price, account_equity=None, risk_pct=None,
                       avg_volume=None, max_trade_pct=MAX_POSITION_SHARE_OF_AVG_VOL,
                       max_alloc_pct=MAX_CAPITAL_ALLOCATION_PCT):
    if account_equity is None:
        account_equity = ACCOUNT_EQUITY
    if risk_pct is None:
        risk_pct = RISK_PCT
    risk_amount = account_equity * risk_pct
    gap = abs(entry_price - stop_price)
    if gap <= 0:
        return 0
    size = max(1, int(risk_amount / gap))

    if entry_price > 0:
        max_by_capital = int(account_equity / entry_price)
        if max_by_capital > 0:
            size = min(size, max_by_capital)

        max_by_allocation = int((account_equity * max_alloc_pct) / entry_price)
        if max_by_allocation > 0:
            size = min(size, max_by_allocation)

    if avg_volume is not None:
        try:
            avg_vol_num = float(avg_volume)
        except Exception:
            avg_vol_num = 0.0
        if avg_vol_num > 0:
            max_by_liquidity = int(avg_vol_num * max_trade_pct)
            if max_by_liquidity > 0:
                size = min(size, max_by_liquidity)

    return max(1, size)

def calc_rr_ratio(entry, stop, target):
    risk = abs(entry - stop)
    if risk <= 0:
        return 0
    return round((target - entry) / risk, 1)

def calc_mfi(candles, period=14):
    """Money Flow Index (0-100)."""
    if len(candles) < period + 1:
        return None
    pos_flow = 0
    neg_flow = 0
    for i in range(len(candles) - period, len(candles)):
        tp_curr = (float(candles[i]["high_price"]) + float(candles[i]["low_price"]) + float(candles[i]["close_price"])) / 3
        tp_prev = (float(candles[i-1]["high_price"]) + float(candles[i-1]["low_price"]) + float(candles[i-1]["close_price"])) / 3
        mf = tp_curr * int(candles[i].get("volume") or 0)
        if tp_curr > tp_prev:
            pos_flow += mf
        else:
            neg_flow += mf
    if neg_flow == 0:
        return 100.0
    ratio = pos_flow / neg_flow
    return round(100 - 100 / (1 + ratio), 1)

def calc_vwap(ticks):
    """Calculate VWAP from intraday ticks."""
    if not ticks:
        return None
    cum_pv = 0
    cum_vol = 0
    for t in ticks:
        price = float(t.get("contract_rate") or 0)
        qty = int(t.get("contract_quantity") or 0)
        if price > 0 and qty > 0:
            cum_pv += price * qty
            cum_vol += qty
    if cum_vol == 0:
        return None
    return round(cum_pv / cum_vol, 2)


def _coerce_tick_datetime(tick):
    created = tick.get("created_at")
    if created:
        try:
            return datetime.fromisoformat(str(created).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass

    unix_time = tick.get("unix_time")
    if unix_time is None:
        return None
    try:
        ts = int(unix_time)
        if ts > 1_000_000_000_000:
            ts //= 1000
        return datetime.fromtimestamp(ts)
    except Exception:
        return None


def assess_intraday_data_quality(ticks):
    """Assess whether intraday ticks are complete enough to trust VWAP."""
    if not ticks:
        return {
            "tick_count": 0,
            "session_minutes": 0,
            "is_complete": False,
            "reason": "No intraday ticks available",
        }

    times = [_coerce_tick_datetime(t) for t in ticks]
    times = [t for t in times if t is not None]
    if not times:
        return {
            "tick_count": len(ticks),
            "session_minutes": 0,
            "is_complete": False,
            "reason": "Intraday ticks missing usable timestamps",
        }

    start_ts = min(times)
    end_ts = max(times)
    session_minutes = max(0, int((end_ts - start_ts).total_seconds() // 60))
    tick_count = len(ticks)

    if tick_count < MIN_INTRADAY_TICKS_FOR_VWAP:
        return {
            "tick_count": tick_count,
            "session_minutes": session_minutes,
            "is_complete": False,
            "reason": f"Too few intraday ticks ({tick_count} < {MIN_INTRADAY_TICKS_FOR_VWAP})",
        }

    if session_minutes < MIN_INTRADAY_SESSION_MINUTES:
        return {
            "tick_count": tick_count,
            "session_minutes": session_minutes,
            "is_complete": False,
            "reason": (
                "Intraday session coverage too short "
                f"({session_minutes}m < {MIN_INTRADAY_SESSION_MINUTES}m)"
            ),
        }

    return {
        "tick_count": tick_count,
        "session_minutes": session_minutes,
        "is_complete": True,
        "reason": "Intraday session completeness check passed",
    }


def _is_fundamental_stale(fund_row, max_age_days=FUNDAMENTAL_STALE_DAYS):
    if not fund_row:
        return True
    published = str(fund_row.get("published_date") or "")[:10]
    if not published:
        return True
    try:
        days_old = (datetime.now().date() - datetime.strptime(published, "%Y-%m-%d").date()).days
        return days_old > max_age_days
    except Exception:
        return True


def _compute_data_confidence(*, bars, avg_volume, circuit_volatile, liquidity_flag,
                             fundamental_stale, intraday_complete, has_live_price,
                             has_full_52w_context, excessive_forward_fill):
    score = 100
    if bars < 252:
        score -= 15
    if avg_volume < 10_000:
        score -= 15
    if liquidity_flag:
        score -= 10
    if circuit_volatile:
        score -= 15
    if fundamental_stale:
        score -= 10
    if not intraday_complete:
        score -= 10
    if not has_live_price:
        score -= 5
    if not has_full_52w_context:
        score -= 10
    if excessive_forward_fill:
        score -= 10
    return max(0, min(100, int(score)))


# ═══════════════════════════════════════════════════════════════════════
#  SIGNAL CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

def classify_signal(*, rsi, macd_hist, cross, bb_pct, price,
                    sma20, sma50, sma200, vol_ratio, obv_trend,
                    stoch_k, stoch_d, breakout_candidate):
    score = 0
    if rsi is not None:
        if rsi < RSI_OVERSOLD: score += 2
        elif rsi < 40: score += 1
        elif rsi > RSI_OVERBOUGHT: score -= 2
        elif rsi > 65: score -= 1
    if macd_hist is not None:
        if macd_hist > 0: score += 1
        else: score -= 1
    if cross == "GOLDEN": score += 2
    elif cross == "BULLISH": score += 1
    elif cross == "DEATH": score -= 2
    elif cross == "BEARISH": score -= 1
    if bb_pct is not None:
        if bb_pct < 20: score += 1
        elif bb_pct > 80: score -= 1
    if sma20 and sma50 and price > sma20 > sma50: score += 1
    elif sma50 and price < sma50: score -= 1
    if sma200 and price < sma200: score -= 2
    if vol_ratio >= 1.5 and macd_hist is not None and macd_hist > 0: score += 1
    if vol_ratio >= 1.5 and macd_hist is not None and macd_hist < 0: score -= 1
    if obv_trend == "RISING": score += 1
    elif obv_trend == "FALLING": score -= 1
    if stoch_k is not None and stoch_d is not None:
        if stoch_k < 20 and stoch_k > stoch_d: score += 1
        elif stoch_k > 80 and stoch_k < stoch_d: score -= 1
    if breakout_candidate: score += 2

    if score >= 5: return "STRONG BUY"
    elif score >= 2: return "BUY"
    elif score <= -5: return "STRONG SELL"
    elif score <= -2: return "SELL"
    return "HOLD"


def calc_confidence(signal, rsi, macd_hist, vol_ratio, obv_trend,
                    cross, bb_pct, asym_score):
    conf = 50
    if signal in ("STRONG BUY", "STRONG SELL"): conf = 80
    elif signal in ("BUY", "SELL"): conf = 65
    if rsi is not None and (rsi < 25 or rsi > 75): conf += 5
    if macd_hist is not None and abs(macd_hist) > 2: conf += 5
    if vol_ratio >= 2.0: conf += 5
    if obv_trend in ("RISING", "FALLING"): conf += 3
    if cross in ("GOLDEN", "DEATH"): conf += 10
    if asym_score > 70 or asym_score < 30: conf += 5
    return min(100, max(0, conf))


# ═══════════════════════════════════════════════════════════════════════
#  SCORE BREAKDOWN (Technical, Fundamental, Volume, Backtest)
# ═══════════════════════════════════════════════════════════════════════

def calc_technical_score(a):
    """Technical sub-score (0-100), weight: 30%."""
    score = 50
    if a.get("sma20") and a.get("sma50") and a.get("sma200"):
        if a["price"] > a["sma20"] > a["sma50"] > a["sma200"]: score = 95
        elif a["price"] > a["sma20"] and a["price"] > a["sma50"]: score = 75
        elif a["price"] > a["sma50"]: score = 60
        elif a["price"] < a["sma50"] and a["price"] < a["sma200"]: score = 15
        else: score = 35
    elif a.get("sma20") and a.get("sma50"):
        if a["price"] > a["sma20"] > a["sma50"]: score = 75
        elif a["price"] > a["sma50"]: score = 60
        else: score = 35

    # RSI positioning
    rsi = a.get("rsi")
    if rsi is not None:
        if 40 <= rsi <= 60: score += 5    # healthy zone
        elif rsi < RSI_OVERSOLD: score += 10  # potential reversal
        elif rsi > RSI_OVERBOUGHT: score -= 10

    # MACD
    if a.get("macd_hist") is not None:
        if a["macd_hist"] > 0: score += 5
        else: score -= 5
    if a.get("macd_just_bullish"): score += 10

    # Patterns
    for p in a.get("patterns", []):
        score += 5

    # 52W proximity
    if a.get("high_prox") is not None and a["high_prox"] < 5: score += 10

    return min(100, max(0, round(score)))


def calc_fundamental_score(fund):
    """Fundamental sub-score (0-100), weight: 35%."""
    if not fund:
        return 50  # no data
    score = 0
    eps = float(fund.get("eps") or 0)
    pe  = float(fund.get("pe_ratio") or 0)
    bv  = float(fund.get("book_value") or 0)

    price_approx = eps * pe if eps and pe else 0
    pbv = price_approx / bv if bv > 0 else None

    if 0 < pe <= 15: score += 25
    elif 15 < pe <= 25: score += 18
    elif 25 < pe <= 40: score += 10

    if eps > 30: score += 20
    elif eps > 15: score += 16
    elif eps > 5: score += 12
    elif eps > 0: score += 8

    if pbv and pbv < 1.5: score += 15
    elif pbv and pbv < 3: score += 8

    div_yield = float(fund.get("div_yield") or 0)
    if div_yield > 5: score += 10
    elif div_yield > 2: score += 5

    roe = float(fund.get("roe") or 0)
    if roe > 20: score += 10
    elif roe > 10: score += 5

    return min(100, max(0, round(score)))


def calc_volume_score(a):
    """Volume sub-score (0-100), weight: 15%."""
    score = 50
    vr = min(a.get("vol_ratio", 1), 5)
    score += (vr - 1) * 10
    if a.get("obv_trend") == "RISING": score += 15
    elif a.get("obv_trend") == "FALLING": score -= 15
    mfi = a.get("mfi")
    if mfi is not None:
        if 40 <= mfi <= 60: score += 5
        elif mfi > 80: score -= 5
        elif mfi < 20: score += 5
    return min(100, max(0, round(score)))


def calc_backtest_score(a):
    """Backtest / risk-adjusted score (0-100), weight: 20%.
    Uses volatility, drawdown, and risk metrics as proxy backtesting."""
    score = 70
    if a.get("atr") and a["price"] > 0:
        atr_pct = a["atr"] / a["price"] * 100
        if atr_pct > 5: score -= 25
        elif atr_pct > 3: score -= 12
        elif atr_pct < 1.5: score += 10
    if a.get("vol_20d", 0) > 3: score -= 15
    elif a.get("vol_20d", 0) < 1: score += 10
    if a.get("max_drawdown", 0) > 30: score -= 15
    elif a.get("max_drawdown", 0) < 10: score += 10
    rr = a.get("rr_ratio", 0)
    if rr >= 3: score += 10
    elif rr >= 2: score += 5
    elif rr < 1.5: score -= 10
    return min(100, max(0, round(score)))


# ═══════════════════════════════════════════════════════════════════════
#  STRENGTHS & WEAKNESSES
# ═══════════════════════════════════════════════════════════════════════

def build_strengths(a, fund):
    """Return list of strength strings."""
    strengths = []
    if a.get("sma20") and a.get("sma50") and a["price"] > a["sma20"] > a["sma50"]:
        strengths.append("Strong uptrend — Price above SMA20 and SMA50")
    if a.get("cross") == "GOLDEN":
        strengths.append("Golden Cross — SMA20 crossed above SMA50")
    if a.get("rsi") and 40 <= a["rsi"] <= 60:
        strengths.append(f"RSI in healthy zone ({a['rsi']:.1f})")
    if a.get("rsi") and a["rsi"] < RSI_OVERSOLD:
        strengths.append(f"RSI oversold at {a['rsi']:.1f} — Potential bounce")
    if a.get("macd_just_bullish"):
        strengths.append("Bullish MACD crossover just occurred")
    if a.get("macd_hist") and a["macd_hist"] > 0:
        strengths.append(f"Positive MACD histogram ({a['macd_hist']:.2f})")
    if a.get("vol_ratio", 0) >= 1.5:
        strengths.append(f"Volume surge ({a['vol_ratio']:.1f}x average)")
    if a.get("obv_trend") == "RISING":
        strengths.append("OBV rising — Accumulation phase")
    if a.get("asym_score", 50) > 65:
        strengths.append(f"Smart money accumulating (Score: {a['asym_score']:.0f})")
    if a.get("high_prox") is not None and a["high_prox"] < 5:
        strengths.append(f"Near 52-week high (within {a['high_prox']:.1f}%)")
    if a.get("bb_squeeze"):
        strengths.append("Bollinger squeeze — Volatility contraction")
    if a.get("bb_breakout"):
        strengths.append("Bollinger breakout with volume confirmation")
    if "Hammer" in a.get("patterns", []):
        strengths.append("Hammer pattern — Bullish reversal signal")
    if "Bullish Engulfing" in a.get("patterns", []):
        strengths.append("Bullish engulfing pattern")
    if a.get("rr_ratio", 0) >= 3:
        strengths.append(f"Excellent R:R ratio ({a['rr_ratio']:.1f}:1)")
    if fund:
        pe = float(fund.get("pe_ratio") or 0)
        if 0 < pe < 15:
            strengths.append(f"Low P/E ratio ({pe:.1f}) — Value play")
        eps = float(fund.get("eps") or 0)
        if eps > 20:
            strengths.append(f"Strong EPS (Rs. {eps:.2f})")
        div_yield = float(fund.get("div_yield") or 0)
        if div_yield > 3:
            strengths.append(f"Good dividend yield ({div_yield:.1f}%)")
    return strengths


def build_weaknesses(a, fund):
    """Return list of weakness strings."""
    weaknesses = []
    if a.get("sma50") and a["price"] < a["sma50"]:
        weaknesses.append("Below SMA50 — Potential downtrend")
    if a.get("sma200") and a["price"] < a["sma200"]:
        weaknesses.append("Below SMA200 — Long-term downtrend")
    if a.get("cross") == "DEATH":
        weaknesses.append("Death Cross — SMA20 crossed below SMA50")
    if a.get("rsi") and a["rsi"] > RSI_OVERBOUGHT:
        weaknesses.append(f"RSI overbought ({a['rsi']:.1f})")
    if a.get("macd_hist") is not None and a["macd_hist"] < 0:
        weaknesses.append(f"Negative MACD histogram ({a['macd_hist']:.2f})")
    if a.get("macd_just_bearish"):
        weaknesses.append("Bearish MACD crossover just occurred")
    if a.get("obv_trend") == "FALLING":
        weaknesses.append("OBV falling — Distribution phase")
    if a.get("vpt_bearish_div"):
        weaknesses.append("VPT bearish divergence — Price vs volume diverging")
    if a.get("fib_618_broken"):
        weaknesses.append("Below Fibonacci 61.8% — Trend invalidated")
    if a.get("circuit_flag"):
        weaknesses.append("Circuit breaker history — High volatility risk")
    if a.get("liquidity_flag"):
        weaknesses.append("Low liquidity — Difficult to exit positions")
    if a.get("vol_20d", 0) > 3:
        weaknesses.append(f"High volatility ({a['vol_20d']:.1f}% daily std dev)")
    if a.get("max_drawdown", 0) > 30:
        weaknesses.append(f"Large max drawdown ({a['max_drawdown']:.1f}%)")
    if a.get("sell_dist_pct", 0) > 50:
        weaknesses.append("High sell-side concentration from brokers")
    if a.get("rr_ratio", 0) < 1.5:
        weaknesses.append(f"Poor R:R ratio ({a.get('rr_ratio', 0):.1f}:1)")
    if fund:
        pe = float(fund.get("pe_ratio") or 0)
        if pe > 40:
            weaknesses.append(f"Very high P/E ({pe:.1f}) — Overvaluation risk")
    month = datetime.now().month
    if month in (1, 2):
        weaknesses.append("Post-festive seasonal weakness period")
    data_conf = int(a.get("data_confidence") or 0)
    if data_conf < 60:
        weaknesses.append(f"Low data confidence ({data_conf}/100) — signal reliability reduced")
    elif data_conf < 75:
        weaknesses.append(f"Moderate data confidence ({data_conf}/100)")
    return weaknesses


# ═══════════════════════════════════════════════════════════════════════
#  TREND DETERMINATION
# ═══════════════════════════════════════════════════════════════════════

def determine_trend(a):
    """Return human-readable trend string."""
    price = a.get("price", 0)
    sma20 = a.get("sma20")
    sma50 = a.get("sma50")
    sma200 = a.get("sma200")

    if sma20 and sma50 and sma200:
        if price > sma20 > sma50 > sma200:
            return "Strong Uptrend"
        elif price > sma20 and price > sma50:
            return "Uptrend"
        elif price < sma20 < sma50 < sma200:
            return "Strong Downtrend"
        elif price < sma50:
            return "Downtrend"
    elif sma20 and sma50:
        if price > sma20 > sma50:
            return "Uptrend"
        elif price < sma50:
            return "Downtrend"

    cross = a.get("cross", "NEUTRAL")
    if cross == "GOLDEN": return "Strong Uptrend"
    if cross == "DEATH": return "Strong Downtrend"
    if cross == "BULLISH": return "Uptrend"
    if cross == "BEARISH": return "Downtrend"
    return "Sideways"


# ═══════════════════════════════════════════════════════════════════════
#  EPS GROWTH CALCULATION
# ═══════════════════════════════════════════════════════════════════════

def calc_eps_growth(fundamentals_list):
    """Calculate EPS growth from most recent two entries."""
    if len(fundamentals_list) < 2:
        return None
    curr_eps = float(fundamentals_list[0].get("eps") or 0)
    prev_eps = float(fundamentals_list[1].get("eps") or 0)
    if prev_eps == 0:
        return None
    return round((curr_eps - prev_eps) / abs(prev_eps) * 100, 1)


# ═══════════════════════════════════════════════════════════════════════
#  BROKER ACTIVITY CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

def classify_broker_activity(broker_summary, asym_score):
    """Classify as SMART MONEY BUYING/SELLING/NEUTRAL."""
    if asym_score > 65:
        return "SMART MONEY BUYING"
    elif asym_score < 35:
        return "SMART MONEY SELLING"
    return "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════
#  RISK LEVEL
# ═══════════════════════════════════════════════════════════════════════

def determine_risk_level(a):
    vol = a.get("vol_20d", 0)
    if vol > 3: return "High"
    if vol > 1.5: return "Medium"
    return "Low"


# ═══════════════════════════════════════════════════════════════════════
#  CHART DATA BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def build_price_chart_data(candles, num_days=60):
    """Build price + volume chart data for Chart.js (last N days)."""
    recent = candles[-num_days:] if len(candles) >= num_days else candles
    labels = []
    prices = []
    volumes = []
    sma20_data = []
    sma50_data = []

    all_closes = [float(c["close_price"]) for c in candles]

    for i, c in enumerate(recent):
        idx = len(candles) - len(recent) + i
        labels.append(str(c["trading_date"])[:10])
        prices.append(round(float(c["close_price"]), 2))
        volumes.append(int(c.get("volume") or 0))

        # SMA20
        if idx >= 19:
            sma20_data.append(round(sum(all_closes[idx-19:idx+1]) / 20, 2))
        else:
            sma20_data.append(None)

        # SMA50
        if idx >= 49:
            sma50_data.append(round(sum(all_closes[idx-49:idx+1]) / 50, 2))
        else:
            sma50_data.append(None)

    return {
        "labels": labels,
        "prices": prices,
        "volumes": volumes,
        "sma20": sma20_data,
        "sma50": sma50_data,
    }


def build_intraday_chart_data(ticks):
    """Build intraday price chart data."""
    if not ticks:
        return None
    labels = []
    prices = []
    volumes = []
    for t in ticks:
        ts = t.get("unix_time")
        if ts:
            try:
                ts_int = int(ts)
                # unix_time is in seconds (e.g. 1771305360 = 2026)
                # If it looks like milliseconds (>1e12), convert
                if ts_int > 1e12:
                    ts_int = ts_int // 1000
                dt = datetime.fromtimestamp(ts_int)
                labels.append(dt.strftime("%H:%M"))
            except:
                labels.append(str(ts))
        else:
            labels.append("")
        prices.append(float(t.get("contract_rate") or 0))
        volumes.append(int(t.get("contract_quantity") or 0))
    return {"labels": labels, "prices": prices, "volumes": volumes}


# ═══════════════════════════════════════════════════════════════════════
#  MAIN SINGLE-STOCK ANALYSIS ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════

def analyze_single_stock(symbol, quiet=False):
    """Run comprehensive single-stock analysis. Returns full data dict.
    If quiet=True, suppress per-step progress output (used in --all mode).
    """
    def log(msg):
        if not quiet:
            print(msg)

    log(f"\n{'=' * 65}")
    log(f"  📊 NEPSE Single Stock Analyser — {symbol}")
    log(f"{'=' * 65}")

    conn = get_conn()
    try:
        log(f"\n  🔌 Connected to database")
        log(f"  📈 Analyzing {symbol}...\n")

        # ── FETCH ALL DATA ──
        log(f"  [1/8] Fetching OHLCV data...")
        raw_candles = fetch_ohlcv(conn, symbol)
        if not raw_candles:
            log(f"  ❌ No OHLCV data found for {symbol}")
            return None

        corp_actions = fetch_corp_actions(conn, symbol)
        dividends = fetch_dividends(conn, symbol)

        log(f"  [2/8] Fetching company info...")
        company = fetch_company_details(conn, symbol)
        security = fetch_security_info(conn, symbol)
        snap52 = fetch_52w_snapshot(conn, symbol)
        live_ltp_row = fetch_live_ltp(conn, symbol)

        log(f"  [3/8] Fetching fundamentals...")
        fund_list = fetch_fundamentals(conn, symbol)
        fund = fund_list[0] if fund_list else {}
        fundamental_stale = _is_fundamental_stale(fund)

        log(f"  [4/8] Fetching intraday data...")
        intraday_ticks = fetch_intraday_ticks(conn, symbol)
        intraday_quality = assess_intraday_data_quality(intraday_ticks)
        vwap = calc_vwap(intraday_ticks) if intraday_quality["is_complete"] else None

        log(f"  [5/8] Fetching broker activity...")
        broker_summary = fetch_broker_summary(conn, symbol)

        log(f"  [6/8] Fetching market context...")
        market_ctx = fetch_market_context(conn)
        ranking = fetch_scrip_ranking(conn, symbol)

        # ── ADJUST & PREPARE DATA ──
        log(f"  [7/8] Computing indicators...")
        # Bridge: append live candle if daily_ohlcv lags behind
        bridged_candles = bridge_live_candle(raw_candles, live_ltp_row)
        candles = get_adjusted_series(bridged_candles, corp_actions, dividends)
        candles = forward_fill_zero_volume_days(candles)
        max_fill_streak = _max_forward_fill_streak(candles)

        if len(candles) < 20:
            log(f"  ❌ Insufficient data for {symbol} ({len(candles)} candles)")
            return None

        closes  = [float(c["close_price"]) for c in candles]
        volumes = [int(c.get("volume") or 0) for c in candles]

        # Use live LTP as the display price (matches official NEPSE website).
        # Fall back to adjusted close only if live data isn't available.
        if live_ltp_row and float(live_ltp_row.get("last_traded_price") or 0) > 0:
            price = float(live_ltp_row["last_traded_price"])
            has_live_price = True
        else:
            price = closes[-1]
            has_live_price = False

        if price <= 0:
            log(f"  ❌ Invalid price for {symbol}")
            return None

        # ── FLAGS ──
        circuit_flag = is_circuit_volatile(candles)
        liquidity_flag = is_low_liquidity(candles)

        # ── MOVING AVERAGES ──
        sma5   = calc_sma(closes, 5)
        sma10  = calc_sma(closes, 10)
        sma20  = calc_sma(closes, 20)
        sma50  = calc_sma(closes, 50)
        sma200 = calc_sma(closes, 200)

        # ── RSI ──
        rsi = calc_rsi(closes) if len(candles) >= MIN_BARS_RSI else None

        # ── MACD ──
        macd_val, sig_val, macd_hist, macd_line = (None, None, None, [])
        macd_just_bullish = False
        macd_just_bearish = False
        if len(candles) >= MIN_BARS_MACD:
            macd_val, sig_val, macd_hist, macd_line = calc_macd(closes)
            if macd_line and len(macd_line) >= 2:
                signal_ema = calc_ema(macd_line, 9)
                if len(signal_ema) >= 2:
                    prev_hist = macd_line[-2] - signal_ema[-2]
                    curr_hist = macd_line[-1] - signal_ema[-1]
                    if prev_hist <= 0 and curr_hist > 0: macd_just_bullish = True
                    if prev_hist >= 0 and curr_hist < 0: macd_just_bearish = True

        # ── ATR ──
        atr = calc_circuit_adjusted_atr(candles) if len(candles) >= MIN_BARS_ATR else None
        if atr is None and len(candles) >= MIN_BARS_ATR:
            atr = calc_atr(candles)

        # ── STOCHASTIC ──
        stoch_k, stoch_d = (None, None)
        if len(candles) >= MIN_BARS_STOCH:
            stoch_k, stoch_d = calc_stochastic(candles)

        # ── OBV ──
        obv_trend = calc_obv_trend(closes, volumes)
        obv_series = calc_obv(closes, volumes)

        # ── VPT ──
        vpt_series = calc_vpt(closes, volumes)
        vpt_bearish_div = False
        if len(closes) >= 20 and len(vpt_series) >= 20:
            price_recent_high = max(closes[-10:])
            price_prev_high   = max(closes[-20:-10])
            vpt_recent_high   = max(vpt_series[-10:])
            vpt_prev_high     = max(vpt_series[-20:-10])
            if price_recent_high > price_prev_high and vpt_recent_high < vpt_prev_high:
                vpt_bearish_div = True

        # ── ROC ──
        roc_20 = calc_roc(closes, 20)
        roc_60 = calc_roc(closes, 60) if len(closes) > MIN_BARS_ROC60 else None

        # ── BOLLINGER BANDS ──
        bb_upper, bb_middle, bb_lower = (None, None, None)
        if len(candles) >= MIN_BARS_BB:
            bb_upper, bb_middle, bb_lower = calc_bollinger_bands(closes)
        bb_squeeze = is_bollinger_squeeze(bb_upper, bb_middle, bb_lower)
        vol_avg = sum(volumes[-20:]) / min(len(volumes[-20:]), 20) if volumes else 0
        vol_ratio = round(volumes[-1] / vol_avg, 2) if vol_avg > 0 else 0
        bb_breakout = is_bollinger_breakout(price, bb_upper, vol_ratio)
        bb_pct = None
        if bb_upper is not None and bb_lower is not None and bb_upper != bb_lower:
            bb_pct = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1)

        # ── MFI ──
        mfi = calc_mfi(candles)

        # ── 52-WEEK HIGH/LOW ──
        hi52 = (float(snap52.get("hi52") or 0)
                or float(company.get("fifty_two_week_high") or 0)
                or (max(closes[-252:]) if len(closes) >= 252 else max(closes)))
        lo52 = (float(snap52.get("lo52") or 0)
                or float(company.get("fifty_two_week_low") or 0)
                or (min(closes[-252:]) if len(closes) >= 252 else min(closes)))
        has_full_52w_context = len(closes) >= 252
        is_52w_proxy = not has_full_52w_context

        sector = (company.get("sector_name")
                  or security.get("sector_name")
                  or "")
        company_name = (company.get("security_name")
                        or security.get("security_name")
                        or symbol)

        high_prox = round((hi52 - price) / hi52 * 100, 1) if hi52 > 0 else 100
        range_pct = round((price - lo52) / (hi52 - lo52) * 100, 1) if hi52 != lo52 else 50

        # ── PIVOT POINTS ──
        pivots = {}
        if len(candles) >= 2:
            prev = candles[-2]
            pivots = calc_pivot_points(
                float(prev["high_price"]),
                float(prev["low_price"]),
                float(prev["close_price"]))

        # ── FIBONACCI ──
        fib = {}
        if hi52 > lo52:
            fib = calc_fibonacci_retracement(lo52, hi52)
        fib_618_broken = price < fib.get("fib_618", 0) if fib else False

        # ── CANDLESTICK PATTERNS ──
        patterns = detect_candlestick_patterns(candles) if len(candles) >= 2 else []

        # ── MA CROSSOVERS ──
        cross = "NEUTRAL"
        if sma20 is not None and sma50 is not None and len(closes) >= 51:
            prev_sma20 = sum(closes[-21:-1]) / 20
            prev_sma50 = sum(closes[-51:-1]) / 50
            if sma20 > sma50 and prev_sma20 <= prev_sma50: cross = "GOLDEN"
            elif sma20 < sma50 and prev_sma20 >= prev_sma50: cross = "DEATH"
            elif sma20 > sma50: cross = "BULLISH"
            else: cross = "BEARISH"

        # ── STOP / TARGETS ──
        stop_loss = calc_stop_loss(price, atr)
        target1, target2 = calc_targets(price, atr)
        rr_ratio = calc_rr_ratio(price, stop_loss, target1)
        position_size = calc_position_size(price, stop_loss, avg_volume=vol_avg)

        # ── BREAKOUT ──
        breakout_52w = price >= hi52 and vol_ratio > 1.2
        breakout_candidate = False
        if sma50 is not None:
            breakout_candidate = (price > sma50 and price >= 0.98 * hi52
                                  and vol_ratio >= 1.5 and (macd_hist or 0) > 0)

        # ── BROKER METRICS ──
        # Compute asymmetry score from broker summary
        total_buy = sum(float(b.get("total_amt") or 0) for b in broker_summary.get("buyers", []))
        total_sell = sum(float(s.get("total_amt") or 0) for s in broker_summary.get("sellers", []))
        buy_amts = sorted([float(b.get("total_amt") or 0) for b in broker_summary.get("buyers", [])], reverse=True)
        sell_amts = sorted([float(s.get("total_amt") or 0) for s in broker_summary.get("sellers", [])], reverse=True)
        buy_conc = sum(buy_amts[:3]) / total_buy * 100 if total_buy > 0 and buy_amts else 0
        sell_conc = sum(sell_amts[:3]) / total_sell * 100 if total_sell > 0 and sell_amts else 0
        raw_asym = buy_conc - sell_conc
        asym_score = max(0, min(100, round(50 + raw_asym / 2, 1)))
        broker_participants = set()
        broker_participants.update(
            str(b.get("buyer_broker_id"))
            for b in broker_summary.get("buyers", [])
            if b.get("buyer_broker_id") is not None
        )
        broker_participants.update(
            str(s.get("seller_broker_id"))
            for s in broker_summary.get("sellers", [])
            if s.get("seller_broker_id") is not None
        )
        broker_signal_reliability = "HIGH"
        if len(broker_participants) < MIN_BROKER_PARTICIPANTS or (total_buy + total_sell) < MIN_BROKER_TOTAL_VALUE:
            asym_score = 50.0
            broker_signal_reliability = "LOW"
        sell_dist_pct = sell_conc
        broker_activity = classify_broker_activity(broker_summary, asym_score)

        # ── VOLATILITY ──
        returns_20 = []
        if len(closes) >= 21:
            for i in range(-20, 0):
                if closes[i-1] > 0:
                    returns_20.append((closes[i] - closes[i-1]) / closes[i-1] * 100)
        vol_20d = 0
        if returns_20:
            mu = sum(returns_20) / len(returns_20)
            vol_20d = round((sum((r - mu)**2 for r in returns_20) / len(returns_20)) ** 0.5, 2)

        # Max drawdown
        peak, max_dd = closes[0], 0
        for c_val in closes:
            if c_val > peak: peak = c_val
            dd = (peak - c_val) / peak * 100
            if dd > max_dd: max_dd = dd

        # ── DAILY CHANGE ──
        prev_close = float(candles[-2]["close_price"]) if len(candles) >= 2 else price
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
        change_abs = round(price - prev_close, 2)

        data_confidence = _compute_data_confidence(
            bars=len(candles),
            avg_volume=vol_avg,
            circuit_volatile=circuit_flag,
            liquidity_flag=liquidity_flag,
            fundamental_stale=fundamental_stale,
            intraday_complete=intraday_quality.get("is_complete", False),
            has_live_price=has_live_price,
            has_full_52w_context=has_full_52w_context,
            excessive_forward_fill=max_fill_streak > MAX_FORWARD_FILL_STREAK,
        )

        data_quality_alerts = []
        if not intraday_quality.get("is_complete", False):
            data_quality_alerts.append(intraday_quality.get("reason") or "Intraday VWAP not trusted")
        if fundamental_stale:
            data_quality_alerts.append("Fundamental snapshot is stale")
        if is_52w_proxy:
            data_quality_alerts.append("52-week range is proxy-based (<252 sessions)")
        if broker_signal_reliability == "LOW":
            data_quality_alerts.append("Broker asymmetry reliability is low due to sparse participation")
        if not has_live_price:
            data_quality_alerts.append("Live market snapshot unavailable; using last adjusted close")
        if max_fill_streak > MAX_FORWARD_FILL_STREAK:
            data_quality_alerts.append(
                f"Extended zero-volume forward-fill streak ({max_fill_streak} sessions)"
            )

        # ── ANALYSIS DICT ──
        a = {
            "symbol": symbol, "company_name": company_name,
            "sector": sector, "price": price,
            "change_pct": change_pct, "change_abs": change_abs,
            "prev_close": prev_close,
            "sma5": sma5, "sma10": sma10, "sma20": sma20,
            "sma50": sma50, "sma200": sma200,
            "rsi": rsi, "macd_val": macd_val, "macd_hist": macd_hist,
            "macd_just_bullish": macd_just_bullish,
            "macd_just_bearish": macd_just_bearish,
            "atr": atr, "stoch_k": stoch_k, "stoch_d": stoch_d,
            "obv_trend": obv_trend, "vpt_bearish_div": vpt_bearish_div,
            "roc_20": roc_20, "roc_60": roc_60,
            "bb_upper": bb_upper, "bb_middle": bb_middle, "bb_lower": bb_lower,
            "bb_pct": bb_pct, "bb_squeeze": bb_squeeze, "bb_breakout": bb_breakout,
            "vol_ratio": vol_ratio, "vol_avg": vol_avg, "mfi": mfi, "vwap": vwap,
            "hi52": hi52, "lo52": lo52, "high_prox": high_prox, "range_pct": range_pct,
            "pivots": pivots, "fib": fib, "fib_618_broken": fib_618_broken,
            "patterns": patterns, "cross": cross,
            "stop_loss": stop_loss, "target1": target1, "target2": target2,
            "rr_ratio": rr_ratio, "position_size": position_size,
            "breakout_52w": breakout_52w, "breakout_candidate": breakout_candidate,
            "asym_score": asym_score, "sell_dist_pct": sell_dist_pct,
            "broker_activity": broker_activity,
            "vol_20d": vol_20d, "max_drawdown": round(max_dd, 1),
            "circuit_flag": circuit_flag, "liquidity_flag": liquidity_flag,
            "data_confidence": data_confidence,
            "max_forward_fill_streak": max_fill_streak,
            "fundamental_stale": fundamental_stale,
            "intraday_quality": intraday_quality,
            "vwap_trusted": bool(intraday_quality.get("is_complete", False) and vwap is not None),
            "has_full_52w_context": has_full_52w_context,
            "is_52w_proxy": is_52w_proxy,
            "broker_signal_reliability": broker_signal_reliability,
            "data_quality_alerts": data_quality_alerts,
        }

        # ── SIGNAL ──
        signal = classify_signal(
            rsi=rsi, macd_hist=macd_hist, cross=cross, bb_pct=bb_pct,
            price=price, sma20=sma20, sma50=sma50, sma200=sma200,
            vol_ratio=vol_ratio, obv_trend=obv_trend,
            stoch_k=stoch_k, stoch_d=stoch_d,
            breakout_candidate=breakout_candidate)
        confidence = calc_confidence(signal, rsi, macd_hist, vol_ratio, obv_trend,
                                     cross, bb_pct, asym_score)
        if data_confidence < 60:
            confidence = max(0, confidence - 15)
        elif data_confidence < 75:
            confidence = max(0, confidence - 7)
        a["signal"] = signal
        a["confidence"] = confidence

        # ── TREND ──
        a["trend"] = determine_trend(a)
        a["risk_level"] = determine_risk_level(a)

        # ── EPS GROWTH ──
        eps_growth = calc_eps_growth(fund_list)

        # ── FUNDAMENTAL DATA (must be built BEFORE calc_fundamental_score) ──
        fund_data = {
            "eps": float(fund.get("eps") or 0),
            "pe_ratio": float(fund.get("pe_ratio") or 0),
            "book_value": float(fund.get("book_value") or 0),
            "net_profit": float(fund.get("net_profit") or 0),
            "published_date": str(fund.get("published_date") or "")[:10],
            "fiscal_year": fund.get("fiscal_year", ""),
            "quarter": fund.get("quarter", ""),
            "roe": 0,
            "div_yield": 0,
            "pbv": None,
        }
        bv = fund_data["book_value"]
        f_eps = fund_data["eps"]
        f_pe = fund_data["pe_ratio"]
        if bv > 0:
            fund_data["pbv"] = round(price / bv, 2)
            if f_eps > 0:
                fund_data["roe"] = round(f_eps / bv * 100, 1)

        # Dividend yield
        div_cash = [d for d in dividends if float(d.get("cash_dividend_percent") or 0) > 0]
        if div_cash and price > 0:
            latest_div = float(div_cash[0].get("cash_dividend_percent") or 0)
            fund_data["div_yield"] = round(latest_div / price * 100, 2)

        a["fund_data"] = fund_data
        a["eps_growth"] = eps_growth

        # ── SCORE BREAKDOWN ──
        log(f"  [8/8] Computing scores...")
        tech_score = calc_technical_score(a)
        fund_score = calc_fundamental_score(fund_data)
        vol_score_val = calc_volume_score(a)
        bt_score = calc_backtest_score(a)

        # Composite: 30% Technical + 35% Fundamental + 15% Volume + 20% Backtest
        composite = (tech_score * 0.30 + fund_score * 0.35
                     + vol_score_val * 0.15 + bt_score * 0.20)

        # Modifiers
        broker_mod = 0
        if asym_score > 65: broker_mod = 5
        elif asym_score < 35: broker_mod = -5

        market_mod = 0
        idx_data = market_ctx.get("index", {})
        idx_chg = float(idx_data.get("change_percent") or 0)
        if idx_chg > 1: market_mod = 5
        elif idx_chg < -1: market_mod = -5

        sector_mod = 0  # Could be expanded with sector sub-index data

        modifier_total = broker_mod + market_mod + sector_mod
        if tech_score < 40 and modifier_total > 3:
            modifier_total = 3
        if data_confidence < 60:
            modifier_total -= 5

        composite = max(0, min(100, composite + modifier_total))

        a["tech_score"] = tech_score
        a["fund_score"] = fund_score
        a["vol_score"] = vol_score_val
        a["bt_score"] = bt_score
        a["composite"] = round(composite, 1)
        a["broker_mod"] = broker_mod
        a["market_mod"] = market_mod
        a["sector_mod"] = sector_mod
        a["modifier_total"] = modifier_total

        # ── STRENGTHS & WEAKNESSES ──
        a["strengths"] = build_strengths(a, fund_data)
        a["weaknesses"] = build_weaknesses(a, fund_data)

        # ── CHART DATA ──
        a["price_chart"] = build_price_chart_data(candles, 60)
        a["intraday_chart"] = build_intraday_chart_data(intraday_ticks)

        # ── BROKER DATA ──
        a["broker_summary"] = broker_summary

        # ── COMPANY INFO ──
        a["company_info"] = {
            "name": company_name,
            "sector": sector,
            "listing_date": str(company.get("listing_date") or ""),
            "market_cap": float(company.get("market_capitalization") or 0),
            "listed_shares": float(company.get("stock_listed_shares") or 0),
            "promoter_pct": float(company.get("promoter_percentage") or 0),
            "public_pct": float(company.get("public_percentage") or 0),
        }

        # ── MARKET CONTEXT ──
        a["market"] = market_ctx
        a["ranking"] = ranking

        # ── DIVIDEND HISTORY ──
        a["dividend_history"] = dividends[:10]

        # ── SECTOR PEERS ──
        peers = fetch_sector_peers(conn, sector, symbol)
        a["sector_peers"] = peers

        # ── CANDLE COUNT ──
        a["total_candles"] = len(candles)
        a["data_days"] = len(candles)

        log(f"\n  ✅ Analysis complete for {symbol}")
        log(f"     Signal: {signal} | Confidence: {confidence}% | Composite: {composite:.1f}/100")
        log(f"     Data confidence: {data_confidence}/100 | VWAP trusted: {a.get('vwap_trusted')} | 52W proxy: {a.get('is_52w_proxy')}")
        return a

    finally:
        conn.close()
        log(f"  🔌 Database connection closed.")
