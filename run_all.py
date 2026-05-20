#!/usr/bin/env python3
"""
Run all data collection scripts serially, one by one.

Usage:
    python run_all.py
"""

import subprocess
import sys
import time

SCRIPTS = [
    "run_floorsheet_collection.py",
    "run_scrip_price_graph_collection.py",
    "run_nepse_sub_indices_collection.py",
    "run_trade_turnover_subindices_collection.py",
    "run_company_details_collection.py",
    "run_market_summary_collection.py",
    "run_top_movers_collection.py",
    "run_scrip_rankings_collection.py",
    "run_daily_index_graph_collection.py",
    "run_all_analayser.py"
]


def main() -> int:
    total_start = time.time()
    results = []

    print("\n" + "=" * 60)
    print("  RUNNING ALL COLLECTORS")
    print("=" * 60)
    print(f"  Scripts to run: {len(SCRIPTS)}\n")

    for i, script in enumerate(SCRIPTS, 1):
        label = script.replace("run_", "").replace("_collection.py", "")
        print(f"[{i}/{len(SCRIPTS)}] Running {script} ...")
        start = time.time()

        result = subprocess.run(
            [sys.executable, script],
            cwd=sys.path[0] or ".",
        )

        elapsed = time.time() - start
        status = "✓ OK" if result.returncode == 0 else "✗ FAILED"
        results.append((script, result.returncode, elapsed))
        print(f"  {status} ({elapsed:.1f}s)\n")

    total_elapsed = time.time() - total_start
    passed = sum(1 for _, rc, _ in results if rc == 0)
    failed = len(results) - passed

    print("=" * 60)
    print("  ALL COLLECTORS — SUMMARY")
    print("=" * 60)
    for script, rc, elapsed in results:
        icon = "✓" if rc == 0 else "✗"
        print(f"  {icon} {script:<50s} {elapsed:>7.1f}s")
    print("-" * 60)
    print(f"  Total: {passed} passed, {failed} failed, {total_elapsed:.1f}s elapsed")
    print("=" * 60 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
