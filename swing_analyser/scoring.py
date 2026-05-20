"""
NEPSE Swing Trading Analyser — Universal Scoring Engine (v1.0)

Penalty-based scoring system that ranks EVERY equity on a 0–100
Swing Tradability Scale.  Hard filters become scoring penalties,
not gates — so every stock gets a score regardless of market conditions.

Imports all fetch / indicator functions from logic.py — zero duplication.

Tier 1 Enhancements: Broker validation + Fundamental deep scoring
- Integrates broker_tracker signal validation for institutional alignment
- Enhances fundamentals using single_analyser deep scoring
"""

from collections import defaultdict
from datetime import datetime

from swing_analyser.logic import (
    # Database
    get_conn, q, qone,
    # Batch fetchers (reuse, don't duplicate)
    fetch_all_ohlcv, fetch_all_corp_actions, fetch_all_dividends,
    fetch_all_company_details, fetch_all_securities, fetch_52w_from_snapshots,
    fetch_all_live_ltp, fetch_all_fundamentals, fetch_broker_scores,
    fetch_market_regime,
    # Data pipeline
    bridge_live_candle, get_adjusted_series, forward_fill_zero_volume_days,
    resample_to_weekly,
    # Indicators
    calc_sma, calc_ema, calc_rsi, calc_macd, calc_atr, calc_stochastic,
    calc_obv_trend, calc_roc, calc_bollinger_bands, calc_adx,
    detect_candlestick_patterns, is_bollinger_squeeze,
    is_circuit_volatile, seasonality_adj,
    check_macd_bullish_crossover, check_ma_crossover,
    # Setup detection (reuse the exact same function)
    _detect_swing_setups,
    # Risk management helpers
    _calc_entry_zone, _est_hold_period,
    # Constants
    ACCOUNT_EQUITY, RISK_PCT, ATR_SL_MULT, ATR_T1_MULT, ATR_T2_MULT,
    RSI_OVERBOUGHT, RSI_OVERSOLD, MIN_RR_RATIO,
    MIN_BROKER_LIQ_VOLUME, MAX_POSITION_SHARE_OF_AVG_VOL,
    MAX_CAPITAL_ALLOCATION_PCT, _is_fundamental_stale,
    _compute_data_confidence,
)

# ──────────────────────────────────────────────────────────────────────
#  TIER 1 ENHANCEMENTS: Broker tracker & single analyser integration
# ──────────────────────────────────────────────────────────────────────
try:
    from single_analyser.logic import calc_fundamental_score as single_calc_fund_score
except ImportError:
    # Fallback if single_analyser not available
    def single_calc_fund_score(fund):
        """Fallback fundamental scorer."""
        if not fund:
            return 50
        score = 0
        eps = float(fund.get("eps") or 0)
        pe = float(fund.get("pe_ratio") or 0)
        
        if 0 < pe <= 15: score += 25
        elif 15 < pe <= 25: score += 18
        elif 25 < pe <= 40: score += 10
        
        if eps > 30: score += 20
        elif eps > 15: score += 16
        elif eps > 5: score += 12
        elif eps > 0: score += 8
        
        div_yield = float(fund.get("div_yield") or 0)
        if div_yield > 5: score += 10
        elif div_yield > 2: score += 5
        
        roe = float(fund.get("roe") or 0)
        if roe > 20: score += 10
        elif roe > 10: score += 5
        
        return min(100, max(0, round(score)))

BROKER_TRACKER_AVAILABLE = False  # Disabled for now to avoid hang issues

# ═══════════════════════════════════════════════════════════════════════
#  UNIVERSAL SCORING CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

RANK_MIN_BARS   = 60    # Relaxed from 100 → 60 for ranking
RANK_MIN_VOL    = 1000  # Relaxed from 5000 → 1000 for ranking
HOTLIST_MIN_SCORE = 65  # Must score ≥ 65 AND have a setup


# ═══════════════════════════════════════════════════════════════════════
#  TIER CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

