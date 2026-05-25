"""
NEPSE Analytics Engine — Logic Module (v3.0)
All database queries, indicator calculations, analysis functions, and scoring.

Implements every formula from the NEPSE Quantitative Research Document:
  RSI (80/20 NEPSE thresholds), MACD, EMA, SMA, ATR, Stochastic,
  Bollinger Bands, OBV, VPT, ROC, Pivot Points, Fibonacci Retracement,
  Candlestick Patterns, Broker Intelligence, Composite Scoring, etc.
"""

import os, math
from datetime import datetime, timedelta
from collections import defaultdict

import pymysql
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

ACCOUNT_EQUITY = 100_000          # Rs 1 lakh default — change before running
RISK_PCT       = 0.015            # Risk 1.5% of equity per trade
ATR_SL_MULT    = 1.5              # Stop-loss = Entry − 1.5 × ATR
ATR_T1_MULT    = 2.0              # Target 1  = Entry + 2.0 × ATR
ATR_T2_MULT    = 3.5              # Target 2  = Entry + 3.5 × ATR
RSI_OVERBOUGHT = 80               # NEPSE-calibrated (not standard 70)
RSI_OVERSOLD   = 20               # NEPSE-calibrated (not standard 30)
MIN_BARS_RSI   = 100
MIN_BARS_MACD  = 35
MIN_BARS_BB    = 20
MIN_BARS_ATR   = 15
MIN_BARS_STOCH = 14
MIN_BARS_ROC60 = 61
MIN_BARS_SMA200= 200
LOW_LIQ_THRESH = 5000             # Min avg vol (SMA_20)
CIRCUIT_LIMIT  = 0.10             # Strict NEPSE 10% circuit threshold
MIN_RR_RATIO   = 2.0              # Minimum reward-to-risk ratio
MAX_FORWARD_FILL_STREAK = 5
LIVE_CANDLE_DEVIATION_BUFFER = 0.02

# Dynamic RSI thresholds tied to market regime
# Module-level cache — set during run_full_analysis() after regime is determined
_DYNAMIC_RSI = {"overbought": RSI_OVERBOUGHT, "oversold": RSI_OVERSOLD}

def set_dynamic_rsi(regime):
    """Set RSI thresholds based on market regime.
    STRONG_BULL: wider band (85/30) — don't sell too early in rallies
    NEUTRAL:     standard NEPSE (80/20)
    STRONG_BEAR: tighter band (70/15) — don't buy too early in crashes"""
    global _DYNAMIC_RSI
    r = regime.get("regime", "NEUTRAL")
    if r == "STRONG_BULL":
        _DYNAMIC_RSI = {"overbought": 85, "oversold": 30}
    elif r == "BULLISH":
        _DYNAMIC_RSI = {"overbought": 82, "oversold": 25}
    elif r == "STRONG_BEAR":
        _DYNAMIC_RSI = {"overbought": 70, "oversold": 15}
    elif r == "BEARISH":
        _DYNAMIC_RSI = {"overbought": 75, "oversold": 18}
    else:
        _DYNAMIC_RSI = {"overbought": RSI_OVERBOUGHT, "oversold": RSI_OVERSOLD}

def get_rsi_ob():
    """Get current dynamic overbought threshold."""
    return _DYNAMIC_RSI["overbought"]

def get_rsi_os():
    """Get current dynamic oversold threshold."""
    return _DYNAMIC_RSI["oversold"]


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
#  BATCH DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════

def fetch_all_ohlcv(conn):
    """Single query for ALL equity symbols.
    LEFT JOINs daily_prices to get real open_price (daily_ohlcv.open_price is always 0).
    Also appends symbol-date rows that exist in daily_prices but are missing in daily_ohlcv.
    JOINs securities to filter to Equity + NULL instrument_type only."""
    print("  [pre] Batch-fetching OHLCV data (with open_price fix)...")
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
        JOIN securities s ON do.symbol = s.symbol
        WHERE do.close_price > 0 AND do.close_price IS NOT NULL
          AND (s.instrument_type = 'Equity' OR s.instrument_type IS NULL)

        UNION ALL

        SELECT
            dp.symbol, dp.trading_date,
            COALESCE(NULLIF(dp.open_price, 0), dp.close_price) AS open_price,
            CASE WHEN NULLIF(dp.open_price, 0) IS NULL THEN 1 ELSE 0 END AS is_synthetic_open,
            dp.high_price, dp.low_price, dp.close_price, dp.volume
        FROM daily_prices dp
        JOIN securities s ON dp.symbol = s.symbol
        LEFT JOIN daily_ohlcv do
            ON do.symbol = dp.symbol AND do.trading_date = dp.trading_date
        WHERE do.symbol IS NULL
          AND dp.close_price > 0
          AND dp.trading_date < CURDATE()
          AND (s.instrument_type = 'Equity' OR s.instrument_type IS NULL)

        ORDER BY symbol, trading_date ASC
    """)
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)

def fetch_all_corp_actions(conn):
    rows = q(conn, """
        SELECT symbol, action_type, ratio, book_close_date
        FROM corporate_actions ORDER BY book_close_date ASC
    """)
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)

def fetch_all_dividends(conn):
    rows = q(conn, """
        SELECT symbol, bonus_share_percent, cash_dividend_percent, book_close_date
        FROM dividends ORDER BY book_close_date ASC
    """)
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)

def fetch_all_company_details(conn):
    rows = q(conn, """
        SELECT symbol, security_name, sector_name, fifty_two_week_high,
               fifty_two_week_low, market_capitalization, stock_listed_shares
        FROM company_details
    """)
    return {r["symbol"]: r for r in rows}

def fetch_all_securities(conn):
    """Fallback sector lookup — 753 symbols vs 384 in company_details."""
    rows = q(conn, """
        SELECT symbol, sector_name, instrument_type FROM securities
    """)
    return {r["symbol"]: r for r in rows}


def fetch_52w_from_snapshots(conn):
    """Get 52-week high/low from live_market_snapshots (more up-to-date than company_details)."""
    rows = q(conn, """
        SELECT symbol,
               MAX(fifty_two_week_high) as hi52,
               MIN(fifty_two_week_low)  as lo52
        FROM live_market_snapshots
        WHERE fifty_two_week_high > 0 AND fifty_two_week_low > 0
        GROUP BY symbol
    """)
    return {r["symbol"]: r for r in rows}


def fetch_all_live_ltp(conn):
    """Batch-fetch the latest last_traded_price from live_market_snapshots.
    This is the REAL current price matching the official NEPSE website.
    daily_ohlcv may lag by a day or more; this bridges the gap."""
    print("  [pre] Batch-fetching live LTP from live_market_snapshots...")
    rows = q(conn, """
        SELECT l.symbol, l.last_traded_price, l.percent_change,
               l.open_price, l.high_price, l.low_price,
               l.total_traded_quantity AS volume, l.trading_date
        FROM live_market_snapshots l
        INNER JOIN (
            SELECT symbol, MAX(snapshot_timestamp) AS max_ts
            FROM live_market_snapshots
            WHERE trading_date = (SELECT MAX(trading_date) FROM live_market_snapshots)
            GROUP BY symbol
        ) latest ON l.symbol = latest.symbol AND l.snapshot_timestamp = latest.max_ts
        WHERE l.last_traded_price > 0
    """)
    return {r["symbol"]: r for r in rows}


def bridge_live_candle(ohlcv_candles, live_row):
    """Append a synthetic candle from live_market_snapshots if daily_ohlcv
    doesn't have data for the live trading date yet (data lag bridge).
    Returns the updated candles list (not adjusted — call before adjustment)."""
    if not live_row or not ohlcv_candles:
        return ohlcv_candles
    live_date = str(live_row.get("trading_date") or "")[:10]
    last_ohlcv_date = str(ohlcv_candles[-1].get("trading_date") or "")[:10]
    today_iso = datetime.now().date().isoformat()
    # Avoid appending partial intraday candles for the current session.
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
            "symbol": live_row.get("symbol", ohlcv_candles[-1].get("symbol", "")),
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

# ═══════════════════════════════════════════════════════════════════════
#  PRICE ADJUSTMENT — Corporate Actions
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

    # From dividends table
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

    # From corporate_actions table
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
    adjusted_above_raw = 0
    for i, c in enumerate(candles):
        row = dict(c)
        row["close_price"] = closes[i]
        row["open_price"]  = opens[i]
        row["high_price"]  = highs[i]
        row["low_price"]   = lows[i]

        # Keep OHLC internally consistent after adjustment.
        row["high_price"] = max(row["high_price"], row["open_price"], row["close_price"])
        row["low_price"] = min(row["low_price"], row["open_price"], row["close_price"])

        raw_close = float(c.get("close_price") or 0)
        if raw_close > 0 and row["close_price"] > raw_close * 1.001:
            adjusted_above_raw += 1

        adj.append(row)

    if adjusted_above_raw:
        print(f"  ⚠ price-adjust warning: {adjusted_above_raw} rows adjusted above raw close")

    return adj

# ═══════════════════════════════════════════════════════════════════════
#  DATA QUALITY — Forward Fill & Flags
# ═══════════════════════════════════════════════════════════════════════

def forward_fill_zero_volume_days(candles):
    """For any day with volume == 0, carry forward previous active session's
    close as OHLC and keep volume = 0.  Prevents MA/time-series misalignment."""
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
    """Check if stock hit 10% circuit on >threshold of last lookback sessions."""
    if len(candles) < 2:
        return False
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    circuit_days = 0
    for i in range(1, len(recent)):
        prev_close = float(recent[i-1]["close_price"])
        curr_close = float(recent[i]["close_price"])
        if prev_close > 0:
            pct_move = abs(curr_close - prev_close) / prev_close
            if pct_move >= CIRCUIT_LIMIT:
                circuit_days += 1
    return circuit_days > threshold


def is_low_liquidity(candles, min_avg_volume=None):
    """Flag if SMA_20(volume) < threshold."""
    if min_avg_volume is None:
        min_avg_volume = LOW_LIQ_THRESH
    if len(candles) < 5:
        return True
    vols = [int(c.get("volume") or 0) for c in candles[-20:]]
    avg_vol = sum(vols) / len(vols) if vols else 0
    return avg_vol < min_avg_volume

# ═══════════════════════════════════════════════════════════════════════
#  INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════

def calc_sma(values, period):
    """Simple Moving Average of last `period` values."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def calc_ema(values, period):
    """EMA seeded with SMA of first `period` values.
    Returns list of length max(0, len(values) - period + 1)."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    ema = [seed]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_rsi(closes, period=14):
    """Wilder's RSI.  NEPSE thresholds: 80 overbought / 20 oversold."""
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
    """Returns (macd_val, signal_val, histogram, macd_line_series)."""
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if len(ema12) < 15 or not ema26:
        return None, None, None, []
    macd_line = [ema12[14 + i] - ema26[i] for i in range(len(ema26))]
    signal_line = calc_ema(macd_line, 9)
    if not signal_line:
        return macd_line[-1] if macd_line else None, None, None, macd_line
    macd_val  = macd_line[-1]
    sig_val   = signal_line[-1]
    histogram = macd_val - sig_val
    return (round(macd_val, 2), round(sig_val, 2), round(histogram, 2), macd_line)


