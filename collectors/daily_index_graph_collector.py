"""
NEPSE daily index graph data collector.

Fires all 17 graph endpoints concurrently via asyncio.gather() using a
single shared httpx.AsyncClient, then batch-upserts the data points into
the daily_index_graph table.

Each endpoint returns a list of [unix_time, index_value] arrays representing
intraday ticks for one index/sub-index.  The unique key on (index_id, unix_time)
ensures reruns safely refresh data in place.

Logs progress to system_logs and records run metadata in collection_runs.
"""

import asyncio
import json
import logging
import time
from datetime import datetime

import httpx

from db.config import get_connection

logger = logging.getLogger(__name__)

# Base URL of the FastAPI server
API_BASE_URL = "http://localhost:8000"

# index_id → (index_name, API path)
INDEX_ENDPOINTS = {
    1:  ("nepse_index",                "/DailyNepseIndexGraph"),
    2:  ("sensitive_index",            "/DailySensitiveIndexGraph"),
    3:  ("float_index",                "/DailyFloatIndexGraph"),
    4:  ("sensitive_float_index",      "/DailySensitiveFloatIndexGraph"),
    5:  ("banking_subindex",           "/DailyBankSubindexGraph"),
    6:  ("development_bank_subindex",  "/DailyDevelopmentBankSubindexGraph"),
    7:  ("finance_subindex",           "/DailyFinanceSubindexGraph"),
    8:  ("hotel_tourism_subindex",     "/DailyHotelTourismSubindexGraph"),
    9:  ("hydropower_subindex",        "/DailyHydroPowerSubindexGraph"),
    10: ("investment_subindex",        "/DailyInvestmentSubindexGraph"),
    11: ("life_insurance_subindex",    "/DailyLifeInsuranceSubindexGraph"),
    12: ("manufacturing_subindex",     "/DailyManufacturingProcessingSubindexGraph"),
    13: ("microfinance_subindex",      "/DailyMicrofinanceSubindexGraph"),
    14: ("mutual_fund_subindex",       "/DailyMutualFundSubindexGraph"),
    15: ("non_life_insurance_subindex", "/DailyNonLifeInsuranceSubindexGraph"),
    16: ("others_subindex",            "/DailyOthersSubindexGraph"),
    17: ("trading_subindex",           "/DailyTradingSubindexGraph"),
}

# Reverse lookup for --index argument
_NAME_TO_ID = {name: idx for idx, (name, _) in INDEX_ENDPOINTS.items()}


class DailyIndexGraphCollector:
    """Collect intraday index graph data for all NEPSE indices."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self, index_names: list[str] | None = None) -> dict:
        """Run a full daily-index-graph collection cycle.

        Args:
            index_names: List of index names to collect (e.g. ["nepse_index"]),
                         or None for all 17.

        Returns a summary dict with per-index counts and totals.
        """
        # Resolve which indices to fetch
        if index_names is None:
            indices = dict(INDEX_ENDPOINTS)
        else:
            indices = {}
            for name in index_names:
                idx = _NAME_TO_ID.get(name)
                if idx is not None:
                    indices[idx] = INDEX_ENDPOINTS[idx]
                else:
                    logger.warning("Unknown index name: %s", name)

        start = time.time()
        summary = {
            "records_collected": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "records_failed": 0,
            "indices_succeeded": 0,
            "indices_failed": 0,
            "per_index": {},
            "trading_date": datetime.now().strftime("%Y-%m-%d"),
            "status": "started",
            "error_message": None,
        }

        await self._log_system(
            "INFO",
            f"Daily index graph collection started ({len(indices)} indices)",
        )

        try:
            # 1. Fire all endpoints concurrently
            all_results, failed_names = await self._fetch_all(indices)

            summary["indices_failed"] = len(failed_names)

            # 2. Batch-upsert each index's data
            for index_id, index_name, rows in all_results:
                count = len(rows)
                summary["per_index"][index_name] = count
                summary["records_collected"] += count

                if not rows:
                    continue

                # Derive trading_date from first data point
                first_ts = rows[0][2]  # unix_time
                trading_date = datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d")
                summary["trading_date"] = trading_date

                try:
                    inserted, updated = await self._batch_upsert(rows)
                    summary["records_inserted"] += inserted
                    summary["records_updated"] += updated
                    summary["indices_succeeded"] += 1
                except Exception as exc:
                    summary["records_failed"] += count
                    summary["indices_failed"] += 1
                    logger.error("Batch upsert failed for %s: %s", index_name, exc)

            # 3. Determine final status
            if summary["indices_failed"] == 0:
                summary["status"] = "completed"
            elif summary["indices_succeeded"] > 0:
                summary["status"] = "partial"
                summary["error_message"] = f"Failed indices: {', '.join(failed_names)}"
            else:
                summary["status"] = "failed"
                summary["error_message"] = f"All indices failed: {', '.join(failed_names)}"

        except Exception as exc:
            summary["status"] = "failed"
            summary["error_message"] = str(exc)
            logger.exception("Daily index graph collection failed")
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

    async def _fetch_all(
        self, indices: dict[int, tuple[str, str]]
    ) -> tuple[list[tuple[int, str, list]], list[str]]:
        """Fetch all requested index endpoints concurrently.

        Returns:
            (list of (index_id, index_name, rows), list of failed_index_names)
            Each row is a tuple ready for DB insertion:
              (index_id, index_name, unix_time, index_value, trading_date)
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [
                self._fetch_one(client, index_id, index_name, path)
                for index_id, (index_name, path) in indices.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_data: list[tuple[int, str, list]] = []
        failed_names: list[str] = []

        for (index_id, (index_name, _)), result in zip(indices.items(), results):
            if isinstance(result, Exception):
                logger.error("Fetch failed for %s: %s", index_name, result)
                failed_names.append(index_name)
                continue
            all_data.append((index_id, index_name, result))

        return all_data, failed_names

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        index_id: int,
        index_name: str,
        path: str,
    ) -> list[tuple]:
        """Fetch a single graph endpoint and map data points to DB rows.

        Each API data point is [unix_time, index_value].
        """
        resp = await client.get(f"{self.base_url}{path}")
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list):
            return []

        rows = []
        for point in data:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            unix_time = int(point[0])
            index_value = point[1]
            trading_date = datetime.fromtimestamp(unix_time).strftime("%Y-%m-%d")
            rows.append((index_id, index_name, unix_time, index_value, trading_date))

        return rows

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _batch_upsert(self, rows: list[tuple]) -> tuple[int, int]:
        """Batch-upsert graph data points using executemany.

        Returns (inserted_count, updated_count).
        """
        sql = """
            INSERT INTO daily_index_graph (
                index_id, index_name, unix_time, index_value, trading_date
            ) VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                index_value = VALUES(index_value),
                index_name  = VALUES(index_name)
        """
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(sql, rows)
                # executemany rowcount: 1 per insert, 2 per update
                total_affected = cur.rowcount
                # Estimate: if total_affected > len(rows), some were updates
                # Each insert contributes 1, each update contributes 2
                # inserted + 2*updated = total_affected
                # inserted + updated = len(rows)
                # → updated = total_affected - len(rows)
                updated = max(0, total_affected - len(rows))
                inserted = len(rows) - updated
                return inserted, updated

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
            VALUES (%s, 'daily_index_graph_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            logger.error("System log write failed: %s", exc)
