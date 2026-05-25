#!/usr/bin/env python3
"""
Run all analyzer modules in parallel.

Usage:
    python run_all_analayser.py
"""

import subprocess
import sys
import time

COMMANDS = [
    ("analysor", [sys.executable, "-m", "analysor"]),
    ("single_analyser --all", [sys.executable, "-m", "single_analyser", "--all"]),
    ("swing_analyser --mode full", [sys.executable, "-m", "swing_analyser", "--mode", "full"]),
    ("master_trader --allow-stale-data", [sys.executable, "-m", "master_trader", "--allow-stale-data"]),
    ("broker_tracker", [sys.executable, "-m", "broker_tracker"]),
]


def main() -> int:
    total_start = time.time()
    processes = []

    print("\n" + "=" * 60)
    print("  RUNNING ALL ANALYZERS (PARALLEL)")
    print("=" * 60)
    print(f"  Commands to run: {len(COMMANDS)}\n")

    for label, cmd in COMMANDS:
        print(f"  Starting: {label}")
        p = subprocess.Popen(
            cmd,
            stdout=sys.stdout,
            stderr=sys.stderr,
            cwd=sys.path[0] or ".",
        )
        processes.append((label, p, time.time()))

    print("\n  Waiting for all processes to finish...\n")

    results = []
    for label, p, start_time in processes:
        rc = p.wait()
        elapsed = time.time() - start_time
        results.append((label, rc, elapsed))

    total_elapsed = time.time() - total_start
    passed = sum(1 for _, rc, _ in results if rc == 0)
    failed = len(results) - passed

    print("\n" + "=" * 60)
    print("  ALL ANALYZERS \u2014 SUMMARY")
    print("=" * 60)
    for label, rc, elapsed in results:
        icon = "\u2713" if rc == 0 else "\u2717"
        print(f"  {icon} {label:<35s} {elapsed:>7.1f}s")
    print("-" * 60)
    print(f"  Total: {passed} passed, {failed} failed, {total_elapsed:.1f}s elapsed")
    print("=" * 60 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