def calc_atr(candles, period=14):
    """Average True Range via Wilder smoothing."""
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
    """ATR with circuit-day TR down-weighting to avoid stop compression artifacts."""
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
    """%K and %D."""
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


def calc_obv(closes, volumes):
    """On-Balance Volume — returns full OBV series."""
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
    """OBV slope direction over last `lookback` sessions."""
    obv_series = calc_obv(closes, volumes)
    if len(obv_series) >= lookback:
        slope = obv_series[-1] - obv_series[-lookback]
        if slope > 0:   return "RISING"
        if slope < 0:   return "FALLING"
    return "FLAT"


def calc_vpt(closes, volumes):
    """Volume Price Trend — returns full VPT series."""
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
    """Rate of Change: ((C_t - C_{t-n}) / C_{t-n}) * 100."""
    if len(closes) <= n or closes[-n-1] == 0:
        return None
    return round((closes[-1] - closes[-n-1]) / closes[-n-1] * 100, 2)


def calc_bollinger_bands(closes, period=20, std_dev=2):
    """Returns (upper, middle, lower) or (None, None, None)."""
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
    """Bands within 4% of price → squeeze."""
    if upper is None or middle is None or lower is None or middle == 0:
        return False
    return (upper - lower) / middle < 0.04


def is_bollinger_breakout(close, upper, vol_ratio):
    """Close above upper band AND volume ratio >= 1.5."""
    if upper is None:
        return False
    return close > upper and vol_ratio >= 1.5


def calc_pivot_points(h_prev, l_prev, c_prev):
    """Standard + Fibonacci pivots.  Returns dict."""
    p = (h_prev + l_prev + c_prev) / 3
    r1 = (2 * p) - l_prev
    s1 = (2 * p) - h_prev
    hl = h_prev - l_prev
    return {
        "P":  round(p, 2),
        "R1": round(r1, 2),
        "S1": round(s1, 2),
        "R1_fib": round(p + 0.382 * hl, 2),
        "S1_fib": round(p - 0.382 * hl, 2),
        "R2_fib": round(p + 0.618 * hl, 2),
        "S2_fib": round(p - 0.618 * hl, 2),
    }


def calc_fibonacci_retracement(swing_low, swing_high):
    """Returns dict of fib levels at 0.382, 0.500, 0.618."""
    diff = swing_high - swing_low
    return {
        "fib_382": round(swing_high - 0.382 * diff, 2),
        "fib_500": round(swing_high - 0.500 * diff, 2),
        "fib_618": round(swing_high - 0.618 * diff, 2),
    }


def detect_candlestick_patterns(candles):
    """Detect Doji, Hammer, Bullish Engulfing on most recent candle(s).
    Returns list of pattern name strings."""
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

    # Doji: |O - C| <= 0.05 * (H - L)
    if body <= 0.05 * hl:
        patterns.append("Doji")

    # Hammer: small body at top, long lower shadow, no upper shadow
    # Trend condition: prev close < SMA20 (approx: use last 20 closes)
    closes_20 = [float(candles[i]["close_price"]) for i in range(max(0, len(candles)-20), len(candles))]
    sma20 = sum(closes_20) / len(closes_20) if closes_20 else cl
    prev_close = float(p["close_price"])

    if prev_close < sma20:  # downtrend context
        if (body <= 0.3 * hl and
            min(o, cl) - l >= 2 * body and
            h - max(o, cl) <= 0.1 * hl):
            patterns.append("Hammer")

    # Bullish Engulfing
    po = float(p["open_price"])
    pc = float(p["close_price"])
    if pc < po and cl > o and o < pc and cl > po:
        patterns.append("Bullish Engulfing")

    return patterns


def calc_stop_loss(entry_price, atr, multiplier=None):
    """ATR-based stop loss for longs."""
    if multiplier is None:
        multiplier = ATR_SL_MULT
    if atr is None or atr <= 0:
        return round(entry_price * 0.95, 2)
    return round(entry_price - multiplier * atr, 2)


def calc_targets(entry_price, atr):
    """ATR-based targets."""
    if atr is None or atr <= 0:
        return round(entry_price * 1.05, 2), round(entry_price * 1.10, 2)
    t1 = round(entry_price + ATR_T1_MULT * atr, 2)
    t2 = round(entry_price + ATR_T2_MULT * atr, 2)
    return t1, t2


def calc_position_size(entry_price, stop_price, account_equity=None, risk_pct=None):
    """Shares = risk_amount / |entry - stop|."""
    if account_equity is None:
        account_equity = ACCOUNT_EQUITY
    if risk_pct is None:
        risk_pct = RISK_PCT
    risk_amount = account_equity * risk_pct
    gap = abs(entry_price - stop_price)
    if gap <= 0:
        return 0
    return max(1, int(risk_amount / gap))


def calc_rr_ratio(entry, stop, target):
    """Reward-to-risk ratio."""
    risk = abs(entry - stop)
    if risk <= 0:
        return 0
    return round((target - entry) / risk, 1)


def is_breakout_candidate(close, sma50, high_52w, vol_ratio, macd_hist):
    """All 4 conditions must be met."""
    return (close > sma50 and
            close >= 0.98 * high_52w and
            vol_ratio >= 1.5 and
            (macd_hist or 0) > 0)

# ═══════════════════════════════════════════════════════════════════════
#  MARKET CONTEXT
# ═══════════════════════════════════════════════════════════════════════

def get_market_regime(conn):
    """Multi-day regime detection using 10-day trend of NEPSE index.
    Prevents a single green/red day from flipping all signals."""
    rows = q(conn, """
        SELECT change_percent, current_value
        FROM market_indices
        WHERE index_name = 'NEPSE'
        ORDER BY date DESC LIMIT 10
    """)
    if not rows:
        return {"regime": "NEUTRAL", "factor": 1.0, "chg": 0, "trend": 0}

    today_chg = float(rows[0].get("change_percent") or 0)
    closes = [float(r.get("current_value") or 0) for r in rows
              if float(r.get("current_value") or 0) > 0]

    if len(closes) >= 5:
        sma10 = sum(closes) / len(closes)
        trend = (closes[0] - sma10) / sma10 * 100 if sma10 > 0 else 0
    else:
        trend = today_chg

    # Narrowed factor range: ±5% max (was ±10%)
    # Requires sustained multi-day trend, not just one day
    if trend > 3.0:
        return {"regime": "STRONG_BULL", "factor": 1.05, "chg": today_chg, "trend": round(trend, 2)}
    if trend > 1.0:
        return {"regime": "BULLISH",     "factor": 1.02, "chg": today_chg, "trend": round(trend, 2)}
    if trend < -3.0:
        return {"regime": "STRONG_BEAR", "factor": 0.95, "chg": today_chg, "trend": round(trend, 2)}
    if trend < -1.0:
        return {"regime": "BEARISH",     "factor": 0.98, "chg": today_chg, "trend": round(trend, 2)}
    return {"regime": "NEUTRAL", "factor": 1.0, "chg": today_chg, "trend": round(trend, 2)}


