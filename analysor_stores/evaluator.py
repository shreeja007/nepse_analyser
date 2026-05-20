"""
analysor_stores.evaluator — Accuracy evaluation engine.

Compares stored analysis predictions against actual price movements
from nepsego.daily_ohlcv at 7, 14, and 30-day horizons.

Usage:
    python -m analysor_stores.evaluator              # Evaluate all pending
    python -m analysor_stores.evaluator --force       # Re-evaluate everything
    python -m analysor_stores.evaluator --horizon 7   # Only 7-day horizon
"""

from __future__ import annotations

import sys
from datetime import date, datetime

from analysor_stores.config import ensure_database, get_conn, ANALYSIS_DB, SOURCE_DB


# ═══════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

HORIZONS = [7, 14, 30]          # Trading-day horizons to evaluate
HOLD_BAND_PCT = 5.0             # HOLD is "correct" if price stays within ±5%
DIRECTION_THRESHOLD = 0.0       # Minimum % change to count as directional

# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _fetch_pending_snapshots(conn, horizons: list[int], force: bool = False):
    """
    Fetch snapshots that need evaluation for the given horizons.
    Returns list of dicts with snapshot + run info.
    """
    if force:
        # Re-evaluate all snapshots that have enough candle data
        sql = """
            SELECT
                s.id AS snapshot_id, s.run_id, s.symbol, s.analysis_date,
                s.price, s.`signal`, s.signal_numeric, s.sector,
                s.stop_loss, s.target1, s.target2
            FROM analysis_snapshots s
            WHERE s.price IS NOT NULL
              AND s.price > 0
            ORDER BY s.analysis_date, s.symbol
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()
    else:
        # Only snapshots missing one or more horizon evaluations
        union_parts = " UNION ALL ".join(["SELECT %s AS h"] * len(horizons))
        sql = f"""
            SELECT DISTINCT
                s.id AS snapshot_id, s.run_id, s.symbol, s.analysis_date,
                s.price, s.`signal`, s.signal_numeric, s.sector,
                s.stop_loss, s.target1, s.target2
            FROM analysis_snapshots s
            WHERE s.price IS NOT NULL
              AND s.price > 0
              AND EXISTS (
                  SELECT 1 FROM ({union_parts}) horizons
                  WHERE NOT EXISTS (
                      SELECT 1 FROM analysis_accuracy aa
                      WHERE aa.snapshot_id = s.id
                        AND aa.horizon_days = horizons.h
                        AND aa.trade_outcome != 'PENDING'
                  )
              )
            ORDER BY s.analysis_date, s.symbol
        """
        with conn.cursor() as cur:
            cur.execute(sql, tuple(horizons))
            return cur.fetchall()


def _fetch_candles(source_conn, symbol: str, after_date: date,
                   max_days: int) -> list[dict]:
    """
    Fetch OHLCV candles from nepsego.daily_ohlcv for N trading days
    after the analysis date.
    """
    sql = """
        SELECT trading_date, high_price, low_price, close_price
        FROM daily_ohlcv
        WHERE symbol = %s
          AND trading_date > %s
          AND close_price > 0
        ORDER BY trading_date ASC
        LIMIT %s
    """
    with source_conn.cursor() as cur:
        cur.execute(sql, (symbol, after_date, max_days))
        return cur.fetchall()


def _evaluate_snapshot(snap: dict, candles: list[dict],
                       horizon: int) -> dict | None:
    """
    Evaluate a single snapshot at a given horizon.
    Returns a dict ready for INSERT into analysis_accuracy, or None if
    not enough candle data yet.
    """
    if len(candles) < horizon:
        return None  # Not enough trading days yet

    window = candles[:horizon]
    entry_price = float(snap["price"])
    signal = snap["signal"]
    signal_num = snap["signal_numeric"]
    stop_loss = float(snap["stop_loss"]) if snap.get("stop_loss") else None
    target1 = float(snap["target1"]) if snap.get("target1") else None
    target2 = float(snap["target2"]) if snap.get("target2") else None

    # Walk candles to find max/min and first hit days
    max_high = 0
    min_low = float("inf")
    first_target_day = None
    first_stop_day = None
    eval_price = float(window[-1]["close_price"])

    for day_num, c in enumerate(window, 1):
        h = float(c["high_price"])
        l = float(c["low_price"])

        if h > max_high:
            max_high = h
        if l < min_low:
            min_low = l

        # Check target1 hit
        if target1 and first_target_day is None and h >= target1:
            first_target_day = day_num

        # Check stop-loss hit
        if stop_loss and first_stop_day is None and l <= stop_loss:
            first_stop_day = day_num

    price_change_pct = ((eval_price - entry_price) / entry_price) * 100

    # Target / stop hit booleans
    t1_hit = bool(target1 and max_high >= target1)
    t2_hit = bool(target2 and max_high >= target2)
    sl_hit = bool(stop_loss and min_low <= stop_loss)

    # Direction correctness
    if signal in ("BUY", "STRONG BUY"):
        direction_correct = price_change_pct > DIRECTION_THRESHOLD
    elif signal in ("SELL", "STRONG SELL"):
        direction_correct = price_change_pct < -DIRECTION_THRESHOLD
    elif signal == "HOLD":
        direction_correct = abs(price_change_pct) <= HOLD_BAND_PCT
    else:
        direction_correct = None

    # Trade outcome logic
    if signal == "HOLD":
        if abs(price_change_pct) <= HOLD_BAND_PCT:
            outcome = "HOLD_CORRECT"
        else:
            outcome = "HOLD_INCORRECT"
    elif signal in ("BUY", "STRONG BUY"):
        if t1_hit and (not sl_hit or (first_target_day and first_stop_day
                                       and first_target_day <= first_stop_day)):
            outcome = "WIN"
        elif sl_hit and (not t1_hit or (first_stop_day and first_target_day
                                         and first_stop_day < first_target_day)):
            outcome = "LOSS"
        elif t1_hit and sl_hit:
            outcome = "PARTIAL"
        elif price_change_pct > 0:
            outcome = "PARTIAL"  # Profit but target not hit
        else:
            outcome = "LOSS"
    elif signal in ("SELL", "STRONG SELL"):
        # For SELL signals: "winning" means price dropped
        if price_change_pct < -DIRECTION_THRESHOLD:
            if sl_hit:
                outcome = "PARTIAL"
            else:
                outcome = "WIN"
        else:
            outcome = "LOSS"
    else:
        outcome = "NEUTRAL"

    return {
        "snapshot_id": snap["snapshot_id"],
        "run_id": snap["run_id"],
        "symbol": snap["symbol"],
        "analysis_date": snap["analysis_date"],
        "horizon_days": horizon,
        "evaluation_date": date.today(),
        "price_at_analysis": entry_price,
        "price_at_eval": eval_price,
        "max_high_in_window": max_high,
        "min_low_in_window": min_low if min_low != float("inf") else None,
        "price_change_pct": round(price_change_pct, 4),
        "target1_hit": t1_hit,
        "target2_hit": t2_hit,
        "stop_loss_hit": sl_hit,
        "first_target_hit_day": first_target_day,
        "first_stop_hit_day": first_stop_day,
        "direction_correct": direction_correct,
        "trade_outcome": outcome,
        "signal": signal,
        "signal_numeric": signal_num,
        "sector": snap.get("sector"),
    }


_UPSERT_ACCURACY = """
INSERT INTO analysis_accuracy (
    snapshot_id, run_id, symbol, analysis_date, horizon_days,
    evaluation_date, price_at_analysis, price_at_eval,
    max_high_in_window, min_low_in_window, price_change_pct,
    target1_hit, target2_hit, stop_loss_hit,
    first_target_hit_day, first_stop_hit_day,
    direction_correct, trade_outcome,
    `signal`, signal_numeric, sector, evaluated_at
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, %s,
    %s, %s,
    %s, %s, %s, %s
)
ON DUPLICATE KEY UPDATE
    evaluation_date     = VALUES(evaluation_date),
    price_at_eval       = VALUES(price_at_eval),
    max_high_in_window  = VALUES(max_high_in_window),
    min_low_in_window   = VALUES(min_low_in_window),
    price_change_pct    = VALUES(price_change_pct),
    target1_hit         = VALUES(target1_hit),
    target2_hit         = VALUES(target2_hit),
    stop_loss_hit       = VALUES(stop_loss_hit),
    first_target_hit_day = VALUES(first_target_hit_day),
    first_stop_hit_day  = VALUES(first_stop_hit_day),
    direction_correct   = VALUES(direction_correct),
    trade_outcome       = VALUES(trade_outcome),
    evaluated_at        = VALUES(evaluated_at)
