"""
analysor_stores.reporter — CLI accuracy reporting and statistics.

Prints detailed accuracy breakdowns from the analysis_accuracy table:
signal-level stats, sector breakdowns, watchlist hit rates, confusion matrix.

Usage:
    python -m analysor_stores.reporter              # Full report
    python -m analysor_stores.reporter --compact     # Summary only
"""

from __future__ import annotations

import sys
from analysor_stores.config import ensure_database, get_conn


# ═══════════════════════════════════════════════════════════════════════
#  QUERY HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _q(conn, sql, params=None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def _qone(conn, sql, params=None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


# ═══════════════════════════════════════════════════════════════════════
#  REPORT SECTIONS
# ═══════════════════════════════════════════════════════════════════════

def _header(title: str):
    w = 72
    print(f"\n{'═' * w}")
    print(f"  {title}")
    print(f"{'═' * w}")


def _sub_header(title: str):
    print(f"\n  ── {title} {'─' * max(1, 55 - len(title))}")


def _report_overview(conn):
    """Database overview: total runs, snapshots, evaluations."""
    _header("DATABASE OVERVIEW")

    runs = _qone(conn, "SELECT COUNT(*) AS c FROM analysis_runs")
    snaps = _qone(conn, "SELECT COUNT(*) AS c FROM analysis_snapshots")
    evals = _qone(conn, """
        SELECT COUNT(*) AS c FROM analysis_accuracy
        WHERE trade_outcome != 'PENDING'
    """)
    pending = _qone(conn, """
        SELECT COUNT(*) AS c FROM analysis_accuracy
        WHERE trade_outcome = 'PENDING'
    """)

    dates = _qone(conn, """
        SELECT MIN(analysis_date) AS first_date,
               MAX(analysis_date) AS last_date,
               COUNT(DISTINCT analysis_date) AS unique_dates
        FROM analysis_snapshots
    """)

    print(f"  Analysis runs:       {runs['c']:>8,d}")
    print(f"  Total snapshots:     {snaps['c']:>8,d}")
    print(f"  Evaluated:           {evals['c']:>8,d}")
    print(f"  Pending:             {pending['c']:>8,d}")
    if dates and dates["first_date"]:
        print(f"  Date range:          {dates['first_date']} → {dates['last_date']} "
              f"({dates['unique_dates']} trading days)")


def _report_accuracy_by_horizon(conn):
    """Overall accuracy by horizon."""
    _header("OVERALL ACCURACY BY HORIZON")

    rows = _q(conn, """
        SELECT
            horizon_days,
            COUNT(*)                                        AS total,
            SUM(direction_correct = 1)                      AS dir_wins,
            ROUND(SUM(direction_correct = 1)*100.0/COUNT(*), 1) AS dir_pct,
            SUM(trade_outcome = 'WIN')                      AS wins,
            SUM(trade_outcome = 'LOSS')                     AS losses,
            SUM(trade_outcome = 'PARTIAL')                  AS partials,
            ROUND(SUM(trade_outcome = 'WIN')*100.0
                  /NULLIF(SUM(trade_outcome IN ('WIN','LOSS','PARTIAL')),0), 1)
                                                            AS win_rate,
            ROUND(AVG(price_change_pct), 2)                 AS avg_chg
        FROM analysis_accuracy
        WHERE trade_outcome != 'PENDING'
        GROUP BY horizon_days
        ORDER BY horizon_days
    """)

    if not rows:
        print("\n  No evaluated data yet. Run the evaluator first:")
        print("    python -m analysor_stores.evaluator")
        return

    hdr = (f"  {'Horizon':>8s} | {'Total':>6s} | {'Dir.Acc%':>8s} | "
           f"{'Wins':>5s} | {'Loss':>5s} | {'Part':>5s} | "
           f"{'WinRate%':>8s} | {'AvgChg%':>8s}")
    print(hdr)
    print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*8}-+-{'-'*5}-+-{'-'*5}-+-"
          f"{'-'*5}-+-{'-'*8}-+-{'-'*8}")

    for r in rows:
        dir_pct = float(r['dir_pct'] or 0) if r['dir_pct'] else 0.0
        wins = int(r['wins'] or 0) if r['wins'] else 0
        losses = int(r['losses'] or 0) if r['losses'] else 0
        partials = int(r['partials'] or 0) if r['partials'] else 0
        win_rate = float(r['win_rate'] or 0) if r['win_rate'] else 0.0
        avg_chg = float(r['avg_chg'] or 0) if r['avg_chg'] else 0.0
        print(f"  {r['horizon_days']:>5d}  d | {r['total']:>6d} | "
              f"{dir_pct:>7.1f}% | {wins:>5d} | "
              f"{losses:>5d} | {partials:>5d} | "
              f"{win_rate:>7.1f}% | {avg_chg:>+7.2f}%")