def seasonality_bonus():
    """Ashad/Shrawan (June–July) bullish window → +5 pts."""
    m = datetime.now().month
    if m in (6, 7):
        return 5
    return 0


def seasonality_penalty():
    """Post-festive seasonal drain (Jan–Feb) → -5 pts."""
    m = datetime.now().month
    if m in (1, 2):
        return -5
    return 0

# ═══════════════════════════════════════════════════════════════════════
#  BROKER INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════

def calc_broker_concentration(conn):
    """Buy/sell asymmetry score.  0-100 with 50=neutral, >50=accumulation."""
    print("  [pre] Computing broker concentration (buy/sell asymmetry)...")
    try:
        # Check how many days of floorsheet data are available
        days_row = qone(conn, """
            SELECT COUNT(DISTINCT trading_date) as day_count
            FROM floorsheet_transactions
            WHERE trading_date >= DATE_SUB(
                (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 30 DAY)
        """)
        avail_days = int(days_row.get("day_count") or 0)
        if avail_days < 10:
            print(f"  ⚠ Broker concentration based on only {avail_days} days of floorsheet data (ideally 30)")

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

        scores = {}
        all_syms = set(sym_buy) | set(sym_sell)
        for sym in all_syms:
            total = buy_total_map.get(sym, 0)
            if total <= 0:
                scores[sym] = 50
                continue
            buy_amts = sorted(sym_buy.get(sym, []), reverse=True)
            buy_conc = sum(buy_amts[:3]) / total * 100 if buy_amts else 0
            sell_amts = sorted(sym_sell.get(sym, []), reverse=True)
            sell_conc = sum(sell_amts[:3]) / total * 100 if sell_amts else 0
            raw_asym = buy_conc - sell_conc
            scores[sym] = max(0, min(100, round(50 + raw_asym / 2, 1)))
        return scores, avail_days
    except Exception as e:
        print(f"  ⚠ Broker concentration error: {e}")
        return {}, 0


