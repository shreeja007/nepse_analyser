#!/usr/bin/env python3
"""
Runner script for trade/turnover/transaction sub-indices data collection.

Usage:
    python run_trade_turnover_subindices_collection.py

Initializes the database pool, runs the collector, prints a summary
to stdout, and ensures the pool is closed on exit.
"""

import asyncio
import logging
import sys

from db.config import init_pool, close_pool
from collectors.trade_turnover_subindices_collector import TradeTurnoverSubindicesCollector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> int:
    """Run the trade-turnover-transaction collection pipeline."""
    try:
        logger.info("Initializing database connection pool...")
        await init_pool()
    except Exception as exc:
        logger.error("Failed to connect to the database: %s", exc)
        print(f"\n✗ Database connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        collector = TradeTurnoverSubindicesCollector()
        logger.info("Starting trade turnover subindices collection...")
        summary = await collector.collect()

        # Print clean summary to stdout
        print("\n" + "=" * 60)
        print("  TRADE TURNOVER/TRANSACTION SUBINDICES COLLECTION SUMMARY")
        print("=" * 60)
        print(f"  Trading Date      : {summary.get('trading_date', 'N/A')}")
        print(f"  Status            : {summary['status']}")
        print(f"  Records Collected : {summary['records_collected']}")
        print(f"  Records Inserted  : {summary['records_inserted']}")
        print(f"  Records Failed    : {summary['records_failed']}")
        print(f"  Duration          : {summary.get('duration_seconds', 0)}s")
        if summary.get("error_message"):
            print(f"  Error             : {summary['error_message']}")
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
    raise SystemExit(asyncio.run(main()))
