import concurrent.futures
import multiprocessing

_worker_state = {}

def _init_worker(corps, divs, details, securities, snapshots, broker_scores, sell_dist, regime, live_ltp):
    global _worker_state
    _worker_state['corps'] = corps
    _worker_state['divs'] = divs
    _worker_state['details'] = details
    _worker_state['securities'] = securities
    _worker_state['snapshots'] = snapshots
    _worker_state['broker_scores'] = broker_scores
    _worker_state['sell_dist'] = sell_dist
    _worker_state['regime'] = regime
    _worker_state['live_ltp'] = live_ltp

def _process_single_symbol(sym, raw_candles):
    global _worker_state
    all_corps = _worker_state.get('corps', {})
    all_divs = _worker_state.get('divs', {})
    all_details = _worker_state.get('details', {})
    all_securities = _worker_state.get('securities', {})
    all_52w_snapshots = _worker_state.get('snapshots', {})
    broker_scores = _worker_state.get('broker_scores', {})
    sell_distribution = _worker_state.get('sell_dist', {})
    market_regime = _worker_state.get('regime', {})
    all_live_ltp = _worker_state.get('live_ltp', {})

    skip_stats = {
        "short_history": 0,
        "bad_price": 0,
        "stale_forward_fill": 0,
    }

    try:
        live_row = all_live_ltp.get(sym)
        bridged_candles = bridge_live_candle(raw_candles, live_row)
        candles = get_adjusted_series(
            bridged_candles, all_corps.get(sym, []), all_divs.get(sym, []))
        candles = forward_fill_zero_volume_days(candles)
        max_fill_streak = _max_forward_fill_streak(candles)

        if len(candles) < 20:
            skip_stats["short_history"] += 1
            return None, skip_stats
        if max_fill_streak > MAX_FORWARD_FILL_STREAK:
            skip_stats["stale_forward_fill"] += 1
            return None, skip_stats

        closes  = [float(c["close_price"]) for c in candles]
        volumes = [int(c.get("volume") or 0) for c in candles]

        if live_row and float(live_row.get("last_traded_price") or 0) > 0:
            price = float(live_row["last_traded_price"])
        else:
            price = closes[-1]

        if price <= 0:
            skip_stats["bad_price"] += 1
            return None, skip_stats

        circuit_flag = is_circuit_volatile(candles)
        liquidity_flag = is_low_liquidity(candles)
        sma5   = calc_sma(closes, 5)
        sma10  = calc_sma(closes, 10)
        sma20  = calc_sma(closes, 20)
        sma50  = calc_sma(closes, 50)
        sma200 = calc_sma(closes, 200)
        rsi = calc_rsi(closes) if len(candles) >= MIN_BARS_RSI else None

        macd_val, sig_val, macd_hist, macd_line = (None, None, None, [])
        if len(candles) >= MIN_BARS_MACD:
            macd_val, sig_val, macd_hist, macd_line = calc_macd(closes)

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

        atr = calc_circuit_adjusted_atr(candles) if len(candles) >= MIN_BARS_ATR else None
        if atr is None and len(candles) >= MIN_BARS_ATR:
            atr = calc_atr(candles)

        stoch_k, stoch_d = (None, None)
        if len(candles) >= MIN_BARS_STOCH:
            stoch_k, stoch_d = calc_stochastic(candles)

        obv_trend = calc_obv_trend(closes, volumes)
        obv_series = calc_obv(closes, volumes)
        vpt_series = calc_vpt(closes, volumes)

        vpt_bearish_div = False
        if len(closes) >= 20 and len(vpt_series) >= 20:
            price_recent_high = max(closes[-10:])
            price_prev_high   = max(closes[-20:-10])
            vpt_recent_high   = max(vpt_series[-10:])
            vpt_prev_high     = max(vpt_series[-20:-10])
            if price_recent_high > price_prev_high and vpt_recent_high < vpt_prev_high:
                vpt_bearish_div = True

        roc_20 = calc_roc(closes, 20)
        roc_60 = calc_roc(closes, 60) if len(closes) > MIN_BARS_ROC60 else None

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

        det = all_details.get(sym, {})
        snap52 = all_52w_snapshots.get(sym, {})
        hi52 = (float(snap52.get("hi52") or 0)
                or float(det.get("fifty_two_week_high") or 0)
                or (max(closes[-252:]) if len(closes) >= 252 else max(closes)))
        lo52 = (float(snap52.get("lo52") or 0)
                or float(det.get("fifty_two_week_low") or 0)
                or (min(closes[-252:]) if len(closes) >= 252 else min(closes)))
        sector = (det.get("sector_name")
                  or all_securities.get(sym, {}).get("sector_name")
                  or "")

        high_prox = round((hi52 - price) / hi52 * 100, 1) if hi52 > 0 else 100
        range_pct = round((price - lo52) / (hi52 - lo52) * 100, 1) if hi52 != lo52 else 50

        pivots = {}
        if len(candles) >= 2:
            prev = candles[-2]
            pivots = calc_pivot_points(
                float(prev["high_price"]),
                float(prev["low_price"]),
                float(prev["close_price"])
            )

        fib = {}
        if hi52 > lo52:
            fib = calc_fibonacci_retracement(lo52, hi52)

        fib_618_broken = False
        if fib and price < fib.get("fib_618", 0):
            fib_618_broken = True

        patterns = detect_candlestick_patterns(candles) if len(candles) >= 2 else []

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

        stop_loss = calc_stop_loss(price, atr)
        target1, target2 = calc_targets(price, atr)
        rr_ratio = calc_rr_ratio(price, stop_loss, target1)
        position_size = calc_position_size(price, stop_loss)

        breakout_52w = False
        if price >= hi52 and vol_ratio > 1.2:
            breakout_52w = True
        breakout_candidate = False
        if sma50 is not None:
            breakout_candidate = is_breakout_candidate(price, sma50, hi52, vol_ratio, macd_hist)

        asym_score = broker_scores.get(sym, 50)
        sell_dist_pct = sell_distribution.get(sym, 0)

        returns_20 = []
        if len(closes) >= 21:
            for i in range(-20, 0):
                if closes[i-1] > 0:
                    returns_20.append((closes[i] - closes[i-1]) / closes[i-1] * 100)
        vol_20d = 0
        if returns_20:
            mu = sum(returns_20) / len(returns_20)
            vol_20d = round((sum((r - mu)**2 for r in returns_20) / len(returns_20)) ** 0.5, 2)

        peak, max_dd = closes[0], 0
        for c in closes:
            if c > peak:
                peak = c
            dd = (peak - c) / peak * 100
            if dd > max_dd:
                max_dd = dd

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
            pe=0,
        )

        signal = _classify_signal(
            rsi=rsi, macd_hist=macd_hist, cross=cross,
            bb_pct=bb_pct, price=price, sma20=sma20, sma50=sma50, sma200=sma200,
            vol_ratio=vol_ratio, obv_trend=obv_trend,
            stoch_k=stoch_k, stoch_d=stoch_d,
            breakout_candidate=breakout_candidate,
        )

        confidence = _calc_confidence(signal, rsi, macd_hist, vol_ratio, obv_trend,
                                      cross, bb_pct, asym_score)

        return {
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
        }, skip_stats

    except Exception as e:
        return None, {"error": f"{sym}:{type(e).__name__}"}

