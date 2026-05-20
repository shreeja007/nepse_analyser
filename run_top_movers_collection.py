#!/usr/bin/env python3
"""
Runner script for NEPSE top movers (gainers & losers) data collection.

Usage:
    python run_top_movers_collection.py              # both gainers and losers
    python run_top_movers_collection.py --type gainer # gainers only
    python run_top_movers_collection.py --type loser  # losers only

Initializes the database pool, runs the top movers collector, prints
a summary to stdout, and ensures the pool is closed on exit.
"""

import argparse
import asyncio
import logging
import sys

from db.config import init_pool, close_pool
from collectors.top_movers_collector import TopMoversCollector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Collect NEPSE top movers data")
    parser.add_argument(
        "--type",
        choices=["gainer", "loser"],
        default=None,
        help="Collect only gainers or only losers (default: both)",
    )
    return parser.parse_args()


async def main(mover_types: list[str] | None) -> int:
    """Run the NEPSE top movers collection pipeline."""
    try:
        logger.info("Initializing database connection pool...")
        await init_pool()
    except Exception as exc:
        logger.error("Failed to connect to the database: %s", exc)
        print(f"\n✗ Database connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        collector = TopMoversCollector()
        logger.info("Starting NEPSE top movers collection...")
        summary = await collector.collect(mover_types=mover_types)

        # Print clean summary to stdout
        print("\n" + "=" * 55)
        print("  NEPSE TOP MOVERS COLLECTION SUMMARY")
        print("=" * 55)
        print(f"  Trading Date      : {summary.get('trading_date', 'N/A')}")
        print(f"  Status            : {summary['status']}")
        print(f"  Gainers Collected : {summary['gainers_collected']}")
        print(f"  Losers Collected  : {summary['losers_collected']}")
        print(f"  Total Collected   : {summary['records_collected']}")
        print(f"  Records Inserted  : {summary['records_inserted']}")
        print(f"  Records Updated   : {summary['records_updated']}")
        print(f"  Records Failed    : {summary['records_failed']}")
        print(f"  Duration          : {summary.get('duration_seconds', 0)}s")
        if summary.get("error_message"):
            print(f"  Error             : {summary['error_message']}")
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
    types = [args.type] if args.type else None
    raise SystemExit(asyncio.run(main(types)))
