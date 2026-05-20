"""
Company details data collector.

Fetches company details for all active securities from the FastAPI
server (GET /CompanyDetails?symbol=...) and upserts them into the
company_details table.

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

# Base URL of the FastAPI server
API_BASE_URL = "http://localhost:8000"


class CompanyDetailsCollector:
    """Collect company details for all active securities."""

    def __init__(self, base_url: str = API_BASE_URL, request_delay: float = REQUEST_DELAY):
        self.base_url = base_url.rstrip("/")
        self.request_delay = request_delay

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect(self, symbol: str | None = None) -> dict:
        """Run a full company details collection cycle.

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

        await self._log_system("INFO", "Company details collection started")

        try:
            # 1. Get list of symbols to process
            if symbol:
                symbols = [symbol]
                await self._log_system("INFO", f"Single-symbol mode: {symbol}")
            else:
                symbols = await self._fetch_symbols()
                await self._log_system("INFO", f"Fetched {len(symbols)} active symbols from CompanyList")

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
            logger.exception("Company details collection failed")
            await self._log_system("ERROR", f"Collection failed: {exc}")

        summary["duration_seconds"] = round(time.time() - start, 2)
        await self._save_collection_run(summary)
        total_sym = len(symbols) if "symbols" in dir() else "?"
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
        """Fetch and upsert company details for a single symbol."""
        try:
            record = await self._fetch_company_details(symbol)
            summary["symbols_processed"] += 1

            if not record:
                return

            summary["records_collected"] += 1

            try:
                inserted, updated = await self._upsert_record(record)
                summary["records_inserted"] += inserted
                summary["records_updated"] += updated
            except Exception as exc:
                summary["records_failed"] += 1
                logger.error("Upsert failed for %s: %s", symbol, exc)

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

    async def _fetch_company_details(self, symbol: str) -> dict | None:
        """Fetch company details for a single symbol.

        Retries with exponential backoff on 429 Too Many Requests.
        Returns a mapped dict ready for DB insertion, or None if no data.
        """
        url = f"{self.base_url}/CompanyDetails"
        backoff = 2.0

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

            if not isinstance(data, dict):
                return None

            return self._map_response(data, symbol)

        # All retries exhausted
        logger.error("Gave up on %s after %d rate-limit retries", symbol, MAX_RETRIES)
        return None

    def _map_response(self, data: dict, symbol: str) -> dict:
        """Map the API response to database column names.

        API structure (deeply nested):
            security:
              id, symbol, isin, securityName, listingDate, permittedToTrade,
              tickSize, creditRating, faceValue, activeStatus,
              capitalGainBaseDate, tradingStartDate, isPromoter,
              instrumentType: {description}
              shareGroupId:   {name}
              companyId:
                companyName, email, companyWebsite, companyContactPerson,
                companyRegistrationNumber,
                sectorMaster: {sectorDescription, regulatoryBody}
            securityDailyTradeDto:
              fiftyTwoWeekHigh, fiftyTwoWeekLow, lastUpdatedDateTime
            Top-level:
              securityId, stockListedShares, paidUpCapital,
              issuedCapital, marketCapitalization, publicShares,
              publicPercentage, promoterShares, promoterPercentage,
              updatedDate
        """
        security = data.get("security", {}) or {}
        trade_dto = data.get("securityDailyTradeDto", {}) or {}
        instrument = security.get("instrumentType", {}) or {}
        company = security.get("companyId", {}) or {}
        sector = company.get("sectorMaster", {}) or {}
        share_grp = security.get("shareGroupId", {}) or {}

        # Parse datetime strings like "2026-02-17T14:59:57.374855"
        def _parse_datetime(raw: str | None) -> str | None:
            if raw and isinstance(raw, str) and len(raw) >= 10:
                try:
                    return raw[:19].replace("T", " ")
                except (ValueError, IndexError):
                    pass
            return None

        last_updated = _parse_datetime(
            trade_dto.get("lastUpdatedDateTime") or data.get("updatedDate")
        )
        company_updated = _parse_datetime(data.get("updatedDate"))

        return {
            "security_id": data.get("securityId") or security.get("id"),
            "symbol": security.get("symbol", symbol),
            "security_name": security.get("securityName", ""),
            "company_name": company.get("companyName", ""),
            "sector_name": sector.get("sectorDescription", ""),
            "regulatory_body": sector.get("regulatoryBody", ""),
            "isin": security.get("isin", ""),
            "instrument_type": instrument.get("description", ""),
            "face_value": security.get("faceValue"),
            "tick_size": security.get("tickSize"),
            "credit_rating": security.get("creditRating"),
            "share_group": share_grp.get("name"),
            "is_promoter": security.get("isPromoter"),
            "listing_date": security.get("listingDate"),
            "capital_gain_base_date": security.get("capitalGainBaseDate"),
            "trading_start_date": security.get("tradingStartDate"),
            "permitted_to_trade": security.get("permittedToTrade", ""),
            "status": security.get("activeStatus", ""),
            "stock_listed_shares": data.get("stockListedShares"),
            "paid_up_capital": data.get("paidUpCapital"),
            "issued_capital": data.get("issuedCapital"),
            "market_capitalization": data.get("marketCapitalization"),
            "public_shares": data.get("publicShares"),
            "public_percentage": data.get("publicPercentage"),
            "promoter_shares": data.get("promoterShares"),
            "promoter_percentage": data.get("promoterPercentage"),
            "fifty_two_week_high": trade_dto.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": trade_dto.get("fiftyTwoWeekLow"),
            "email": company.get("email", ""),
            "website": company.get("companyWebsite", ""),
            "contact_person": company.get("companyContactPerson", ""),
            "company_registration_number": company.get("companyRegistrationNumber", ""),
            "last_updated_time": last_updated,
            "company_updated_date": company_updated,
        }

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _upsert_record(self, rec: dict) -> tuple[int, int]:
        """Upsert a company details record. Returns (inserted, updated)."""
        sql = """
            INSERT INTO company_details (
                security_id, symbol, security_name, company_name, sector_name,
                regulatory_body, isin, instrument_type,
                face_value, tick_size, credit_rating, share_group, is_promoter,
                listing_date, capital_gain_base_date, trading_start_date,
                permitted_to_trade, status,
                stock_listed_shares, paid_up_capital, issued_capital,
                market_capitalization, public_shares, public_percentage,
                promoter_shares, promoter_percentage,
                fifty_two_week_high, fifty_two_week_low,
                email, website, contact_person,
                company_registration_number,
                last_updated_time, company_updated_date
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                symbol                      = VALUES(symbol),
                security_name               = VALUES(security_name),
                company_name                = VALUES(company_name),
                sector_name                 = VALUES(sector_name),
                regulatory_body             = VALUES(regulatory_body),
                isin                        = VALUES(isin),
                instrument_type             = VALUES(instrument_type),
                face_value                  = VALUES(face_value),
                tick_size                   = VALUES(tick_size),
                credit_rating               = VALUES(credit_rating),
                share_group                 = VALUES(share_group),
                is_promoter                 = VALUES(is_promoter),
                listing_date                = VALUES(listing_date),
                capital_gain_base_date      = VALUES(capital_gain_base_date),
                trading_start_date          = VALUES(trading_start_date),
                permitted_to_trade          = VALUES(permitted_to_trade),
                status                      = VALUES(status),
                stock_listed_shares         = VALUES(stock_listed_shares),
                paid_up_capital             = VALUES(paid_up_capital),
                issued_capital              = VALUES(issued_capital),
                market_capitalization        = VALUES(market_capitalization),
                public_shares               = VALUES(public_shares),
                public_percentage           = VALUES(public_percentage),
                promoter_shares             = VALUES(promoter_shares),
                promoter_percentage         = VALUES(promoter_percentage),
                fifty_two_week_high         = VALUES(fifty_two_week_high),
                fifty_two_week_low          = VALUES(fifty_two_week_low),
                email                       = VALUES(email),
                website                     = VALUES(website),
                contact_person              = VALUES(contact_person),
                company_registration_number = VALUES(company_registration_number),
                last_updated_time           = VALUES(last_updated_time),
                company_updated_date        = VALUES(company_updated_date)
        """

        row = (
            rec["security_id"], rec["symbol"], rec["security_name"],
            rec["company_name"], rec["sector_name"], rec["regulatory_body"],
            rec["isin"], rec["instrument_type"],
            rec["face_value"], rec["tick_size"], rec["credit_rating"],
            rec["share_group"], rec["is_promoter"],
            rec["listing_date"], rec["capital_gain_base_date"],
            rec["trading_start_date"],
            rec["permitted_to_trade"], rec["status"],
            rec["stock_listed_shares"], rec["paid_up_capital"],
            rec["issued_capital"], rec["market_capitalization"],
            rec["public_shares"], rec["public_percentage"],
            rec["promoter_shares"], rec["promoter_percentage"],
            rec["fifty_two_week_high"], rec["fifty_two_week_low"],
            rec["email"], rec["website"], rec["contact_person"],
            rec["company_registration_number"],
            rec["last_updated_time"], rec["company_updated_date"],
        )

        inserted = 0
        updated = 0

        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, row)
                if cur.rowcount == 1:
                    inserted = 1
                elif cur.rowcount == 2:
                    updated = 1

        return inserted, updated

    async def _save_collection_run(self, summary: dict) -> None:
        """Write a row to collection_runs capturing this run's outcome."""
        sql = """
            INSERT INTO collection_runs (
                trading_date, collection_type,
                records_collected, records_inserted, records_updated, records_failed,
                status, error_message, duration_seconds
            ) VALUES (%s, 'securities', %s, %s, %s, %s, %s, %s, %s)
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
            VALUES (%s, 'company_details_collector', %s, %s)
        """
        ctx_json = json.dumps(context) if context else None
        try:
            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, (level, message, ctx_json))
        except Exception as exc:
            logger.error("System log write failed: %s", exc)
