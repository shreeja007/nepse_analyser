"""
NEPSE market summary data collector.

Fetches the daily market summary from the FastAPI server
(GET /Summary) and upserts it into the market_summary table.
The unique key on trading_date ensures one row per trading day;
reruns on the same day safely update the existing row.

Trading date is obtained from GET /IsNepseOpen (asOf field),
falling back to datetime.now() if unavailable.

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

# API response key → database column mapping
_FIELD_MAP = {
    "Total Turnover Rs:": "total_turnover",
    "Total Traded Shares": "total_traded_shares",
    "Total Transactions": "total_transactions",
    "Total Scrips Traded": "total_scrips_traded",
    "Total Market Capitalization Rs:": "total_market_cap",
    "Total Float Market Capitalization Rs:": "total_float_market_cap",
}


class MarketSummaryCollector:
    """Collect daily NEPSE market summary data."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self) -> dict:
        """Run a full market-summary collection cycle.

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
            "trading_date": datetime.now().strftime("%Y-%m-%d"),
            "status": "started",
            "error_message": None,
        }

        await self._log_system("INFO", "Market summary collection started")

        try:
            # 1. Fetch summary + trading date from the REST API
            raw_summary, trading_date = await self._fetch_summary()
            summary["trading_date"] = trading_date

            if not raw_summary:
                summary["status"] = "completed"
                summary["duration_seconds"] = round(time.time() - start, 2)
                await self._log_system("INFO", "No summary data returned by API")
                await self._save_collection_run(summary)
                return summary

            summary["records_collected"] = 1

            # 2. Map API fields to DB columns
            record = self._map_response(raw_summary, trading_date)

            await self._log_system(
                "INFO",
                f"Fetched market summary for {trading_date}",
                {"trading_date": trading_date},
            )

            # 3. Upsert the record
            was_insert = await self._upsert_record(record)
            if was_insert:
                summary["records_inserted"] = 1
            else:
                summary["records_updated"] = 1

            summary["status"] = "completed"

        except Exception as exc:
            summary["status"] = "failed"
            summary["records_failed"] = max(summary["records_collected"], 1)
            summary["error_message"] = str(exc)
            logger.exception("Market summary collection failed")
            await self._log_system("ERROR", f"Collection failed: {exc}")

        summary["duration_seconds"] = round(time.time() - start, 2)
        await self._save_collection_run(summary)
        await self._log_system(
            "INFO",
            f"Collection finished — status={summary['status']}, "
            f"collected={summary['records_collected']}, "
            f"inserted={summary['records_inserted']}, "
            f"updated={summary['records_updated']}, "
            f"duration={summary['duration_seconds']}s",
        )
        return summary

    # ------------------------------------------------------------------
    # API fetch
    # ------------------------------------------------------------------

    async def _fetch_summary(self) -> tuple[dict, str]:
        """Fetch market summary and trading date from the API.

        Returns (raw_summary_dict, trading_date_str).
        Trading date comes from /IsNepseOpen (asOf field), falls back
        to today's date if unavailable.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Fetch summary data
            resp = await client.get(f"{self.base_url}/Summary")
            resp.raise_for_status()
            raw_summary = resp.json()

            # Fetch trading date from /IsNepseOpen
            trading_date = datetime.now().strftime("%Y-%m-%d")
            try:
                status_resp = await client.get(f"{self.base_url}/IsNepseOpen")
                status_resp.raise_for_status()
                status_data = status_resp.json()
                as_of = status_data.get("asOf", "")
                if as_of and len(as_of) >= 10:
                    trading_date = as_of[:10]
            except Exception as exc:
                logger.warning("Could not fetch trading date from /IsNepseOpen: %s", exc)

        return raw_summary, trading_date

    # ------------------------------------------------------------------
    # Response mapping
    # ------------------------------------------------------------------

    def _map_response(self, data: dict, trading_date: str) -> dict:
        """Map the API response to database column names.

        API structure (flat dict):
            "Total Turnover Rs:" → total_turnover
            "Total Traded Shares" → total_traded_shares
            "Total Transactions" → total_transactions
            "Total Scrips Traded" → total_scrips_traded
            "Total Market Capitalization Rs:" → total_market_cap
            "Total Float Market Capitalization Rs:" → total_float_market_cap
        """
        record = {"trading_date": trading_date}
        for api_key, db_col in _FIELD_MAP.items():
            record[db_col] = data.get(api_key)
        return record

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _upsert_record(self, rec: dict) -> bool:
        """Upsert a market summary record.

        Uses INSERT … ON DUPLICATE KEY UPDATE on trading_date.
        Returns True if a new row was inserted, False if updated.
        """
        sql = """
            INSERT INTO market_summary (
                trading_date, total_turnover, total_traded_shares,
                total_transactions, total_scrips_traded,
                total_market_cap, total_float_market_cap
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                total_turnover         = VALUES(total_turnover),
                total_traded_shares    = VALUES(total_traded_shares),
                total_transactions     = VALUES(total_transactions),
                total_scrips_traded    = VALUES(total_scrips_traded),
                total_market_cap       = VALUES(total_market_cap),
                total_float_market_cap = VALUES(total_float_market_cap)
        """
        row = (
            rec["trading_date"],
            rec["total_turnover"],
            rec["total_traded_shares"],
            rec["total_transactions"],
            rec["total_scrips_traded"],
            rec["total_market_cap"],
            rec["total_float_market_cap"],
        )
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, row)
                # rowcount == 1 → inserted, rowcount == 2 → updated
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
            VALUES (%s, 'market_summary_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            logger.error("System log write failed: %s", exc)
