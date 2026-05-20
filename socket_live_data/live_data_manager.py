"""
Live Data Manager
Orchestrates real-time data collection and storage
"""

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Any

from .config import MAX_CONSECUTIVE_FAILURES_WARN, MAX_POINTS_PER_SYMBOL
from .floorsheet_client import FloorsheetClient

logger = logging.getLogger(__name__)


class LiveDataManager:
    """Manages live data collection and processing"""

    def __init__(self, uri: str = "ws://localhost:5555", *, max_points_per_symbol: int = MAX_POINTS_PER_SYMBOL):
        self.client = FloorsheetClient(uri)
        self.collected_data: Dict[str, List[Dict[str, Any]]] = {}
        self.is_running = False
        self.max_points_per_symbol = max(1, int(max_points_per_symbol))
        self._consecutive_failures: Dict[str, int] = defaultdict(int)
        self._stats: Dict[str, Any] = {
            "cycles": 0,
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "last_error": None,
            "last_cycle_at": None,
        }

    async def start_monitoring(self, symbols: List[str], interval: int = 5):
        """
        Start monitoring stocks

        Args:
            symbols: List of stock symbols to monitor
            interval: Polling interval in seconds
        """
        symbols_clean = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
        if not symbols_clean:
            raise ValueError("At least one valid symbol is required for monitoring")

        interval_seconds = max(1, int(interval))
        await self.client.connect()
        self.is_running = True

        logger.info("Starting live monitoring for: %s", ", ".join(symbols_clean))

        try:
            message_id = 1
            while self.is_running:
                ok_count = 0
                fail_count = 0

                for symbol in symbols_clean:
                    if not self.is_running:
                        break

                    self._stats["requests"] += 1
                    data = await self.client.fetch_floorsheet_of(symbol, str(message_id))
                    message_id += 1

                    if self._is_valid_payload(data):
                        self._store_data(symbol, data)
                        self._consecutive_failures[symbol] = 0
                        self._stats["successes"] += 1
                        ok_count += 1
                    else:
                        self._consecutive_failures[symbol] += 1
                        self._stats["failures"] += 1
                        fail_count += 1
                        if self._consecutive_failures[symbol] >= MAX_CONSECUTIVE_FAILURES_WARN:
                            logger.warning(
                                "Consecutive fetch failures for %s: %d",
                                symbol,
                                self._consecutive_failures[symbol],
                            )

                self._stats["cycles"] += 1
                self._stats["last_cycle_at"] = datetime.now().isoformat()
                logger.info(
                    "Monitoring cycle %d complete: success=%d failed=%d",
                    self._stats["cycles"],
                    ok_count,
                    fail_count,
                )
                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("Monitoring task cancelled")
            raise
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
        except Exception as e:
            self._stats["last_error"] = str(e)
            logger.error("Error during monitoring: %s", e)
        finally:
            await self.client.disconnect()
            self.is_running = False
            logger.info("Monitoring stopped")

    @staticmethod
    def _is_valid_payload(data: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(data, dict):
            return False
        if data.get("error"):
            return False
        if "data" not in data:
            return False
        return data.get("data") is not None

    def _store_data(self, symbol: str, data: Dict[str, Any]):
        """Store collected data with per-symbol cap to avoid unbounded growth."""
        if symbol not in self.collected_data:
            self.collected_data[symbol] = []

        self.collected_data[symbol].append({
            "timestamp": datetime.now().isoformat(),
            "message_id": data.get("messageId"),
            "rate_limit": data.get("rate_limit"),
            "data": data.get("data", data),
        })

        overflow = len(self.collected_data[symbol]) - self.max_points_per_symbol
        if overflow > 0:
            del self.collected_data[symbol][0:overflow]

    def get_latest_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get latest collected data for a symbol"""
        if symbol in self.collected_data and len(self.collected_data[symbol]) > 0:
            return self.collected_data[symbol][-1]
        return None

    def get_monitoring_stats(self) -> Dict[str, Any]:
        """Get a snapshot of monitoring counters and failure streaks."""
        return {
            **self._stats,
            "tracked_symbols": sorted(self.collected_data.keys()),
            "consecutive_failures": dict(self._consecutive_failures),
            "samples_per_symbol": {k: len(v) for k, v in self.collected_data.items()},
        }

    def export_data(self, filename: str):
        """Export collected data to JSON file"""
        payload = {
            "exported_at": datetime.now().isoformat(),
            "stats": self.get_monitoring_stats(),
            "data": self.collected_data,
        }
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            logger.info("Data exported to %s", filename)
        except Exception as e:
            logger.error("Error exporting data: %s", e)

    def stop_monitoring(self):
        """Stop the monitoring loop"""
        self.is_running = False
        logger.info("Stopping monitoring...")


async def main():
    """Example usage"""
    manager = LiveDataManager()

    # Monitor these stocks
    symbols_to_monitor = ["NABIL", "NICA", "DDBL"]

    try:
        # Start monitoring (polling every 5 seconds)
        await manager.start_monitoring(symbols_to_monitor, interval=5)
    finally:
        # Export collected data
        manager.export_data("live_data_export.json")


if __name__ == "__main__":
    asyncio.run(main())