def find_boom_stocks(conn, broker_scores, all_ohlcv, all_corps, all_divs, floorsheet_days=3, all_live_ltp=None):
    """Detect 'BOOM' stocks: broker accumulation + strong technicals.
    floorsheet_days: actual number of trading days available in floorsheet data."""
    print("  [pre] Scanning for BOOM stocks...")
    boom_stocks = []
    try:
        # Get top buyer brokers per symbol (last 5 sessions)
        top_buyer_rows = q(conn, """
            SELECT symbol, buyer_broker_id, buyer_broker_name,
                   COUNT(DISTINCT trading_date) as sessions,
                   SUM(amount) as total_amt
            FROM floorsheet_transactions
            WHERE trading_date >= DATE_SUB(
                (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 10 DAY)
            GROUP BY symbol, buyer_broker_id, buyer_broker_name
            ORDER BY symbol, total_amt DESC
        """)
        # Build: symbol → [(broker_id, broker_name, sessions, amt)]
        sym_buyers = defaultdict(list)
        for r in top_buyer_rows:
            sym_buyers[r["symbol"]].append({
                "broker_id": r["buyer_broker_id"],
                "broker_name": r["buyer_broker_name"],
                "sessions": int(r["sessions"] or 0),
                "amount": float(r["total_amt"] or 0),
            })

        # Get sell concentration for divergence detection
        sell_conc_rows = q(conn, """
            SELECT symbol, seller_broker_id, SUM(amount) as sell_amt
            FROM floorsheet_transactions
            WHERE trading_date >= DATE_SUB(
                (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 10 DAY)
            GROUP BY symbol, seller_broker_id
        """)
        sym_sell_conc = defaultdict(list)
        for r in sell_conc_rows:
            sym_sell_conc[r["symbol"]].append(float(r["sell_amt"] or 0))

    except Exception as e:
        print(f"  ⚠ Boom stock query error: {e}")
        return [], {}

    # Detect sell-side distribution per symbol
    sell_distribution = {}
    for sym, sell_amts in sym_sell_conc.items():
        sorted_amts = sorted(sell_amts, reverse=True)
        total = sum(sorted_amts)
        if total > 0:
            top3_pct = sum(sorted_amts[:3]) / total * 100
            sell_distribution[sym] = top3_pct
        else:
            sell_distribution[sym] = 0

    for sym, raw_candles in all_ohlcv.items():
        # Bridge: append live candle if daily_ohlcv lags behind
        live_row = all_live_ltp.get(sym) if all_live_ltp else None
        bridged_candles = bridge_live_candle(raw_candles, live_row)
        candles = get_adjusted_series(bridged_candles, all_corps.get(sym, []), all_divs.get(sym, []))
        candles = forward_fill_zero_volume_days(candles)
        if len(candles) < MIN_BARS_RSI:
            continue

        closes  = [float(c["close_price"]) for c in candles]
        volumes = [int(c.get("volume") or 0) for c in candles]

        # Use live LTP if available (matches official NEPSE website)
        if live_row and float(live_row.get("last_traded_price") or 0) > 0:
            price = float(live_row["last_traded_price"])
        else:
            price = closes[-1]

        asym_score = broker_scores.get(sym, 50)
        if asym_score <= 65:
            continue

        # Check for consistent top-3 buyer
        # Dynamic threshold: require buying in >= 50% of available days (min 1)
        min_sessions = max(1, floorsheet_days // 2)
        buyers = sym_buyers.get(sym, [])[:3]
        consistent_buyer = any(b["sessions"] >= min_sessions for b in buyers)
        if not consistent_buyer:
            continue

        # Volume ratio
        vol_avg = sum(volumes[-20:]) / min(len(volumes[-20:]), 20) if volumes else 0
        vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 0
        if vol_ratio < 1.3:
            continue

        # RSI 40-75 (not overbought by NEPSE standards)
        rsi = calc_rsi(closes)
        if rsi is None or rsi < 40 or rsi > 75:
            continue

        # Price above SMA20
        sma20 = calc_sma(closes, 20)
        if sma20 is None or price < sma20:
            continue

        boom_stocks.append({
            "symbol": sym,
            "price": price,
            "asym_score": asym_score,
            "top_buyers": buyers[:3],
            "vol_ratio": round(vol_ratio, 2),
            "rsi": rsi,
            "signal": "🔥 BROKER ACCUMULATION — WATCH FOR BREAKOUT",
        })

    boom_stocks.sort(key=lambda x: x["asym_score"], reverse=True)
    return boom_stocks, sell_distribution, floorsheet_days

# ═══════════════════════════════════════════════════════════════════════
#  ANALYSIS 1: MARKET OVERVIEW
# ═══════════════════════════════════════════════════════════════════════

def market_overview(conn):
    print("  [1] Market Overview...")
    summary = qone(conn, "SELECT * FROM market_summary ORDER BY trading_date DESC LIMIT 1")
    indices = q(conn, "SELECT * FROM market_indices ORDER BY date DESC, index_name")
    latest_date = None
    if indices:
        latest_date = indices[0].get("date")
        indices = [i for i in indices if i.get("date") == latest_date]
    subs = q(conn, "SELECT * FROM nepse_sub_indices ORDER BY percent_change DESC")

    # Market breadth — filtered to latest date only (table has multiple dates)
    breadth = {"advances": 0, "declines": 0, "unchanged": 0}
    try:
        breadth_rows = q(conn, """
            SELECT
                SUM(CASE WHEN percent_change > 0 THEN 1 ELSE 0 END) as advances,
                SUM(CASE WHEN percent_change < 0 THEN 1 ELSE 0 END) as declines,
                SUM(CASE WHEN percent_change = 0 THEN 1 ELSE 0 END) as unchanged
            FROM daily_trade_turnover_transaction_subindices
            WHERE created_at >= (
                SELECT MAX(DATE(created_at))
                FROM daily_trade_turnover_transaction_subindices
            )
        """)
        if breadth_rows and breadth_rows[0]:
            breadth = {
                "advances": int(breadth_rows[0].get("advances") or 0),
                "declines": int(breadth_rows[0].get("declines") or 0),
                "unchanged": int(breadth_rows[0].get("unchanged") or 0),
            }
    except:
        pass

    return {
        "summary": summary, "indices": indices,
        "sub_indices": subs, "date": latest_date,
        "breadth": breadth,
    }

# ═══════════════════════════════════════════════════════════════════════
#  COMPREHENSIVE PER-SYMBOL ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def analyze_all_symbols(all_ohlcv, all_corps, all_divs, all_details, all_securities,
                        all_52w_snapshots, broker_scores,
                        sell_distribution, market_regime, all_live_ltp=None):
    """Run all indicator calculations on every symbol.
    Returns dict: symbol → full analysis dict.
    all_live_ltp: dict symbol→row from live_market_snapshots for accurate LTP."""
    print("  [2] Analyzing all symbols (indicators, patterns, flags)...")

    if all_live_ltp is None:
        all_live_ltp = {}

    results = {}
    error_count = 0
    error_samples = []
    skip_stats = {
        "short_history": 0,
        "bad_price": 0,
        "stale_forward_fill": 0,
    }
    season_adj = seasonality_bonus() + seasonality_penalty()

    for sym, raw_candles in all_ohlcv.items():
        try:
            # Bridge: append live candle if daily_ohlcv lags behind
            live_row = all_live_ltp.get(sym)
            bridged_candles = bridge_live_candle(raw_candles, live_row)

            # Adjust prices (for indicator calculation)
            candles = get_adjusted_series(
                bridged_candles, all_corps.get(sym, []), all_divs.get(sym, []))
            # Forward fill zero-volume days
            candles = forward_fill_zero_volume_days(candles)
            max_fill_streak = _max_forward_fill_streak(candles)

            if len(candles) < 20:
                skip_stats["short_history"] += 1
                continue

            if max_fill_streak > MAX_FORWARD_FILL_STREAK:
                skip_stats["stale_forward_fill"] += 1
                continue

            closes  = [float(c["close_price"]) for c in candles]
            volumes = [int(c.get("volume") or 0) for c in candles]

            # Use live LTP as the display price (matches official NEPSE website).
            # Fall back to adjusted close only if live data isn't available.
            if live_row and float(live_row.get("last_traded_price") or 0) > 0:
                price = float(live_row["last_traded_price"])
            else:
                price = closes[-1]

            if price <= 0:
                skip_stats["bad_price"] += 1
                continue

            # ── FLAGS ──
            circuit_flag = is_circuit_volatile(candles)
            liquidity_flag = is_low_liquidity(candles)

            # ── MOVING AVERAGES ──
            sma5   = calc_sma(closes, 5)
            sma10  = calc_sma(closes, 10)
            sma20  = calc_sma(closes, 20)
            sma50  = calc_sma(closes, 50)
            sma200 = calc_sma(closes, 200)

            # ── RSI (NEPSE 80/20) ──
            rsi = calc_rsi(closes) if len(candles) >= MIN_BARS_RSI else None

            # ── MACD ──
            macd_val, sig_val, macd_hist, macd_line = (None, None, None, [])
            if len(candles) >= MIN_BARS_MACD:
                macd_val, sig_val, macd_hist, macd_line = calc_macd(closes)

            # Check if MACD just crossed (histogram sign change)
            macd_just_bullish = False
            macd_just_bearish = False
            if macd_line and len(macd_line) >= 2:
                signal_ema = calc_ema(macd_line, 9)
                if len(signal_ema) >= 2:
                    prev_hist = macd_line[-2] - signal_ema[-2]
                    curr_hist = macd_line[-1] - signal_ema[-1]
                    if prev_hist <= 0 and curr_hist > 0:
                        macd_just_bullish = True
                    if prev_hist >= 0 and curr_hist < 0:
                        macd_just_bearish = True

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

            # VPT Bearish Divergence: price new high but VPT lower high
            vpt_bearish_div = False
            if len(closes) >= 20 and len(vpt_series) >= 20:
                # Compare last 10 vs prev 10
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

            # ── 52-WEEK HIGH / LOW ──
            # Priority: live_market_snapshots > company_details > computed from OHLCV
            det = all_details.get(sym, {})
            snap52 = all_52w_snapshots.get(sym, {})
            hi52 = (float(snap52.get("hi52") or 0)
                    or float(det.get("fifty_two_week_high") or 0)
                    or (max(closes[-252:]) if len(closes) >= 252 else max(closes)))
            lo52 = (float(snap52.get("lo52") or 0)
                    or float(det.get("fifty_two_week_low") or 0)
                    or (min(closes[-252:]) if len(closes) >= 252 else min(closes)))
            # Sector: company_details > securities fallback
            sector = (det.get("sector_name")
                      or all_securities.get(sym, {}).get("sector_name")
                      or "")

            high_prox = round((hi52 - price) / hi52 * 100, 1) if hi52 > 0 else 100
            range_pct = round((price - lo52) / (hi52 - lo52) * 100, 1) if hi52 != lo52 else 50

            # ── PIVOT POINTS ──
            pivots = {}
            if len(candles) >= 2:
                prev = candles[-2]
                pivots = calc_pivot_points(
                    float(prev["high_price"]),
                    float(prev["low_price"]),
                    float(prev["close_price"])
                )

            # ── FIBONACCI RETRACEMENT ──
            fib = {}
            if hi52 > lo52:
                fib = calc_fibonacci_retracement(lo52, hi52)

            fib_618_broken = False
            if fib and price < fib.get("fib_618", 0):
                fib_618_broken = True

            # ── CANDLESTICK PATTERNS ──
            patterns = detect_candlestick_patterns(candles) if len(candles) >= 2 else []

            # ── MA CROSSOVERS ──
            cross = "NEUTRAL"
            if sma20 is not None and sma50 is not None and len(closes) >= 51:
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

            # ── STOP / TARGETS ──
            stop_loss = calc_stop_loss(price, atr)
            target1, target2 = calc_targets(price, atr)
            rr_ratio = calc_rr_ratio(price, stop_loss, target1)
            position_size = calc_position_size(price, stop_loss)

            # ── BREAKOUT CHECK ──
            breakout_52w = False
            if price >= hi52 and vol_ratio > 1.2:
                breakout_52w = True
            breakout_candidate = False
            if sma50 is not None:
                breakout_candidate = is_breakout_candidate(price, sma50, hi52, vol_ratio, macd_hist)

            # ── BROKER METRICS ──
            asym_score = broker_scores.get(sym, 50)
            sell_dist_pct = sell_distribution.get(sym, 0)

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
            for c in closes:
                if c > peak:
                    peak = c
                dd = (peak - c) / peak * 100
                if dd > max_dd:
                    max_dd = dd

            # ── BUILD REASONS ──
            reasons = _build_reasons(
                price=price, rsi=rsi, macd_val=macd_val, macd_hist=macd_hist,
                macd_just_bullish=macd_just_bullish, macd_just_bearish=macd_just_bearish,
                sma20=sma20, sma50=sma50, sma200=sma200,
                cross=cross, bb_pct=bb_pct, bb_upper=bb_upper, bb_lower=bb_lower,
                bb_squeeze=bb_squeeze, bb_breakout=bb_breakout,
                vol_ratio=vol_ratio, obv_trend=obv_trend,
                vpt_bearish_div=vpt_bearish_div,
                stoch_k=stoch_k, stoch_d=stoch_d,
                patterns=patterns, high_prox=high_prox, lo52=lo52,
                fib_618_broken=fib_618_broken,
                asym_score=asym_score, sell_dist_pct=sell_dist_pct,
                roc_20=roc_20, roc_60=roc_60,
                pivots=pivots, circuit_flag=circuit_flag,
                pe=0,  # filled later from fundamentals
            )

            # ── SIGNAL CLASSIFICATION ──
            signal = _classify_signal(
                rsi=rsi, macd_hist=macd_hist, cross=cross,
                bb_pct=bb_pct, price=price, sma20=sma20, sma50=sma50, sma200=sma200,
                vol_ratio=vol_ratio, obv_trend=obv_trend,
                stoch_k=stoch_k, stoch_d=stoch_d,
                breakout_candidate=breakout_candidate,
            )

            # ── CONFIDENCE ──
            confidence = _calc_confidence(signal, rsi, macd_hist, vol_ratio, obv_trend,
                                          cross, bb_pct, asym_score)

            results[sym] = {
                "symbol": sym, "sector": sector, "price": price,
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
                "vol_ratio": vol_ratio, "vol_avg": vol_avg,
                "hi52": hi52, "lo52": lo52, "high_prox": high_prox,
                "range_pct": range_pct,
                "pivots": pivots, "fib": fib, "fib_618_broken": fib_618_broken,
                "patterns": patterns, "cross": cross,
                "stop_loss": stop_loss, "target1": target1, "target2": target2,
                "rr_ratio": rr_ratio, "position_size": position_size,
                "breakout_52w": breakout_52w, "breakout_candidate": breakout_candidate,
                "asym_score": asym_score, "sell_dist_pct": sell_dist_pct,
                "vol_20d": vol_20d, "max_drawdown": round(max_dd, 1),
                "circuit_flag": circuit_flag, "liquidity_flag": liquidity_flag,
                "signal": signal, "confidence": confidence,
                "reasons": reasons,
            }
        except Exception as e:
            error_count += 1
            if len(error_samples) < 5:
                error_samples.append(f"{sym}:{type(e).__name__}")
            continue

    if error_count:
        sample_text = ", ".join(error_samples)
        print(f"  ⚠ symbol analysis errors: {error_count} ({sample_text})")

    skipped_total = sum(skip_stats.values())
    if skipped_total:
        print(
            "  ⚠ symbol skip summary: "
            f"short_history={skip_stats['short_history']}, "
            f"stale_forward_fill={skip_stats['stale_forward_fill']}, "
            f"bad_price={skip_stats['bad_price']}"
        )

    return results


