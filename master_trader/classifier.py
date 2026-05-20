"""Timeframe classifier for NEPSE Master Trader.

This module classifies a stock into one or more buckets:
  - short: 1-5 day momentum setup
  - swing: 1-2 month swing setup
  - long: accumulation profile
  - hotlist: highest conviction cross-timeframe ideas
"""

from __future__ import annotations

from typing import Any


RSI_SHORT_MAX = 80
RSI_SHORT_MIN = 52
MIN_AVG_VOLUME = 5000
MIN_DATA_BARS = 120
MIN_DATA_CONFIDENCE = 60


def _fmt_bool(ok: bool, text: str) -> str:
    return ("PASS: " if ok else "FAIL: ") + text


def classify_stock(stock: dict[str, Any], sector_pe_avg: float | None) -> dict[str, Any]:
    """Classify one stock into trade buckets and return reasons.

    Returns:
        {
            "short": bool,
            "swing": bool,
            "long": bool,
            "hotlist": bool,
            "reasons": {
                "short": [..],
                "swing": [..],
                "long": [..],
                "hotlist": [..],
            }
        }
    """

    reasons = {"short": [], "swing": [], "long": [], "hotlist": []}

    price = float(stock.get("price") or 0)
    rsi = stock.get("rsi")
    vwap = stock.get("vwap")
    top_mover_streak = int(stock.get("top_mover_streak") or 0)
    vol_ratio = float(stock.get("vol_ratio") or 0)
    high_prox = float(stock.get("high_prox") or 100)
    score = float(stock.get("score") or 0)
    has_setup = bool(stock.get("setup_type"))
    weekly_uptrend = bool(stock.get("weekly_uptrend"))
    rr_ratio = float(stock.get("rr_ratio") or 0)
    sector_rsi_pct = stock.get("sector_rsi_pct")
    scrip_rank_turnover = stock.get("scrip_rank_turnover")
    try:
        scrip_rank_turnover = int(scrip_rank_turnover) if scrip_rank_turnover is not None else None
    except Exception:
        scrip_rank_turnover = None
    pe = float(stock.get("pe") or 0)
    eps = float(stock.get("eps") or 0)
    pb_ratio = stock.get("pb_ratio")
    fundamental_score = float(stock.get("fundamental_score") or 0)
    has_dividend_history = bool(stock.get("has_dividend_history"))
    broker_asym = float(stock.get("broker_asym") or 50)
    boom_flag = bool(stock.get("boom_flag"))
    circuit_volatile = bool(stock.get("circuit_volatile"))
    avg_volume = float(stock.get("avg_volume") or 0)
    data_bars = int(stock.get("data_bars") or 0)
    data_confidence = int(stock.get("data_confidence") or 0)
    fundamental_stale = bool(stock.get("fundamental_stale"))
    veto_reasons = [str(v) for v in (stock.get("veto_reasons") or []) if v]
    hard_veto = bool(stock.get("hard_veto")) or bool(veto_reasons)

    if hard_veto:
        reason_text = ", ".join(veto_reasons[:3]) if veto_reasons else "policy veto"
        msg = f"FAIL: hard veto active ({reason_text})"
        reasons["short"].append(msg)
        reasons["swing"].append(msg)
        reasons["long"].append(msg)
        reasons["hotlist"].append(msg)
        return {
            "short": False,
            "swing": False,
            "long": False,
            "hotlist": False,
            "reasons": reasons,
        }

    if data_bars < MIN_DATA_BARS:
        msg = f"FAIL: insufficient data bars ({data_bars} < {MIN_DATA_BARS})"
        reasons["short"].append(msg)
        reasons["swing"].append(msg)
        reasons["long"].append(msg)
        reasons["hotlist"].append(msg)
        return {
            "short": False,
            "swing": False,
            "long": False,
            "hotlist": False,
            "reasons": reasons,
        }

    if data_confidence < MIN_DATA_CONFIDENCE:
        msg = f"FAIL: data confidence below floor ({data_confidence} < {MIN_DATA_CONFIDENCE})"
        reasons["short"].append(msg)
        reasons["swing"].append(msg)
        reasons["long"].append(msg)
        reasons["hotlist"].append(msg)
        return {
            "short": False,
            "swing": False,
            "long": False,
            "hotlist": False,
            "reasons": reasons,
        }

    if circuit_volatile:
        msg = "FAIL: circuit volatility flag active"
        reasons["short"].append(msg)
        reasons["swing"].append(msg)
        reasons["long"].append(msg)
        reasons["hotlist"].append(msg)
        return {
            "short": False,
            "swing": False,
            "long": False,
            "hotlist": False,
            "reasons": reasons,
        }

    if avg_volume < MIN_AVG_VOLUME:
        msg = f"FAIL: average volume below {MIN_AVG_VOLUME:.0f} (avg={avg_volume:.0f})"
        reasons["short"].append(msg)
        reasons["swing"].append(msg)
        reasons["long"].append(msg)
        reasons["hotlist"].append(msg)
        return {
            "short": False,
            "swing": False,
            "long": False,
            "hotlist": False,
            "reasons": reasons,
        }

    # Short-term bucket
    short_cond_1 = top_mover_streak >= 2 or vol_ratio > 2.0 or (scrip_rank_turnover is not None and scrip_rank_turnover <= 20)
    short_cond_2 = rsi is not None and RSI_SHORT_MIN <= float(rsi) <= RSI_SHORT_MAX
    short_cond_3 = vwap is not None and price > float(vwap)
    short_cond_4 = high_prox > 2.0
    short_cond_5 = sector_rsi_pct is None or float(sector_rsi_pct) >= 45

    reasons["short"].append(
        _fmt_bool(
            short_cond_1,
            "top-mover/turnover leadership or volume ratio > 2.0 "
            f"(streak={top_mover_streak}, vol={vol_ratio:.2f}x, turnover_rank={scrip_rank_turnover})",
        )
    )
    reasons["short"].append(
        _fmt_bool(short_cond_2, f"RSI in momentum zone {RSI_SHORT_MIN}-{RSI_SHORT_MAX} (rsi={rsi})")
    )
    reasons["short"].append(
        _fmt_bool(short_cond_3, f"price above VWAP (price={price:.2f}, vwap={vwap})")
    )
    reasons["short"].append(
        _fmt_bool(short_cond_4, f"not within 2% of 52W high (high_prox={high_prox:.2f}%)")
    )
    reasons["short"].append(
        _fmt_bool(short_cond_5, f"sector-relative RSI percentile >= 45 (sector_pct={sector_rsi_pct})")
    )
    short_ok = all((short_cond_1, short_cond_2, short_cond_3, short_cond_4, short_cond_5))

    # Swing bucket
    swing_cond_1 = score >= 65
    swing_cond_2 = has_setup
    swing_cond_3 = weekly_uptrend
    swing_cond_4 = rr_ratio >= 2.0
    swing_cond_5 = sector_rsi_pct is None or float(sector_rsi_pct) >= 40
    swing_cond_6 = not fundamental_stale

    reasons["swing"].append(_fmt_bool(swing_cond_1, f"universal score >= 65 (score={score:.1f})"))
    reasons["swing"].append(_fmt_bool(swing_cond_2, f"one of named setups detected ({stock.get('setup_type')})"))
    reasons["swing"].append(_fmt_bool(swing_cond_3, f"weekly uptrend confirmed ({weekly_uptrend})"))
    reasons["swing"].append(_fmt_bool(swing_cond_4, f"R:R >= 2.0 (rr={rr_ratio:.2f})"))
    reasons["swing"].append(
        _fmt_bool(swing_cond_5, f"sector-relative RSI percentile >= 40 (sector_pct={sector_rsi_pct})")
    )
    reasons["swing"].append(_fmt_bool(swing_cond_6, f"fundamental snapshot is fresh (stale={fundamental_stale})"))
    swing_ok = all((swing_cond_1, swing_cond_2, swing_cond_3, swing_cond_4, swing_cond_5, swing_cond_6))

    # Long-term accumulation bucket
    long_cond_1 = sector_pe_avg is not None and sector_pe_avg > 0 and pe > 0 and pe < sector_pe_avg
    long_cond_2 = eps > 0 and has_dividend_history
    long_cond_3 = pb_ratio is None or float(pb_ratio) < 1.5
    long_cond_4 = fundamental_score >= 60

    reasons["long"].append(
        _fmt_bool(long_cond_1, f"P/E below sector average (pe={pe:.2f}, sector_avg={sector_pe_avg})")
    )
    reasons["long"].append(
        _fmt_bool(long_cond_2, f"positive EPS and dividend/bonus history (eps={eps:.2f})")
    )
    reasons["long"].append(
        _fmt_bool(long_cond_3, f"price near book value with P/B < 1.5 (pb={pb_ratio})")
    )
    reasons["long"].append(
        _fmt_bool(long_cond_4, f"strong fundamental score (fundamental_score={fundamental_score:.1f})")
    )
    long_ok = all((long_cond_1, long_cond_2, long_cond_3, long_cond_4))

    # Hotlist bucket
    hot_cond_1 = score >= 75
    hot_cond_2 = has_setup
    broker_trust_label = str(stock.get("broker_trust_label") or "UNRATED").upper()
    high_trust_accum_brokers = int(stock.get("high_trust_accum_brokers") or 0)
    trusted_asymmetry = broker_asym > 55 and broker_trust_label in {"HIGH", "MEDIUM"}
    convergence_signal = high_trust_accum_brokers >= 2
    hot_cond_3 = boom_flag or trusted_asymmetry or convergence_signal
    hot_cond_4 = rr_ratio >= 2.0
    hot_cond_5 = not fundamental_stale
    reasons["hotlist"].append(_fmt_bool(hot_cond_1, f"score >= 75 (score={score:.1f})"))
    reasons["hotlist"].append(_fmt_bool(hot_cond_2, f"setup detected ({stock.get('setup_type')})"))
    reasons["hotlist"].append(
        _fmt_bool(
            hot_cond_3,
            (
                "BOOM accumulation flag or trusted broker asymmetry > 55 "
                f"or >=2 high-trust accumulating brokers "
                f"(boom={boom_flag}, asym={broker_asym:.1f}, trust={broker_trust_label}, "
                f"high_trust_accum={high_trust_accum_brokers})"
            ),
        )
    )
    reasons["hotlist"].append(_fmt_bool(hot_cond_4, f"R:R >= 2.0 (rr={rr_ratio:.2f})"))
    reasons["hotlist"].append(_fmt_bool(hot_cond_5, f"fundamental snapshot is fresh (stale={fundamental_stale})"))
    hot_ok = all((hot_cond_1, hot_cond_2, hot_cond_3, hot_cond_4, hot_cond_5))

    return {
        "short": short_ok,
        "swing": swing_ok,
        "long": long_ok,
        "hotlist": hot_ok,
        "reasons": reasons,
    }
