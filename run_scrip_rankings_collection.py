#!/usr/bin/env python3
"""
Runner script for NEPSE scrip rankings data collection.

Usage:
    python run_scrip_rankings_collection.py                          # all three
    python run_scrip_rankings_collection.py --category trade         # trade only
    python run_scrip_rankings_collection.py --category turnover      # turnover only
    python run_scrip_rankings_collection.py --category transaction   # transactions only

Initializes the database pool, runs the scrip rankings collector,
prints a summary to stdout, and ensures the pool is closed on exit.
"""

import argparse
import asyncio
import logging
import sys

from db.config import init_pool, close_pool
from collectors.scrip_rankings_collector import ScripRankingsCollector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Collect NEPSE scrip rankings data")
    parser.add_argument(
        "--category",
        choices=["trade", "turnover", "transaction"],
        default=None,
        help="Collect only one category (default: all three)",
    )
    return parser.parse_args()


async def main(categories: list[str] | None) -> int:
    """Run the NEPSE scrip rankings collection pipeline."""
    try:
        logger.info("Initializing database connection pool...")
        await init_pool()
    except Exception as exc:
        logger.error("Failed to connect to the database: %s", exc)
        print(f"\n✗ Database connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        collector = ScripRankingsCollector()
        logger.info("Starting NEPSE scrip rankings collection...")
        summary = await collector.collect(categories=categories)

        # Print clean summary to stdout
        print("\n" + "=" * 55)
        print("  NEPSE SCRIP RANKINGS COLLECTION SUMMARY")
        print("=" * 55)
        print(f"  Trading Date         : {summary.get('trading_date', 'N/A')}")
        print(f"  Status               : {summary['status']}")
        print(f"  Trade Collected      : {summary['trade_collected']}")
        print(f"  Turnover Collected   : {summary['turnover_collected']}")
        print(f"  Transaction Collected: {summary['transaction_collected']}")
        print(f"  Total Collected      : {summary['records_collected']}")
        print(f"  Records Inserted     : {summary['records_inserted']}")
        print(f"  Records Updated      : {summary['records_updated']}")
        print(f"  Records Failed       : {summary['records_failed']}")
        print(f"  Duration             : {summary.get('duration_seconds', 0)}s")
        if summary.get("error_message"):
            print(f"  Error                : {summary['error_message']}")
        print("=" * 55 + "\n")

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
    cats = [args.category] if args.category else None
    raise SystemExit(asyncio.run(main(cats)))