def _build_reasons(*, price, rsi, macd_val, macd_hist,
                   macd_just_bullish, macd_just_bearish,
                   sma20, sma50, sma200, cross,
                   bb_pct, bb_upper, bb_lower,
                   bb_squeeze, bb_breakout,
                   vol_ratio, obv_trend, vpt_bearish_div,
                   stoch_k, stoch_d, patterns, high_prox, lo52,
                   fib_618_broken, asym_score, sell_dist_pct,
                   roc_20, roc_60, pivots, circuit_flag, pe):
    """Build programmatic reason strings for a stock."""
    reasons = []

    # ── BULLISH REASONS ──
    if macd_just_bullish:
        reasons.append("✅ Bullish MACD Crossover")
    if rsi is not None and rsi < get_rsi_os():
        reasons.append(f"✅ RSI Oversold Recovery (RSI: {rsi})")
    if sma20 and sma50 and price > sma20 and price > sma50:
        reasons.append("✅ Above SMA20 & SMA50")
    if cross == "GOLDEN":
        reasons.append("✅ Golden Cross (SMA50 > SMA200)")
    if vol_ratio >= 1.5:
        reasons.append(f"✅ Volume Surge ({vol_ratio:.1f}x avg)")
    if high_prox is not None and high_prox <= 2:
        reasons.append(f"✅ 52W Breakout Zone (within {high_prox:.1f}% of high)")
    if bb_squeeze and bb_breakout:
        reasons.append("✅ Bollinger Squeeze Breakout")
    if "Hammer" in patterns:
        reasons.append("✅ Hammer Pattern Detected")
    if "Bullish Engulfing" in patterns:
        reasons.append("✅ Bullish Engulfing Pattern")
    if stoch_k is not None and stoch_d is not None and stoch_k > stoch_d and stoch_k < 20:
        reasons.append(f"✅ Stoch Bullish Cross (K:{stoch_k:.0f} D:{stoch_d:.0f})")
    if obv_trend == "RISING":
        reasons.append("✅ OBV Rising Trend")
    if asym_score > 65:
        reasons.append(f"✅ Smart Money Accumulating (Score: {asym_score:.0f})")
    if sma20 and sma50 and price > sma20 > sma50:
        reasons.append("✅ Uptrend: Price > SMA20 > SMA50")
    if pe and 0 < pe < 15:
        reasons.append(f"✅ Low PE ({pe:.0f}) — Value Play")

    # ── BEARISH REASONS ──
    if macd_just_bearish or (macd_hist is not None and macd_hist < 0):
        reasons.append(f"❌ Bearish MACD ({macd_hist or 0:.2f})")
    if rsi is not None and rsi > get_rsi_ob():
        reasons.append(f"❌ RSI Overbought ({rsi:.1f} > {get_rsi_ob()})")
    if sma50 and price < sma50:
        reasons.append("❌ Below SMA50")
    if sma200 and price < sma200:
        reasons.append("❌ Below SMA200 — Downtrend")
    if lo52 and lo52 > 0 and price <= lo52 * 1.02:
        reasons.append("❌ 52W Low Breakdown")
    if cross == "DEATH":
        reasons.append("❌ Death Cross (SMA50 < SMA200)")
    if bb_lower and price <= bb_lower:
        reasons.append("❌ At Lower Bollinger Band")
    if vol_ratio >= 1.5 and macd_hist is not None and macd_hist < 0:
        reasons.append("❌ High Volume Selling")
    if stoch_k is not None and stoch_d is not None and stoch_k > 80 and stoch_d > 80:
        reasons.append(f"❌ Stoch Overbought (K:{stoch_k:.0f} D:{stoch_d:.0f})")
    if obv_trend == "FALLING":
        reasons.append("❌ OBV Falling — Distribution")
    if vpt_bearish_div:
        reasons.append("❌ VPT Bearish Divergence")
    if fib_618_broken:
        reasons.append("❌ Fib 61.8% Broken — Trend Invalid")
    if pe and pe > 30:
        reasons.append(f"⚠️ High PE ({pe:.0f}) — Overvalued Risk")
    if sell_dist_pct > 50 and macd_hist is not None and macd_hist > 0:
        reasons.append("⚠️ Broker Divergence — Smart Money Selling")
    if circuit_flag:
        reasons.append("⚠️ Circuit Breaker History")

    # Seasonal
    month = datetime.now().month
    if month in (1, 2):
        reasons.append("⚠️ Post-Festive Seasonal Drain")
    if month in (6, 7):
        reasons.append("⚠️ Ashad/Shrawan Seasonal Boost")

    # ── NEUTRAL / CONTEXT ──
    if "Doji" in patterns:
        reasons.append("ℹ️ Doji — Indecision, Wait for Confirmation")
    if sma20 and price < sma20 and sma50 and price > sma50:
        reasons.append("ℹ️ Inside SMA20 Pullback Zone")
    if roc_20 is not None:
        roc60_str = f"{roc_60:+.1f}%" if roc_60 is not None else "N/A"
        reasons.append(f"ℹ️ ROC20: {roc_20:+.1f}% | ROC60: {roc60_str}")
    if pivots:
        reasons.append(f"ℹ️ Pivot R1: {pivots.get('R1', 0):.0f} | S1: {pivots.get('S1', 0):.0f}")

    return " | ".join(reasons) if reasons else "No significant signals"


def _classify_signal(*, rsi, macd_hist, cross, bb_pct, price,
                     sma20, sma50, sma200, vol_ratio, obv_trend,
                     stoch_k, stoch_d, breakout_candidate):
    """Dual-axis signal: Trend (where is it going?) × Timing (is NOW good?).

    Trend Indicators: MA alignment, MACD histogram, OBV direction
      → Determines if the stock is in an uptrend, downtrend, or neutral

    Timing Indicators: RSI, Stochastic, Bollinger %B, volume spikes
      → Determines if it's a good entry/exit point RIGHT NOW

    The signal comes from the INTERSECTION, not the sum:
      Uptrend + Good timing   → STRONG BUY
      Uptrend + Neutral timing → HOLD (trend already priced in)
      Uptrend + Bad timing     → SELL (take profit)
      Downtrend + Good timing  → BUY (contrarian entry)
      Downtrend + Bad timing   → STRONG SELL
    """

    # ── TREND SCORE (is the stock trending up or down?) ──
    trend = 0

    # MA Crossovers — strongest trend signal
    if cross == "GOLDEN":
        trend += 3
    elif cross == "BULLISH":
        trend += 1
    elif cross == "DEATH":
        trend -= 3
    elif cross == "BEARISH":
        trend -= 1

    # MACD histogram — trend momentum
    if macd_hist is not None:
        if macd_hist > 0:
            trend += 1
        else:
            trend -= 1

    # OBV — accumulation/distribution trend
    if obv_trend == "RISING":
        trend += 1
    elif obv_trend == "FALLING":
        trend -= 1

    # Long-term trend context
    if sma200 and price > sma200:
        trend += 1
    elif sma200 and price < sma200:
        trend -= 1

    # ── TIMING SCORE (is NOW a good entry/exit point?) ──
    timing = 0

    # RSI — contrarian: oversold = good buy timing, overbought = good sell timing
    if rsi is not None:
        if rsi < get_rsi_os():
            timing += 3      # Deeply oversold — strong buy timing
        elif rsi < get_rsi_os() + 10:
            timing += 2      # Approaching oversold (e.g. RSI 20-30) — good timing
        elif rsi < 40:
            timing += 1      # Getting cheap
        elif rsi > get_rsi_ob():
            timing -= 3      # Deeply overbought — strong sell timing
        elif rsi > get_rsi_ob() - 10:
            timing -= 2      # Approaching overbought (e.g. RSI 70-80) — bad timing
        # NOTE: RSI 40 to (overbought-10) is NEUTRAL timing — no longer penalizes uptrends

    # Stochastic — short-term overbought/oversold
    if stoch_k is not None and stoch_d is not None:
        if stoch_k < 20 and stoch_k > stoch_d:
            timing += 1      # Oversold bullish cross
        elif stoch_k > 80 and stoch_k < stoch_d:
            timing -= 1      # Overbought bearish cross

    # Bollinger %B — contrarian: near lower band = buy, near upper = sell
    if bb_pct is not None:
        if bb_pct < 15:
            timing += 1      # Near lower band — potential bounce
        elif bb_pct > 90:
            timing -= 1      # Extended above upper band

    # Volume spike — confirms timing only when directional
    if vol_ratio >= 1.5:
        if rsi is not None and rsi < 40:
            timing += 1      # Volume on a dip = capitulation (bullish timing)
        elif rsi is not None and rsi > get_rsi_ob():
            timing -= 1      # Volume at top = blow-off (bearish timing)

    # Breakout — special case: overrides normal timing
    if breakout_candidate:
        trend += 2
        timing += 1

    # ── SIGNAL MATRIX ──
    # Classify trend direction
    if trend >= 3:
        trend_dir = "STRONG_UP"
    elif trend >= 1:
        trend_dir = "UP"
    elif trend <= -3:
        trend_dir = "STRONG_DOWN"
    elif trend <= -1:
        trend_dir = "DOWN"
    else:
        trend_dir = "FLAT"

    # Classify timing
    if timing >= 2:
        timing_dir = "GOOD"      # Oversold / good entry
    elif timing <= -2:
        timing_dir = "BAD"       # Overbought / take profit
    else:
        timing_dir = "NEUTRAL"

    # ── DECISION MATRIX ──
    # Strong uptrend
    if trend_dir == "STRONG_UP":
        if timing_dir == "GOOD":
            return "STRONG BUY"
        elif timing_dir == "BAD":
            return "HOLD"        # Don't sell into a strong trend, just hold
        else:
            return "BUY"         # Strong trend + neutral timing = still a buy

    # Mild uptrend
    if trend_dir == "UP":
        if timing_dir == "GOOD":
            return "BUY"
        elif timing_dir == "BAD":
            return "SELL"        # Uptrend losing momentum + bad timing = take profit
        else:
            return "HOLD"

    # Flat / no trend
    if trend_dir == "FLAT":
        if timing_dir == "GOOD":
            return "BUY"         # No trend but oversold = speculative buy
        elif timing_dir == "BAD":
            return "SELL"        # No trend but overbought = sell
        else:
            return "HOLD"

    # Mild downtrend
    if trend_dir == "DOWN":
        if timing_dir == "GOOD":
            return "HOLD"        # Downtrend but oversold = wait for confirmation
        elif timing_dir == "BAD":
            return "STRONG SELL"
        else:
            return "SELL"

    # Strong downtrend
    if trend_dir == "STRONG_DOWN":
        if timing_dir == "GOOD":
            return "HOLD"        # Even oversold in a crash = don't catch falling knife
        elif timing_dir == "BAD":
            return "STRONG SELL"
        else:
            return "SELL"

    return "HOLD"


