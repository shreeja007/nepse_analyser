"""
Trade/turnover/transaction sub-indices data collector.

Fetches a point-in-time snapshot of per-scrip trade details from the
FastAPI server (GET /TradeTurnoverTransactionSubindices) and inserts
them into the daily_trade_turnover_transaction_subindices table.

Each collection run creates a new set of rows representing a snapshot.

Logs progress to system_logs and records run metadata in collection_runs.
"""

import json
import logging
import time
from datetime import datetime

import httpx

from db.config import get_connection

logger = logging.getLogger(__name__)

# Base URL of the FastAPI server
API_BASE_URL = "http://localhost:8000"

# DB batch size for inserts
BATCH_SIZE = 200


class TradeTurnoverSubindicesCollector:
    """Collect trade/turnover/transaction sub-indices snapshot data."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self) -> dict:
        """Run a full trade-turnover-transaction collection cycle.

        Returns a summary dict with keys:
            records_collected, records_inserted, records_failed,
            trading_date, duration_seconds, status
        """
        start = time.time()
        summary = {
            "records_collected": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "records_failed": 0,
            "trading_date": datetime.now().strftime("%Y-%m-%d"),
            "status": "started",
            "error_message": None,
        }

        await self._log_system("INFO", "Trade turnover subindices collection started")

        try:
            # 1. Fetch data from the REST API
            records = await self._fetch_data()
            summary["records_collected"] = len(records)

            if not records:
                summary["status"] = "completed"
                summary["duration_seconds"] = round(time.time() - start, 2)
                await self._log_system("INFO", "No records returned by API")
                await self._save_collection_run(summary)
                return summary

            await self._log_system(
                "INFO",
                f"Fetched {len(records)} scrip records from API",
            )

            # 2. Insert in batches
            for batch_start in range(0, len(records), BATCH_SIZE):
                batch = records[batch_start : batch_start + BATCH_SIZE]
                try:
                    inserted = await self._insert_batch(batch)
                    summary["records_inserted"] += inserted
                except Exception as exc:
                    summary["records_failed"] += len(batch)
                    logger.error("Batch insert failed: %s", exc)

            # 3. Determine final status
            if summary["records_failed"] == 0:
                summary["status"] = "completed"
            elif summary["records_failed"] < summary["records_collected"]:
                summary["status"] = "partial"
            else:
                summary["status"] = "failed"

        except Exception as exc:
            summary["status"] = "failed"
            summary["error_message"] = str(exc)
            logger.exception("Trade turnover subindices collection failed")
            await self._log_system("ERROR", f"Collection failed: {exc}")

        summary["duration_seconds"] = round(time.time() - start, 2)
        await self._save_collection_run(summary)
        await self._log_system(
            "INFO",
            f"Collection finished — status={summary['status']}, "
            f"collected={summary['records_collected']}, "
            f"inserted={summary['records_inserted']}, "
            f"failed={summary['records_failed']}, "
            f"duration={summary['duration_seconds']}s",
        )
        return summary

    # ------------------------------------------------------------------
    # API fetch
    # ------------------------------------------------------------------

    async def _fetch_data(self) -> list[dict]:
        """Fetch trade/turnover/transaction data from the API.

        The API returns {"scripsDetails": {symbol: {...}, ...}, "sectorsDetails": {...}}.
        We extract the per-scrip records from scripsDetails and map them
        to database columns.
        """
        url = f"{self.base_url}/TradeTurnoverTransactionSubindices"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        scrips = data.get("scripsDetails", {}) if isinstance(data, dict) else {}
        records = []

        for _key, item in scrips.items():
            if not isinstance(item, dict):
                continue
            records.append({
                "symbol": item.get("symbol", ""),
                "sector": item.get("sector"),
                "name": item.get("name"),
                "category": item.get("category"),
                "turnover": item.get("Turnover", 0),
                "transaction_count": item.get("transaction", 0),
                "volume": item.get("volume", 0),
                "ltp": item.get("ltp", 0),
                "previous_close": item.get("previousClose", 0),
                "point_change": item.get("pointChange", 0),
                "percent_change": item.get("percentageChange", 0),
                "last_updated_time": item.get("lastUpdatedDateTime", 0),
            })

        return records

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _insert_batch(self, batch: list[dict]) -> int:
        """Insert a batch of records. Returns the number of rows inserted."""
        sql = """
            INSERT INTO daily_trade_turnover_transaction_subindices (
                symbol, sector, name, category,
                turnover, transaction_count, volume, ltp,
                previous_close, point_change, percent_change,
                last_updated_time
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        rows = [
            (
                rec["symbol"], rec["sector"], rec["name"], rec["category"],
                rec["turnover"], rec["transaction_count"], rec["volume"], rec["ltp"],
                rec["previous_close"], rec["point_change"], rec["percent_change"],
                rec["last_updated_time"],
            )
            for rec in batch
        ]

        inserted = 0
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                for row in rows:
                    await cur.execute(sql, row)
                    inserted += cur.rowcount

        return inserted

    async def _save_collection_run(self, summary: dict) -> None:
        """Write a row to collection_runs capturing this run's outcome."""
        sql = """
            INSERT INTO collection_runs (
                trading_date, collection_type,
                records_collected, records_inserted, records_updated, records_failed,
                status, error_message, duration_seconds
            ) VALUES (%s, 'daily_summary', %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            summary["trading_date"],
            summary["records_collected"],
            summary["records_inserted"],
            summary["records_updated"],
            summary["records_failed"],
            summary["status"],
            summary.get("error_message"),
            summary.get("duration_seconds"),
        )
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, params)
        except Exception as exc:
            logger.error("Failed to save collection run: %s", exc)

    # ------------------------------------------------------------------
    # System logging
    # ------------------------------------------------------------------

    async def _log_system(self, level: str, message: str, context: dict | None = None) -> None:
        """Insert a row into system_logs."""
        sql = """
            INSERT INTO system_logs (log_level, component, message, context)
            VALUES (%s, 'trade_turnover_subindices_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            logger.error("System log write failed: %s", exc)
