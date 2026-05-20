"""
Floorsheet data collector.

Fetches all floorsheet transactions from the running FastAPI server
(GET /Floorsheet) and upserts them into the floorsheet_transactions
table. Logs progress to system_logs and records run metadata in
collection_runs.
"""

import json
import logging
import time
from datetime import datetime

import httpx

from db.config import get_connection

logger = logging.getLogger(__name__)

# Batch size for DB inserts
BATCH_SIZE = 500

# Base URL reused across collector methods
API_BASE_URL = "http://localhost:8000"


class FloorsheetCollector:
    """Collect floorsheet data and store it in the database."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self) -> dict:
        """Run a full floorsheet collection cycle.

        Returns a summary dict with keys:
            records_collected, records_inserted, records_updated,
            records_failed, trading_date, duration_seconds, status
        """
        start = time.time()
        summary = {
            "records_collected": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "records_failed": 0,
            "trading_date": None,
            "status": "started",
            "error_message": None,
        }

        await self._log_system("INFO", "Floorsheet collection started")

        try:
            # 1. Fetch data from the REST API
            records = await self._fetch_floorsheet()
            summary["records_collected"] = len(records)

            if not records:
                summary["status"] = "completed"
                summary["duration_seconds"] = round(time.time() - start, 2)
                await self._log_system("INFO", "No floorsheet records returned by API")
                await self._save_collection_run(summary)
                return summary

            # Derive trading date from the first record
            trading_date = self._parse_date(records[0].get("businessDate", ""))
            summary["trading_date"] = str(trading_date) if trading_date else None

            await self._log_system(
                "INFO",
                f"Fetched {len(records)} records for trading date {summary['trading_date']}",
            )

            # 2. Upsert into floorsheet_transactions in batches
            for batch_start in range(0, len(records), BATCH_SIZE):
                batch = records[batch_start : batch_start + BATCH_SIZE]
                batch_num = batch_start // BATCH_SIZE + 1
                try:
                    inserted, updated = await self._upsert_batch(batch, trading_date)
                    summary["records_inserted"] += inserted
                    summary["records_updated"] += updated
                except Exception as exc:
                    summary["records_failed"] += len(batch)
                    logger.error("Batch %d failed: %s", batch_num, exc)
                    await self._log_system(
                        "ERROR",
                        f"Batch {batch_num} failed: {exc}",
                    )

                if batch_num % 5 == 0 or batch_start + BATCH_SIZE >= len(records):
                    await self._log_system(
                        "INFO",
                        f"Progress: {min(batch_start + BATCH_SIZE, len(records))}/{len(records)} records processed",
                    )

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
            logger.exception("Floorsheet collection failed")
            await self._log_system("ERROR", f"Collection failed: {exc}")

        summary["duration_seconds"] = round(time.time() - start, 2)
        await self._save_collection_run(summary)
        await self._log_system(
            "INFO",
            f"Collection finished — status={summary['status']}, "
            f"collected={summary['records_collected']}, "
            f"inserted={summary['records_inserted']}, "
            f"updated={summary['records_updated']}, "
            f"failed={summary['records_failed']}, "
            f"duration={summary['duration_seconds']}s",
        )
        return summary

    # ------------------------------------------------------------------
    # API fetch
    # ------------------------------------------------------------------

    async def _fetch_floorsheet(self) -> list[dict]:
        """Fetch all floorsheet data from the REST API.

        The underlying AsyncNepse.getFloorSheet() handles NEPSE pagination
        internally, so the /Floorsheet endpoint returns the complete dataset.
        """
        url = f"{self.base_url}/Floorsheet"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, list):
            return data
        # Defensive: handle unexpected wrapper objects
        if isinstance(data, dict):
            # Some API versions wrap in {"floorsheets": [...]}
            for key in ("floorsheets", "data", "content"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data]
        return []

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _upsert_batch(self, batch: list[dict], trading_date) -> tuple[int, int]:
        """Upsert a batch of records. Returns (inserted, updated) counts."""
        sql = """
            INSERT INTO floorsheet_transactions (
                contract_id, trade_book_id, trading_date, collection_timestamp,
                symbol, security_id, security_name,
                buyer_broker_id, buyer_broker_name,
                seller_broker_id, seller_broker_name,
                quantity, rate, amount
            ) VALUES (
                %s, %s, %s, NOW(),
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                trade_book_id      = VALUES(trade_book_id),
                collection_timestamp = NOW(),
                symbol             = VALUES(symbol),
                security_id        = VALUES(security_id),
                security_name      = VALUES(security_name),
                buyer_broker_id    = VALUES(buyer_broker_id),
                buyer_broker_name  = VALUES(buyer_broker_name),
                seller_broker_id   = VALUES(seller_broker_id),
                seller_broker_name = VALUES(seller_broker_name),
                quantity           = VALUES(quantity),
                rate               = VALUES(rate),
                amount             = VALUES(amount)
        """

        rows = []
        for rec in batch:
            rows.append((
                rec.get("contractId"),
                rec.get("tradeBookId"),
                self._parse_date(rec.get("businessDate", "")),
                rec.get("stockSymbol", ""),
                rec.get("stockId"),
                rec.get("securityName", ""),
                self._parse_broker_id(rec.get("buyerMemberId", "")),
                rec.get("buyerBrokerName", ""),
                self._parse_broker_id(rec.get("sellerMemberId", "")),
                rec.get("sellerBrokerName", ""),
                rec.get("contractQuantity", 0),
                rec.get("contractRate", 0),
                rec.get("contractAmount", 0),
            ))

        inserted = 0
        updated = 0

        async with get_connection() as conn:
            async with conn.cursor() as cur:
                for row in rows:
                    await cur.execute(sql, row)
                    # affected_rows: 1 = inserted, 2 = updated (MySQL convention)
                    if cur.rowcount == 1:
                        inserted += 1
                    elif cur.rowcount == 2:
                        updated += 1

        return inserted, updated

    async def _save_collection_run(self, summary: dict) -> None:
        """Write a row to collection_runs capturing this run's outcome."""
        sql = """
            INSERT INTO collection_runs (
                trading_date, collection_type,
                records_collected, records_inserted, records_updated, records_failed,
                status, error_message, duration_seconds
            ) VALUES (%s, 'floorsheet', %s, %s, %s, %s, %s, %s, %s)
        """
        trading_date = summary.get("trading_date")
        # Use today if trading_date is unavailable
        if not trading_date:
            trading_date = datetime.now().strftime("%Y-%m-%d")

        params = (
            trading_date,
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
            VALUES (%s, 'floorsheet_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            # Fall back to Python logger if DB logging fails
            logger.error("System log write failed: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(date_str: str):
        """Parse a business date string into a date object.

        Handles formats like '2026-02-17T00:00:00' and '2026-02-17'.
        """
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str).date()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_broker_id(member_id) -> int:
        """Extract numeric broker ID from a member ID value."""
        if isinstance(member_id, int):
            return member_id
        if isinstance(member_id, str):
            # Strip non-digit characters (e.g. "broker_42" -> 42)
            digits = "".join(c for c in member_id if c.isdigit())
            return int(digits) if digits else 0
        return 0
