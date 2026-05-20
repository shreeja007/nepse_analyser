"""
NEPSE Single-Stock Deep Analysis Engine v1.0 — Package Entry Point

Usage:
    python -m single_analyser NABIL           # Analyze NABIL
    python -m single_analyser NABIL SCB HBL   # Analyze multiple symbols
    python -m single_analyser --all           # Analyze ALL symbols → single combined HTML
    python -m single_analyser NABIL --output DIR  # Custom output dir
"""

import os
import sys
import time


def _parse_args():
    """Parse CLI arguments safely using positional indices, not values."""
    argv = sys.argv[1:]
    output_dir = None
    is_all = "--all" in argv

    # Identify which argv indices are consumed by flags
    consumed_indices = set()
    for i, a in enumerate(argv):
        if a.startswith("-"):
            consumed_indices.add(i)
            if a == "--output" and i + 1 < len(argv):
                output_dir = argv[i + 1]
                consumed_indices.add(i + 1)

    # Symbol args = everything not consumed by flags
    symbols = [argv[i].upper().strip() for i in range(len(argv))
               if i not in consumed_indices]

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    return symbols, output_dir, is_all


def main():
    """Run single-stock analysis for one or more symbols."""
    from single_analyser.logic import analyze_single_stock, get_conn, q
    from single_analyser.html_extractor import (
        build_html, write_report,
        build_all_stocks_html, write_all_stocks_report,
    )

    symbols, output_dir, is_all = _parse_args()

    # Handle --all flag
    if is_all:
        conn = get_conn()
        try:
            rows = q(conn, """
                SELECT DISTINCT do.symbol
                FROM daily_ohlcv do
                JOIN securities s ON do.symbol = s.symbol
                WHERE do.close_price > 0
                  AND (s.instrument_type = 'Equity' OR s.instrument_type IS NULL)
                ORDER BY do.symbol
            """)
            symbols = [r["symbol"] for r in rows]
            print(f"\n  📋 Found {len(symbols)} equity symbols to analyze")
        finally:
            conn.close()

    if not symbols:
        print("=" * 60)
        print("  📊 NEPSE Single Stock Analyser v1.0")
        print("=" * 60)
        print("\n  Usage:")
        print("    python -m single_analyser NABIL           # Single stock")
        print("    python -m single_analyser NABIL SCB HBL   # Multiple stocks")
        print("    python -m single_analyser --all           # All equity symbols")
        print("    python -m single_analyser NABIL --output DIR")
        print()
        return

    print("=" * 60)
    print("  📊 NEPSE Single Stock Analyser v1.0")
    print(f"  Analyzing {len(symbols)} symbol(s)")
    print("=" * 60)

    t0 = time.time()

    # ── --all mode: single combined HTML ──
    if is_all:
        all_data = []
        failed = []
        total = len(symbols)
        for i, symbol in enumerate(symbols, 1):
            try:
                data = analyze_single_stock(symbol, quiet=True)
                if data:
                    all_data.append(data)
                    sig = data.get("signal", "HOLD")
                    score = data.get("composite", 0)
                    print(f"  [{i:>3}/{total}] {symbol:<12s} → {sig:<12s} | Score: {score:.1f}")
                else:
                    failed.append(symbol)
                    print(f"  [{i:>3}/{total}] {symbol:<12s} → SKIPPED (no data)")
            except Exception as e:
                failed.append(symbol)
                print(f"  [{i:>3}/{total}] {symbol:<12s} → ERROR: {e}")

        elapsed = time.time() - t0

        if all_data:
            html = build_all_stocks_html(all_data, failed)
            filepath = write_all_stocks_report(html, output_dir)
            print(f"\n  ✅ All stocks complete ({len(all_data)} analyzed, {len(failed)} failed)")
            print(f"  ⏱️  Total time: {elapsed:.1f}s")
            print(f"  📄 Report: {filepath}")
            print(f"  📄 Open: file:///{filepath.replace(os.sep, '/')}")

            # Persist to nepsego_analysis DB
            try:
                from analysor_stores import save_batch_single_analysis
                save_batch_single_analysis(all_data, filepath, elapsed)
            except Exception as e:
                print(f"  ⚠️  DB store skipped: {e}")
        else:
            print(f"\n  ❌ No stocks analyzed successfully")
        print("=" * 60)
        return

    # ── Individual stock mode: one HTML per symbol ──
    results = []
    for symbol in symbols:
        try:
            t_single = time.time()
            data = analyze_single_stock(symbol)
            if data:
                html = build_html(data)
                filepath = write_report(html, symbol, output_dir)
                results.append((symbol, filepath, data.get("signal", "HOLD"),
                                data.get("composite", 0)))

                # Persist to nepsego_analysis DB
                try:
                    from analysor_stores import save_single_analysis
                    save_single_analysis(symbol, data, filepath,
                                         time.time() - t_single)
                except Exception as e:
                    print(f"  ⚠️  DB store skipped: {e}")
            else:
                print(f"\n  ⚠️ No data found for {symbol}")
                results.append((symbol, None, "ERROR", 0))
        except Exception as e:
            print(f"\n  ❌ Error analyzing {symbol}: {e}")
            results.append((symbol, None, "ERROR", 0))

    elapsed = time.time() - t0

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  📋 Analysis Summary")
    print(f"{'=' * 60}")
    print(f"  ⏱️  Total time: {elapsed:.1f}s ({len(results)} symbols)\n")

    for sym, path, signal, composite in results:
        if path:
            print(f"  ✅ {sym:10s} | {signal:12s} | Score: {composite:5.1f} | {os.path.basename(path)}")
        else:
            print(f"  ❌ {sym:10s} | No data or error")

    if results and results[0][1]:
        print(f"\n  📄 Open: file:///{results[0][1].replace(os.sep, '/')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
