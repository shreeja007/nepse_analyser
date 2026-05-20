"""Main Entry Point for socket_live_data.

Commands:
- test: test websocket connectivity
- fetch: fetch FloorsheetOf(symbol)
- fetch-all: fetch Floorsheet
- monitor: periodically poll symbols and export collected data
- call: call any websocket route with optional params

All commands save their JSON outputs under socket_live_data/output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

from .config import (
    DEFAULT_SYMBOLS,
    LOG_FILE,
    LOG_LEVEL,
    MAX_POINTS_PER_SYMBOL,
    POLLING_INTERVAL,
    WEBSOCKET_SERVER,
)
from .floorsheet_client import FloorsheetClient
from .live_data_manager import LiveDataManager


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def _output_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(here, "output")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _resolve_out_path(filename: str) -> str:
    """Resolve an output filename to a full path.

    - Absolute paths are respected.
    - Relative paths are written under socket_live_data/output.
    """

    name = str(filename or "").strip()
    if not name:
        raise ValueError("Output filename is empty")

    if os.path.isabs(name):
        os.makedirs(os.path.dirname(name) or ".", exist_ok=True)
        return name

    return os.path.join(_output_dir(), name)


def _default_filename(prefix: str, *, route: str | None = None, symbol: str | None = None) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts: list[str] = [prefix]
    if route:
        parts.append(str(route).strip().replace(" ", "_"))
    if symbol:
        parts.append(str(symbol).strip().upper())
    parts.append(ts)
    safe = "_".join(p for p in parts if p)
    return f"{safe}.json"


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _summarize_response(data: Any) -> None:
    if data is None:
        print("No payload received")
        return

    if not isinstance(data, dict):
        print(f"Payload Type: {type(data)}")
        if isinstance(data, list):
            print(f"Records: {len(data)}")
            if data:
                print(f"Sample Record: {data[0]}")
        else:
            s = str(data)
            print(s if len(s) <= 400 else s[:397] + "...")
        return

    if "error" in data:
        err = data.get("error")
        err_type = data.get("error_type")
        if err_type:
            print(f"Server Error Type: {err_type}")
        print(f"Server Error: {err if err else '(empty)'}")

    print(f"Message ID: {data.get('messageId')}")

    rate_limit = data.get("rate_limit") or {}
    if isinstance(rate_limit, dict) and rate_limit:
        print(
            "Rate Limit Remaining: "
            f"{rate_limit.get('remaining')} / {rate_limit.get('limit')} "
            f"(reset: {rate_limit.get('reset_time')})"
        )
    else:
        print("Rate Limit Remaining: -")

    payload = data.get("data")

    if isinstance(payload, dict) and payload.get("error"):
        print(f"Tool Error: {payload.get('error')}")

    print(f"Data Type: {type(payload)}")

    if isinstance(payload, list):
        print(f"Records: {len(payload)}")
        if payload:
            print(f"Sample Record: {payload[0]}")
        return

    if isinstance(payload, dict):
        keys = list(payload.keys())
        print(f"Keys: {keys[:12]}{' ...' if len(keys) > 12 else ''}")

        def _short(v: object) -> str:
            if isinstance(v, dict):
                return f"<dict keys={len(v)}>"
            if isinstance(v, list):
                return f"<list len={len(v)}>"
            s = str(v)
            return s if len(s) <= 120 else s[:117] + "..."

        if keys:
            sample_keys = keys[:3]
            sample = {k: _short(payload.get(k)) for k in sample_keys}
            print(f"Sample: {sample}")
        return

    if payload is None:
        print(
            "No data returned (None). This can mean: no trades for the symbol today, "
            "upstream returned empty, or the server hit an exception."
        )
        return

    s = str(payload)
    print(s if len(s) <= 400 else s[:397] + "...")


async def test_connection() -> bool:
    logger.info("Testing WebSocket connection...")

    client = FloorsheetClient(WEBSOCKET_SERVER)
    try:
        await client.connect()
        logger.info("[OK] Successfully connected to WebSocket server")
        await client.disconnect()
        return True
    except Exception as e:
        logger.error("[ERROR] Connection failed: %s", e)
        return False


async def fetch_single_floorsheet(symbol: str) -> None:
    logger.info("Fetching floorsheet for %s...", symbol)

    client = FloorsheetClient(WEBSOCKET_SERVER)
    try:
        await client.connect()
        data = await client.fetch_floorsheet_of(symbol)

        out_name = _default_filename("fetch", route="FloorsheetOf", symbol=symbol)
        out_path = _resolve_out_path(out_name)
        _write_json(out_path, data)
        print(f"Saved: {out_path}")

        has_error = isinstance(data, dict) and (
            "error" in data or (isinstance(data.get("data"), dict) and data["data"].get("error"))
        )
        has_data = isinstance(data, dict) and (data.get("data") is not None) and ("error" not in data)
        if has_data and not has_error:
            logger.info("Successfully fetched %s floorsheet", symbol)
        else:
            logger.error("Failed to fetch %s floorsheet", symbol)

        print(f"\n{symbol} Floorsheet Data:")
        _summarize_response(data)

    finally:
        await client.disconnect()


async def fetch_all_floorsheet() -> None:
    logger.info("Fetching general floorsheet...")

    client = FloorsheetClient(WEBSOCKET_SERVER)
    try:
        await client.connect()
        data = await client.fetch_floorsheet()

        out_name = _default_filename("fetch", route="Floorsheet")
        out_path = _resolve_out_path(out_name)
        _write_json(out_path, data)
        print(f"Saved: {out_path}")

        has_error = isinstance(data, dict) and (
            "error" in data or (isinstance(data.get("data"), dict) and data["data"].get("error"))
        )
        has_data = isinstance(data, dict) and (data.get("data") is not None) and ("error" not in data)
        if has_data and not has_error:
            logger.info("Successfully fetched general floorsheet")
        else:
            logger.error("Failed to fetch general floorsheet")

        print("\nGeneral Floorsheet Data:")
        _summarize_response(data)

    finally:
        await client.disconnect()


async def call_route(
    route: str,
    params_json: str | None = None,
    *,
    dump: bool = False,
    out_file: str | None = None,
) -> None:
    logger.info("Calling route %s...", route)

    params: dict[str, Any] = {}
    if params_json:
        try:
            parsed = json.loads(params_json)
            if not isinstance(parsed, dict):
                raise ValueError("params must be a JSON object")
            params = parsed
        except Exception as e:
            raise ValueError(f"Invalid --params JSON: {e}")

    client = FloorsheetClient(WEBSOCKET_SERVER)
    try:
        await client.connect()
        data = await client.fetch_route(route, params, message_id="1")

        if not out_file:
            symbol_hint = params.get("symbol") if isinstance(params, dict) else None
            out_file = _default_filename("call", route=route, symbol=str(symbol_hint) if symbol_hint else None)

        out_path = _resolve_out_path(out_file)
        _write_json(out_path, data)
        print(f"Saved: {out_path}")

        if dump:
            print(json.dumps(data, indent=2, ensure_ascii=False) if data is not None else "null")
        else:
            _summarize_response(data)

    finally:
        await client.disconnect()


async def monitor_stocks(symbols: str | None, interval: int, max_points: int) -> None:
    symbol_list = (symbols.split(",") if symbols else DEFAULT_SYMBOLS)
    symbol_list = [s.strip().upper() for s in symbol_list]

    logger.info("Starting monitoring for: %s (interval: %ss)", symbol_list, interval)

    manager = LiveDataManager(WEBSOCKET_SERVER, max_points_per_symbol=max_points)
    try:
        await manager.start_monitoring(symbol_list, interval=interval)
    finally:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = _resolve_out_path(f"floorsheet_data_{timestamp}.json")
        manager.export_data(export_path)
        logger.info("Monitoring stats: %s", manager.get_monitoring_stats())
        logger.info("Data exported to %s", export_path)
        print(f"Saved: {export_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live NEPSE data collection via WebSocket",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python -m socket_live_data test
  python -m socket_live_data fetch --symbol NABIL
  python -m socket_live_data fetch-all
  python -m socket_live_data monitor --symbols "NABIL,NICA" --interval 5
  python -m socket_live_data call --route CompanyDetails --params '{"symbol":"NABIL"}'
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    subparsers.add_parser("test", help="Test WebSocket connection")

    fetch_parser = subparsers.add_parser("fetch", help="Fetch floorsheet for a stock")
    fetch_parser.add_argument("--symbol", type=str, default="NABIL", help="Stock symbol")

    subparsers.add_parser("fetch-all", help="Fetch general floorsheet")

    monitor_parser = subparsers.add_parser("monitor", help="Monitor stocks")
    monitor_parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    monitor_parser.add_argument(
        "--interval", type=int, default=POLLING_INTERVAL, help="Polling interval in seconds"
    )
    monitor_parser.add_argument(
        "--max-points",
        type=int,
        default=MAX_POINTS_PER_SYMBOL,
        help="Maximum in-memory samples per symbol",
    )

    call_parser = subparsers.add_parser("call", help="Call any websocket route")
    call_parser.add_argument(
        "--route", type=str, required=True, help="Route name, e.g. Summary, LiveMarket"
    )
    call_parser.add_argument(
        "--params", type=str, default=None, help='Optional JSON object string, e.g. {"symbol":"NABIL"}'
    )
    call_parser.add_argument("--dump", action="store_true", help="Print full JSON response to stdout")
    call_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Write full JSON response to a file (relative paths go under socket_live_data/output)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "test":
            success = await test_connection()
            sys.exit(0 if success else 1)

        if args.command == "fetch":
            await fetch_single_floorsheet(args.symbol.upper())
            return

        if args.command == "fetch-all":
            await fetch_all_floorsheet()
            return

        if args.command == "monitor":
            await monitor_stocks(args.symbols, args.interval, args.max_points)
            return

        if args.command == "call":
            await call_route(args.route, args.params, dump=args.dump, out_file=args.out)
            return

        raise ValueError(f"Unknown command: {args.command}")

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
