"""
NEPSE top movers (gainers & losers) data collector.

Fetches the top gainers and top losers from the FastAPI server
(GET /TopGainers and GET /TopLosers) concurrently, then upserts
them into the top_movers table tagged by mover_type.

The unique key on (trading_date, mover_type, security_id) ensures
reruns safely refresh the list in place.

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


class TopMoversCollector:
    """Collect daily NEPSE top gainers and losers data."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self, mover_types: list[str] | None = None) -> dict:
        """Run a full top-movers collection cycle.

        Args:
            mover_types: List of types to collect, e.g. ["gainer"],
                         ["loser"], or ["gainer", "loser"].
                         Defaults to both if None.

        Returns a summary dict with keys:
            records_collected, records_inserted, records_updated,
            records_failed, trading_date, duration_seconds, status,
            gainers_collected, losers_collected
        """
        if mover_types is None:
            mover_types = ["gainer", "loser"]

        start = time.time()
        summary = {
            "records_collected": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "records_failed": 0,
            "gainers_collected": 0,
            "losers_collected": 0,
            "trading_date": datetime.now().strftime("%Y-%m-%d"),
            "status": "started",
            "error_message": None,
        }

        await self._log_system("INFO", f"Top movers collection started (types={mover_types})")

        try:
            # 1. Fetch data from the REST API
            all_records, trading_date = await self._fetch_movers(mover_types)
            summary["trading_date"] = trading_date

            if not all_records:
                summary["status"] = "completed"
                summary["duration_seconds"] = round(time.time() - start, 2)
                await self._log_system("INFO", "No top-mover records returned by API")
                await self._save_collection_run(summary)
                return summary

            # Count by type
            for rec in all_records:
                if rec["mover_type"] == "gainer":
                    summary["gainers_collected"] += 1
                else:
                    summary["losers_collected"] += 1
            summary["records_collected"] = len(all_records)

            await self._log_system(
                "INFO",
                f"Fetched {summary['gainers_collected']} gainers, "
                f"{summary['losers_collected']} losers for {trading_date}",
            )

            # 2. Upsert all records
            for rec in all_records:
                try:
                    was_insert = await self._upsert_record(rec)
                    if was_insert:
                        summary["records_inserted"] += 1
                    else:
                        summary["records_updated"] += 1
                except Exception as exc:
                    summary["records_failed"] += 1
                    logger.error(
                        "Upsert failed for %s %s: %s",
                        rec.get("mover_type"),
                        rec.get("symbol"),
                        exc,
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
            logger.exception("Top movers collection failed")
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

    async def _fetch_movers(self, mover_types: list[str]) -> tuple[list[dict], str]:
        """Fetch top gainers and/or losers concurrently.

        Returns (list_of_mapped_records, trading_date_str).
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Build tasks for requested types
            tasks = []
            if "gainer" in mover_types:
                tasks.append(self._fetch_one(client, "/TopGainers", "gainer"))
            if "loser" in mover_types:
                tasks.append(self._fetch_one(client, "/TopLosers", "loser"))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Fetch trading date from /IsNepseOpen
            trading_date = await self._fetch_trading_date(client)

        # Flatten and tag with trading_date
        all_records: list[dict] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Fetch failed: %s", result)
                raise result
            for rec in result:
                rec["trading_date"] = trading_date
                all_records.append(rec)

        return all_records, trading_date

    async def _fetch_one(self, client: httpx.AsyncClient, path: str, mover_type: str) -> list[dict]:
        """Fetch a single endpoint and map its records."""
        resp = await client.get(f"{self.base_url}{path}")
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list):
            return []

        return [self._map_record(item, mover_type) for item in data if isinstance(item, dict)]

    async def _fetch_trading_date(self, client: httpx.AsyncClient) -> str:
        """Get the trading date from /IsNepseOpen, falling back to today."""
        trading_date = datetime.now().strftime("%Y-%m-%d")
        try:
            resp = await client.get(f"{self.base_url}/IsNepseOpen")
            resp.raise_for_status()
            as_of = resp.json().get("asOf", "")
            if as_of and len(as_of) >= 10:
                trading_date = as_of[:10]
        except Exception as exc:
            logger.warning("Could not fetch trading date from /IsNepseOpen: %s", exc)
        return trading_date

    # ------------------------------------------------------------------
    # Response mapping
    # ------------------------------------------------------------------

    def _map_record(self, item: dict, mover_type: str) -> dict:
        """Map a single API item to database column names.

        API structure:
            securityId, symbol, securityName, ltp, cp,
            pointChange, percentageChange
        """
        return {
            "mover_type": mover_type,
            "security_id": item.get("securityId"),
            "symbol": item.get("symbol", ""),
            "security_name": item.get("securityName", ""),
            "ltp": item.get("ltp"),
            "previous_close": item.get("cp"),
            "point_change": item.get("pointChange"),
            "percent_change": item.get("percentageChange"),
        }

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _upsert_record(self, rec: dict) -> bool:
        """Upsert a single top-mover record.

        Uses INSERT … ON DUPLICATE KEY UPDATE on
        (trading_date, mover_type, security_id).
        Returns True if inserted, False if updated.
        """
        sql = """
            INSERT INTO top_movers (
                trading_date, mover_type, security_id, symbol,
                security_name, ltp, previous_close,
                point_change, percent_change
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                symbol         = VALUES(symbol),
                security_name  = VALUES(security_name),
                ltp            = VALUES(ltp),
                previous_close = VALUES(previous_close),
                point_change   = VALUES(point_change),
                percent_change = VALUES(percent_change)
        """
        row = (
            rec["trading_date"],
            rec["mover_type"],
            rec["security_id"],
            rec["symbol"],
            rec["security_name"],
            rec["ltp"],
            rec["previous_close"],
            rec["point_change"],
            rec["percent_change"],
        )
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, row)
                return cur.rowcount == 1

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
            VALUES (%s, 'top_movers_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            logger.error("System log write failed: %s", exc)