def classify_tier(score):
    """Classify a 0–100 score into a named tier."""
    if score >= 80:
        return ("PRIME", "🔥", "#ff6e40")
    if score >= 65:
        return ("STRONG", "✅", "#00e676")
    if score >= 50:
        return ("WATCH", "👀", "#ffd740")
    if score >= 35:
        return ("WEAK", "⚠️", "#ff9800")
    return ("AVOID", "❌", "#ff5252")


# ═══════════════════════════════════════════════════════════════════════
#  UNIVERSAL SCORE CALCULATOR
# ═══════════════════════════════════════════════════════════════════════

def calc_universal_score(*, price, sma20, sma50, sma200,
                         rsi, macd_hist, macd_just_bullish,
                         vol_ratio, obv_trend, adx, cross,
                         bb_pct, atr, hi52, lo52, high_prox,
                         broker_asym, fund,
                         fundamental_stale,
                         weekly_uptrend, w_rsi,
                         roc_20, roc_60,
                         setup_conf, has_setup,
                         avg_volume, circuit_volatile,
                         fundamental_score=None):
    """
    Penalty-based 0–100 universal swing tradability score.

    Unlike _calc_swing_composite which is only called for stocks that
    survive all hard filters, this scores EVERY stock with soft penalties.
    
    Args:
        fundamental_score: Pre-calculated fundamental score (0-100).
                          If None, will be computed from fund dict.
    """

    # ── 1. TREND ALIGNMENT (25%) ──
    trend = 50
    if sma20 and sma50 and sma200:
        if price > sma20 > sma50 > sma200:
            trend = 100
        elif price > sma20 and price > sma50:
            trend = 80
        elif price > sma50:
            trend = 60
        elif price < sma50 and price < sma200:
            trend = 10
        else:
            trend = 30
    elif sma20 and sma50:
        if price > sma20 > sma50:
            trend = 80
        elif price > sma50:
            trend = 60
        else:
            trend = 30

    if weekly_uptrend:
        trend = min(100, trend + 10)
    if cross == "GOLDEN":
        trend = min(100, trend + 15)
    elif cross == "DEATH":
        trend = max(0, trend - 15)

    # PENALTY: below SMA200 → cap trend score
    if sma200 and price < sma200:
        trend = min(trend, 30)

    trend = max(0, min(100, trend))

    # ── 2. MOMENTUM TIMING (20%) ──
    mom = 50
    if rsi is not None:
        if 40 <= rsi <= 60:
            mom += 10
        elif rsi < RSI_OVERSOLD:
            mom += 15       # Potential reversal
        elif rsi > RSI_OVERBOUGHT:
            mom -= 15
    if macd_hist is not None:
        mom += 15 if macd_hist > 0 else -10
    if macd_just_bullish:
        mom += 10
    if roc_20 is not None:
        if roc_20 > 10:
            mom += 10
        elif roc_20 > 3:
            mom += 5
        elif roc_20 < -10:
            mom -= 10
    if roc_60 is not None:
        if roc_60 > 15:
            mom += 5
        elif roc_60 < -15:
            mom -= 5
    mom = max(0, min(100, mom))

    # ── 3. VOLUME CONVICTION (20%) ──
    vol = 50
    vr = min(vol_ratio, 5)
    vol += (vr - 1) * 8
    if obv_trend == "RISING":
        vol += 15
    elif obv_trend == "FALLING":
        vol -= 15
    if broker_asym > 65:
        vol += 12
    elif broker_asym > 55:
        vol += 5
    elif broker_asym < 40:
        vol -= 10

    # PENALTY: low liquidity → soft deduction, not exclusion
    if avg_volume < 1000:
        vol -= 25
    elif avg_volume < 2000:
        vol -= 15
    elif avg_volume < 5000:
        vol -= 8

    vol = max(0, min(100, vol))

    # ── 4. VOLATILITY SUITABILITY (10%) ──
    volatility = 60   # Neutral-positive default
    if atr and price > 0:
        atr_pct = atr / price * 100
        # Sweet spot: 1.5–5%
        if 1.5 <= atr_pct <= 5.0:
            volatility = 80
        elif atr_pct < 1.0:
            volatility = 25    # Dead stock
        elif atr_pct < 1.5:
            volatility = 50    # Sluggish
        elif atr_pct <= 8.0:
            volatility = 55    # Acceptable
        elif atr_pct <= 12.0:
            volatility = 30    # Risky swing
        else:
            volatility = 10    # Untradeable
    if adx is not None:
        if adx < 10:
            volatility -= 10   # No trend at all
        elif adx > 25:
            volatility += 10   # Strong trend

    # PENALTY: circuit-volatile history
    if circuit_volatile:
        volatility -= 15

    volatility = max(0, min(100, volatility))

    # ── 5. SETUP BONUS (15%) ──
    if has_setup and setup_conf > 0:
        setup = max(0, min(100, setup_conf))
    else:
        setup = 25   # Neutral default — no setup ≠ zero score

    # ── 6. RISK HEADROOM (5%) ──
    risk = 60
    if bb_pct is not None:
        if bb_pct > 90:
            risk -= 15
        elif bb_pct < 20:
            risk += 10
    if high_prox is not None:
        if high_prox < 3:
            risk -= 15    # Near 52W high
        elif high_prox > 30:
            risk += 10    # Plenty of headroom
    risk = max(0, min(100, risk))

    # ── 7. FUNDAMENTAL FLOOR (5%) ──
    if fundamental_score is not None:
        # Use provided deep fundamental score
        funda = fundamental_score
    else:
        # Fallback: compute from fund dict
        funda = 50
        if fund:
            pe = float(fund.get("pe_ratio") or 0)
            eps = float(fund.get("eps") or 0)
            if 0 < pe <= 15:
                funda += 20
            elif 15 < pe <= 25:
                funda += 10
            elif pe > 40:
                funda -= 15
            if eps > 20:
                funda += 15
            elif eps > 5:
                funda += 8
            elif eps <= 0:
                funda -= 15
    
    if fundamental_stale:
        funda -= 10
    funda = max(0, min(100, funda))

    # ── WEIGHTED COMPOSITE ──
    score = (
        trend      * 0.25 +
        mom        * 0.20 +
        vol        * 0.20 +
        volatility * 0.10 +
        setup      * 0.15 +
        risk       * 0.05 +
        funda      * 0.05
    )

    # Apply seasonality
    score += seasonality_adj()
    score = max(0, min(100, score))

    return {
        "universal_score": round(score, 2),
        "trend_score": round(trend, 1),
        "momentum_score": round(mom, 1),
        "volume_score": round(vol, 1),
        "volatility_score": round(volatility, 1),
        "setup_score": round(setup, 1),
        "risk_score": round(risk, 1),
        "fundamental_score": round(funda, 1),
    }


