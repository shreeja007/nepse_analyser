"""
Live Floorsheet Data Client
Connects to WebSocket server to fetch real-time floorsheet data
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State

from .config import (
    MAX_RETRIES,
    RETRY_BACKOFF_MULTIPLIER,
    RETRY_DELAY,
    WEBSOCKET_CONNECT_TIMEOUT,
    WEBSOCKET_TIMEOUT,
)

logger = logging.getLogger(__name__)


class FloorsheetClient:
    """WebSocket client for fetching live floorsheet data"""

    def __init__(
        self,
        uri: str = "ws://localhost:5555",
        *,
        request_timeout: int = WEBSOCKET_TIMEOUT,
        connect_timeout: int = WEBSOCKET_CONNECT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        retry_delay: int = RETRY_DELAY,
    ):
        self.uri = uri
        self.websocket = None
        self.request_timeout = max(1, int(request_timeout))
        self.connect_timeout = max(1, int(connect_timeout))
        self.max_retries = max(1, int(max_retries))
        self.retry_delay = max(1, int(retry_delay))

    def _is_connected(self) -> bool:
        if self.websocket is None:
            return False

        # websockets >= 15 returns ClientConnection which exposes `.state`
        # (CONNECTING/OPEN/CLOSING/CLOSED) instead of `.closed`.
        state = getattr(self.websocket, "state", None)
        if state is not None:
            return state == State.OPEN

        # Back-compat with older protocol objects.
        closed = getattr(self.websocket, "closed", None)
        if isinstance(closed, bool):
            return not closed
        return True

    async def _reset_connection(self) -> None:
        if self.websocket is not None:
            try:
                await self.websocket.close()
            except Exception:
                pass
        self.websocket = None

    async def connect(self):
        """Connect to the WebSocket server"""
        if self._is_connected():
            return

        last_error: Exception | None = None
        delay_seconds = self.retry_delay

        for attempt in range(1, self.max_retries + 1):
            try:
                self.websocket = await asyncio.wait_for(
                    websockets.connect(
                        self.uri,
                        ping_interval=20,
                        ping_timeout=20,
                        close_timeout=5,
                    ),
                    timeout=self.connect_timeout,
                )
                logger.info("Connected to %s", self.uri)
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "WebSocket connect attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                await self._reset_connection()
                if attempt < self.max_retries:
                    await asyncio.sleep(delay_seconds)
                    delay_seconds *= RETRY_BACKOFF_MULTIPLIER

        raise ConnectionError(f"Unable to connect to {self.uri}") from last_error

    async def disconnect(self):
        """Disconnect from the WebSocket server"""
        if self.websocket is None:
            return
        await self._reset_connection()
        logger.info("Disconnected from server")

    async def _ensure_connected(self) -> None:
        if not self._is_connected():
            await self.connect()

    @staticmethod
    def _normalize_message_id(message_id: str | int) -> str:
        return str(message_id).strip() or "1"

    @staticmethod
    def _validate_response(data: Dict[str, Any], expected_message_id: str) -> None:
        message_id = str(data.get("messageId") or "").strip()
        if message_id and message_id != expected_message_id:
            logger.warning("Mismatched messageId in response: expected=%s got=%s", expected_message_id, message_id)

        # Server may return top-level error OR embed error inside `data`.
        if data.get("error"):
            logger.warning("Server returned error payload: %s", data.get("error"))
        embedded = data.get("data")
        if isinstance(embedded, dict) and embedded.get("error"):
            logger.warning("Server returned error payload (data.error): %s", embedded.get("error"))

    async def _send_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        expected_message_id = self._normalize_message_id(request.get("messageId", "1"))

        for attempt in range(1, 3):
            try:
                await self._ensure_connected()
                if not self.websocket:
                    return None

                await asyncio.wait_for(self.websocket.send(json.dumps(request)), timeout=self.request_timeout)
                response_raw = await asyncio.wait_for(self.websocket.recv(), timeout=self.request_timeout)
                payload = json.loads(response_raw)

                if not isinstance(payload, dict):
                    logger.error("Unexpected non-dict response payload")
                    return None

                self._validate_response(payload, expected_message_id)
                return payload

            except (asyncio.TimeoutError, ConnectionClosed) as exc:
                logger.warning("Request failed (attempt %d/2): %s", attempt, exc)
                await self._reset_connection()
                if attempt == 2:
                    return None
            except json.JSONDecodeError as exc:
                logger.error("Failed to decode websocket JSON response: %s", exc)
                return None
            except Exception as exc:
                logger.error("Unexpected websocket request error: %s", exc)
                await self._reset_connection()
                if attempt == 2:
                    return None

        return None

    async def fetch_route(
        self,
        route: str,
        params: Dict[str, Any] | None = None,
        *,
        message_id: str | int = "1",
    ) -> Optional[Dict[str, Any]]:
        """Send an arbitrary route request to the WebSocket server."""
        route_clean = str(route or "").strip()
        if not route_clean:
            logger.error("Cannot fetch route: route is empty")
            return None
        request = {
            "messageId": self._normalize_message_id(message_id),
            "route": route_clean,
            "params": params or {},
        }
        logger.info("Requesting route %s (messageId=%s)", route_clean, request["messageId"])
        return await self._send_request(request)

    async def fetch_floorsheet(self, message_id: str = "1") -> Optional[Dict[str, Any]]:
        """Fetch live floorsheet for all stocks"""
        request = {
            "messageId": self._normalize_message_id(message_id),
            "route": "Floorsheet",
            "params": {}
        }
        logger.info("Requesting live floorsheet (messageId=%s)", request["messageId"])
        return await self._send_request(request)

    async def fetch_floorsheet_of(self, symbol: str, message_id: str = "2") -> Optional[Dict[str, Any]]:
        """Fetch live floorsheet for specific stock"""
        symbol_clean = (symbol or "").strip().upper()
        if not symbol_clean:
            logger.error("Cannot fetch floorsheet: symbol is empty")
            return None

        request = {
            "messageId": self._normalize_message_id(message_id),
            "route": "FloorsheetOf",
            "params": {"symbol": symbol_clean}
        }
        logger.info("Requesting floorsheet for %s (messageId=%s)", symbol_clean, request["messageId"])
        return await self._send_request(request)

    async def fetch_multiple_floorsheets(self, symbols: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Fetch floorsheet for multiple stocks"""
        results: Dict[str, Optional[Dict[str, Any]]] = {}
        for idx, symbol in enumerate(symbols or []):
            symbol_clean = (symbol or "").strip().upper()
            if not symbol_clean:
                continue
            data = await self.fetch_floorsheet_of(symbol_clean, message_id=str(idx + 10))
            results[symbol_clean] = data
            await asyncio.sleep(0.1)  # Small delay between requests

        return results


async def main():
    """Example usage"""
    client = FloorsheetClient()

    try:
        # Connect to server
        await client.connect()

        # Fetch general floorsheet
        general_floorsheet = await client.fetch_floorsheet()
        if general_floorsheet:
            print("\n" + "="*60)
            print("GENERAL FLOORSHEET")
            print("="*60)
            print(json.dumps(general_floorsheet, indent=2)[:500])  # Print first 500 chars

        # Fetch specific stock floorsheet
        specific_floorsheet = await client.fetch_floorsheet_of("NABIL")
        if specific_floorsheet:
            print("\n" + "="*60)
            print("NABIL FLOORSHEET")
            print("="*60)
            print(json.dumps(specific_floorsheet, indent=2)[:500])  # Print first 500 chars

        # Fetch multiple stocks
        print("\n" + "="*60)
        print("FETCHING MULTIPLE STOCKS")
        print("="*60)
        symbols = ["NABIL", "NICA", "DDBL"]
        multiple = await client.fetch_multiple_floorsheets(symbols)
        for symbol, data in multiple.items():
            if data:
                print(f"{symbol}: OK")
            else:
                print(f"{symbol}: FAILED")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
