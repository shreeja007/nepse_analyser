#!/usr/bin/env python3
"""
CLI utility to fetch and print NEPSE floorsheet data.

Uses the REST API endpoints exposed by server.py:
- /Floorsheet (all trades for the current trading day)
- /FloorsheetOf?symbol=SYMBOL (trades for a single symbol)
"""

import argparse
import json
import os
import socket
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def build_url(base_url: str, symbol: str | None) -> str:
    base = base_url.rstrip("/")
    if symbol:
        query = urlencode({"symbol": symbol})
        return f"{base}/FloorsheetOf?{query}"
    return f"{base}/Floorsheet"


def fetch_json(url: str, timeout: int) -> object:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8")
        return json.loads(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch NEPSE floorsheet data and print it to stdout."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NEPSE_API_BASE_URL", "http://localhost:8000"),
        help="Base URL of the REST API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--symbol",
        help="Optional stock symbol (uses /FloorsheetOf when provided)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items printed (only applies if the response is a list)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--watch",
        type=int,
        default=None,
        help="Poll interval in seconds (e.g., 60 or 30). When set, keeps polling until Ctrl+C.",
    )
    parser.add_argument(
        "--only-new",
        action="store_true",
        help="When watching, print only new trades (by contractId).",
    )

    args = parser.parse_args()

    url = build_url(args.base_url, args.symbol)
    seen_contracts = set()

    def fetch_and_print() -> int:
        try:
            data = fetch_json(url, args.timeout)
        except (TimeoutError, socket.timeout):
            print(f"Request timed out for {url}", file=sys.stderr)
            return 1
        except HTTPError as e:
            try:
                body = e.read().decode("utf-8")
            except Exception:
                body = str(e)
            print(f"HTTP error {e.code} for {url}:\n{body}", file=sys.stderr)
            return 1
        except URLError as e:
            print(f"Connection error for {url}: {e}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as e:
            print(f"Invalid JSON response from {url}: {e}", file=sys.stderr)
            return 1

        output = data

        if isinstance(data, list) and args.only_new:
            new_items = []
            for item in data:
                if isinstance(item, dict):
                    contract_id = item.get("contractId")
                else:
                    contract_id = None
                if contract_id is None or contract_id not in seen_contracts:
                    new_items.append(item)
                if contract_id is not None:
                    seen_contracts.add(contract_id)
            output = new_items

        if isinstance(output, list) and args.limit is not None:
            output = output[: args.limit]

        print(json.dumps(output, indent=2, ensure_ascii=False), flush=True)
        return 0

    if args.watch is None:
        return fetch_and_print()

    try:
        while True:
            fetch_and_print()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