# ═══════════════════════════════════════════════════════════════════════
#  HOTLIST BUILDER
# ═══════════════════════════════════════════════════════════════════════

def _generate_hotlist_reason(stock):
    """Auto-generate a one-liner explaining why this stock is on the hotlist."""
    parts = []
    setup = stock.get("setup_type", "")
    setup_label = setup.replace("_", " ").title()

    if stock.get("weekly_uptrend"):
        parts.append("weekly uptrend intact")
    if stock.get("cross") == "GOLDEN":
        parts.append("fresh golden cross")
    elif stock.get("cross") == "BULLISH":
        parts.append("bullish MA alignment")
    if stock.get("macd_just_bullish"):
        parts.append("MACD just turned bullish")
    if stock.get("obv_trend") == "RISING":
        parts.append("rising OBV")
    if stock.get("broker_asym", 50) > 60:
        parts.append(f"broker accumulation ({stock['broker_asym']:.0f})")
    if stock.get("bb_squeeze"):
        parts.append("Bollinger squeeze")

    if not parts:
        parts.append("strong multi-factor alignment")

    reason = f"{setup_label} setup with {', '.join(parts[:3])}"
    return reason[0].upper() + reason[1:]


def build_hotlist(ranked_stocks, account_equity=100_000, broker_signals=None):
    """
    Filter ranked stocks to must-not-miss hotlist:
    score ≥ 65 AND at least one swing setup detected AND R:R ≥ 2.0 AND confidence ≥ 60.
    
    **Tier 1 Enhancement**: Add broker signal validation
    - Prefer stocks with broker accumulation signals (BUY/STRONG/MODERATE)
    - Allow high-confidence setups without broker signal (score ≥ 75)
    
    Args:
        broker_signals: dict[symbol] -> signal info {signal: str, strength: str, ...}
    """
    hotlist = []
    broker_signals = broker_signals or {}
    
    for s in ranked_stocks:
        # Base hotlist criteria
        if not (
            s["universal_score"] >= HOTLIST_MIN_SCORE
            and s.get("setup_type")
            and float(s.get("rr_ratio") or 0) >= MIN_RR_RATIO
            and int(s.get("data_confidence") or 0) >= 60
        ):
            continue
        
        # Tier 1: Broker signal validation
        symbol = s.get("symbol")
        broker_info = broker_signals.get(symbol, {})
        broker_signal = broker_info.get("signal", "UNKNOWN")
        broker_strength = broker_info.get("strength", "WEAK")
        
        # Allow if:
        # 1) Broker signal is positive (accumulating), OR
        # 2) Score is very high (≥75) and has strong setup (≥70 confidence)
        broker_aligned = broker_signal in ("BUY", "STRONG", "HOLD") or broker_strength in ("STRONG", "MODERATE")
        high_conviction = s["universal_score"] >= 75 and s.get("confidence", 0) >= 70
        
        if not (broker_aligned or high_conviction):
            # Skip if no broker support and not high-conviction
            continue
        
        entry = dict(s)
        entry["hotlist_reason"] = _generate_hotlist_reason(s)
        entry["broker_signal"] = broker_signal
        entry["broker_strength"] = broker_strength
        entry["broker_aligned"] = broker_aligned
        hotlist.append(entry)

    hotlist.sort(key=lambda x: x["universal_score"], reverse=True)
    return hotlist


