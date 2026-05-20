"""
NEPSE Swing Trading Analyser v1.0 — Package Entry Point

Identifies and ranks mid-term swing trade candidates (1–2 month hold)
from the nepsego database.  Produces a self-contained HTML report with
an actionable watchlist, entry/exit levels, and risk context.

Usage:
    python -m swing_analyser                    # Strict-filter watchlist (default)
    python -m swing_analyser --mode rank        # Universal ranking + hotlist
    python -m swing_analyser --mode full        # Both combined in one report
    python -m swing_analyser --output DIR       # Custom output directory
    python -m swing_analyser --top N            # Show top N candidates (default 15)
    python -m swing_analyser --min-volume 5000  # Custom min avg volume
    python -m swing_analyser --equity 500000    # Portfolio size (default 100000)
"""

import os
import sys
import time


def main():
    """Run the swing-trading analysis pipeline and generate the HTML report."""

    # ── Parse CLI args ──
    argv = sys.argv[1:]
    output_dir = None
    top_n = 15
    min_vol = 5000
    equity = None
    mode = "swing"   # "swing", "rank", or "full"

    i = 0
    while i < len(argv):
        if argv[i] == "--output" and i + 1 < len(argv):
            output_dir = argv[i + 1]
            os.makedirs(output_dir, exist_ok=True)
            i += 2
        elif argv[i] == "--top" and i + 1 < len(argv):
            top_n = int(argv[i + 1])
            i += 2
        elif argv[i] == "--min-volume" and i + 1 < len(argv):
            min_vol = int(argv[i + 1])
            i += 2
        elif argv[i] == "--equity" and i + 1 < len(argv):
            equity = int(argv[i + 1])
            i += 2
        elif argv[i] == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1].lower()
            if mode not in ("swing", "rank", "full"):
                print(f"  ⚠ Unknown mode '{mode}', defaulting to 'swing'")
                mode = "swing"
            i += 2
        else:
            i += 1

    mode_labels = {
        "swing": "Strict-Filter Watchlist",
        "rank":  "Universal Ranking + Hotlist",
        "full":  "Combined Analysis",
    }

    print("=" * 62)
    print("  🔄 NEPSE Swing Trading Analyser v1.0")
    print(f"  Mode: {mode_labels[mode]}")
    print("=" * 62)

    t0 = time.time()

    swing_data = None
    ranking_data = None

    # ── Phase 1: Run analysis ──
    if mode in ("swing", "full"):
        from swing_analyser.logic import run_swing_analysis
        swing_data = run_swing_analysis(
            top_n=top_n, min_avg_volume=min_vol, account_equity=equity
        )

    if mode in ("rank", "full"):
        from swing_analyser.scoring import run_ranking_analysis
        ranking_data = run_ranking_analysis(account_equity=equity)

    # ── Phase 2: Generate HTML ──
    if mode == "swing":
        from swing_analyser.html_report import build_html, write_report
        html = build_html(swing_data)
        filepath = write_report(html, output_dir)
    elif mode == "rank":
        from swing_analyser.html_ranking import build_ranking_html, write_ranking_report
        html = build_ranking_html(ranking_data)
        filepath = write_ranking_report(html, output_dir)
    else:  # full
        from swing_analyser.html_ranking import build_full_html, write_ranking_report
        html = build_full_html(swing_data, ranking_data)
        filepath = write_ranking_report(html, output_dir)

    elapsed = time.time() - t0

    # ── Phase 3: Print summary ──
    print(f"\n  ⏱️  Total time: {elapsed:.1f}s")

    if swing_data:
        wl = swing_data.get("watchlist", [])
        print(f"  📊 Symbols analyzed: {swing_data.get('total_analyzed', 0)}")
        print(f"  🎯 Swing candidates: {len(wl)}")
        if wl:
            top = wl[0]
            print(f"\n  🔥 Top pick: {top['symbol']} — {top['setup_type']}")
            print(f"     Entry: Rs {top['entry_zone'][0]:.0f}–{top['entry_zone'][1]:.0f}"
                  f"  |  SL: Rs {top['stop_loss']:.0f}"
                  f"  |  T1: Rs {top['target_1']:.0f}"
                  f"  |  R:R {top['rr_ratio']:.1f}:1"
                  f"  |  Confidence: {top['confidence']:.0f}%")
        else:
            print("\n  ℹ️  No swing trade candidates passed all filters today.")

    if ranking_data:
        ranked = ranking_data.get("ranked", [])
        hotlist = ranking_data.get("hotlist", [])
        tiers = ranking_data.get("tiers", {})
        print(f"  🔢 Stocks ranked: {len(ranked)}")
        print(f"  🎯 Hotlist: {len(hotlist)}")
        print(f"     🔥 PRIME: {tiers.get('PRIME',0)} | ✅ STRONG: {tiers.get('STRONG',0)}"
              f" | 👀 WATCH: {tiers.get('WATCH',0)}")
        if hotlist:
            h = hotlist[0]
            print(f"\n  🏆 Top hotlist: {h['symbol']} — score {h['universal_score']:.0f}"
                  f" — {h.get('setup_type','')}")

    print(f"\n  📄 Report: file:///{filepath.replace(os.sep, '/')}")
    print("=" * 62)
    return filepath


if __name__ == "__main__":
    main()