def analyze_all_symbols(all_ohlcv, all_corps, all_divs, all_details, all_securities,
                        all_52w_snapshots, broker_scores,
                        sell_distribution, market_regime, all_live_ltp=None):
    """Run all indicator calculations on every symbol using multiprocessing."""
    print("  [2] Analyzing all symbols (indicators, patterns, flags)...")

    if all_live_ltp is None:
        all_live_ltp = {}

    results = {}
    error_count = 0
    error_samples = []
    skip_stats_total = {
        "short_history": 0,
        "bad_price": 0,
        "stale_forward_fill": 0,
    }

    max_workers = multiprocessing.cpu_count()
    init_args = (all_corps, all_divs, all_details, all_securities, all_52w_snapshots, broker_scores, sell_distribution, market_regime, all_live_ltp)
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker, initargs=init_args) as executor:
        futures = {
            executor.submit(_process_single_symbol, sym, raw_candles): sym
            for sym, raw_candles in all_ohlcv.items()
        }
        
        for future in concurrent.futures.as_completed(futures):
            sym = futures[future]
            try:
                res, skips = future.result()
                if skips:
                    if 'error' in skips:
                        error_count += 1
                        if len(error_samples) < 5:
                            error_samples.append(skips['error'])
                    else:
                        for k, v in skips.items():
                            if k in skip_stats_total:
                                skip_stats_total[k] += v
                if res:
                    results[sym] = res
            except Exception as e:
                error_count += 1
                if len(error_samples) < 5:
                    error_samples.append(f"{sym}:{type(e).__name__}")

    if error_count:
        sample_text = ", ".join(error_samples)
        print(f"  ⚠ symbol analysis errors: {error_count} ({sample_text})")

    skipped_total = sum(skip_stats_total.values())
    if skipped_total:
        print(
            "  ⚠ symbol skip summary: "
            f"short_history={skip_stats_total['short_history']}, "
            f"stale_forward_fill={skip_stats_total['stale_forward_fill']}, "
            f"bad_price={skip_stats_total['bad_price']}"
        )

    return results