def _calc_confidence(signal, rsi, macd_hist, vol_ratio, obv_trend,
                     cross, bb_pct, asym_score):
    """Calculate confidence with PENALTIES for contradicting indicators.
    A BUY signal with falling OBV should NOT show 80% confidence."""
    conf = 50
    if signal in ("STRONG BUY", "STRONG SELL"):
        conf = 80
    elif signal in ("BUY", "SELL"):
        conf = 65

    is_bullish = signal in ("BUY", "STRONG BUY")
    is_bearish = signal in ("SELL", "STRONG SELL")

    # ── CONFIRMATIONS (boost confidence) ──
    if rsi is not None:
        if (is_bullish and rsi < 35) or (is_bearish and rsi > 70):
            conf += 5  # RSI confirms direction

    if macd_hist is not None and abs(macd_hist) > 2:
        if (is_bullish and macd_hist > 0) or (is_bearish and macd_hist < 0):
            conf += 5  # MACD confirms direction

    if vol_ratio >= 2.0:
        conf += 3  # High volume adds conviction either way

    if cross in ("GOLDEN",) and is_bullish:
        conf += 10
    elif cross in ("DEATH",) and is_bearish:
        conf += 10

    if asym_score > 70 and is_bullish:
        conf += 5  # Smart money confirms buy
    elif asym_score < 30 and is_bearish:
        conf += 5  # Smart money confirms sell

    # ── CONTRADICTIONS (penalize confidence) ──
    if is_bullish:
        if obv_trend == "FALLING":
            conf -= 10  # Buying but distribution happening
        if cross in ("DEATH", "BEARISH"):
            conf -= 15  # Buying into a downtrend
        if rsi is not None and rsi > get_rsi_ob():
            conf -= 10  # Buying at overbought levels
        if macd_hist is not None and macd_hist < -2:
            conf -= 8   # MACD strongly bearish
        if asym_score < 35:
            conf -= 5   # Smart money not buying

    if is_bearish:
        if obv_trend == "RISING":
            conf -= 10  # Selling but accumulation happening
        if cross in ("GOLDEN", "BULLISH"):
            conf -= 15  # Selling into an uptrend
        if rsi is not None and rsi < get_rsi_os():
            conf -= 10  # Selling at oversold levels
        if macd_hist is not None and macd_hist > 2:
            conf -= 8   # MACD strongly bullish
        if asym_score > 65:
            conf -= 5   # Smart money accumulating

    return min(100, max(10, conf))  # Floor at 10%, not 0%

# ═══════════════════════════════════════════════════════════════════════
#  FUNDAMENTAL ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def fundamental_analysis(conn):
    print("  [3] Fundamental Analysis...")
    raw_rows = q(conn, """
        SELECT cf.symbol, cf.eps, cf.pe_ratio, cf.book_value, cf.net_profit,
               cf.fiscal_year, cf.quarter,
               cd.sector_name, cd.fifty_two_week_high, cd.fifty_two_week_low,
               cd.market_capitalization, cd.stock_listed_shares
        FROM company_fundamentals cf
        JOIN company_details cd ON cf.symbol = cd.symbol
        ORDER BY cf.symbol, cf.published_date DESC
    """)
    seen, rows = set(), []
    for r in raw_rows:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            rows.append(r)

    div_rows = q(conn, """
        SELECT d.symbol, d.cash_dividend_percent
        FROM dividends d
        WHERE d.book_close_date = (
            SELECT MAX(d2.book_close_date) FROM dividends d2
            WHERE d2.symbol = d.symbol AND d2.cash_dividend_percent > 0
        )
    """)
    div_map = {r["symbol"]: float(r["cash_dividend_percent"] or 0) for r in div_rows}

    results = {}
    for r in rows:
        eps   = float(r["eps"]          or 0)
        pe    = float(r["pe_ratio"]     or 0)
        bv    = float(r["book_value"]   or 0)
        mcap  = float(r["market_capitalization"] or 0)
        hi52  = float(r["fifty_two_week_high"]   or 0)
        lo52  = float(r["fifty_two_week_low"]    or 0)

        price_approx = eps * pe if eps and pe else 0
        pbv   = round(price_approx / bv, 2) if bv > 0 else None
        roe   = round(eps / bv * 100, 1)     if bv > 0 and eps > 0 else 0

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

        if div_yield > 5:   score += 10
        elif div_yield > 2: score += 5
        if roe > 20:        score += 10
        elif roe > 10:      score += 5

        results[r["symbol"]] = {
            "symbol": r["symbol"], "sector": r["sector_name"],
            "eps": eps, "pe_ratio": pe, "book_value": bv, "pbv": pbv,
            "net_profit": float(r["net_profit"] or 0),
            "fiscal_year": r["fiscal_year"], "quarter": r["quarter"],
            "hi52": hi52, "lo52": lo52, "mcap": mcap,
            "roe": roe, "div_yield": div_yield,
            "fund_score": score,
        }
    return results

# ═══════════════════════════════════════════════════════════════════════
#  SECTOR ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def sector_breakdown(conn):
    print("  [4] Sector Breakdown...")
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


def calc_sector_breadth(all_analysis, all_details, all_securities=None):
    """For each sector, % of stocks above SMA50."""
    if all_securities is None:
        all_securities = {}
    sector_stocks = defaultdict(list)
    for sym, data in all_analysis.items():
        sector = (data.get("sector")
                  or all_details.get(sym, {}).get("sector_name")
                  or all_securities.get(sym, {}).get("sector_name")
                  or "Other")
        sector_stocks[sector].append(data)

    breadth = {}
    for sector, stocks in sector_stocks.items():
        above_sma50 = sum(1 for s in stocks if s.get("sma50") and s["price"] > s["sma50"])
        total = len(stocks)
        breadth[sector] = {
            "total": total,
            "above_sma50": above_sma50,
            "pct": round(above_sma50 / total * 100, 1) if total > 0 else 0,
            "uptrend": above_sma50 / total > 0.5 if total > 0 else False,
        }
    return breadth

# ═══════════════════════════════════════════════════════════════════════
#  COMPOSITE SCORING & WATCHLIST
# ═══════════════════════════════════════════════════════════════════════

