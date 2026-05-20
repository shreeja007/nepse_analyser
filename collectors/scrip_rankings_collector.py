"""
NEPSE scrip rankings data collector.

Fetches the top-ten scrips by share-traded, turnover, and transaction
count from the FastAPI server (three endpoints fired concurrently with
asyncio.gather()) and upserts them into the scrip_rankings table.

The unique key on (trading_date, category, security_id) ensures reruns
safely refresh the rankings in place.

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

# Endpoint → (category value, metric field name in API response)
_ENDPOINTS = {
    "/TopTenTradeScrips": ("trade", "shareTraded"),
    "/TopTenTurnoverScrips": ("turnover", "turnover"),
    "/TopTenTransactionScrips": ("transaction", "totalTrades"),
}

# API field that holds the closing/last-traded price for each endpoint
_PRICE_FIELDS = {
    "/TopTenTradeScrips": "closingPrice",
    "/TopTenTurnoverScrips": "closingPrice",
    "/TopTenTransactionScrips": "lastTradedPrice",
}


class ScripRankingsCollector:
    """Collect daily NEPSE scrip ranking data across three categories."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self, categories: list[str] | None = None) -> dict:
        """Run a full scrip-rankings collection cycle.

        Args:
            categories: List of categories to collect, e.g. ["trade"],
                        ["turnover", "transaction"], or None for all three.

        Returns a summary dict with keys:
            records_collected, records_inserted, records_updated,
            records_failed, trading_date, duration_seconds, status,
            trade_collected, turnover_collected, transaction_collected
        """
        if categories is None:
            categories = ["trade", "turnover", "transaction"]

        start = time.time()
        summary = {
            "records_collected": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "records_failed": 0,
            "trade_collected": 0,
            "turnover_collected": 0,
            "transaction_collected": 0,
            "trading_date": datetime.now().strftime("%Y-%m-%d"),
            "status": "started",
            "error_message": None,
        }

        await self._log_system("INFO", f"Scrip rankings collection started (categories={categories})")

        try:
            # 1. Fetch all requested categories concurrently
            all_records, trading_date = await self._fetch_rankings(categories)
            summary["trading_date"] = trading_date

            if not all_records:
                summary["status"] = "completed"
                summary["duration_seconds"] = round(time.time() - start, 2)
                await self._log_system("INFO", "No ranking records returned by API")
                await self._save_collection_run(summary)
                return summary

            # Count by category
            for rec in all_records:
                cat = rec["category"]
                summary[f"{cat}_collected"] += 1
            summary["records_collected"] = len(all_records)

            await self._log_system(
                "INFO",
                f"Fetched {summary['trade_collected']} trade, "
                f"{summary['turnover_collected']} turnover, "
                f"{summary['transaction_collected']} transaction for {trading_date}",
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
                        rec.get("category"),
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
            logger.exception("Scrip rankings collection failed")
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

    async def _fetch_rankings(self, categories: list[str]) -> tuple[list[dict], str]:
        """Fetch ranking lists concurrently for requested categories.

        Returns (list_of_mapped_records, trading_date_str).
        """
        # Build endpoint→category lookup for requested categories
        endpoints_to_fetch = {
            path: info
            for path, info in _ENDPOINTS.items()
            if info[0] in categories
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [
                self._fetch_one(client, path, cat, metric_field)
                for path, (cat, metric_field) in endpoints_to_fetch.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Fetch trading date
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

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        path: str,
        category: str,
        metric_field: str,
    ) -> list[dict]:
        """Fetch a single endpoint and map its records."""
        resp = await client.get(f"{self.base_url}{path}")
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list):
            return []

        price_field = _PRICE_FIELDS[path]
        return [
            self._map_record(item, category, metric_field, price_field, rank=idx + 1)
            for idx, item in enumerate(data)
            if isinstance(item, dict)
        ]

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

    def _map_record(
        self,
        item: dict,
        category: str,
        metric_field: str,
        price_field: str,
        rank: int,
    ) -> dict:
        """Map a single API item to database column names.

        API structure (varies by endpoint):
            securityId, symbol, securityName,
            shareTraded | turnover | totalTrades,
            closingPrice | lastTradedPrice
        """
        return {
            "category": category,
            "rank": rank,
            "security_id": item.get("securityId"),
            "symbol": item.get("symbol", ""),
            "security_name": item.get("securityName", ""),
            "metric_value": item.get(metric_field),
            "closing_price": item.get(price_field),
        }

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _upsert_record(self, rec: dict) -> bool:
        """Upsert a single scrip-ranking record.

        Uses INSERT … ON DUPLICATE KEY UPDATE on
        (trading_date, category, security_id).
        Returns True if inserted, False if updated.
        """
        sql = """
            INSERT INTO scrip_rankings (
                trading_date, category, `rank`, security_id,
                symbol, security_name, metric_value, closing_price
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                `rank`         = VALUES(`rank`),
                symbol         = VALUES(symbol),
                security_name  = VALUES(security_name),
                metric_value   = VALUES(metric_value),
                closing_price  = VALUES(closing_price)
        """
        row = (
            rec["trading_date"],
            rec["category"],
            rec["rank"],
            rec["security_id"],
            rec["symbol"],
            rec["security_name"],
            rec["metric_value"],
            rec["closing_price"],
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
            VALUES (%s, 'scrip_rankings_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            logger.error("System log write failed: %s", exc)
