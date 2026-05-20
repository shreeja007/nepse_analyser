# Socket Live Data Workspace

Real-time NEPSE market data collection via WebSocket server.

## Overview

This folder contains tools for fetching live floorsheet and market data from the WebSocket server running on `ws://0.0.0.0:5555`.

## Structure

```
socket_live_data/
├── __init__.py              # Module initialization
├── __main__.py              # Package CLI entrypoint (python -m socket_live_data)
├── floorsheet_client.py     # WebSocket client for floorsheet data
├── live_data_manager.py     # Monitoring + export orchestrator
└── output/                  # Saved JSON outputs
└── README.md                # This file
```

## Quick Start

### 1. Start the WebSocket Server

From the project root:

```bash
python socketServer.py
```

The server will be available at `ws://0.0.0.0:5555`

### 2. Fetch Live Data

From the `socket_live_data` folder:

```bash
python floorsheet_client.py
```

Or use the package CLI from the project root:

```bash
python -m socket_live_data test
python -m socket_live_data fetch --symbol NABIL

# Call any route (useful to explore what's available)
python -m socket_live_data call --route Summary
python -m socket_live_data call --route LiveMarket
python -m socket_live_data call --route CompanyDetails --params '{"symbol":"NABIL"}'

# All commands auto-save JSON under socket_live_data/output
# (you'll see a `Saved: ...` line after each run).

# Optional: choose the filename (relative paths go under socket_live_data/output)
python -m socket_live_data call --route CompanyDetails --params '{"symbol":"NABIL"}' --out company_NABIL.json

# Print full JSON to the terminal (can be large)
python -m socket_live_data call --route CompanyDetails --params '{"symbol":"NABIL"}' --dump
```

## Available Routes

### General Market Data

- `Floorsheet` - All stock floorsheet data
- `LiveMarket` - Live market data
- `Summary` - Market summary
- `NepseIndex` - Main index data
- `TopGainers` - Top gaining stocks
- `TopLosers` - Top losing stocks

### Stock-Specific Data

- `FloorsheetOf` - Floorsheet for specific stock (requires symbol parameter)
- `CompanyDetails` - Company details (requires symbol parameter)
- `PriceVolumeHistory` - Price/volume history (requires symbol parameter)
- `DailyScripPriceGraph` - Daily price graph (requires symbol parameter)

## Usage Examples

### Using FloorsheetClient

```python
import asyncio
from floorsheet_client import FloorsheetClient

async def example():
    client = FloorsheetClient()
    await client.connect()

    # Get all floorsheet
    data = await client.fetch_floorsheet()

    # Get specific stock
    nabil = await client.fetch_floorsheet_of("NABIL")

    # Get multiple stocks
    result = await client.fetch_multiple_floorsheets(["NABIL", "NICA", "DDBL"])

    await client.disconnect()

asyncio.run(example())
```

## Rate Limiting

- The server implements per-IP rate limiting
- Each response includes rate limit information
- If rate limited, wait for reset_time before retrying

## Notes

- All requests require proper JSON formatting
- Symbol validation is performed server-side
- Responses include messageId for tracking
