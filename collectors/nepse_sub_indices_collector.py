"""
NEPSE sub-indices data collector.

Fetches the current sub-indices snapshot from the FastAPI server
(GET /NepseSubIndices) and inserts it into the nepse_sub_indices table.
Each run creates a new set of rows representing a point-in-time snapshot.

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


class NepseSubIndicesCollector:
    """Collect NEPSE sub-indices snapshot data."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self) -> dict:
        """Run a full sub-indices collection cycle.

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

        await self._log_system("INFO", "NEPSE sub-indices collection started")

        try:
            # 1. Fetch sub-indices from the REST API
            records = await self._fetch_sub_indices()
            summary["records_collected"] = len(records)

            if not records:
                summary["status"] = "completed"
                summary["duration_seconds"] = round(time.time() - start, 2)
                await self._log_system("INFO", "No sub-indices records returned by API")
                await self._save_collection_run(summary)
                return summary

            await self._log_system(
                "INFO",
                f"Fetched {len(records)} sub-indices from API",
            )

            # 2. Insert all records
            for rec in records:
                try:
                    await self._insert_record(rec)
                    summary["records_inserted"] += 1
                except Exception as exc:
                    summary["records_failed"] += 1
                    logger.error("Insert failed for %s: %s", rec.get("index_name"), exc)

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
            logger.exception("NEPSE sub-indices collection failed")
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

    async def _fetch_sub_indices(self) -> list[dict]:
        """Fetch all sub-indices from the NepseSubIndices endpoint.

        The API returns a dict keyed by index name. Each value has:
        id, index, change, perChange, currentValue.
        We flatten this into a list of mapped dicts for insertion.
        """
        url = f"{self.base_url}/NepseSubIndices"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        # Response is a dict: {"Microfinance Index": {id, index, change, ...}, ...}
        if isinstance(data, dict):
            return [
                {
                    "sub_index_id": item.get("id"),
                    "index_name": item.get("index", key),
                    "points_change": item.get("change", 0),
                    "percent_change": item.get("perChange", 0),
                    "current_value": item.get("currentValue", 0),
                }
                for key, item in data.items()
                if isinstance(item, dict)
            ]
        # Defensive: handle list format
        if isinstance(data, list):
            return [
                {
                    "sub_index_id": item.get("id"),
                    "index_name": item.get("index", ""),
                    "points_change": item.get("change", 0),
                    "percent_change": item.get("perChange", 0),
                    "current_value": item.get("currentValue", 0),
                }
                for item in data
                if isinstance(item, dict)
            ]
        return []

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _insert_record(self, rec: dict) -> None:
        """Insert a single sub-index record (plain INSERT, no upsert)."""
        sql = """
            INSERT INTO nepse_sub_indices (
                sub_index_id, index_name, points_change,
                percent_change, current_value
            ) VALUES (%s, %s, %s, %s, %s)
        """
        params = (
            rec["sub_index_id"],
            rec["index_name"],
            rec["points_change"],
            rec["percent_change"],
            rec["current_value"],
        )
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)

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
            VALUES (%s, 'nepse_sub_indices_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            logger.error("System log write failed: %s", exc)
