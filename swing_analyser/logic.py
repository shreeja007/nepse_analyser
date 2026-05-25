"""
NEPSE Swing Trading Analyser — Logic Module (v1.0)

Core engine: data fetching, indicator calculations, swing setup detection,
composite scoring, and watchlist generation for 1–2 month swing trades.
"""

import os, math
from datetime import datetime, timedelta
from collections import defaultdict

import pymysql

_DYNAMIC_RSI = {"ob": 80, "os": 20}

def set_dynamic_rsi(regime_dict):
    global _DYNAMIC_RSI
    reg = regime_dict.get("regime", "NEUTRAL")
    if reg == "STRONG_BULL":
        _DYNAMIC_RSI["ob"] = 85
        _DYNAMIC_RSI["os"] = 30
    elif reg == "STRONG_BEAR":
        _DYNAMIC_RSI["ob"] = 70
        _DYNAMIC_RSI["os"] = 15
    else:
        _DYNAMIC_RSI["ob"] = 80
        _DYNAMIC_RSI["os"] = 20

def get_rsi_ob(): return _DYNAMIC_RSI["ob"]
def get_rsi_os(): return _DYNAMIC_RSI["os"]


from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════
#  CONSTANTS — tuned for 1–2 month swing trades
# ═══════════════════════════════════════════════════════════════════════

ACCOUNT_EQUITY = 100_000      # Default; overridden by --equity CLI arg
RISK_PCT       = 0.015
ATR_SL_MULT    = 1.5              # Align risk doctrine with RR >= 2.0 baseline
ATR_T1_MULT    = 3.0              # Target 1 = 3× risk
ATR_T2_MULT    = 5.0              # Target 2 = 5× risk (swing sized)
RSI_OVERBOUGHT = 80  # Deprecated in favor of get_rsi_ob()               # NEPSE-calibrated
RSI_OVERSOLD = 20    # Deprecated in favor of get_rsi_os()
LOW_LIQ_THRESH = 5000
CIRCUIT_LIMIT  = 0.10
MIN_RR_RATIO   = 2.0
MIN_DATA_BARS  = 100
MAX_ATR_PCT    = 8.0
MIN_BROKER_PARTICIPANTS = 5
MIN_BROKER_TOTAL_AMOUNT = 5_000_000
MIN_BROKER_LIQ_VOLUME = 15_000
FUNDAMENTAL_STALE_DAYS = 540
MAX_POSITION_SHARE_OF_AVG_VOL = 0.02
MAX_CAPITAL_ALLOCATION_PCT = 0.25
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
#  BATCH DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════