def _report_accuracy_by_signal(conn):
    """Breakdown by signal type for each horizon."""
    _header("ACCURACY BY SIGNAL TYPE")

    rows = _q(conn, """
        SELECT
            `signal`,
            horizon_days,
            COUNT(*)                                        AS total,
            ROUND(SUM(direction_correct=1)*100.0/COUNT(*),1) AS dir_pct,
            SUM(trade_outcome = 'WIN')                      AS wins,
            SUM(trade_outcome = 'LOSS')                     AS losses,
            ROUND(SUM(trade_outcome='WIN')*100.0
                  /NULLIF(SUM(trade_outcome IN ('WIN','LOSS','PARTIAL')),0),1)
                                                            AS win_rate,
            ROUND(AVG(price_change_pct), 2)                 AS avg_chg
        FROM analysis_accuracy
        WHERE trade_outcome != 'PENDING'
        GROUP BY `signal`, horizon_days
        ORDER BY FIELD(`signal`,'STRONG BUY','BUY','HOLD','SELL','STRONG SELL'),
                 horizon_days
    """)

    if not rows:
        return

    hdr = (f"  {'Signal':<12s} | {'Hor':>4s} | {'N':>5s} | {'Dir%':>5s} | "
           f"{'Win':>4s} | {'Loss':>4s} | {'WR%':>5s} | {'AvgChg':>7s}")
    print(hdr)
    print(f"  {'-'*12}-+-{'-'*4}-+-{'-'*5}-+-{'-'*5}-+-"
          f"{'-'*4}-+-{'-'*4}-+-{'-'*5}-+-{'-'*7}")

    prev_signal = None
    for r in rows:
        if prev_signal and r["signal"] != prev_signal:
            print(f"  {'-'*12}-+-{'-'*4}-+-{'-'*5}-+-{'-'*5}-+-"
                  f"{'-'*4}-+-{'-'*4}-+-{'-'*5}-+-{'-'*7}")
        prev_signal = r["signal"]

        dir_pct = float(r['dir_pct'] or 0) if r['dir_pct'] else 0.0
        wins = int(r['wins'] or 0) if r['wins'] else 0
        losses = int(r['losses'] or 0) if r['losses'] else 0
        win_rate = float(r['win_rate'] or 0) if r['win_rate'] else 0.0
        avg_chg = float(r['avg_chg'] or 0) if r['avg_chg'] else 0.0
        print(f"  {r['signal']:<12s} | {r['horizon_days']:>3d}d | "
              f"{r['total']:>5d} | {dir_pct:>4.1f}% | "
              f"{wins:>4d} | {losses:>4d} | "
              f"{win_rate:>4.1f}% | {avg_chg:>+6.2f}%")


def _report_accuracy_by_sector(conn):
    """Top sectors by directional accuracy (14-day horizon)."""
    _header("SECTOR ACCURACY (14-day horizon)")

    rows = _q(conn, """
        SELECT
            COALESCE(sector, 'Unknown') AS sector,
            COUNT(*) AS total,
            ROUND(SUM(direction_correct=1)*100.0/COUNT(*),1) AS dir_pct,
            SUM(trade_outcome='WIN') AS wins,
            ROUND(AVG(price_change_pct), 2) AS avg_chg
        FROM analysis_accuracy
        WHERE trade_outcome != 'PENDING'
          AND horizon_days = 14
        GROUP BY sector
        HAVING total >= 3
        ORDER BY dir_pct DESC
        LIMIT 20
    """)

    if not rows:
        print("\n  No 14-day evaluation data yet.")
        return

    hdr = (f"  {'Sector':<35s} | {'N':>5s} | {'Dir%':>5s} | "
           f"{'Wins':>5s} | {'AvgChg':>7s}")
    print(hdr)
    print(f"  {'-'*35}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}")

    for r in rows:
        sector = (r["sector"][:33] + "..") if len(r["sector"]) > 35 else r["sector"]
        dir_pct = float(r['dir_pct'] or 0) if r['dir_pct'] else 0.0
        wins = int(r['wins'] or 0) if r['wins'] else 0
        avg_chg = float(r['avg_chg'] or 0) if r['avg_chg'] else 0.0
        print(f"  {sector:<35s} | {r['total']:>5d} | {dir_pct:>4.1f}% | "
              f"{wins:>5d} | {avg_chg:>+6.2f}%")