"""


# ═══════════════════════════════════════════════════════════════════════
#  MAIN EVALUATION LOOP
# ═══════════════════════════════════════════════════════════════════════

def run_evaluation(horizons: list[int] = None, force: bool = False):
    """
    Evaluate all pending analysis snapshots against actual price data.
    """
    if horizons is None:
        horizons = HORIZONS

    ensure_database()

    print("=" * 65)
    print("  📊 Analysis Accuracy Evaluator")
    print(f"  Horizons: {horizons} trading days")
    print(f"  Mode: {'Force re-evaluate all' if force else 'Pending only'}")
    print("=" * 65)

    conn = get_conn()
    from analysor_stores.config import get_source_conn
    source_conn = get_source_conn()

    try:
        snapshots = _fetch_pending_snapshots(conn, horizons, force)
        total = len(snapshots)

        if total == 0:
            print("\n  ✅ No pending evaluations. All up to date.")
            return

        print(f"\n  Found {total} snapshots to evaluate\n")

        evaluated = 0
        skipped = 0
        inserted = 0

        # Cache candles per (symbol, analysis_date) to avoid repeated DB queries
        # Different runs for the same symbol may have different analysis dates,
        # so keying on symbol alone risks insufficient candle coverage.
        candle_cache: dict[tuple[str, date], list[dict]] = {}

        for i, snap in enumerate(snapshots, 1):
            sym = snap["symbol"]
            a_date = snap["analysis_date"]
            cache_key = (sym, a_date)

            # Fetch candles (cached per symbol+date)
            if cache_key not in candle_cache:
                candle_cache[cache_key] = _fetch_candles(
                    source_conn, sym, a_date, max(horizons) + 5
                )

            snap_candles = candle_cache[cache_key]

            for horizon in horizons:
                result = _evaluate_snapshot(snap, snap_candles, horizon)
                if result is None:
                    skipped += 1
                    continue

                # Upsert into accuracy table
                with conn.cursor() as cur:
                    cur.execute(_UPSERT_ACCURACY, (
                        result["snapshot_id"],
                        result["run_id"],
                        result["symbol"],
                        result["analysis_date"],
                        result["horizon_days"],
                        result["evaluation_date"],
                        result["price_at_analysis"],
                        result["price_at_eval"],
                        result["max_high_in_window"],
                        result["min_low_in_window"],
                        result["price_change_pct"],
                        result["target1_hit"],
                        result["target2_hit"],
                        result["stop_loss_hit"],
                        result["first_target_hit_day"],
                        result["first_stop_hit_day"],
                        result["direction_correct"],
                        result["trade_outcome"],
                        result["signal"],
                        result["signal_numeric"],
                        result["sector"],
                        datetime.now(),
                    ))
                inserted += 1
                evaluated += 1

            # Progress update every 100 symbols
            if i % 100 == 0 or i == total:
                conn.commit()
                print(f"  [{i:>4}/{total}] Evaluated: {evaluated} | "
                      f"Skipped: {skipped} (not enough candles)")

        conn.commit()

        print(f"\n  ✅ Evaluation complete: {inserted} accuracy rows written, "
              f"{skipped} skipped (insufficient data)")

        # Quick summary
        _print_quick_summary(conn)

    finally:
        conn.close()
        source_conn.close()


def _print_quick_summary(conn):
    """Print a brief accuracy summary after evaluation."""
    sql = """
        SELECT
            horizon_days,
            COUNT(*) AS total,
            SUM(direction_correct = 1) AS correct,
            ROUND(SUM(direction_correct = 1) * 100.0 / COUNT(*), 1) AS pct,
            SUM(trade_outcome = 'WIN') AS wins,
            SUM(trade_outcome = 'LOSS') AS losses
        FROM analysis_accuracy
        WHERE trade_outcome != 'PENDING'
        GROUP BY horizon_days
        ORDER BY horizon_days
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    if rows:
        print(f"\n  {'Horizon':>8s} | {'Total':>6s} | {'Dir.Acc':>7s} | "
              f"{'Wins':>5s} | {'Losses':>6s}")
        print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*7}-+-{'-'*5}-+-{'-'*6}")
        for r in rows:
            pct_val = float(r['pct'] or 0) if r['pct'] else 0.0
            wins_val = int(r['wins'] or 0) if r['wins'] else 0
            losses_val = int(r['losses'] or 0) if r['losses'] else 0
            print(f"  {r['horizon_days']:>5d}  d | {r['total']:>6d} | "
                  f"{pct_val:>6.1f}% | {wins_val:>5d} | "
                  f"{losses_val:>6d}")


# ═══════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def main():
    force = "--force" in sys.argv
    horizons = HORIZONS

    if "--horizon" in sys.argv:
        idx = sys.argv.index("--horizon")
        if idx + 1 < len(sys.argv):
            try:
                horizons = [int(sys.argv[idx + 1])]
            except ValueError:
                pass

    run_evaluation(horizons=horizons, force=force)


if __name__ == "__main__":
    main()
