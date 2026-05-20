"""
NEPSE Analytics Engine v3.0 — Package Entry Point

Usage:
    python -m analysor              # Run full analysis + generate report.html
    python -m analysor --output DIR # Custom output directory
"""

import os
import sys
import time


def main():
    """Run the full NEPSE analysis pipeline and generate the HTML report."""
    from analysor.logic import run_full_analysis
    from analysor.html_extractor import build_html, write_report

    output_dir = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]
            os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("  🎯 NEPSE Trading Assistant v3.0")
    print("  AI-Powered Technical Analysis Engine")
    print("=" * 60)

    t0 = time.time()

    # Phase 1: Run analysis
    data = run_full_analysis()

    # Phase 2: Generate HTML
    html = build_html(data)

    # Phase 3: Write report
    filepath = write_report(html, output_dir)

    elapsed = time.time() - t0
    print(f"\n  ⏱️  Total time: {elapsed:.1f}s")

    # Phase 4: Persist to nepsego_analysis DB
    try:
        from analysor_stores import save_full_analysis
        save_full_analysis(data, filepath, elapsed)
    except Exception as e:
        print(f"  ⚠️  DB store skipped: {e}")

    # Quick summary
    wl = data.get("watchlist", [])
    if wl:
        print(f"\n  🔥 Top pick: {wl[0]['symbol']} ({wl[0].get('signal','HOLD')}, "
              f"R:R {wl[0].get('rr_ratio', 0):.1f}:1, "
              f"confidence {wl[0].get('confidence', 0):.0f}%)")
    else:
        print("\n  ℹ️  No watchlist picks passed all filters today.")

    print(f"\n  📄 Open: file:///{filepath.replace(os.sep, '/')}")
    print("=" * 60)
    return filepath


if __name__ == "__main__":
    main()