def _report_top_symbols(conn):
    """Top 20 most accurately predicted symbols (14-day)."""
    _header("TOP 20 SYMBOLS BY ACCURACY (14-day horizon)")

    rows = _q(conn, """
        SELECT
            symbol,
            COUNT(*) AS predictions,
            SUM(direction_correct=1) AS correct,
            ROUND(SUM(direction_correct=1)*100.0/COUNT(*),1) AS accuracy,
            SUM(trade_outcome='WIN') AS wins,
            ROUND(AVG(price_change_pct), 2) AS avg_chg
        FROM analysis_accuracy
        WHERE trade_outcome != 'PENDING'
          AND horizon_days = 14
        GROUP BY symbol
        HAVING predictions >= 3
        ORDER BY accuracy DESC, wins DESC
        LIMIT 20
    """)

    if not rows:
        print("\n  Not enough data yet.")
        return

    hdr = (f"  {'Symbol':<12s} | {'Preds':>6s} | {'Correct':>7s} | "
           f"{'Acc%':>5s} | {'Wins':>5s} | {'AvgChg':>7s}")
    print(hdr)
    print(f"  {'-'*12}-+-{'-'*6}-+-{'-'*7}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}")

    for r in rows:
        correct = int(r['correct'] or 0) if r['correct'] else 0
        accuracy = float(r['accuracy'] or 0) if r['accuracy'] else 0.0
        wins = int(r['wins'] or 0) if r['wins'] else 0
        avg_chg = float(r['avg_chg'] or 0) if r['avg_chg'] else 0.0
        print(f"  {r['symbol']:<12s} | {r['predictions']:>6d} | "
              f"{correct:>7d} | {accuracy:>4.1f}% | "
              f"{wins:>5d} | {avg_chg:>+6.2f}%")


def _report_watchlist_hitrate(conn):
    """How often watchlist picks hit their targets."""
    _header("WATCHLIST HIT RATE")

    rows = _q(conn, """
        SELECT
            aa.horizon_days,
            COUNT(*) AS total_picks,
            SUM(aa.target1_hit = 1) AS t1_hits,
            ROUND(SUM(aa.target1_hit=1)*100.0/COUNT(*), 1) AS t1_rate,
            SUM(aa.target2_hit = 1) AS t2_hits,
            ROUND(SUM(aa.target2_hit=1)*100.0/COUNT(*), 1) AS t2_rate,
            SUM(aa.stop_loss_hit = 1) AS sl_hits,
            ROUND(SUM(aa.stop_loss_hit=1)*100.0/COUNT(*), 1) AS sl_rate,
            ROUND(AVG(aa.price_change_pct), 2) AS avg_chg
        FROM watchlist_snapshots ws
        JOIN analysis_snapshots s ON s.run_id = ws.run_id AND s.symbol = ws.symbol
        JOIN analysis_accuracy aa ON aa.snapshot_id = s.id
        WHERE aa.trade_outcome != 'PENDING'
        GROUP BY aa.horizon_days
        ORDER BY aa.horizon_days
    """)

    if not rows:
        print("\n  No watchlist evaluation data yet.")
        return

    hdr = (f"  {'Horizon':>8s} | {'Picks':>6s} | {'T1 Hit%':>8s} | "
           f"{'T2 Hit%':>8s} | {'SL Hit%':>8s} | {'AvgChg':>7s}")
    print(hdr)
    print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*7}")

    for r in rows:
        t1_rate = float(r['t1_rate'] or 0) if r['t1_rate'] else 0.0
        t2_rate = float(r['t2_rate'] or 0) if r['t2_rate'] else 0.0
        sl_rate = float(r['sl_rate'] or 0) if r['sl_rate'] else 0.0
        avg_chg = float(r['avg_chg'] or 0) if r['avg_chg'] else 0.0
        print(f"  {r['horizon_days']:>5d}  d | {r['total_picks']:>6d} | "
              f"{t1_rate:>7.1f}% | {t2_rate:>7.1f}% | "
              f"{sl_rate:>7.1f}% | {avg_chg:>+6.2f}%")