def compute_composite_scores(all_analysis, fundamentals, sector_breadth, market_regime):
    """5-dimension weighted composite from research doc:
    Price Action & Trend (30%), Momentum (25%), Volume (20%),
    Sector Strength (15%), Risk & Structure (10%).
    Apply min-max normalization."""
    print("  [5] Computing composite scores...")

    raw_scores = {}
    for sym, a in all_analysis.items():
        f = fundamentals.get(sym, {})

        # Update reasons with PE info if available
        pe = f.get("pe_ratio", 0)
        if pe > 0:
            # Re-inject PE reason
            current_reasons = a.get("reasons", "")
            if pe < 15:
                if "Low PE" not in current_reasons:
                    current_reasons += f" | ✅ Low PE ({pe:.0f}) — Value Play"
            elif pe > 30:
                if "High PE" not in current_reasons:
                    current_reasons += f" | ⚠️ High PE ({pe:.0f}) — Overvalued Risk"
            a["reasons"] = current_reasons

        # ── 1. Price Action & Trend (30%) ──
        pa_score = 50
        if a.get("sma20") and a.get("sma50") and a.get("sma200"):
            if a["price"] > a["sma20"] > a["sma50"] > a["sma200"]:
                pa_score = 100
            elif a["price"] > a["sma20"] and a["price"] > a["sma50"]:
                pa_score = 80
            elif a["price"] > a["sma50"]:
                pa_score = 60
            elif a["price"] < a["sma50"] and a["price"] < a["sma200"]:
                pa_score = 10
            else:
                pa_score = 30
        elif a.get("sma20") and a.get("sma50"):
            if a["price"] > a["sma20"] > a["sma50"]:
                pa_score = 80
            elif a["price"] > a["sma50"]:
                pa_score = 60
            else:
                pa_score = 30

        # Candlestick patterns bonus
        for p in a.get("patterns", []):
            pa_score += 10
        # 52W proximity bonus
        if a.get("high_prox") is not None and a["high_prox"] < 5:
            pa_score += 20
        pa_score = min(100, pa_score)

        # ── 2. Momentum Velocity (25%) ──
        mom_score = 50
        roc_component = 0
        if a.get("roc_20") is not None:
            roc_component = min(max(a["roc_20"], -30), 30) / 30 * 40
        rsi_component = 0
        if a.get("rsi") is not None:
            # Map 20-80 range to 0-30
            rsi_component = min(max((a["rsi"] - get_rsi_os()) / (get_rsi_ob() - get_rsi_os()), 0), 1) * 30
        macd_component = 0
        if a.get("macd_hist") is not None:
            macd_component = 15 if a["macd_hist"] > 0 else -15
        mom_score = 50 + roc_component + rsi_component + macd_component
        mom_score = min(100, max(0, mom_score))

        # ── 3. Volume & Liquidity (20%) ──
        vol_score = 50
        vr = min(a.get("vol_ratio", 1), 5)
        vol_score += (vr - 1) * 10
        if a.get("obv_trend") == "RISING":
            vol_score += 15
        elif a.get("obv_trend") == "FALLING":
            vol_score -= 15
        vol_score = min(100, max(0, vol_score))

        # ── 4. Sector Strength (15%) ──
        sector = a.get("sector", "")
        sb = sector_breadth.get(sector, {})
        sect_score = sb.get("pct", 50)

        # ── 5. Risk & Structure (10%) ──
        risk_score = 70
        if a.get("atr") and a["price"] > 0:
            atr_pct = a["atr"] / a["price"] * 100
            if atr_pct > 5:
                risk_score -= 30
            elif atr_pct > 3:
                risk_score -= 15
        if a.get("vol_20d", 0) > 3:
            risk_score -= 20
        risk_score = min(100, max(0, risk_score))

        composite = (pa_score * 0.30 + mom_score * 0.25 + vol_score * 0.20
                     + sect_score * 0.15 + risk_score * 0.10)

        # Apply market factor as bounded additive adjustment (not multiplicative)
        # Max impact: ±5 points on a 0-100 scale instead of ±10% scaling
        regime_adj = (market_regime.get("factor", 1.0) - 1.0) * 100
        composite = composite + regime_adj

        # Seasonal
        composite += seasonality_bonus() + seasonality_penalty()

        raw_scores[sym] = {
            "composite_raw": composite,
            "pa_score": round(pa_score, 1),
            "mom_score": round(mom_score, 1),
            "vol_score": round(vol_score, 1),
            "sect_score": round(sect_score, 1),
            "risk_score": round(risk_score, 1),
            "fund_score": f.get("fund_score", 0),
            "pe": f.get("pe_ratio", 0),
            "eps": f.get("eps", 0),
            "roe": f.get("roe", 0),
            "div_yield": f.get("div_yield", 0),
        }

    # Min-max normalization
    if raw_scores:
        vals = [v["composite_raw"] for v in raw_scores.values()]
        min_v = min(vals)
        max_v = max(vals)
        rng = max_v - min_v if max_v != min_v else 1

        for sym in raw_scores:
            normalized = (raw_scores[sym]["composite_raw"] - min_v) / rng * 100
            raw_scores[sym]["composite"] = round(normalized, 2)
            # Flag extreme momentum
            raw_scores[sym]["extreme_momentum"] = normalized > 90

    # Merge back into all_analysis
    for sym in raw_scores:
        if sym in all_analysis:
            all_analysis[sym].update(raw_scores[sym])

    return all_analysis


def build_watchlist(all_analysis):
    """Filter and rank for Tomorrow's Watchlist.
    Filtering: remove low liquidity, circuit volatile, below SMA200, R:R < 2.0.
    Sort by composite score descending. Return top 10."""
    print("  [6] Building tomorrow's watchlist...")

    candidates = []
    circuit_alerts = []

    for sym, a in all_analysis.items():
        # Circuit alert section
        if a.get("circuit_flag"):
            circuit_alerts.append(a)
            continue

        # Filtering
        if a.get("liquidity_flag"):
            continue
        if a.get("sma200") and a["price"] < a["sma200"]:
            continue
        if a.get("rr_ratio", 0) < MIN_RR_RATIO:
            continue

        # Only BUY / STRONG BUY for watchlist
        if a.get("signal") not in ("BUY", "STRONG BUY"):
            continue

        candidates.append(a)

    candidates.sort(key=lambda x: x.get("composite", 0), reverse=True)
    circuit_alerts.sort(key=lambda x: x.get("symbol", ""))

    return candidates[:10], circuit_alerts

# ═══════════════════════════════════════════════════════════════════════
#  ADDITIONAL DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════

def top_gainers_losers(conn):
    print("  [7] Top Gainers & Losers...")
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
    print("  [8] Dividends & Corporate Actions...")
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
    print("  [9] Floorsheet Forensics...")
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
    print("  [10] Scrip Rankings...")
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
#  MOMENTUM COMPOSITE SCORE (Research Doc Formula)
# ═══════════════════════════════════════════════════════════════════════

def calc_momentum_composite(all_analysis):
    """Research doc formula:
    Score = (0.4 × ROC_20_norm) + (0.3 × RSI_14_norm) + (0.3 × VolRatio_norm)
    Each component normalized to 0-100 before weighting, then min-max to 0-100."""
    print("  [pre] Computing momentum composite scores...")

    raw_scores = {}
    for sym, a in all_analysis.items():
        roc = a.get("roc_20") or 0
        rsi = a.get("rsi") or 50
        vr  = a.get("vol_ratio", 1)
        # Normalize each component to 0-100 before weighting
        roc_norm = min(max((roc + 30) / 60 * 100, 0), 100)   # ±30 ROC → 0-100
        rsi_norm = rsi                                          # already 0-100
        vr_norm  = min(vr / 5.0 * 100, 100)                    # cap 5x → 0-100
        raw = 0.4 * roc_norm + 0.3 * rsi_norm + 0.3 * vr_norm
        raw_scores[sym] = raw

    if not raw_scores:
        return

    vals = list(raw_scores.values())
    min_v = min(vals)
    max_v = max(vals)
    rng = max_v - min_v if max_v != min_v else 1

    for sym, raw in raw_scores.items():
        normalized = (raw - min_v) / rng * 100
        if sym in all_analysis:
            all_analysis[sym]["momentum_score"] = round(normalized, 2)
            if normalized > 90:
                all_analysis[sym]["extreme_momentum"] = True

# ═══════════════════════════════════════════════════════════════════════
#  STRONG PICKS (BUY/SELL sorted by composite)
# ═══════════════════════════════════════════════════════════════════════

def get_strong_picks(all_analysis, top_n=15):
    """Sort all analyzed symbols by composite.  Top = buy, bottom = sell."""
    scored = [(sym, a) for sym, a in all_analysis.items() if "composite" in a]
    scored.sort(key=lambda x: x[1].get("composite", 0), reverse=True)

    buy  = [a for _, a in scored[:top_n]]
    sell = [a for _, a in scored[-top_n:]][::-1]
    return {"buy": buy, "sell": sell}

