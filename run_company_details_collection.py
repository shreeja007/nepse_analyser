#!/usr/bin/env python3
"""
Runner script for company details data collection.

Usage:
    python run_company_details_collection.py              # all symbols
    python run_company_details_collection.py --symbol NABIL  # single symbol

Initializes the database pool, runs the company details collector,
prints a summary to stdout, and ensures the pool is closed on exit.
"""

import argparse
import asyncio
import logging
import sys

from db.config import init_pool, close_pool
from collectors.company_details_collector import CompanyDetailsCollector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main(symbol: str | None = None) -> int:
    """Run the company details collection pipeline."""
    try:
        logger.info("Initializing database connection pool...")
        await init_pool()
    except Exception as exc:
        logger.error("Failed to connect to the database: %s", exc)
        print(f"\n✗ Database connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        collector = CompanyDetailsCollector()
        mode = f"symbol={symbol}" if symbol else "all symbols"
        logger.info("Starting company details collection (%s)...", mode)
        summary = await collector.collect(symbol=symbol)

        # Print clean summary to stdout
        print("\n" + "=" * 55)
        print("  COMPANY DETAILS COLLECTION SUMMARY")
        print("=" * 55)
        print(f"  Trading Date      : {summary.get('trading_date', 'N/A')}")
        print(f"  Status            : {summary['status']}")
        print(f"  Symbols Processed : {summary['symbols_processed']}")
        print(f"  Symbols Failed    : {summary['symbols_failed']}")
        print(f"  Records Collected : {summary['records_collected']}")
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
    parser = argparse.ArgumentParser(
        description="Collect company details from the NEPSE API."
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Optional: run for a single symbol (e.g. NABIL) instead of all.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(symbol=args.symbol)))