def _report_boom_hitrate(conn):
    """How often boom stock picks performed well."""
    _header("BOOM STOCK HIT RATE")

    rows = _q(conn, """
        SELECT
            aa.horizon_days,
            COUNT(*) AS total,
            SUM(aa.price_change_pct >= 15) AS big_movers,
            ROUND(SUM(aa.price_change_pct >= 15)*100.0/COUNT(*), 1) AS big_rate,
            SUM(aa.direction_correct = 1) AS dir_correct,
            ROUND(SUM(aa.direction_correct=1)*100.0/COUNT(*), 1) AS dir_pct,
            ROUND(AVG(aa.price_change_pct), 2) AS avg_chg
        FROM boom_stock_snapshots bs
        JOIN analysis_snapshots s ON s.run_id = bs.run_id AND s.symbol = bs.symbol
        JOIN analysis_accuracy aa ON aa.snapshot_id = s.id
        WHERE aa.trade_outcome != 'PENDING'
        GROUP BY aa.horizon_days
        ORDER BY aa.horizon_days
    """)

    if not rows:
        print("\n  No boom stock evaluation data yet.")
        return

    hdr = (f"  {'Horizon':>8s} | {'Total':>6s} | {'≥15%':>5s} | "
           f"{'Big%':>5s} | {'Dir%':>5s} | {'AvgChg':>7s}")
    print(hdr)
    print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}")

    for r in rows:
        big_movers = int(r['big_movers'] or 0) if r['big_movers'] else 0
        big_rate = float(r['big_rate'] or 0) if r['big_rate'] else 0.0
        dir_pct = float(r['dir_pct'] or 0) if r['dir_pct'] else 0.0
        avg_chg = float(r['avg_chg'] or 0) if r['avg_chg'] else 0.0
        print(f"  {r['horizon_days']:>5d}  d | {r['total']:>6d} | "
              f"{big_movers:>5d} | {big_rate:>4.1f}% | "
              f"{dir_pct:>4.1f}% | {avg_chg:>+6.2f}%")


def _report_confusion_matrix(conn):
    """Signal × Outcome confusion matrix (14-day horizon)."""
    _header("CONFUSION MATRIX (14-day horizon)")

    rows = _q(conn, """
        SELECT `signal`, trade_outcome, COUNT(*) AS cnt
        FROM analysis_accuracy
        WHERE trade_outcome != 'PENDING'
          AND horizon_days = 14
        GROUP BY `signal`, trade_outcome
        ORDER BY FIELD(`signal`,'STRONG BUY','BUY','HOLD','SELL','STRONG SELL'),
                 FIELD(trade_outcome,'WIN','LOSS','PARTIAL','NEUTRAL',
                       'HOLD_CORRECT','HOLD_INCORRECT')
    """)

    if not rows:
        print("\n  No data yet.")
        return

    # Build matrix
    signals = ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]
    outcomes = ["WIN", "LOSS", "PARTIAL", "HOLD_CORRECT", "HOLD_INCORRECT", "NEUTRAL"]

    matrix: dict[str, dict[str, int]] = {s: {o: 0 for o in outcomes} for s in signals}
    for r in rows:
        sig = r["signal"]
        out = r["trade_outcome"]
        if sig in matrix and out in matrix[sig]:
            matrix[sig][out] = r["cnt"]

    # Print
    out_labels = ["WIN", "LOSS", "PART", "H_OK", "H_BAD", "NEUT"]
    hdr = f"  {'Signal':<12s}" + "".join(f" | {o:>6s}" for o in out_labels) + " | TOTAL"
    print(hdr)
    sep = f"  {'-'*12}" + "".join(f"-+-{'-'*6}" for _ in out_labels) + "-+------"
    print(sep)

    for sig in signals:
        vals = [matrix[sig][o] for o in outcomes]
        total = sum(vals)
        line = f"  {sig:<12s}" + "".join(f" | {v:>6d}" for v in vals) + f" | {total:>5d}"
        print(line)