def fetch_all_ohlcv(conn):
    """Batch-fetch ALL equity OHLCV with open_price fix.
    Appends rows from daily_prices when a symbol-date is missing in daily_ohlcv."""
    print("  [data] Fetching OHLCV (with open_price fix)...")
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
          AND s.instrument_type = 'Equity'

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
          AND s.instrument_type = 'Equity'

        ORDER BY symbol, trading_date ASC
    """)
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)


def fetch_all_corp_actions(conn):
    rows = q(conn, "SELECT symbol, action_type, ratio, book_close_date FROM corporate_actions ORDER BY book_close_date ASC")
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)


def fetch_all_dividends(conn):
    rows = q(conn, "SELECT symbol, bonus_share_percent, cash_dividend_percent, book_close_date FROM dividends ORDER BY book_close_date ASC")
    data = defaultdict(list)
    for r in rows:
        data[r["symbol"]].append(r)
    return dict(data)


def fetch_all_company_details(conn):
    rows = q(conn, "SELECT symbol, security_name, sector_name, fifty_two_week_high, fifty_two_week_low, market_capitalization, stock_listed_shares FROM company_details")
    return {r["symbol"]: r for r in rows}


def fetch_all_securities(conn):
    rows = q(conn, "SELECT symbol, sector_name, instrument_type FROM securities")
    return {r["symbol"]: r for r in rows}


def fetch_52w_from_snapshots(conn):
    rows = q(conn, "SELECT symbol, MAX(fifty_two_week_high) as hi52, MIN(fifty_two_week_low) as lo52 FROM live_market_snapshots WHERE fifty_two_week_high > 0 AND fifty_two_week_low > 0 GROUP BY symbol")
    return {r["symbol"]: r for r in rows}


def fetch_all_live_ltp(conn):
    """Latest LTP from live_market_snapshots."""
    print("  [data] Fetching live LTP...")
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


def fetch_all_fundamentals(conn):
    """Latest fundamentals per symbol."""
    raw = q(conn, """
     SELECT cf.symbol, cf.eps, cf.pe_ratio, cf.book_value, cf.net_profit,
         cf.published_date,
               cd.sector_name
        FROM company_fundamentals cf
        JOIN company_details cd ON cf.symbol = cd.symbol
        ORDER BY cf.symbol, cf.published_date DESC
    """)
    seen, result = set(), {}
    for r in raw:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            result[r["symbol"]] = r
    return result


def fetch_broker_scores(conn):
    """Buy/sell asymmetry per symbol from floorsheet."""
    print("  [data] Computing broker asymmetry...")
    try:
        # Fetch max date once to avoid repeating the subquery 3 times
        max_date_row = qone(conn, "SELECT MAX(trading_date) AS max_dt FROM floorsheet_transactions")
        max_dt = max_date_row.get("max_dt")
        if not max_dt:
            return {}
        buy_rows = q(conn, """
            SELECT symbol, buyer_broker_id, SUM(amount) AS buy_amt
            FROM floorsheet_transactions
            WHERE trading_date >= DATE_SUB(%s, INTERVAL 30 DAY)
            GROUP BY symbol, buyer_broker_id
        """, (max_dt,))
        sell_rows = q(conn, """
            SELECT symbol, seller_broker_id, SUM(amount) AS sell_amt
            FROM floorsheet_transactions
            WHERE trading_date >= DATE_SUB(%s, INTERVAL 30 DAY)
            GROUP BY symbol, seller_broker_id
        """, (max_dt,))
        buy_total_rows = q(conn, """
            SELECT symbol, SUM(amount) AS total_buy
            FROM floorsheet_transactions
            WHERE trading_date >= DATE_SUB(%s, INTERVAL 30 DAY)
            GROUP BY symbol
        """, (max_dt,))
        buy_total_map = {r["symbol"]: float(r["total_buy"] or 0) for r in buy_total_rows}
        sym_buy = defaultdict(list)
        participants = defaultdict(set)
        for r in buy_rows:
            sym_buy[r["symbol"]].append(float(r["buy_amt"] or 0))
            participants[r["symbol"]].add(r.get("buyer_broker_id"))
        sym_sell = defaultdict(list)
        for r in sell_rows:
            sym_sell[r["symbol"]].append(float(r["sell_amt"] or 0))
            participants[r["symbol"]].add(r.get("seller_broker_id"))

        scores = {}
        for sym in set(sym_buy) | set(sym_sell):
            total = buy_total_map.get(sym, 0)
            if total <= 0:
                scores[sym] = 50
                continue

            # Low participant count makes concentration metrics unstable.
            if len(participants.get(sym, set())) < MIN_BROKER_PARTICIPANTS:
                scores[sym] = 50
                continue

            # Thin traded value creates brittle concentration signals.
            if total < MIN_BROKER_TOTAL_AMOUNT:
                scores[sym] = 50
                continue

            ba = sorted(sym_buy.get(sym, []), reverse=True)
            bc = sum(ba[:3]) / total * 100 if ba else 0
            sa = sorted(sym_sell.get(sym, []), reverse=True)
            sc = sum(sa[:3]) / total * 100 if sa else 0
            scores[sym] = max(0, min(100, round(50 + (bc - sc) / 2, 1)))
        return scores
    except Exception as e:
        print(f"  ⚠ Broker scores error: {e}")
        return {}


def get_market_regime(conn):
    """Multi-day regime detection using 10-day trend of NEPSE index.
    Prevents a single green/red day from flipping all signals."""
    try:
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

        if trend > 3.0:
            return {"regime": "STRONG_BULL", "factor": 1.05, "chg": today_chg, "trend": round(trend, 2)}
        if trend > 1.0:
            return {"regime": "BULLISH",     "factor": 1.02, "chg": today_chg, "trend": round(trend, 2)}
        if trend < -3.0:
            return {"regime": "STRONG_BEAR", "factor": 0.95, "chg": today_chg, "trend": round(trend, 2)}
        if trend < -1.0:
            return {"regime": "BEARISH",     "factor": 0.98, "chg": today_chg, "trend": round(trend, 2)}
        return {"regime": "NEUTRAL", "factor": 1.0, "chg": today_chg, "trend": round(trend, 2)}
    except Exception as e:
        print(f"  ⚠ Market regime query failed ({e}), defaulting to NEUTRAL")
        return {"regime": "NEUTRAL", "factor": 1.0, "chg": 0, "trend": 0}


def _is_fundamental_stale(fund_row, max_age_days=FUNDAMENTAL_STALE_DAYS):
    if not fund_row:
        return True
    pd_val = str(fund_row.get("published_date") or "")[:10]
    if not pd_val:
        return True
    try:
        age = (datetime.now().date() - datetime.strptime(pd_val, "%Y-%m-%d").date()).days
        return age > max_age_days
    except ValueError:
        return True


def _compute_data_confidence(*, bars, avg_volume, circuit_volatile, fundamental_stale, has_live_price,
                             excessive_forward_fill):
    score = 100
    if bars < 150:
        score -= 20
    if avg_volume < 10_000:
        score -= 15
    if circuit_volatile:
        score -= 15
    if fundamental_stale:
        score -= 10
    if not has_live_price:
        score -= 5
    if excessive_forward_fill:
        score -= 10
    return max(0, min(100, int(score)))


# ═══════════════════════════════════════════════════════════════════════
#  DATA PIPELINE — Adjust, Fill, Resample
# ═══════════════════════════════════════════════════════════════════════

def bridge_live_candle(ohlcv_candles, live_row):
    if not live_row or not ohlcv_candles:
        return ohlcv_candles
    live_date = str(live_row.get("trading_date") or "")[:10]
    last_date = str(ohlcv_candles[-1].get("trading_date") or "")[:10]
    today_iso = datetime.now().date().isoformat()
    if live_date and live_date > last_date and live_date < today_iso:
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
            "volume": max(0, int(live_row.get("volume") or 0)),
            "is_synthetic_open": 0,
            "is_live_bridge": 1,
        }
        return ohlcv_candles + [synthetic]
    return ohlcv_candles


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
        cash = float(div.get("cash_dividend_percent") or 0)
        if bonus > 0:
            adjustments.append((bcd, 1.0 / (1.0 + bonus / 100.0)))
        if cash > 0:
            cum_price = None
            for c in candles:
                if str(c["trading_date"]) < bcd:
                    cum_price = float(c["close_price"])
                else:
                    break
            if cum_price and cum_price > 0:
                factor = (cum_price - cash) / cum_price
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
                    rr = float(parts[0]) / float(parts[1])
                    cum_price = None
                    for c in candles:
                        if str(c["trading_date"]) < bcd:
                            cum_price = float(c["close_price"])
                        else:
                            break
                    if cum_price and cum_price > 0:
                        terp = (cum_price + 100.0 * rr) / (1.0 + rr)
                        factor = terp / cum_price
                        if 0 < factor < 1 and not _is_dup_adjustment(adjustments, bcd, factor):
                            adjustments.append((bcd, factor))
            except (ValueError, ZeroDivisionError):
                pass
        elif "bonus" in atype or "split" in atype:
            try:
                factor = None
                if ":" in ratio_str:
                    parts = ratio_str.split(":")
                    if len(parts) == 2:
                        factor = 1.0 / (1.0 + float(parts[0]) / float(parts[1]))
                elif ratio_str.endswith("%"):
                    pct = float(ratio_str.rstrip("%"))
                    if pct > 0:
                        factor = 1.0 / (1.0 + pct / 100.0)
                if factor is not None and 0 < factor < 1 and not _is_dup_adjustment(adjustments, bcd, factor):
                    adjustments.append((bcd, factor))
            except (ValueError, ZeroDivisionError):
                pass
    if not adjustments:
        return candles
    adjustments.sort(key=lambda x: x[0])
    dates = [str(c["trading_date"]) for c in candles]
    closes = [float(c["close_price"]) for c in candles]
    opens = [float(c.get("open_price") or c["close_price"]) for c in candles]
    highs = [float(c.get("high_price") or c["close_price"]) for c in candles]
    lows = [float(c.get("low_price") or c["close_price"]) for c in candles]
    for event_date, factor in adjustments:
        for i, d in enumerate(dates):
            if d < event_date:
                closes[i] *= factor
                opens[i] *= factor
                highs[i] *= factor
                lows[i] *= factor
    adj = []
    for i, c in enumerate(candles):
        row = dict(c)
        row["close_price"] = closes[i]
        row["open_price"] = opens[i]
        row["high_price"] = highs[i]
        row["low_price"] = lows[i]
        adj.append(row)
    return adj


def forward_fill_zero_volume_days(candles):
    if not candles:
        return candles
    filled = []
    last_active = None
    zero_streak = 0
    for c in candles:
        row = dict(c)
        vol = int(row.get("volume") or 0)
        if vol == 0 and last_active is not None:
            zero_streak += 1
            for k in ("open_price", "high_price", "low_price", "close_price"):
                row[k] = last_active
            row["is_forward_filled"] = 1
        else:
            zero_streak = 0
            row["is_forward_filled"] = 0
            last_active = float(row["close_price"])
        row["forward_fill_streak"] = zero_streak
        row["forward_fill_limit_exceeded"] = int(zero_streak > MAX_FORWARD_FILL_STREAK)
        filled.append(row)
    return filled


def _max_forward_fill_streak(candles):
    max_streak = 0
    for c in candles:
        max_streak = max(max_streak, int(c.get("forward_fill_streak") or 0))
    return max_streak


def resample_to_weekly(candles):
    """Aggregate daily candles into weekly OHLCV (Sun–Thu for NEPSE)."""
    if not candles:
        return []
    weeks = []
    week = None
    for c in candles:
        try:
            dt = datetime.strptime(str(c["trading_date"])[:10], "%Y-%m-%d")
        except ValueError:
            continue
        iso_year, iso_week, _ = dt.isocalendar()
        key = (iso_year, iso_week)
        o = float(c.get("open_price") or c["close_price"])
        h = float(c.get("high_price") or c["close_price"])
        l = float(c.get("low_price") or c["close_price"])
        cl = float(c["close_price"])
        v = int(c.get("volume") or 0)
        if week is None or week["_key"] != key:
            if week:
                weeks.append(week)
            week = {"_key": key, "trading_date": c["trading_date"],
                    "open_price": o, "high_price": h, "low_price": l,
                    "close_price": cl, "volume": v}
        else:
            if h > week["high_price"]:
                week["high_price"] = h
            if l < week["low_price"]:
                week["low_price"] = l
            week["close_price"] = cl
            week["volume"] += v
            week["trading_date"] = c["trading_date"]
    if week:
        weeks.append(week)
    for w in weeks:
        del w["_key"]
    return weeks


# ═══════════════════════════════════════════════════════════════════════
#  INDICATOR CALCULATIONS
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
    mv, sv = macd_line[-1], signal_line[-1]
    return round(mv, 2), round(sv, 2), round(mv - sv, 2), macd_line

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
    """Slow Stochastic: smooth raw %K with d_period SMA, then derive %D."""
    if len(candles) < k_period:
        return None, None
    raw_k = []
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1: i + 1]
        highest = max(float(c["high_price"]) for c in window)
        lowest = min(float(c["low_price"]) for c in window)
        close = float(candles[i]["close_price"])
        raw_k.append((close - lowest) / (highest - lowest) * 100 if highest != lowest else 50.0)
    # Slow %K = SMA(raw_k, d_period)
    if len(raw_k) < d_period:
        return round(raw_k[-1], 1), None
    slow_k = []
    for i in range(d_period - 1, len(raw_k)):
        slow_k.append(sum(raw_k[i - d_period + 1: i + 1]) / d_period)
    # Slow %D = SMA(slow_k, d_period)
    if len(slow_k) < d_period:
        return round(slow_k[-1], 1), None
    slow_d = sum(slow_k[-d_period:]) / d_period
    return round(slow_k[-1], 1), round(slow_d, 1)

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

def calc_obv_trend(closes, volumes, lookback=30):
    """OBV trend over 30 bars (6 trading weeks) — appropriate for swing."""
    obv = calc_obv(closes, volumes)
    if len(obv) >= lookback:
        slope = obv[-1] - obv[-lookback]
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
    return round(middle + std_dev * sigma, 2), round(middle, 2), round(middle - std_dev * sigma, 2)

def calc_adx(candles, period=14):
    """Average Directional Index — trend strength (>25 = trending)."""
    if len(candles) < period * 2 + 1:
        return None
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(candles)):
        hi = float(candles[i]["high_price"])
        lo = float(candles[i]["low_price"])
        phi = float(candles[i-1]["high_price"])
        plo = float(candles[i-1]["low_price"])
        pc = float(candles[i-1]["close_price"])
        up = hi - phi
        down = plo - lo
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr_list.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    # Wilder smooth
    atr_s = sum(tr_list[:period]) / period
    pdm_s = sum(plus_dm[:period]) / period
    mdm_s = sum(minus_dm[:period]) / period
    dx_vals = []
    for i in range(period, len(tr_list)):
        atr_s = (atr_s * (period - 1) + tr_list[i]) / period
        pdm_s = (pdm_s * (period - 1) + plus_dm[i]) / period
        mdm_s = (mdm_s * (period - 1) + minus_dm[i]) / period
        if atr_s == 0:
            dx_vals.append(0)
            continue
        pdi = pdm_s / atr_s * 100
        mdi = mdm_s / atr_s * 100
        dsum = pdi + mdi
        dx_vals.append(abs(pdi - mdi) / dsum * 100 if dsum > 0 else 0)
    if len(dx_vals) < period:
        return round(dx_vals[-1], 1) if dx_vals else None
    adx = sum(dx_vals[:period]) / period
    for dx in dx_vals[period:]:
        adx = (adx * (period - 1) + dx) / period
    return round(adx, 1)

def detect_candlestick_patterns(candles):
    if len(candles) < 2:
        return []
    patterns = []
    c, p = candles[-1], candles[-2]
    if any(int(x.get("is_synthetic_open") or 0) for x in (c, p)):
        return []
    if any(int(x.get("forward_fill_limit_exceeded") or 0) for x in (c, p)):
        return []
    o = float(c["open_price"])
    h = float(c["high_price"])
    l = float(c["low_price"])
    cl = float(c["close_price"])
    hl = h - l
    body = abs(o - cl)
    if hl <= 0:
        return []
    if body <= 0.05 * hl:
        patterns.append("Doji")
    closes_20 = [float(candles[i]["close_price"]) for i in range(max(0, len(candles)-20), len(candles))]
    sma20 = sum(closes_20) / len(closes_20) if closes_20 else cl
    if float(p["close_price"]) < sma20:
        if body <= 0.3 * hl and min(o, cl) - l >= 2 * body and h - max(o, cl) <= 0.1 * hl:
            patterns.append("Hammer")
    po, pc = float(p["open_price"]), float(p["close_price"])
    if pc < po and cl > o and o < pc and cl > po:
        patterns.append("Bullish Engulfing")
    return patterns

def is_bollinger_squeeze(upper, middle, lower):
    """BB squeeze tuned for NEPSE frontier-market volatility (6% threshold)."""
    if upper is None or middle is None or lower is None or middle == 0:
        return False
    return (upper - lower) / middle < 0.06

def is_circuit_volatile(candles, lookback=5, threshold=2):
    if len(candles) < 2:
        return False
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    count = 0
    for i in range(1, len(recent)):
        pc = float(recent[i-1]["close_price"])
        cc = float(recent[i]["close_price"])
        if pc > 0 and abs(cc - pc) / pc >= CIRCUIT_LIMIT:
            count += 1
    return count > threshold

def check_macd_bullish_crossover(macd_line):
    """Detect if MACD histogram just turned positive (bullish crossover)."""
    if macd_line and len(macd_line) >= 2:
        sig_ema = calc_ema(macd_line, 9)
        if len(sig_ema) >= 2:
            prev_h = macd_line[-2] - sig_ema[-2]
            curr_h = macd_line[-1] - sig_ema[-1]
            if prev_h <= 0 and curr_h > 0:
                return True
    return False

def check_ma_crossover(closes, sma20, sma50):
    """Classify 20/50 MA crossover status (GOLDEN, DEATH, BULLISH, BEARISH, NEUTRAL)."""
    if sma20 is not None and sma50 is not None and len(closes) >= 51:
        prev_sma20 = sum(closes[-21:-1]) / 20
        prev_sma50 = sum(closes[-51:-1]) / 50
        if sma20 > sma50 and prev_sma20 <= prev_sma50:
            return "GOLDEN"
        elif sma20 < sma50 and prev_sma20 >= prev_sma50:
            return "DEATH"
        elif sma20 > sma50:
            return "BULLISH"
        else:
            return "BEARISH"
    return "NEUTRAL"

def is_low_liquidity(candles, min_avg=None):
    if min_avg is None:
        min_avg = LOW_LIQ_THRESH
    if len(candles) < 5:
        return True
    vols = [int(c.get("volume") or 0) for c in candles[-20:]]
    return (sum(vols) / len(vols) if vols else 0) < min_avg

def seasonality_adj():
    m = datetime.now().month
    if m in (6, 7): return 5    # Ashad/Shrawan bullish
    if m in (1, 2): return -5   # Post-festive drain
    return 0


# ═══════════════════════════════════════════════════════════════════════
#  SWING SETUP DETECTION
# ═══════════════════════════════════════════════════════════════════════

def _detect_swing_setups(*, price, candles, weekly_uptrend, w_rsi,
                         sma20, sma50, rsi, macd_hist, macd_just_bullish,
                         adx, bb_squeeze, stoch_k, stoch_d, obv_trend,
                         vol_ratio, lo52, patterns, broker_asym, cross):
    """Detect which swing setup(s) the stock matches. Returns list of setup dicts."""
    setups = []

    # Weekly trend (received pre-computed from orchestrator — bug #8 dedup)

    # ── 1. PULLBACK TO SUPPORT ──
    if (weekly_uptrend and sma20 and sma50 and
        sma20 > sma50 and price <= sma20 * 1.02 and price >= sma50 * 0.98 and
        rsi is not None and 30 <= rsi <= 55 and
        obv_trend != "FALLING"):
        conf = 60
        if patterns and any(p in ("Hammer", "Bullish Engulfing", "Doji") for p in patterns):
            conf += 15
        if macd_hist is not None and macd_hist > -1:
            conf += 10
        if broker_asym > 55:
            conf += 5
        if w_rsi and 40 < w_rsi < 70:
            conf += 5
        setups.append({
            "setup_type": "PULLBACK_TO_SUPPORT",
            "confidence": min(conf, 95),
            "reasoning": [
                "Weekly uptrend intact (price > weekly SMA10)",
                f"Daily pullback to SMA20/50 zone (RSI: {rsi:.0f})",
                f"Patterns: {', '.join(patterns)}" if patterns else "No reversal pattern yet",
            ],
        })

    # ── 2. BREAKOUT ACCUMULATION ──
    squeeze_sessions = 0
    if len(candles) >= 20:
        for i in range(max(0, len(candles) - 30), len(candles)):
            sub = [float(candles[j]["close_price"]) for j in range(max(0, i-19), i+1)]
            if len(sub) >= 20:
                bu, bm, bl = calc_bollinger_bands(sub)
                if bu and bm and bl and bm > 0 and (bu - bl) / bm < 0.06:
                    squeeze_sessions += 1

    if (bb_squeeze and squeeze_sessions >= 10 and
        adx is not None and adx < 25 and
        broker_asym > 55):
        conf = 55
        if vol_ratio >= 1.3:
            conf += 15
        if squeeze_sessions >= 20:
            conf += 10
        if broker_asym > 65:
            conf += 10
        setups.append({
            "setup_type": "BREAKOUT_ACCUMULATION",
            "confidence": min(conf, 95),
            "reasoning": [
                f"Bollinger squeeze for {squeeze_sessions} sessions",
                f"ADX {adx:.0f} — low trend (consolidating)",
                f"Broker accumulation score: {broker_asym:.0f}",
            ],
        })

    # ── 3. GOLDEN CROSS ENTRY ──
    if (cross == "GOLDEN" and price > sma20 and price > sma50 and
        vol_ratio >= 1.2):
        conf = 65
        if macd_hist and macd_hist > 0:
            conf += 10
        if obv_trend == "RISING":
            conf += 10
        if weekly_uptrend:
            conf += 5
        setups.append({
            "setup_type": "GOLDEN_CROSS_ENTRY",
            "confidence": min(conf, 95),
            "reasoning": [
                "SMA20 just crossed above SMA50 (Golden Cross)",
                f"Price confirmed above both MAs",
                f"Volume ratio: {vol_ratio:.1f}x average",
            ],
        })

    # ── 4. OVERSOLD REVERSAL ──
    near_52w_low = lo52 > 0 and price <= lo52 * 1.05
    if (rsi is not None and rsi < 30 and near_52w_low and
        w_rsi is not None and w_rsi > 25):
        conf = 50
        if patterns and any(p in ("Hammer", "Bullish Engulfing") for p in patterns):
            conf += 20
        if stoch_k is not None and stoch_k < 20 and stoch_d is not None and stoch_k > stoch_d:
            conf += 10
        if vol_ratio >= 1.3:
            conf += 10
        setups.append({
            "setup_type": "OVERSOLD_REVERSAL",
            "confidence": min(conf, 95),
            "reasoning": [
                f"RSI deeply oversold ({rsi:.0f}) near 52W low",
                f"Weekly RSI {w_rsi:.0f} — not in freefall",
                f"Patterns: {', '.join(patterns)}" if patterns else "Awaiting reversal pattern",
            ],
        })

    # ── 5. BASE BREAKOUT ──
    if len(candles) >= 25:
        base_candles = candles[-25:-1]
        base_highs = [float(c["high_price"]) for c in base_candles]
        base_lows = [float(c["low_price"]) for c in base_candles]
        if base_highs and base_lows:
            range_high = max(base_highs)
            range_low = min(base_lows)
            range_pct = (range_high - range_low) / range_low * 100 if range_low > 0 else 999
            if range_pct < 10 and price > range_high and vol_ratio >= 1.5:
                conf = 60
                if adx and adx > 20:
                    conf += 10
                if macd_just_bullish:
                    conf += 10
                if obv_trend == "RISING":
                    conf += 10
                setups.append({
                    "setup_type": "BASE_BREAKOUT",
                    "confidence": min(conf, 95),
                    "reasoning": [
                        f"Broke above {range_pct:.1f}% consolidation range",
                        f"Volume surge: {vol_ratio:.1f}x average",
                        f"Range high was Rs {range_high:.0f}",
                    ],
                })

    # ── 6. SECTOR ROTATION (simpler check) ──
    if (sma50 and price > sma50 and rsi and 40 < rsi < 65 and
        obv_trend == "RISING" and not near_52w_low and
        adx is not None and adx > 20):
        # Only add if no other setup matched (catch-all for trending+volume)
        if not setups:
            conf = 45
            if macd_hist and macd_hist > 0:
                conf += 10
            if broker_asym > 55:
                conf += 10
            if weekly_uptrend:
                conf += 10
            setups.append({
                "setup_type": "TREND_CONTINUATION",
                "confidence": min(conf, 90),
                "reasoning": [
                    f"Above SMA50, ADX {adx:.0f} (trending)",
                    "OBV rising — volume confirms trend",
                    f"RSI {rsi:.0f} — healthy momentum zone",
                ],
            })

    return setups


# ═══════════════════════════════════════════════════════════════════════
#  COMPOSITE SCORING & SIGNAL CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

def _calc_swing_composite(*, price, sma20, sma50, sma200, rsi, macd_hist,
                           macd_just_bullish, vol_ratio, obv_trend, adx,
                           cross, bb_pct, setup_conf, atr, hi52, lo52,
                           broker_asym, fund, weekly_uptrend,
                           roc_20=None, roc_60=None, high_prox=None):
    """6-dimension composite score for swing ranking."""
    # 1. Trend Alignment (25%)
    trend = 50
    if sma20 and sma50 and sma200:
        if price > sma20 > sma50 > sma200: trend = 100
        elif price > sma20 and price > sma50: trend = 80
        elif price > sma50: trend = 60
        elif price < sma50 and price < sma200: trend = 10
        else: trend = 30
    elif sma20 and sma50:
        if price > sma20 > sma50: trend = 80
        elif price > sma50: trend = 60
        else: trend = 30
    if weekly_uptrend:
        trend = min(100, trend + 10)
    if cross == "GOLDEN":
        trend = min(100, trend + 15)
    elif cross == "DEATH":
        trend = max(0, trend - 15)

    # 2. Momentum Timing (20%)
    mom = 50
    if rsi is not None:
        if 40 <= rsi <= 60: mom += 10
        elif rsi < RSI_OVERSOLD: mom += 15
        elif rsi > RSI_OVERBOUGHT: mom -= 15
    if macd_hist is not None:
        mom += 15 if macd_hist > 0 else -10
    if macd_just_bullish:
        mom += 10
    # ROC contribution (research-recommended rate-of-change signal)
    if roc_20 is not None:
        if roc_20 > 10: mom += 10
        elif roc_20 > 3: mom += 5
        elif roc_20 < -10: mom -= 10
    if roc_60 is not None:
        if roc_60 > 15: mom += 5
        elif roc_60 < -15: mom -= 5
    mom = max(0, min(100, mom))

    # 3. Volume Profile (20%) — now includes broker_asym
    vol = 50
    vr = min(vol_ratio, 5)
    vol += (vr - 1) * 8
    if obv_trend == "RISING": vol += 15
    elif obv_trend == "FALLING": vol -= 15
    # Broker accumulation (smart money signal from floorsheet forensics)
    if broker_asym > 65: vol += 12
    elif broker_asym > 55: vol += 5
    elif broker_asym < 40: vol -= 10
    vol = max(0, min(100, vol))

    # 4. Setup Quality (15%)
    setup = max(0, min(100, setup_conf))

    # 5. Risk/Reward (10%) — now uses bb_pct, hi52/lo52 proximity
    risk = 70
    if atr and price > 0:
        atr_pct = atr / price * 100
        if atr_pct > 5: risk -= 25
        elif atr_pct > 3: risk -= 10
    if adx and adx < 15:
        risk -= 10  # Dead stock penalty
    # Bollinger position: penalise if stretched to upper band
    if bb_pct is not None:
        if bb_pct > 90: risk -= 10
        elif bb_pct < 20: risk += 5
    # 52W proximity: penalise near high (limited upside), reward near low
    if high_prox is not None:
        if high_prox < 3: risk -= 10   # within 3% of 52W high
        elif high_prox > 30: risk += 5  # plenty of headroom
    risk = max(0, min(100, risk))

    # 6. Fundamental Floor (10%)
    funda = 50
    if fund:
        pe = float(fund.get("pe_ratio") or 0)
        eps = float(fund.get("eps") or 0)
        if 0 < pe <= 15: funda += 20
        elif 15 < pe <= 25: funda += 10
        elif pe > 40: funda -= 15
        if eps > 20: funda += 15
        elif eps > 5: funda += 8
        elif eps <= 0: funda -= 15
    funda = max(0, min(100, funda))

    composite = (trend * 0.25 + mom * 0.20 + vol * 0.20 +
                 setup * 0.15 + risk * 0.10 + funda * 0.10)

    return {
        "composite": round(composite, 2),
        "trend_score": round(trend, 1),
        "momentum_score": round(mom, 1),
        "volume_score": round(vol, 1),
        "setup_score": round(setup, 1),
        "risk_score": round(risk, 1),
        "fundamental_score": round(funda, 1),
    }


def _classify_signal(composite, setup_conf):
    if composite >= 75 and setup_conf >= 70:
        return "STRONG BUY"
    if composite >= 55 and setup_conf >= 50:
        return "BUY"
    return "HOLD"


def _calc_entry_zone(price, atr, setup_type):
    if atr is None or atr <= 0:
        return (round(price * 0.98, 2), round(price, 2))
    if setup_type in ("PULLBACK_TO_SUPPORT", "OVERSOLD_REVERSAL"):
        return (round(price - atr * 0.3, 2), round(price + atr * 0.2, 2))
    if setup_type in ("BASE_BREAKOUT", "BREAKOUT_ACCUMULATION"):
        return (round(price, 2), round(price + atr * 0.5, 2))
    return (round(price - atr * 0.3, 2), round(price + atr * 0.3, 2))


def _est_hold_period(setup_type):
    return {
        "PULLBACK_TO_SUPPORT": "20–40 days",
        "BREAKOUT_ACCUMULATION": "30–60 days",
        "GOLDEN_CROSS_ENTRY": "30–50 days",
        "OVERSOLD_REVERSAL": "25–45 days",
        "BASE_BREAKOUT": "20–40 days",
        "TREND_CONTINUATION": "30–60 days",
    }.get(setup_type, "30–45 days")


# ═══════════════════════════════════════════════════════════════════════
#  SECTOR BREADTH
# ═══════════════════════════════════════════════════════════════════════

def _calc_sector_breadth(analysis_results, all_details, all_securities):
    sector_stocks = defaultdict(list)
    for sym, data in analysis_results.items():
        sector = (data.get("sector")
                  or all_details.get(sym, {}).get("sector_name")
                  or all_securities.get(sym, {}).get("sector_name")
                  or "Other")
        sector_stocks[sector].append(data)
    breadth = {}
    for sector, stocks in sector_stocks.items():
        above = sum(1 for s in stocks if s.get("sma50") and s["price"] > s["sma50"])
        total = len(stocks)
        breadth[sector] = {
            "total": total, "above_sma50": above,
            "pct": round(above / total * 100, 1) if total > 0 else 0,
        }
    return breadth


# ═══════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════

def run_swing_analysis(top_n=15, min_avg_volume=5000, account_equity=None):
    """Execute the full swing analysis pipeline."""
    equity = account_equity or ACCOUNT_EQUITY
    print(f"\n  📊 Starting swing analysis pipeline (equity: Rs {equity:,.0f})...\n")
    conn = get_conn()
    try:
        # ── Batch fetch ──
        all_ohlcv = fetch_all_ohlcv(conn)
        all_corps = fetch_all_corp_actions(conn)
        all_divs = fetch_all_dividends(conn)
        all_details = fetch_all_company_details(conn)
        all_securities = fetch_all_securities(conn)
        all_52w = fetch_52w_from_snapshots(conn)
        all_live = fetch_all_live_ltp(conn)
        all_fund = fetch_all_fundamentals(conn)
        broker_scores = fetch_broker_scores(conn)
        regime = get_market_regime(conn)
        set_dynamic_rsi(regime)
        total_universe = len(all_ohlcv)

        print(f"  Market regime: {regime['regime']} (NEPSE {regime['chg']:+.2f}%)")

        # ── Per-symbol analysis ──
        print(f"  [engine] Analyzing {len(all_ohlcv)} symbols for swing setups...")
        analysis_results = {}
        swing_candidates = []
        errors = {}  # Track per-symbol errors instead of silent swallow
        processed_symbols = 0
        diagnostics = {
            "insufficient_bars": 0,
            "liquidity_filtered": 0,
            "circuit_filtered": 0,
            "stale_forward_fill": 0,
            "sma200_filtered": 0,
            "atr_filtered": 0,
            "no_setup": 0,
        }

        for sym, raw_candles in all_ohlcv.items():
            processed_symbols += 1
            try:
                # Data pipeline
                live_row = all_live.get(sym)
                bridged = bridge_live_candle(raw_candles, live_row)
                candles = get_adjusted_series(bridged, all_corps.get(sym, []), all_divs.get(sym, []))
                candles = forward_fill_zero_volume_days(candles)
                max_fill_streak = _max_forward_fill_streak(candles)

                if len(candles) < MIN_DATA_BARS:
                    diagnostics["insufficient_bars"] += 1
                    continue

                if max_fill_streak > MAX_FORWARD_FILL_STREAK:
                    diagnostics["stale_forward_fill"] += 1
                    continue

                closes = [float(c["close_price"]) for c in candles]
                volumes = [int(c.get("volume") or 0) for c in candles]

                # Live price
                if live_row and float(live_row.get("last_traded_price") or 0) > 0:
                    price = float(live_row["last_traded_price"])
                else:
                    price = closes[-1]
                if price <= 0:
                    continue

                # Filters — early exit
                if is_low_liquidity(candles, min_avg_volume):
                    diagnostics["liquidity_filtered"] += 1
                    continue
                if is_circuit_volatile(candles):
                    diagnostics["circuit_filtered"] += 1
                    continue

                # Weekly resample
                weekly = resample_to_weekly(candles)

                # Daily indicators
                sma20 = calc_sma(closes, 20)
                sma50 = calc_sma(closes, 50)
                sma200 = calc_sma(closes, 200)
                rsi = calc_rsi(closes)
                macd_val, sig_val, macd_hist, macd_line = calc_macd(closes)
                atr = calc_circuit_adjusted_atr(candles)
                if atr is None:
                    atr = calc_atr(candles)
                stoch_k, stoch_d = calc_stochastic(candles)
                obv_trend = calc_obv_trend(closes, volumes)
                bb_upper, bb_middle, bb_lower = calc_bollinger_bands(closes)
                bb_squeeze = is_bollinger_squeeze(bb_upper, bb_middle, bb_lower)
                adx = calc_adx(candles)
                roc_20 = calc_roc(closes, 20)
                roc_60 = calc_roc(closes, 60) if len(closes) > 61 else None
                patterns = detect_candlestick_patterns(candles)

                vol_avg = sum(volumes[-20:]) / min(len(volumes[-20:]), 20) if volumes else 0
                vol_ratio = round(volumes[-1] / vol_avg, 2) if vol_avg > 0 else 0

                bb_pct = None
                if bb_upper and bb_lower and bb_upper != bb_lower:
                    bb_pct = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1)

                # MACD crossover detection
                macd_just_bullish = check_macd_bullish_crossover(macd_line)

                # MA crossover
                cross = check_ma_crossover(closes, sma20, sma50)

                # 52W data — fixed operator precedence (bug #1)
                det = all_details.get(sym, {})
                snap52 = all_52w.get(sym, {})
                _snap_hi = float(snap52.get("hi52") or 0)
                _det_hi = float(det.get("fifty_two_week_high") or 0)
                _calc_hi = max(closes[-252:]) if len(closes) >= 252 else max(closes)
                hi52 = _snap_hi or _det_hi or _calc_hi
                _snap_lo = float(snap52.get("lo52") or 0)
                _det_lo = float(det.get("fifty_two_week_low") or 0)
                _calc_lo = min(closes[-252:]) if len(closes) >= 252 else min(closes)
                lo52 = _snap_lo or _det_lo or _calc_lo

                sector = (det.get("sector_name")
                          or all_securities.get(sym, {}).get("sector_name") or "")
                broker_asym = broker_scores.get(sym, 50)
                if vol_avg < MIN_BROKER_LIQ_VOLUME:
                    broker_asym = 50

                # ── SMA200 trend filter (with carve-out for OVERSOLD_REVERSAL) ──
                near_52w_low = lo52 > 0 and price <= lo52 * 1.05
                if sma200 and price < sma200:
                    # Allow potential oversold reversals through
                    if not (rsi is not None and rsi < 30 and near_52w_low):
                        diagnostics["sma200_filtered"] += 1
                        analysis_results[sym] = {
                            "symbol": sym, "sector": sector, "price": price,
                            "sma50": sma50, "sma200": sma200,
                        }
                        continue

                # ATR % filter
                if atr and price > 0 and (atr / price * 100) > MAX_ATR_PCT:
                    diagnostics["atr_filtered"] += 1
                    analysis_results[sym] = {
                        "symbol": sym, "sector": sector, "price": price,
                        "sma50": sma50, "sma200": sma200,
                    }
                    continue

                # Weekly uptrend check (computed once, passed to both detector & scorer)
                w_closes = [float(w["close_price"]) for w in weekly] if weekly else []
                w_sma10 = calc_sma(w_closes, 10) if len(w_closes) >= 10 else None
                weekly_uptrend = w_sma10 is not None and price > w_sma10
                w_rsi = calc_rsi(w_closes) if len(w_closes) >= 15 else None

                # ── Detect swing setups ──
                setups = _detect_swing_setups(
                    price=price, candles=candles,
                    weekly_uptrend=weekly_uptrend, w_rsi=w_rsi,
                    sma20=sma20, sma50=sma50,
                    rsi=rsi, macd_hist=macd_hist, macd_just_bullish=macd_just_bullish,
                    adx=adx, bb_squeeze=bb_squeeze,
                    stoch_k=stoch_k, stoch_d=stoch_d,
                    obv_trend=obv_trend, vol_ratio=vol_ratio,
                    lo52=lo52,
                    patterns=patterns, broker_asym=broker_asym, cross=cross,
                )

                if not setups:
                    diagnostics["no_setup"] += 1
                    analysis_results[sym] = {
                        "symbol": sym, "sector": sector, "price": price,
                        "sma50": sma50, "sma200": sma200,
                    }
                    continue

                # Pick best setup
                best_setup = max(setups, key=lambda s: s["confidence"])
                confluence_bonus = min(10, max(0, len(setups) - 1) * 4)
                setup_conf = min(100, best_setup["confidence"] + confluence_bonus)
                fund_data = all_fund.get(sym, {})
                fundamental_stale = _is_fundamental_stale(fund_data)

                # Composite scoring
                high_prox = round((hi52 - price) / hi52 * 100, 1) if hi52 > 0 else 100
                scores = _calc_swing_composite(
                    price=price, sma20=sma20, sma50=sma50, sma200=sma200,
                    rsi=rsi, macd_hist=macd_hist, macd_just_bullish=macd_just_bullish,
                    vol_ratio=vol_ratio, obv_trend=obv_trend, adx=adx,
                    cross=cross, bb_pct=bb_pct,
                    setup_conf=setup_conf,
                    atr=atr, hi52=hi52, lo52=lo52,
                    broker_asym=broker_asym,
                    fund=fund_data,
                    weekly_uptrend=weekly_uptrend,
                    roc_20=roc_20, roc_60=roc_60, high_prox=high_prox,
                )

                # Apply market regime & seasonality
                composite = scores["composite"] * regime.get("factor", 1.0) + seasonality_adj()
                if fundamental_stale:
                    composite -= 3
                composite = max(0, min(100, composite))
                scores["composite"] = round(composite, 2)

                signal = _classify_signal(composite, setup_conf)

                # Risk management
                stop_distance = max((ATR_SL_MULT * atr) if atr else 0.0, price * 0.03)
                stop_loss = round(price - stop_distance, 2) if stop_distance > 0 else round(price * 0.92, 2)
                stop_loss = max(0.01, stop_loss)
                target_1 = round(price + ATR_T1_MULT * atr, 2) if atr else round(price * 1.08, 2)
                target_2 = round(price + ATR_T2_MULT * atr, 2) if atr else round(price * 1.15, 2)
                risk_per_share = abs(price - stop_loss)
                rr_ratio = round((target_1 - price) / risk_per_share, 1) if risk_per_share > 0 else 0
                pos_size = 0
                if risk_per_share > 0 and price > 0:
                    raw_size = max(1, int(equity * RISK_PCT / risk_per_share))
                    max_by_capital = max(1, int(equity / price))
                    max_by_liquidity = max(1, int(vol_avg * MAX_POSITION_SHARE_OF_AVG_VOL)) if vol_avg > 0 else raw_size
                    max_by_allocation = max(1, int((equity * MAX_CAPITAL_ALLOCATION_PCT) / price))
                    pos_size = max(1, min(raw_size, max_by_capital, max_by_liquidity, max_by_allocation))
                # high_prox already computed above for composite scoring
                entry_zone = _calc_entry_zone(price, atr, best_setup["setup_type"])
                data_confidence = _compute_data_confidence(
                    bars=len(candles),
                    avg_volume=vol_avg,
                    circuit_volatile=False,
                    fundamental_stale=fundamental_stale,
                    has_live_price=bool(live_row and float(live_row.get("last_traded_price") or 0) > 0),
                    excessive_forward_fill=max_fill_streak > MAX_FORWARD_FILL_STREAK,
                )

                result = {
                    "symbol": sym, "sector": sector, "price": price,
                    "setup_type": best_setup["setup_type"],
                    "setup_reasoning": best_setup["reasoning"],
                    "all_setups": setups,
                    "confidence": setup_conf,
                    "signal": signal,
                    "entry_zone": entry_zone,
                    "stop_loss": stop_loss,
                    "target_1": target_1,
                    "target_2": target_2,
                    "rr_ratio": rr_ratio,
                    "position_size": pos_size,
                    "hold_period": _est_hold_period(best_setup["setup_type"]),
                    # Indicators
                    "sma20": sma20, "sma50": sma50, "sma200": sma200,
                    "rsi": rsi, "macd_hist": macd_hist,
                    "macd_just_bullish": macd_just_bullish,
                    "atr": atr, "adx": adx,
                    "stoch_k": stoch_k, "stoch_d": stoch_d,
                    "obv_trend": obv_trend, "vol_ratio": vol_ratio,
                    "bb_upper": bb_upper, "bb_lower": bb_lower,
                    "bb_pct": bb_pct, "bb_squeeze": bb_squeeze,
                    "cross": cross, "patterns": patterns,
                    "roc_20": roc_20, "roc_60": roc_60,
                    "hi52": hi52, "lo52": lo52, "high_prox": high_prox,
                    "weekly_uptrend": weekly_uptrend,
                    "broker_asym": broker_asym,
                    "data_confidence": data_confidence,
                    "max_forward_fill_streak": max_fill_streak,
                    "fundamental_stale": fundamental_stale,
                    # Fundamentals
                    "eps": float(fund_data.get("eps") or 0),
                    "pe": float(fund_data.get("pe_ratio") or 0),
                    "book_value": float(fund_data.get("book_value") or 0),
                    # Scores
                    **scores,
                }

                analysis_results[sym] = result

                if signal in ("BUY", "STRONG BUY") and rr_ratio >= MIN_RR_RATIO:
                    swing_candidates.append(result)

            except Exception as e:
                errors[sym] = str(e)
                continue

        # ── Rank & filter ──
        swing_candidates.sort(key=lambda x: x["composite"], reverse=True)
        watchlist = swing_candidates[:top_n]

        # Sector breadth
        sector_breadth = _calc_sector_breadth(analysis_results, all_details, all_securities)

        # Setup distribution
        setup_dist = defaultdict(int)
        for c in swing_candidates:
            setup_dist[c["setup_type"]] += 1

        # Near-misses (rejected but close) — set-based O(1) lookup
        all_with_setups = [v for v in analysis_results.values() if "setup_type" in v]
        wl_syms = {c["symbol"] for c in swing_candidates}
        rejected = [r for r in all_with_setups if r["symbol"] not in wl_syms]
        rejected.sort(key=lambda x: x.get("composite", 0), reverse=True)

        print(f"  ✅ Analysis complete: {processed_symbols}/{total_universe} symbols looped")
        print(f"     Reporting context rows: {len(analysis_results)}")
        print(f"     Swing setups found: {len(all_with_setups)}")
        print(f"     Passed all filters: {len(swing_candidates)}")
        print("     Drops: "
            f"bars={diagnostics['insufficient_bars']}, "
            f"liquidity={diagnostics['liquidity_filtered']}, "
            f"circuit={diagnostics['circuit_filtered']}, "
            f"stale_fill={diagnostics['stale_forward_fill']}, "
            f"sma200={diagnostics['sma200_filtered']}, "
            f"atr={diagnostics['atr_filtered']}, "
            f"no_setup={diagnostics['no_setup']}")
        if errors:
            print(f"  ⚠ {len(errors)} symbols had errors: {', '.join(list(errors.keys())[:5])}{'...' if len(errors) > 5 else ''}")

        return {
            "watchlist": watchlist,
            "rejected": rejected[:10],
            "setup_distribution": dict(setup_dist),
            "sector_breadth": sector_breadth,
            "regime": regime,
            "total_universe": total_universe,
            "total_processed": processed_symbols,
            "total_analyzed": len(analysis_results),
            "total_candidates": len(swing_candidates),
            "diagnostics": diagnostics,
            "errors": errors,
            "account_equity": equity,
            "generation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    finally:
        conn.close()
        print("  🔌 Database connection closed.")
