"""NEPSE Master Trader package entrypoint.

Usage:
    python -m master_trader
    python -m master_trader --equity 500000
    python -m master_trader --quick
    python -m master_trader --track NABIL HBL
"""

from __future__ import annotations

import argparse
import os
import time

from master_trader.html_master import build_master_html, write_master_report
from master_trader.pipeline import run_master_pipeline


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--equity must be a positive integer.")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="master_trader",
        description="Unified NEPSE analysis and trade-plan coordinator.",
    )
    parser.add_argument(
        "--equity",
        type=_positive_int,
        default=None,
        help="Optional portfolio size for position sizing. Omit for screening mode.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip heavier deep-dive enrichments for faster execution.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional output directory for the generated HTML.",
    )
    parser.add_argument(
        "--track",
        nargs="*",
        default=None,
        help="Symbols to evaluate for HOLD/TRIM/EXIT signals.",
    )
    parser.add_argument(
        "--allow-stale-data",
        action="store_true",
        help="Allow report generation when latest daily_ohlcv date is not today.",
    )
    return parser.parse_args()


def main() -> str:
    args = _parse_args()
    if args.output:
        os.makedirs(args.output, exist_ok=True)

    trading_mode = bool(args.equity)

    print("=" * 68)
    print("  NEPSE Master Trader")
    print("  One pipeline, one report, flexible screening and trade plans")
    print(f"  Mode: {'TRADING' if trading_mode else 'SCREENING'}")
    print("=" * 68)

    t0 = time.time()
    report_data = run_master_pipeline(
        equity=args.equity,
        quick=args.quick,
        allow_stale_data=args.allow_stale_data,
        tracked_symbols=args.track or [],
    )

    html = build_master_html(report_data)
    filepath = write_master_report(html, output_dir=args.output)
    elapsed = time.time() - t0

    print(f"\n  Elapsed: {elapsed:.1f}s")
    print(f"  Report: file:///{filepath.replace(os.sep, '/')}")

    hotlist = report_data.get("hotlist", [])
    if hotlist:
        top = hotlist[0]
        print(
            f"  Top hotlist: {top.get('symbol', 'N/A')} "
            f"(score {top.get('score', 0):.0f})"
        )

    tracked = report_data.get("tracked", [])
    if tracked:
        print("\n  Track verdicts:")
        for row in tracked:
            print(
                f"    - {row.get('symbol','N/A')}: {row.get('verdict','HOLD')}"
                f" ({row.get('status_note','')})"
            )

    print("=" * 68)
    return filepath


__all__ = ["main"]