def _report_confidence_calibration(conn):
    """Check if confidence correlates with actual accuracy."""
    _header("CONFIDENCE CALIBRATION (14-day horizon)")

    rows = _q(conn, """
        SELECT
            CASE
                WHEN s.confidence < 40 THEN '< 40%%'
                WHEN s.confidence < 55 THEN '40-55%%'
                WHEN s.confidence < 70 THEN '55-70%%'
                WHEN s.confidence < 85 THEN '70-85%%'
                ELSE '≥ 85%%'
            END AS conf_bucket,
            COUNT(*) AS total,
            ROUND(SUM(aa.direction_correct=1)*100.0/COUNT(*), 1) AS actual_pct,
            ROUND(AVG(s.confidence), 1) AS avg_conf,
            ROUND(AVG(aa.price_change_pct), 2) AS avg_chg
        FROM analysis_accuracy aa
        JOIN analysis_snapshots s ON s.id = aa.snapshot_id
        WHERE aa.trade_outcome != 'PENDING'
          AND aa.horizon_days = 14
          AND s.confidence IS NOT NULL
        GROUP BY conf_bucket
        ORDER BY avg_conf
    """)

    if not rows:
        print("\n  No data yet.")
        return

    hdr = (f"  {'Conf.Bucket':>12s} | {'N':>5s} | {'Avg.Conf':>8s} | "
           f"{'Actual%':>7s} | {'AvgChg':>7s} | Calibration")
    print(hdr)
    print(f"  {'-'*12}-+-{'-'*5}-+-{'-'*8}-+-{'-'*7}-+-{'-'*7}-+-----------")

    for r in rows:
        avg_conf = float(r["avg_conf"] or 0) if r["avg_conf"] else 0.0
        actual = float(r["actual_pct"] or 0) if r["actual_pct"] else 0.0
        avg_chg = float(r['avg_chg'] or 0) if r['avg_chg'] else 0.0
        diff = actual - avg_conf
        if abs(diff) < 5:
            cal = "Well calibrated"
        elif diff > 0:
            cal = f"Under-confident ({diff:+.1f})"
        else:
            cal = f"Over-confident ({diff:+.1f})"

        print(f"  {r['conf_bucket']:>12s} | {r['total']:>5d} | "
              f"{avg_conf:>7.1f}% | {actual:>6.1f}% | "
              f"{avg_chg:>+6.2f}% | {cal}")


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def run_report(compact: bool = False):
    """Generate and print the full accuracy report."""
    ensure_database()

    print("=" * 72)
    print("  📊 NEPSE Analysis Accuracy Report")
    print(f"  Generated: {__import__('datetime').date.today()}")
    print("=" * 72)

    conn = get_conn()
    try:
        # Check if any data exists
        count = _qone(conn, "SELECT COUNT(*) AS c FROM analysis_snapshots")
        if not count or count["c"] == 0:
            print("\n  No analysis data stored yet.")
            print("  Run the analyzer first: python -m analysor")
            return

        _report_overview(conn)
        _report_accuracy_by_horizon(conn)
        _report_accuracy_by_signal(conn)

        if not compact:
            _report_accuracy_by_sector(conn)
            _report_top_symbols(conn)
            _report_watchlist_hitrate(conn)
            _report_boom_hitrate(conn)
            _report_confusion_matrix(conn)
            _report_confidence_calibration(conn)

        print(f"\n{'=' * 72}")
        print("  Tip: Run evaluator first if data looks stale:")
        print("    python -m analysor_stores.evaluator")
        print(f"{'=' * 72}\n")

    finally:
        conn.close()


def main():
    compact = "--compact" in sys.argv
    run_report(compact=compact)


if __name__ == "__main__":
    main()