# ═══════════════════════════════════════════════════════════════════════
#  TRADING SIGNALS TABLE (all symbols with signals)
# ═══════════════════════════════════════════════════════════════════════

def get_trading_signals(all_analysis):
    """All symbols sorted: STRONG BUY first, then BUY, HOLD, SELL, STRONG SELL."""
    signal_order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}
    items = [(sym, a) for sym, a in all_analysis.items()
             if not a.get("circuit_flag") and not a.get("liquidity_flag")]
    items.sort(key=lambda x: (signal_order.get(x[1].get("signal", "HOLD"), 2),
                              -x[1].get("composite", 0)))
    return [a for _, a in items]

# ═══════════════════════════════════════════════════════════════════════
#  MOMENTUM LEADERS TABLE
# ═══════════════════════════════════════════════════════════════════════

def get_momentum_leaders(all_analysis, top_n=50):
    """Top N by momentum_score."""
    items = [(sym, a) for sym, a in all_analysis.items() if "momentum_score" in a]
    items.sort(key=lambda x: x[1].get("momentum_score", 0), reverse=True)
    return [a for _, a in items[:top_n]]

# ═══════════════════════════════════════════════════════════════════════
#  RISK OVERVIEW
# ═══════════════════════════════════════════════════════════════════════

def get_risk_overview(all_analysis, top_n=50):
    """Top N most volatile stocks."""
    items = [(sym, a) for sym, a in all_analysis.items()]
    items.sort(key=lambda x: x[1].get("vol_20d", 0), reverse=True)
    result = []
    for _, a in items[:top_n]:
        vol = a.get("vol_20d", 0)
        risk_level = "HIGH" if vol > 3 else ("MEDIUM" if vol > 1.5 else "LOW")
        a["risk_level"] = risk_level
        result.append(a)
    return result

# ═══════════════════════════════════════════════════════════════════════
#  TECHNICAL SIGNALS (filtered view)
# ═══════════════════════════════════════════════════════════════════════

def get_technical_signals(all_analysis, top_n=60):
    """Return symbols sorted by signal priority + technical relevance."""
    items = [(sym, a) for sym, a in all_analysis.items()
             if a.get("signal") in ("BUY", "STRONG BUY")]
    items.sort(key=lambda x: x[1].get("composite", 0), reverse=True)
    if len(items) < top_n:
        sell_items = [(sym, a) for sym, a in all_analysis.items()
                      if a.get("signal") in ("SELL", "STRONG SELL")]
        sell_items.sort(key=lambda x: x[1].get("composite", 0))
        items.extend(sell_items)
    return [a for _, a in items[:top_n]]

# ═══════════════════════════════════════════════════════════════════════
#  RESEARCH INSIGHTS (static)
# ═══════════════════════════════════════════════════════════════════════

def research_insights():
    return [
        {"title": "📅 The Ashad Effect — Seasonal NEPSE Anomaly",
         "body": "July (Ashad/Shrawan) is historically the most bullish month in NEPSE. "
                 "Government capital expenditure rushes, dividend anticipation, and tax "
                 "clearance cycles create predictable liquidity waves. The scoring engine "
                 "automatically adds a +5-point seasonal bonus during this window."},
        {"title": "🧠 RSI Calibration: 80/20 for NEPSE",
         "body": "Standard RSI thresholds (70/30) cause premature exits in NEPSE bull runs. "
                 "During fierce bull cycles, stocks can hit 10% circuit breakers for consecutive "
                 "days, keeping RSI above 70 while prices double. This engine uses 80 (overbought) "
                 "and 20 (oversold) thresholds calibrated for NEPSE's unique dynamics."},
        {"title": "🔍 Microstructure Forensics — Smart Money Tracking",
         "body": "Broker-level floorsheet data reveals institutional accumulation patterns. "
                 "BOOM stocks are flagged when broker asymmetry > 65, consistent buying across "
                 "5+ sessions, volume ratio ≥ 1.3, and RSI between 40–75 — suggesting smart "
                 "money positioning before a breakout."},
        {"title": "📊 Volume Price Trend (VPT) Divergence",
         "body": "VPT scales volume by price change, giving higher weight to large moves. "
                 "When price makes a new high but VPT makes a lower high, it signals bearish "
                 "divergence — smart money distributing into retail demand."},
        {"title": "⚖️ ATR-Based Risk Management",
         "body": "Stop-loss = Entry − 1.5 × ATR(14). Target 1 = Entry + 2.0 × ATR. "
                 "Target 2 = Entry + 3.5 × ATR. Position size = (1.5% × Equity) / Risk per share. "
                 "Only signals with R:R ≥ 2.0 make the final watchlist."},
        {"title": "📈 Bollinger Squeeze → Breakout",
         "body": "When bands contract to within 4% of price (squeeze), followed by a close "
                 "above the upper band with volume ratio ≥ 1.5, it signals a high-probability "
                 "trend initiation. This is the most reliable breakout pattern on NEPSE."},
        {"title": "🎯 Fibonacci & Pivot Points",
         "body": "Standard and Fibonacci pivot points project next-session S/R levels. "
                 "If price breaks below the 61.8% Fibonacci retracement level, the uptrend "
                 "is mathematically invalidated and the stock is removed from long watchlists."},
    ]

# ═══════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════

def run_full_analysis():
    """Execute the complete analytics pipeline and return all data."""
    print("=" * 65)
    print("  NEPSE Stock Analytics Engine  — v3.0")
    print("=" * 65)

    conn = get_conn()
    try:
        print("\n🔌 Connected to database\n📊 Running analytics...\n")

        # Batch fetch
        all_ohlcv    = fetch_all_ohlcv(conn)
        all_corps    = fetch_all_corp_actions(conn)
        all_divs     = fetch_all_dividends(conn)
        all_details  = fetch_all_company_details(conn)
        all_securities = fetch_all_securities(conn)
        all_52w_snap = fetch_52w_from_snapshots(conn)
        all_live_ltp = fetch_all_live_ltp(conn)

        # Market context
        regime = get_market_regime(conn)
        set_dynamic_rsi(regime)
        print(f"  Market regime: {regime['regime']}  (factor {regime['factor']}, trend {regime.get('trend', 0)})")
        print(f"  Dynamic RSI thresholds: OB={get_rsi_ob()} / OS={get_rsi_os()}")

        s_bonus = seasonality_bonus()
        s_penalty = seasonality_penalty()
        if s_bonus:
            print(f"  Seasonal bonus active: +{s_bonus} pts (Ashad/Shrawan window)")
        if s_penalty:
            print(f"  Seasonal penalty active: {s_penalty} pts (Post-festive drain)")

        # Broker intelligence
        broker_scores, floorsheet_days = calc_broker_concentration(conn)
        boom_stocks, sell_distribution, floorsheet_days = find_boom_stocks(
            conn, broker_scores, all_ohlcv, all_corps, all_divs, floorsheet_days, all_live_ltp)

        # Overview
        ov = market_overview(conn)

        # Core analysis — every symbol
        all_analysis = analyze_all_symbols(
            all_ohlcv, all_corps, all_divs, all_details, all_securities,
            all_52w_snap, broker_scores, sell_distribution, regime, all_live_ltp)

        # Momentum composite scores (research formula)
        calc_momentum_composite(all_analysis)

        # Fundamentals
        fund = fundamental_analysis(conn)

        # Sector breadth
        sector_br = calc_sector_breadth(all_analysis, all_details, all_securities)

        # Composite scoring
        all_analysis = compute_composite_scores(all_analysis, fund, sector_br, regime)

        # Build outputs
        watchlist, circuit_alerts = build_watchlist(all_analysis)
        trading_signals = get_trading_signals(all_analysis)
        strong_picks = get_strong_picks(all_analysis)
        momentum_leaders = get_momentum_leaders(all_analysis)
        tech_signals = get_technical_signals(all_analysis)
        risk_data = get_risk_overview(all_analysis)

        # Additional data
        sectors = sector_breakdown(conn)
        gl = top_gainers_losers(conn)
        da = dividend_actions(conn)
        fl = floorsheet_forensics(conn)
        rk = scrip_rankings(conn)
        research = research_insights()

        data = {
            "overview": ov,
            "regime": regime,
            "watchlist": watchlist,
            "circuit_alerts": circuit_alerts,
            "trading_signals": trading_signals,
            "boom_stocks": boom_stocks,
            "strong_picks": strong_picks,
            "momentum": momentum_leaders,
            "fundamentals": fund,
            "technicals": tech_signals,
            "sectors": sectors,
            "sector_breadth": sector_br,
            "risk": risk_data,
            "gainers_losers": gl,
            "dividends_actions": da,
            "floorsheet": fl,
            "rankings": rk,
            "research": research,
            "all_analysis": all_analysis,
            "floorsheet_days": floorsheet_days,
        }

        print(f"\n  ✅ Analysis complete: {len(all_analysis)} symbols processed")
        return data

    finally:
        conn.close()
        print("  🔌 Database connection closed.")
