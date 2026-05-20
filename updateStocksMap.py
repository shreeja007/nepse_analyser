#!/usr/bin/env python3
"""
NEPSE Stock Map Updater

This script updates the stockmap.json file by fetching the latest security list
and sector information from the NEPSE API. It should be run periodically to
keep the stock map current as the exchange adds new stocks.

Author: NEPSE API Project
License: MIT
"""

import asyncio
import json
import os
import sys
from typing import Dict, Any, Optional
import logging
import argparse
from datetime import datetime

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Please install with: pip install httpx")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('stock_update.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
STOCK_MAP_FILE = "stockmap.json"
API_BASE_URL = "http://localhost:8000"

# Internal sector mapping based on NEPSE indices
INTERNAL_SECTOR_MAP = {
  "Commercial Banks": "Banking SubIndex",
  "Development Banks": "Development Bank Ind.",
  "Finance": "Finance Index",
  "Hotels And Tourism": "Hotels And Tourism",
  "Hydro Power": "HydroPower Index",
  "Investment": "Investment",
  "Life Insurance": "Life Insurance",
  "Manufacturing And Processing": "Manufacturing And Pr.",
  "Microfinance": "Microfinance Index",
  "Mutual Fund": "Mutual Fund",
  "NEPSE": "NEPSE Index",
  "Non Life Insurance": "Non Life Insurance",
  "Others": "Others Index",
  "Tradings": "Trading Index",
  "Promoter Share": "Promoter Share",
}

class StockMapUpdater:
    """Updates the stock map from NEPSE API endpoints"""

    def __init__(self, api_base_url: str = API_BASE_URL):
        self.api_base_url = api_base_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def check_server_health(self) -> bool:
        """Check if the API server is running"""
        try:
            response = await self.client.get(f"{self.api_base_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Server health check failed: {e}")
            return False

    async def fetch_security_list(self) -> list:
        """Fetch the security list from the API"""
        try:
            response = await self.client.get(f"{self.api_base_url}/SecurityList")
            response.raise_for_status()

            data = response.json()
            logger.info(f"Security data fetched: {len(data)} items")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"Security API error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"Failed to fetch security list: {e}")
            raise

    async def fetch_sector_data(self) -> dict:
        """Fetch sector data from the API"""
        try:
            response = await self.client.get(f"{self.api_base_url}/SectorScrips")
            response.raise_for_status()

            data = response.json()
            logger.info(f"Sector data fetched: {len(data)} sectors")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"Sector API error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"Failed to fetch sector data: {e}")
            raise

    def create_symbol_sector_map(self, sector_data: dict) -> dict:
        """Create a reverse lookup map from symbol to sector"""
        symbol_sector_map = {}

        for sector, symbols in sector_data.items():
            if isinstance(symbols, list):
                for symbol in symbols:
                    symbol_sector_map[symbol] = sector

        logger.info(f"Created symbol-sector map with {len(symbol_sector_map)} entries")
        return symbol_sector_map

    def create_stock_map(self, security_data: list, symbol_sector_map: dict) -> dict:
        """Create the stock map from security and sector data"""
        stock_map = {}

        for item in security_data:
            # Only include active securities with symbols
            if (item.get("activeStatus") == "A" and
                item.get("symbol") and
                isinstance(item.get("symbol"), str)):

                symbol = item["symbol"]
                sector = symbol_sector_map.get(symbol, "Unknown")
                internal_sector = INTERNAL_SECTOR_MAP.get(sector, "Others Index")

                stock_map[symbol] = {
                    "name": item.get("securityName", symbol),
                    "sector": sector,
                    "internalSector": internal_sector
                }

        logger.info(f"Created stock map with {len(stock_map)} entries")
        return stock_map

    def save_stock_map(self, stock_map: dict) -> bool:
        """Save the stock map to file"""
        try:
            with open(STOCK_MAP_FILE, 'w', encoding='utf-8') as f:
                json.dump(stock_map, f, indent=2, ensure_ascii=False)

            logger.info(f"Stock map saved successfully to {STOCK_MAP_FILE}")
            return True

        except Exception as e:
            logger.error(f"Failed to save stock map: {e}")
            return False

    async def update_stock_map(self) -> bool:
        """Main function to update the stock map"""
        try:
            # Check server health
            logger.info("Checking API server health...")
            if not await self.check_server_health():
                logger.error("API server is not responding. Please start the server first.")
                return False

            # Fetch data
            logger.info("Fetching security list...")
            security_data = await self.fetch_security_list()

            logger.info("Fetching sector data...")
            sector_data = await self.fetch_sector_data()

            # Process data
            logger.info("Processing data...")
            symbol_sector_map = self.create_symbol_sector_map(sector_data)
            stock_map = self.create_stock_map(security_data, symbol_sector_map)

            # Save to file
            logger.info("Saving stock map...")
            if self.save_stock_map(stock_map):
                logger.info("Stock map update completed successfully!")
                return True
            else:
                logger.error("Failed to save stock map")
                return False

        except Exception as e:
            logger.error(f"Stock map update failed: {e}")
            return False

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Update NEPSE stock map")
    parser.add_argument("--api-url", default=API_BASE_URL,
                      help=f"API base URL (default: {API_BASE_URL})")
    parser.add_argument("--verbose", "-v", action="store_true",
                      help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=== NEPSE Stock Map Updater ===")
    logger.info(f"API URL: {args.api_url}")
    logger.info(f"Target file: {STOCK_MAP_FILE}")

    async with StockMapUpdater(args.api_url) as updater:
        success = await updater.update_stock_map()

        if success:
            logger.info("Update completed successfully!")
            sys.exit(0)
        else:
            logger.error("Update failed!")
            sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Update cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
