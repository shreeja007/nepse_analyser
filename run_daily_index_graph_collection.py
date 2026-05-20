#!/usr/bin/env python3
"""
Runner script for NEPSE daily index graph data collection.

Usage:
    python run_daily_index_graph_collection.py                        # all 17 indices
    python run_daily_index_graph_collection.py --index nepse_index    # one index only
    python run_daily_index_graph_collection.py --index banking_subindex

Initializes the database pool, runs the daily index graph collector,
prints a summary to stdout, and ensures the pool is closed on exit.
"""

import argparse
import asyncio
import logging
import sys

from db.config import init_pool, close_pool
from collectors.daily_index_graph_collector import (
    DailyIndexGraphCollector,
    INDEX_ENDPOINTS,
    _NAME_TO_ID,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Valid index names for the CLI
_VALID_NAMES = sorted(_NAME_TO_ID.keys())


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Collect NEPSE daily index graph data")
    parser.add_argument(
        "--index",
        choices=_VALID_NAMES,
        default=None,
        help="Collect only one index (default: all 17)",
    )
    return parser.parse_args()


async def main(index_names: list[str] | None) -> int:
    """Run the NEPSE daily index graph collection pipeline."""
    try:
        logger.info("Initializing database connection pool...")
        await init_pool()
    except Exception as exc:
        logger.error("Failed to connect to the database: %s", exc)
        print(f"\n✗ Database connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        collector = DailyIndexGraphCollector()
        logger.info("Starting NEPSE daily index graph collection...")
        summary = await collector.collect(index_names=index_names)

        # Print clean summary to stdout
        print("\n" + "=" * 60)
        print("  NEPSE DAILY INDEX GRAPH COLLECTION SUMMARY")
        print("=" * 60)
        print(f"  Trading Date       : {summary.get('trading_date', 'N/A')}")
        print(f"  Status             : {summary['status']}")
        print(f"  Indices Succeeded  : {summary['indices_succeeded']}")
        print(f"  Indices Failed     : {summary['indices_failed']}")
        print(f"  Total Collected    : {summary['records_collected']}")
        print(f"  Records Inserted   : {summary['records_inserted']}")
        print(f"  Records Updated    : {summary['records_updated']}")
        print(f"  Records Failed     : {summary['records_failed']}")
        print(f"  Duration           : {summary.get('duration_seconds', 0)}s")

        # Per-index breakdown
        per_index = summary.get("per_index", {})
        if per_index:
            print("  " + "-" * 42)
            print("  Per-index data points:")
            for name, count in sorted(per_index.items()):
                print(f"    {name:<35s}: {count}")

        if summary.get("error_message"):
            print(f"  Error              : {summary['error_message']}")
        print("=" * 60 + "\n")

        return 0 if summary["status"] == "completed" else 1

    except Exception as exc:
        logger.exception("Unhandled error during collection")
        print(f"\n✗ Collection failed: {exc}", file=sys.stderr)
        return 1

    finally:
        logger.info("Closing database connection pool...")
        await close_pool()


if __name__ == "__main__":
    args = parse_args()
    names = [args.index] if args.index else None
    raise SystemExit(asyncio.run(main(names)))
