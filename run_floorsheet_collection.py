#!/usr/bin/env python3
"""
Runner script for floorsheet data collection.

Usage:
    python run_floorsheet_collection.py

Initializes the database pool, runs the floorsheet collector, prints
a summary to stdout, and ensures the pool is closed on exit.
"""

import asyncio
import logging
import sys

from db.config import init_pool, close_pool
from collectors.floorsheet_collector import FloorsheetCollector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> int:
    """Run the floorsheet collection pipeline."""
    try:
        logger.info("Initializing database connection pool...")
        await init_pool()
    except Exception as exc:
        logger.error("Failed to connect to the database: %s", exc)
        print(f"\n✗ Database connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        collector = FloorsheetCollector()
        logger.info("Starting floorsheet collection...")
        summary = await collector.collect()

        # Print clean summary to stdout
        print("\n" + "=" * 50)
        print("  FLOORSHEET COLLECTION SUMMARY")
        print("=" * 50)
        print(f"  Trading Date     : {summary.get('trading_date', 'N/A')}")
        print(f"  Status           : {summary['status']}")
        print(f"  Records Collected: {summary['records_collected']}")
        print(f"  Records Inserted : {summary['records_inserted']}")
        print(f"  Records Updated  : {summary['records_updated']}")
        print(f"  Records Failed   : {summary['records_failed']}")
        print(f"  Duration         : {summary.get('duration_seconds', 0)}s")
        if summary.get("error_message"):
            print(f"  Error            : {summary['error_message']}")
        print("=" * 50 + "\n")

        return 0 if summary["status"] == "completed" else 1

    except Exception as exc:
        logger.exception("Unhandled error during collection")
        print(f"\n✗ Collection failed: {exc}", file=sys.stderr)
        return 1

    finally:
        logger.info("Closing database connection pool...")
        await close_pool()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