# ═══════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════

def run_ranking_analysis(account_equity=None):
    """
    Score EVERY equity stock on the 0–100 Universal Swing Scale.
    Reuses all fetch/indicator functions from logic.py.
    
    **Tier 1 Enhancement**: Integrates broker signals and deep fundamental scoring.
    """
    equity = account_equity or ACCOUNT_EQUITY
    print(f"\n  📊 Starting universal ranking pipeline (equity: Rs {equity:,.0f})...\n")

    conn = get_conn()
    try:
        broker_tracker_enabled = BROKER_TRACKER_AVAILABLE
        # ── Batch fetch (reuse from logic.py) ──
        all_ohlcv = fetch_all_ohlcv(conn)
        all_corps = fetch_all_corp_actions(conn)
        all_divs = fetch_all_dividends(conn)
        all_details = fetch_all_company_details(conn)
        all_securities = fetch_all_securities(conn)
        all_52w = fetch_52w_from_snapshots(conn)
        all_live = fetch_all_live_ltp(conn)
        all_fund = fetch_all_fundamentals(conn)
        broker_scores = fetch_broker_scores(conn)
        regime = fetch_market_regime(conn)

        # ──────────────────────────────────────────────────────────────────
        #  TIER 1: Broker signal computation (optional)
        # ──────────────────────────────────────────────────────────────────
        broker_signals_by_symbol = {}
        if broker_tracker_enabled:
            try:
                print("  [tier1] Computing broker signals...")
                # Simplified: Use existing broker_scores as proxy for signals
                # (Full broker position analysis deferred to avoid timeout)
                for symbol, score in broker_scores.items():
                    asymmetry = score  # broker_asym is 0-100
                    # Classify signal based on asymmetry
                    if asymmetry > 65:
                        signal = "BUY"
                        strength = "STRONG"
                    elif asymmetry > 55:
                        signal = "HOLD"
                        strength = "MODERATE"
                    else:
                        signal = "UNKNOWN"
                        strength = "WEAK"
                    
                    broker_signals_by_symbol[symbol] = {
                        "signal": signal,
                        "strength": strength,
                        "asymmetry": asymmetry,
                    }
                print(f"     ✓ Broker signals computed for {len(broker_signals_by_symbol)} symbols")
            except Exception as e:
                print(f"  ⚠️  Broker signal computation failed: {e}")
                broker_tracker_enabled = False
        
        # ──────────────────────────────────────────────────────────────────
        #  Pre-compute fundamental scores using single_analyser
        # ──────────────────────────────────────────────────────────────────
        print("  [tier1] Computing deep fundamental scores...")
        fundamental_scores_by_symbol = {}
        for sym, fund_data in all_fund.items():
            fundamental_scores_by_symbol[sym] = single_calc_fund_score(fund_data)

        print(f"  Market regime: {regime['regime']} (NEPSE {regime['chg']:+.2f}%)")
        print(f"  [engine] Ranking {len(all_ohlcv)} symbols...")

        ranked = []
        errors = {}
        skipped_data = 0

        for sym, raw_candles in all_ohlcv.items():
            try:
                # ── Data pipeline (same as swing) ──
                live_row = all_live.get(sym)
                bridged = bridge_live_candle(raw_candles, live_row)
                candles = get_adjusted_series(
                    bridged, all_corps.get(sym, []), all_divs.get(sym, [])
                )
                candles = forward_fill_zero_volume_days(candles)
                excessive_forward_fill = any(
                    int(c.get("forward_fill_limit_exceeded") or 0) for c in candles
                )

                if len(candles) < RANK_MIN_BARS:
                    skipped_data += 1
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

                # Avg volume (20-bar)
                vol_window = volumes[-20:]
                avg_volume = sum(vol_window) / len(vol_window) if vol_window else 0

                if avg_volume < RANK_MIN_VOL:
                    skipped_data += 1
                    continue

                # ── Weekly resample ──
                weekly = resample_to_weekly(candles)

                # ── Daily indicators (reuse all from logic.py) ──
                sma20 = calc_sma(closes, 20)
                sma50 = calc_sma(closes, 50)
                sma200 = calc_sma(closes, 200)
                rsi = calc_rsi(closes)
                macd_val, sig_val, macd_hist, macd_line = calc_macd(closes)
                atr = calc_atr(candles)
                stoch_k, stoch_d = calc_stochastic(candles)
                obv_trend = calc_obv_trend(closes, volumes)
                bb_upper, bb_middle, bb_lower = calc_bollinger_bands(closes)
                bb_squeeze = is_bollinger_squeeze(bb_upper, bb_middle, bb_lower)
                adx = calc_adx(candles)
                roc_20 = calc_roc(closes, 20)
                roc_60 = calc_roc(closes, 60) if len(closes) > 61 else None
                patterns = detect_candlestick_patterns(candles)
                circuit_vol = is_circuit_volatile(candles)

                vol_avg20 = sum(volumes[-20:]) / min(len(volumes[-20:]), 20) if volumes else 0
                vol_ratio = round(volumes[-1] / vol_avg20, 2) if vol_avg20 > 0 else 0

                bb_pct = None
                if bb_upper and bb_lower and bb_upper != bb_lower:
                    bb_pct = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1)

                # MACD crossover
                macd_just_bullish = check_macd_bullish_crossover(macd_line)

                # MA crossover
                cross = check_ma_crossover(closes, sma20, sma50)

                # 52W data (fixed precedence)
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

                high_prox = round((hi52 - price) / hi52 * 100, 1) if hi52 > 0 else 100

                sector = (det.get("sector_name")
                          or all_securities.get(sym, {}).get("sector_name") or "")
                broker_asym = broker_scores.get(sym, 50)
                if avg_volume < MIN_BROKER_LIQ_VOLUME:
                    broker_asym = 50

                # ── Weekly uptrend ──
                w_closes = [float(w["close_price"]) for w in weekly] if weekly else []
                w_sma10 = calc_sma(w_closes, 10) if len(w_closes) >= 10 else None
                weekly_uptrend = w_sma10 is not None and price > w_sma10
                w_rsi = calc_rsi(w_closes) if len(w_closes) >= 15 else None

                # ── Try swing setup detection ──
                near_52w_low = lo52 > 0 and price <= lo52 * 1.05
                try:
                    setups = _detect_swing_setups(
                        price=price, candles=candles,
                        weekly_uptrend=weekly_uptrend, w_rsi=w_rsi,
                        sma20=sma20, sma50=sma50,
                        rsi=rsi, macd_hist=macd_hist,
                        macd_just_bullish=macd_just_bullish,
                        adx=adx, bb_squeeze=bb_squeeze,
                        stoch_k=stoch_k, stoch_d=stoch_d,
                        obv_trend=obv_trend, vol_ratio=vol_ratio,
                        lo52=lo52,
                        patterns=patterns, broker_asym=broker_asym, cross=cross,
                    )
                except Exception:
                    setups = []

                best_setup = max(setups, key=lambda s: s["confidence"]) if setups else None
                confluence_bonus = min(10, max(0, len(setups) - 1) * 4)
                setup_conf = min(100, (best_setup["confidence"] if best_setup else 0) + confluence_bonus)
                has_setup = bool(setups)
                fund_data = all_fund.get(sym, {})
                fundamental_stale = _is_fundamental_stale(fund_data)
                
                # ── TIER 1: Get pre-computed fundamental score ──
                fund_score = fundamental_scores_by_symbol.get(sym, 50)

                # ── Universal score ──
                scores = calc_universal_score(
                    price=price, sma20=sma20, sma50=sma50, sma200=sma200,
                    rsi=rsi, macd_hist=macd_hist,
                    macd_just_bullish=macd_just_bullish,
                    vol_ratio=vol_ratio, obv_trend=obv_trend, adx=adx,
                    cross=cross, bb_pct=bb_pct, atr=atr,
                    hi52=hi52, lo52=lo52, high_prox=high_prox,
                    broker_asym=broker_asym, fund=fund_data,
                    fundamental_stale=fundamental_stale,
                    weekly_uptrend=weekly_uptrend, w_rsi=w_rsi,
                    roc_20=roc_20, roc_60=roc_60,
                    setup_conf=setup_conf, has_setup=has_setup,
                    avg_volume=avg_volume, circuit_volatile=circuit_vol,
                    fundamental_score=fund_score,  # TIER 1: Deep fundamental score
                )

                tier_name, tier_icon, tier_color = classify_tier(scores["universal_score"])

                # ── Risk management (for hotlist candidates) ──
                stop_distance = max((ATR_SL_MULT * atr) if atr else 0.0, price * 0.03)
                stop_loss = round(price - stop_distance, 2) if stop_distance > 0 else round(price * 0.92, 2)
                target_1 = round(price + ATR_T1_MULT * atr, 2) if atr else round(price * 1.08, 2)
                target_2 = round(price + ATR_T2_MULT * atr, 2) if atr else round(price * 1.15, 2)
                risk_per_share = abs(price - stop_loss)
                rr_ratio = round((target_1 - price) / risk_per_share, 1) if risk_per_share > 0 else 0
                if risk_per_share > 0 and price > 0:
                    raw_size = max(1, int((equity * RISK_PCT) / risk_per_share))
                    max_by_capital = max(1, int(equity / price))
                    max_by_liquidity = max(1, int(avg_volume * MAX_POSITION_SHARE_OF_AVG_VOL)) if avg_volume > 0 else raw_size
                    max_by_allocation = max(1, int((equity * MAX_CAPITAL_ALLOCATION_PCT) / price))
                    pos_size = max(1, min(raw_size, max_by_capital, max_by_liquidity, max_by_allocation))
                else:
                    pos_size = 0
                entry_zone = _calc_entry_zone(
                    price, atr, best_setup["setup_type"] if best_setup else "TREND_CONTINUATION"
                )
                data_confidence = _compute_data_confidence(
                    bars=len(candles),
                    avg_volume=avg_volume,
                    circuit_volatile=circuit_vol,
                    fundamental_stale=fundamental_stale,
                    has_live_price=bool(live_row and float(live_row.get("last_traded_price") or 0) > 0),
                    excessive_forward_fill=excessive_forward_fill,
                )

                result = {
                    "symbol": sym,
                    "sector": sector,
                    "price": price,
                    "avg_volume": round(avg_volume),
                    # Setup info
                    "setup_type": best_setup["setup_type"] if best_setup else None,
                    "setup_reasoning": best_setup["reasoning"] if best_setup else [],
                    "all_setups": setups,
                    "confidence": setup_conf,
                    "has_setup": has_setup,
                    # Trade levels
                    "entry_zone": entry_zone,
                    "stop_loss": stop_loss,
                    "target_1": target_1,
                    "target_2": target_2,
                    "rr_ratio": rr_ratio,
                    "position_size": pos_size,
                    "hold_period": _est_hold_period(
                        best_setup["setup_type"] if best_setup else "TREND_CONTINUATION"
                    ),
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
                    "circuit_volatile": circuit_vol,
                    "data_confidence": data_confidence,
                    "fundamental_stale": fundamental_stale,
                    # Fundamentals
                    "eps": float(fund_data.get("eps") or 0),
                    "pe": float(fund_data.get("pe_ratio") or 0),
                    "book_value": float(fund_data.get("book_value") or 0),
                    # TIER 1: Deep fundamentals & broker signals
                    "fundamental_score_deep": fund_score,
                    "broker_signal": broker_signals_by_symbol.get(sym, {}).get("signal", "UNKNOWN"),
                    "broker_strength": broker_signals_by_symbol.get(sym, {}).get("strength", "WEAK"),
                    # Tier
                    "tier_name": tier_name,
                    "tier_icon": tier_icon,
                    "tier_color": tier_color,
                    # Scores
                    **scores,
                }

                ranked.append(result)

            except Exception as e:
                errors[sym] = str(e)
                continue

        # ── Sort by universal score ──
        ranked.sort(key=lambda x: x["universal_score"], reverse=True)

        # ── Tier distribution ──
        tiers = {"PRIME": 0, "STRONG": 0, "WATCH": 0, "WEAK": 0, "AVOID": 0}
        for r in ranked:
            tiers[r["tier_name"]] += 1

        # ── Sector breadth ──
        sector_stocks = defaultdict(list)
        for r in ranked:
            sec = r.get("sector") or "Other"
            sector_stocks[sec].append(r)
        sector_breadth = {}
        for sector, stocks in sector_stocks.items():
            above = sum(1 for s in stocks if s.get("sma50") and s["price"] > s["sma50"])
            total = len(stocks)
            sector_breadth[sector] = {
                "total": total, "above_sma50": above,
                "pct": round(above / total * 100, 1) if total > 0 else 0,
            }

        # ── Build hotlist ──
        hotlist = build_hotlist(ranked, equity, broker_signals=broker_signals_by_symbol)

        print(f"  ✅ Ranking complete: {len(ranked)} stocks scored")
        print(f"     🔥 PRIME: {tiers['PRIME']} | ✅ STRONG: {tiers['STRONG']} "
              f"| 👀 WATCH: {tiers['WATCH']} | ⚠️ WEAK: {tiers['WEAK']} "
              f"| ❌ AVOID: {tiers['AVOID']}")
        print(f"     🎯 Hotlist: {len(hotlist)} must-not-miss stocks (broker-aligned or high-conviction)")
        if broker_tracker_enabled:
            print(f"     📊 [Tier 1] Broker signals computed | Deep fundamental scoring enabled")
        if skipped_data:
            print(f"     ⏭️ Skipped: {skipped_data} (insufficient data/volume)")
        if errors:
            print(f"     ⚠ {len(errors)} errors: "
                  f"{', '.join(list(errors.keys())[:5])}"
                  f"{'...' if len(errors) > 5 else ''}")

        return {
            "ranked": ranked,
            "hotlist": hotlist,
            "tiers": tiers,
            "sector_breadth": sector_breadth,
            "regime": regime,
            "total_ranked": len(ranked),
            "total_skipped": skipped_data,
            "errors": errors,
            "account_equity": equity,
            "generation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    finally:
        conn.close()
        print("  🔌 Database connection closed.")
