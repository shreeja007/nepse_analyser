"""
Daily scrip price graph data collector.

Fetches intraday price graph data for all securities from the FastAPI
server (GET /DailyScripPriceGraph?symbol=...) and upserts them into the
daily_script_price_graph table.

Processes symbols sequentially with a delay between requests to respect
the server's rate limit (60 req/min). Retries with exponential backoff
when a 429 Too Many Requests response is received.

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

# Rate limiting: delay between API calls (seconds)
# 60 requests per 60s window → ~1.1s between requests stays safely under limit
REQUEST_DELAY = 1.1

# Max retries when rate-limited (429)
MAX_RETRIES = 5

# DB batch size for upserts
BATCH_SIZE = 500

# Base URL of the FastAPI server
API_BASE_URL = "http://localhost:8000"


class ScripPriceGraphCollector:
    """Collect daily scrip price graph data for all securities."""

    def __init__(self, base_url: str = API_BASE_URL, request_delay: float = REQUEST_DELAY):
        self.base_url = base_url.rstrip("/")
        self.request_delay = request_delay

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self, symbol: str | None = None) -> dict:
        """Run a full scrip price graph collection cycle.

        Args:
            symbol: If provided, collect data for this single symbol only.

        Returns a summary dict with keys:
            records_collected, records_inserted, records_updated,
            records_failed, symbols_processed, symbols_failed,
            duration_seconds, status
        """
        start = time.time()
        summary = {
            "records_collected": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "records_failed": 0,
            "symbols_processed": 0,
            "symbols_failed": 0,
            "trading_date": datetime.now().strftime("%Y-%m-%d"),
            "status": "started",
            "error_message": None,
        }

        await self._log_system("INFO", "Scrip price graph collection started")

        try:
            # 1. Get list of symbols to process
            if symbol:
                symbols = [symbol]
                await self._log_system("INFO", f"Single-symbol mode: {symbol}")
            else:
                symbols = await self._fetch_symbols()
                await self._log_system("INFO", f"Fetched {len(symbols)} symbols from CompanyList")

            if not symbols:
                summary["status"] = "completed"
                summary["duration_seconds"] = round(time.time() - start, 2)
                await self._log_system("INFO", "No symbols to process")
                await self._save_collection_run(summary)
                return summary

            # 2. Process symbols sequentially with rate-limit delay
            total = len(symbols)
            for idx, sym in enumerate(symbols, 1):
                await self._process_symbol(sym, summary)
                # Delay between API calls to stay under rate limit
                if idx < total:
                    await asyncio.sleep(self.request_delay)

            # 3. Determine final status
            if summary["symbols_failed"] == 0:
                summary["status"] = "completed"
            elif summary["symbols_failed"] < len(symbols):
                summary["status"] = "partial"
            else:
                summary["status"] = "failed"

        except Exception as exc:
            summary["status"] = "failed"
            summary["error_message"] = str(exc)
            logger.exception("Scrip price graph collection failed")
            await self._log_system("ERROR", f"Collection failed: {exc}")

        summary["duration_seconds"] = round(time.time() - start, 2)
        await self._save_collection_run(summary)
        total_sym = len(symbols) if 'symbols' in dir() else '?'
        await self._log_system(
            "INFO",
            f"Collection finished — status={summary['status']}, "
            f"symbols={summary['symbols_processed']}/{total_sym}, "
            f"collected={summary['records_collected']}, "
            f"inserted={summary['records_inserted']}, "
            f"updated={summary['records_updated']}, "
            f"failed={summary['records_failed']}, "
            f"duration={summary['duration_seconds']}s",
        )
        return summary

    # ------------------------------------------------------------------
    # Per-symbol processing
    # ------------------------------------------------------------------

    async def _process_symbol(self, symbol: str, summary: dict) -> None:
        """Fetch and upsert price graph data for a single symbol."""
        try:
            records = await self._fetch_scrip_price_graph(symbol)
            summary["symbols_processed"] += 1

            if not records:
                return

            summary["records_collected"] += len(records)

            # Upsert in batches
            for batch_start in range(0, len(records), BATCH_SIZE):
                batch = records[batch_start : batch_start + BATCH_SIZE]
                try:
                    inserted, updated = await self._upsert_batch(symbol, batch)
                    summary["records_inserted"] += inserted
                    summary["records_updated"] += updated
                except Exception as exc:
                    summary["records_failed"] += len(batch)
                    logger.error("Upsert failed for %s batch: %s", symbol, exc)

            # Progress logging every 50 symbols
            if summary["symbols_processed"] % 50 == 0:
                await self._log_system(
                    "INFO",
                    f"Progress: {summary['symbols_processed']} symbols processed, "
                    f"{summary['records_collected']} records collected",
                )

        except Exception as exc:
            summary["symbols_failed"] += 1
            summary["symbols_processed"] += 1
            logger.error("Failed to process symbol %s: %s", symbol, exc)
            await self._log_system(
                "ERROR",
                f"Failed to process symbol {symbol}: {exc}",
            )

    # ------------------------------------------------------------------
    # API fetch
    # ------------------------------------------------------------------

    async def _fetch_symbols(self) -> list[str]:
        """Fetch all active stock symbols from the CompanyList endpoint."""
        url = f"{self.base_url}/CompanyList"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, list):
            # Skip delisted/deactivated companies (status "D")
            return [
                item["symbol"]
                for item in data
                if "symbol" in item and item.get("status") != "D"
            ]
        return []

    async def _fetch_scrip_price_graph(self, symbol: str) -> list[dict]:
        """Fetch daily scrip price graph data for a single symbol.

        Retries with exponential backoff on 429 Too Many Requests.
        Returns a list of dicts with keys: contractQuantity, contractRate, time.
        """
        url = f"{self.base_url}/DailyScripPriceGraph"
        backoff = 2.0  # initial backoff seconds

        for attempt in range(1, MAX_RETRIES + 1):
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params={"symbol": symbol})

            if resp.status_code == 429:
                wait = backoff * attempt
                logger.warning(
                    "Rate limited on %s (attempt %d/%d), waiting %.1fs...",
                    symbol, attempt, MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        # All retries exhausted
        logger.error("Gave up on %s after %d rate-limit retries", symbol, MAX_RETRIES)
        return []

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _upsert_batch(self, symbol: str, batch: list[dict]) -> tuple[int, int]:
        """Upsert a batch of price graph records. Returns (inserted, updated)."""
        sql = """
            INSERT INTO daily_script_price_graph (
                symbol, contract_quantity, contract_rate, unix_time
            ) VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                contract_quantity = VALUES(contract_quantity),
                contract_rate     = VALUES(contract_rate)
        """

        rows = []
        for rec in batch:
            rows.append((
                symbol,
                rec.get("contractQuantity"),
                rec.get("contractRate", 0),
                rec.get("time"),
            ))

        inserted = 0
        updated = 0

        async with get_connection() as conn:
            async with conn.cursor() as cur:
                for row in rows:
                    await cur.execute(sql, row)
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
            VALUES (%s, 'scrip_price_graph_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            logger.error("System log write failed: %s", exc)
