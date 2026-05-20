# NEPSE API - Comprehensive Documentation

Generated on 2026-02-08

## Project Overview

NEPSE API is an unofficial service that exposes Nepal Stock Exchange (NEPSE) data through three interfaces:
REST API (FastAPI), WebSocket, and MCP (Model Context Protocol) for AI clients. It wraps the AsyncNepse client
from the NepseUnofficialApi library, adds validation, rate limiting, caching, and optional Docker deployment.

This repository is designed for educational and research use. It is not an official data source and does not
guarantee accuracy, availability, or fitness for any purpose.

## Legal and Ethical Use

This project is intended for educational, research, and personal use only. It is not licensed for commercial
use or production trading systems without proper authorization from NEPSE or licensed data providers.
The data is sourced from unofficial channels and may be incomplete or inaccurate. Use at your own risk.

## Architecture

Components:

- FastAPI REST server in server.py (port 8000)
- WebSocket server in socketServer.py (port 5555)
- MCP server in mcp_server.py (default port 9000)

Data flow:

- REST and WebSocket servers call AsyncNepse methods directly.
- MCP server calls REST endpoints via HTTP and validates responses with Pydantic models.
- Validation uses local stockmap.json and a fixed list of index names.

## Ports and Services

- 8000: REST API (FastAPI)
- 5555: WebSocket server
- 9000: MCP server (HTTP transport)

## Quick Start

### Python Setup

```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### Start All Servers

```bash
python start_servers.py
```

### Start Individually

```bash
python server.py
python socketServer.py
python mcp_server.py
```

### Run Data Collection Scripts

```bash
python run_floorsheet_collection.py

# All symbols (≈616 securities)
python run_scrip_price_graph_collection.py
# Single symbol (for testing)
python run_scrip_price_graph_collection.py --symbol NABIL

python run_nepse_sub_indices_collection.py

python run_trade_turnover_subindices_collection.py

# All active symbols
python run_company_details_collection.py
# Single symbol (testing)
python run_company_details_collection.py --symbol NABIL

python run_market_summary_collection.py

python run_top_movers_collection.py              # both
python run_top_movers_collection.py --type gainer # gainers only
python run_top_movers_collection.py --type loser  # losers only

python run_scrip_rankings_collection.py                        # all three
python run_scrip_rankings_collection.py --category trade       # trade only
python run_scrip_rankings_collection.py --category turnover    # turnover only
python run_scrip_rankings_collection.py --category transaction # transaction only

python run_daily_index_graph_collection.py                         # all 17
python run_daily_index_graph_collection.py --index nepse_index     # one index
python run_daily_index_graph_collection.py --index banking_subindex

# run all the imp after market close
python run_all

# Stock analyser
python -m analysor


python -m single_analyser NABIL           # single stock
python -m single_analyser NABIL SCB HBL   # multiple stocks
python -m single_analyser --all           # all equity symbols
python -m single_analyser NABIL --output reports/   # custom output dir

python -m swing_analyser

python -m swing_analyser --mode rank
python -m swing_analyser --mode swing
python -m swing_analyser --mode full

python -m master_trader
python -m master_trader --allow-stale-data
    python -m master_trader --equity 500000
    python -m master_trader --quick
    python -m master_trader --track NABIL HBL

    python -m broker_tracker

    py run_all_analayser.py

    go run ./cmd/sync_daily_prices -config config.yaml -date 2026-04-17 (note:yyyy-mm-dd)

After 7+ trading days of data accumulates, run python -m analysor_stores.evaluator then python -m analysor_stores.reporter to see how accurate your signals are.

```

### Analyzer Data Freshness Safeguard

- `daily_ohlcv` can lag by one trading day depending on upstream availability.
- The analyzers (`analysor`, `single_analyser`, `swing_analyser`) now merge missing symbol-date candles from `daily_prices` when those dates are absent in `daily_ohlcv`.
- Current-session partial candles are intentionally excluded from this fallback (`trading_date < CURDATE()`) to avoid intraday distortion.
- `live_market_snapshots` remains the source for live display price (`last_traded_price`) where available.
- This safeguard prevents one-day indicator lag when `daily_prices` is newer than `daily_ohlcv`.

## Configuration

Environment variables:

- BASE_URL: Base URL the MCP server uses to call REST endpoints. Default is http://localhost:8000.
- PORT: MCP server port. Default is 9000.

HTTP response headers added by REST server:

- Access-Control-Allow-Origin: \*
- Cache-Control: public, max-age=30

## Dependencies

Primary runtime dependencies are pinned in requirements.txt and pyproject.toml.
Core packages: fastapi, uvicorn, websockets, fastmcp, httpx, and nepse (NepseUnofficialApi).

## REST API

Base URL: http://localhost:8000

### Endpoints

Method and handler mapping from server.py:

| Method | Path                                       | Handler                                           | Params     | Description                                          |
| ------ | ------------------------------------------ | ------------------------------------------------- | ---------- | ---------------------------------------------------- |
| GET    | /                                          | get_index                                         |            |                                                      |
| GET    | /CompanyDetails                            | get_company_details                               | symbol     |                                                      |
| GET    | /CompanyList                               | get_company_list                                  |            |                                                      |
| GET    | /DailyBankSubindexGraph                    | get_daily_bank_subindex_graph                     |            |                                                      |
| GET    | /DailyDevelopmentBankSubindexGraph         | get_daily_development_bank_subindex_graph         |            |                                                      |
| GET    | /DailyFinanceSubindexGraph                 | get_daily_finance_subindex_graph                  |            |                                                      |
| GET    | /DailyFloatIndexGraph                      | get_daily_float_index_graph                       |            |                                                      |
| GET    | /DailyHotelTourismSubindexGraph            | get_daily_hotel_tourism_subindex_graph            |            |                                                      |
| GET    | /DailyHydroPowerSubindexGraph              | get_daily_hydro_power_subindex_graph              |            |                                                      |
| GET    | /DailyInvestmentSubindexGraph              | get_daily_investment_subindex_graph               |            |                                                      |
| GET    | /DailyLifeInsuranceSubindexGraph           | get_daily_life_insurance_subindex_graph           |            |                                                      |
| GET    | /DailyManufacturingProcessingSubindexGraph | get_daily_manufacturing_processing_subindex_graph |            |                                                      |
| GET    | /DailyMicrofinanceSubindexGraph            | get_daily_microfinance_subindex_graph             |            |                                                      |
| GET    | /DailyMutualFundSubindexGraph              | get_daily_mutual_fund_subindex_graph              |            |                                                      |
| GET    | /DailyNepseIndexGraph                      | get_daily_nepse_index_graph                       |            |                                                      |
| GET    | /DailyNonLifeInsuranceSubindexGraph        | get_daily_non_life_insurance_subindex_graph       |            |                                                      |
| GET    | /DailyOthersSubindexGraph                  | get_daily_others_subindex_graph                   |            |                                                      |
| GET    | /DailyScripPriceGraph                      | get_daily_scrip_price_graph                       | symbol     |                                                      |
| GET    | /DailySensitiveFloatIndexGraph             | get_daily_sensitive_float_index_graph             |            |                                                      |
| GET    | /DailySensitiveIndexGraph                  | get_daily_sensitive_index_graph                   |            |                                                      |
| GET    | /DailyTradingSubindexGraph                 | get_daily_trading_subindex_graph                  |            |                                                      |
| GET    | /Floorsheet                                | get_floorsheet                                    |            |                                                      |
| GET    | /FloorsheetOf                              | get_floorsheet_of                                 | symbol     |                                                      |
| GET    | /IsNepseOpen                               | is_nepse_open                                     |            |                                                      |
| GET    | /LiveMarket                                | get_live_market                                   |            |                                                      |
| GET    | /MarketDepth                               | get_market_depth                                  | symbol     |                                                      |
| GET    | /NepseIndex                                | get_nepse_index                                   |            |                                                      |
| GET    | /NepseSubIndices                           | get_nepse_subindices                              |            |                                                      |
| GET    | /PriceVolume                               | get_price_volume                                  |            |                                                      |
| GET    | /PriceVolumeHistory                        | get_price_volume_history                          | symbol     |                                                      |
| GET    | /SectorScrips                              | get_sector_scrips                                 |            |                                                      |
| GET    | /SecurityList                              | getSecurityList                                   |            |                                                      |
| GET    | /Summary                                   | get_summary                                       |            |                                                      |
| GET    | /SupplyDemand                              | get_supply_demand                                 |            |                                                      |
| GET    | /TopGainers                                | get_top_gainers                                   |            |                                                      |
| GET    | /TopLosers                                 | get_top_losers                                    |            |                                                      |
| GET    | /TopTenTradeScrips                         | get_top_ten_trade_scrips                          |            |                                                      |
| GET    | /TopTenTransactionScrips                   | get_top_ten_transaction_scrips                    |            |                                                      |
| GET    | /TopTenTurnoverScrips                      | get_top_ten_turnover_scrips                       |            |                                                      |
| GET    | /TradeTurnoverTransactionSubindices        | getTradeTurnoverTransactionSubindices             |            |                                                      |
| GET    | /health                                    | health_check                                      |            |                                                      |
| GET    | /rate-limit/stats                          | get_rate_limit_stats                              |            | Get rate limiting statistics                         |
| GET    | /validate/index/{index_name}               | validate_index                                    | index_name | Validate an index name and return validation result  |
| GET    | /validate/stock/{symbol}                   | validate_stock                                    | symbol     | Validate a stock symbol and return validation result |
| GET    | /validation/stats                          | get_validation_stats                              |            | Get validation statistics                            |

Validation endpoints:

- GET /validate/stock/{symbol}
- GET /validate/index/{index_name}
- GET /validation/stats

Rate limit stats endpoint:

- GET /rate-limit/stats

Notes:

- Stock symbol and index name validation is enforced for routes that accept those parameters.
- Responses include Cache-Control and rate limit headers where applicable.

### REST Usage Examples

```bash
curl http://localhost:8000/health
curl http://localhost:8000/Summary
curl "http://localhost:8000/CompanyDetails?symbol=NABIL"
curl http://localhost:8000/validate/stock/NABIL
```

## WebSocket API

Connection: ws://localhost:5555

Message format:

```json
{
  "route": "Summary",
  "params": {},
  "messageId": "client_msg_1"
}
```

Response format:

```json
{
  "messageId": "client_msg_1",
  "data": { ... },
  "rate_limit": {
    "remaining": 49,
    "limit": 50,
    "reset_time": 1700000000
  }
}
```

Available routes (socketServer.py route_handlers):

- CompanyDetails
- CompanyList
- DailyBankSubindexGraph
- DailyDevelopmentBankSubindexGraph
- DailyFinanceSubindexGraph
- DailyFloatIndexGraph
- DailyHotelTourismSubindexGraph
- DailyHydroPowerSubindexGraph
- DailyInvestmentSubindexGraph
- DailyLifeInsuranceSubindexGraph
- DailyManufacturingProcessingSubindexGraph
- DailyMicrofinanceSubindexGraph
- DailyMutualFundSubindexGraph
- DailyNepseIndexGraph
- DailyNonLifeInsuranceSubindexGraph
- DailyOthersSubindexGraph
- DailyScripPriceGraph
- DailySensitiveFloatIndexGraph
- DailySensitiveIndexGraph
- DailyTradingSubindexGraph
- Floorsheet
- FloorsheetOf
- IsNepseOpen
- LiveMarket
- NepseIndex
- NepseSubIndices
- PriceVolume
- PriceVolumeHistory
- SectorScrips
- SecurityList
- Summary
- SupplyDemand
- TopGainers
- TopLosers
- TopTenTradeScrips
- TopTenTransactionScrips
- TopTenTurnoverScrips
- TradeTurnoverTransactionSubindices

Routes that require a symbol parameter: DailyScripPriceGraph, CompanyDetails, PriceVolumeHistory, FloorsheetOf.

## MCP Server

MCP endpoint (HTTP transport): http://localhost:9000/mcp

Key behavior:

- Uses REST endpoints for data retrieval and Pydantic models for validation.
- Endpoint-level in-memory cache with TTL of 600 seconds.
- Rate limiting middleware for tool calls (configured in mcp_server.py).

### MCP Tools

| Tool                                              | Params               | Description                                                                                             |
| ------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------- |
| get_company_floorsheet                            | symbol, limit, page  | Get floorsheet data for a specific company with pagination support.                                     |
| get_company_list                                  | limit, page          | Get list of all companies listed in NEPSE with pagination support.                                      |
| get_company_name_from_symbol                      | symbol               | Find company name by stock symbol.                                                                      |
| get_company_symbol                                | company_name         | Find stock symbol by company name. Use the first significant word of the company name for best results. |
| get_daily_bank_subindex_graph                     | limit, page          | Get daily Bank subindex graph (time series data). Supports pagination.                                  |
| get_daily_development_bank_subindex_graph         | limit, page          | Get daily Development Bank subindex graph (time series data). Supports pagination.                      |
| get_daily_finance_subindex_graph                  | limit, page          | Get daily Finance subindex graph (time series data). Supports pagination.                               |
| get_daily_float_index_graph                       | limit, page          | Get daily Float index graph (time series data). Supports pagination.                                    |
| get_daily_hotel_tourism_subindex_graph            | limit, page          | Get daily Hotel & Tourism subindex graph (time series data). Supports pagination.                       |
| get_daily_hydropower_subindex_graph               | limit, page          | Get daily Hydropower subindex graph (time series data). Supports pagination.                            |
| get_daily_investment_subindex_graph               | limit, page          | Get daily Investment subindex graph (time series data). Supports pagination.                            |
| get_daily_life_insurance_subindex_graph           | limit, page          | Get daily Life Insurance subindex graph (time series data). Supports pagination.                        |
| get_daily_manufacturing_processing_subindex_graph | limit, page          | Get daily Manufacturing & Processing subindex graph (time series data). Supports pagination.            |
| get_daily_microfinance_subindex_graph             | limit, page          | Get daily Microfinance subindex graph (time series data). Supports pagination.                          |
| get_daily_mutual_fund_subindex_graph              | limit, page          | Get daily Mutual Fund subindex graph (time series data). Supports pagination.                           |
| get_daily_nepse_index_graph                       | limit, page          | Get daily NEPSE index graph (time series data). Supports pagination.                                    |
| get_daily_non_life_insurance_subindex_graph       | limit, page          | Get daily Non-Life Insurance subindex graph (time series data). Supports pagination.                    |
| get_daily_others_subindex_graph                   | limit, page          | Get daily Others subindex graph (time series data). Supports pagination.                                |
| get_daily_sensitive_float_index_graph             | limit, page          | Get daily Sensitive Float index graph (time series data). Supports pagination.                          |
| get_daily_sensitive_index_graph                   | limit, page          | Get daily Sensitive index graph (time series data). Supports pagination.                                |
| get_daily_trading_subindex_graph                  | limit, page          | Get daily Trading subindex graph (time series data). Supports pagination.                               |
| get_floorsheet                                    | limit, page          | Get today's floorsheet data (all transactions) with pagination support.                                 |
| get_live_market                                   | limit, page          | Get real-time live market data for all securities with pagination support.                              |
| get_market_depth                                  | symbol               | Get market depth (bid/ask) for a specific stock.                                                        |
| get_market_status                                 |                      | Get the current status of the NEPSE market.                                                             |
| get_market_summary                                |                      | Get the latest live NEPSE market summary including key metrics.                                         |
| get_nepse_index                                   |                      | Get the NEPSE index and related indices.                                                                |
| get_nepse_subindex                                |                      | Get all NEPSE subindices (sector indices).                                                              |
| get_price_history                                 | symbol, limit, page  | Get historical price and volume data for a company with pagination support.                             |
| get_price_volume                                  | company, limit, page | Get price and volume data for all stocks, or filter by company name or symbol. Supports pagination.     |
| get_supply_demand                                 | limit, page          | Get the current supply and demand data for the NEPSE market, with pagination support.                   |
| get_top_gainers                                   | limit, page          | Get list of top gaining stocks with pagination support.                                                 |
| get_top_losers                                    | limit, page          | Get list of top losing stocks with pagination support.                                                  |
| get_top_traders                                   | limit, page          | Get top traders by volume of Nepse securities with pagination support.                                  |
| get_top_transactions                              | limit, page          | Get top transactions by value for Nepse securities with pagination support.                             |
| get_top_turnover                                  | limit, page          | Get top companies by turnover with pagination support.                                                  |
| ping                                              |                      | Health check tool. Returns {'pong': True}.                                                              |
| validate_stock_symbol_tool                        | symbol               | Validate if a stock symbol exists in NEPSE.                                                             |

### MCP Prompts

| Prompt                     | Params                  | Description                                                                                    |
| -------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------- |
| company-deep-dive          | symbol                  | Get a detailed report on a company: profile, price history, and recent trades.                 |
| live-market-watchlist      | symbols                 | Monitor live prices and volumes for a custom list of stocks.                                   |
| market-depth-analyzer      | symbol                  | Analyze the current bid/ask depth for a stock (only when market is open).                      |
| market-open-status         |                         | Check if the NEPSE market is currently open or closed.                                         |
| market-sentiment-snapshot  |                         | Get a snapshot of today's top gainers, losers, and overall market mood.                        |
| post-market-trade-explorer | symbol                  | Explore all trades for a stock after market close (floorsheet).                                |
| sector-performance         | sector                  | Analyze the performance of a specific sector today.                                            |
| setup-alert                | symbol, type, threshold | Set up a price or volume alert for a stock (UI clients can use this to trigger notifications). |
| stock-quick-lookup         | symbol                  | Get a quick summary of a stock's current price, volume, and latest trades.                     |
| validate-stock-symbol      | symbol                  | Check if a stock symbol is valid and get suggestions if not.                                   |

### MCP Usage Example

```python
from fastmcp import Client

client = Client("http://localhost:9000/mcp")

async def example():
    async with client:
        summary = await client.call_tool("get_market_summary", {})
        print(summary)
```

## Validation System

Validation is centralized in validator.py and used by REST, WebSocket, and MCP servers.
Validation data sources:

- stockmap.json for stock symbols
- A predefined set of NEPSE index names in validator.py

Validation helpers:

- server.py: validate_stock_or_raise, validate_index_or_raise
- socketServer.py: validate_stock_or_return_error, validate_index_or_return_error
- mcp_server.py: validate_stock_symbol, find_symbol_by_company_name, find_company_name_by_symbol

## Rate Limiting

Simple in-memory sliding window limiter in rate_limiter.py.

- Window size: 60 seconds
- Cleanup interval: 300 seconds
  Limits per minute by category:
- default: 60
- health: 50
- market_data: 60
- validation: 120
- websocket: 100
- websocket_message: 50

## Stock Map Updates

The stockmap.json file can be refreshed from live NEPSE endpoints.
Manual update:

```bash
python updateStocksMap.py --verbose
```

Quick update (starts server and updater):

```bash
python quick_update.py
```

Internal sector mapping used by updater:

- Commercial Banks -> Banking SubIndex
- Development Banks -> Development Bank Ind.
- Finance -> Finance Index
- Hotels And Tourism -> Hotels And Tourism
- Hydro Power -> HydroPower Index
- Investment -> Investment
- Life Insurance -> Life Insurance
- Manufacturing And Processing -> Manufacturing And Pr.
- Microfinance -> Microfinance Index
- Mutual Fund -> Mutual Fund
- NEPSE -> NEPSE Index
- Non Life Insurance -> Non Life Insurance
- Others -> Others Index
- Promoter Share -> Promoter Share
- Tradings -> Trading Index

## Scripts and Utilities

Convenience scripts:

- start_servers.py: start REST, WebSocket, and MCP servers
- start_servers.bat: Windows launcher for start_servers.py
- setup.ps1: Windows setup script for venv and dependencies
- setup.sh: Linux/Mac setup script for venv and dependencies
- quick_update.py: start server and run stock map update

## CI/CD and Automation

GitHub Actions workflow:

- .github/workflows/update-stock-map.yml runs daily to refresh stockmap.json

## Testing

Scripts:

- test_mcp.py: tests MCP tools via FastMCP client
- test_rate_limiting.py: exercises HTTP and WebSocket rate limits
- test_update.py: runs stock map update workflow locally
- test.py: basic AsyncNepse call smoke test

## Docker

Dockerfile builds a container running all three servers via start_servers.py.
Exposed ports: 8000 (REST), 5555 (WebSocket), 9000 (MCP).
docker-compose.yml maps the same ports for the published image.

## License

This repository is licensed under the MIT License. See LICENSE for full text.

## Data Models (MCP Pydantic Models)

Models defined in mcp_server.py:

### Summary

Bases: BaseModel
Fields:

- totalTurnoverRs: float = Field(..., alias='Total Turnover Rs:')
- totalTradedShares: float = Field(..., alias='Total Traded Shares')
- totalTransactions: float = Field(..., alias='Total Transactions')
- totalScripsTraded: float = Field(..., alias='Total Scrips Traded')

### PriceVolumeItem

Bases: BaseModel
Fields:

- securityId: str
- securityName: str
- symbol: str
- indexId: int
- totalTradeQuantity: int
- lastTradedPrice: float
- percentageChange: float
- previousClose: float
- closePrice: Optional[float] = None

### SupplyDemand

Bases: BaseModel
Fields:

- symbol: str
- totalOrder: int
- totalQuantity: int
- securityName: str
- securityId: Optional[str] = None

### SupplyDemandData

Bases: BaseModel
Fields:

- supplyList: List[SupplyDemand]
- demandList: List[SupplyDemand]

### TopGainerLoser

Bases: BaseModel
Fields:

- symbol: str
- ltp: float
- pointChange: float
- percentageChange: float
- securityName: str
- securityId: int

### TopTradeScrip

Bases: BaseModel
Fields:

- symbol: str
- shareTraded: int
- closingPrice: float
- securityName: str
- securityId: int

### TopTurnover

Bases: BaseModel
Fields:

- symbol: str
- turnover: float
- closingPrice: float
- securityName: str
- securityId: int

### TopTraders

Bases: BaseModel
Fields:

- securityId: int
- totalTrades: int
- lastTradedPrice: float
- securityName: str
- symbol: str

### TopTransactions

Bases: BaseModel
Fields:

- securityId: int
- totalTrades: int
- lastTradedPrice: float
- securityName: str
- symbol: str

### TopTransaction

Bases: BaseModel
Fields:

- securityId: int
- totalTrades: int
- lastTradedPrice: int
- securityName: str
- symbol: str

### MarketStatus

Bases: BaseModel
Fields:

- isOpen: str
- asOf: str
- id: int

### CompanyInfo

Bases: BaseModel
Fields:

- id: int
- companyName: str
- symbol: str
- securityName: str
- status: str
- companyEmail: str
- website: str
- sectorName: str
- regulatoryBody: str
- instrumentType: str

### LiveMarketItem

Bases: BaseModel
Fields:

- securityId: str
- securityName: str
- symbol: str
- indexId: int
- openPrice: float
- highPrice: float
- lowPrice: float
- totalTradeQuantity: int
- totalTradeValue: float
- lastTradedPrice: float
- percentageChange: float
- lastUpdatedDateTime: str
- lastTradedVolume: int
- previousClose: float
- averageTradedPrice: float
- totalTradedVolume: Optional[int] = None
- numberOfTrades: Optional[int] = None

### MarketIndex

Bases: BaseModel
Fields:

- id: int
- auditId: Optional[int] = None
- exchangeIndexId: Optional[int] = None
- generatedTime: str
- index: str
- close: float
- high: float
- low: float
- previousClose: float
- change: float
- perChange: float
- fiftyTwoWeekHigh: float
- fiftyTwoWeekLow: float
- currentValue: float

### SubIndex

Bases: BaseModel
Fields:

- id: int
- index: str
- change: float
- perChange: float
- currentValue: float

### TradeContract

Bases: BaseModel
Fields:

- contractId: int
- stockSymbol: str
- buyerMemberId: str
- sellerMemberId: str
- contractQuantity: int
- contractRate: float
- contractAmount: float
- businessDate: str
- tradeBookId: int
- stockId: int
- buyerBrokerName: str
- sellerBrokerName: str
- tradeTime: str
- securityName: str

### HistoricalTradeEntry

Bases: BaseModel
Fields:

- businessDate: str
- totalTrades: int
- totalTradedQuantity: int
- totalTradedValue: float
- highPrice: float
- lowPrice: float
- closePrice: float

### MarketDepthItem

Bases: BaseModel
Fields:

- stockId: int
- orderBookOrderPrice: float
- quantity: int
- orderCount: int
- isBuy: int
- buy: bool
- sell: bool

### MarketDepthData

Bases: BaseModel
Fields:

- buyMarketDepthList: List[MarketDepthItem]
- sellMarketDepthList: List[MarketDepthItem]

### MarketDepthResponse

Bases: BaseModel
Fields:

- symbol: str
- totalBuyQty: int
- marketDepth: MarketDepthData
- totalSellQty: int
- timeStamp: Optional[int] = None

### SecurityDailyTradeDto

Bases: BaseModel
Fields:

- securityId: str
- openPrice: float
- highPrice: float
- lowPrice: float
- totalTradeQuantity: int
- totalTrades: int
- lastTradedPrice: float
- previousClose: float
- businessDate: str
- closePrice: float
- fiftyTwoWeekHigh: float
- fiftyTwoWeekLow: float
- lastUpdatedDateTime: str

### InstrumentType

Bases: BaseModel
Fields:

- id: int
- code: str
- description: str
- activeStatus: str

### ShareGroup

Bases: BaseModel
Fields:

- id: int
- name: str
- description: str
- capitalRangeMin: int
- modifiedBy: Optional[str] = None
- modifiedDate: Optional[str] = None
- activeStatus: str
- isDefault: str

### SectorMaster

Bases: BaseModel
Fields:

- id: int
- sectorDescription: str
- activeStatus: str
- regulatoryBody: str

### CompanyId

Bases: BaseModel
Fields:

- id: int
- companyShortName: str
- companyName: str
- email: str
- companyWebsite: str
- companyContactPerson: str
- sectorMaster: SectorMaster
- companyRegistrationNumber: str
- activeStatus: str

### Security

Bases: BaseModel
Fields:

- id: int
- symbol: str
- isin: str
- permittedToTrade: str
- listingDate: str
- creditRating: Optional[str] = None
- tickSize: float
- instrumentType: InstrumentType
- capitalGainBaseDate: str
- faceValue: float
- highRangeDPR: float
- issuerName: Optional[str] = None
- meInstanceNumber: int
- parentId: Optional[int] = None
- recordType: int
- schemeDescription: Optional[str] = None
- schemeName: Optional[str] = None
- secured: Optional[str] = None
- series: Optional[str] = None
- shareGroupId: ShareGroup
- activeStatus: str
- divisor: int
- cdsStockRefId: int
- securityName: str
- tradingStartDate: str
- networthBasePrice: float
- securityTradeCycle: int
- isPromoter: str
- companyId: CompanyId

### SecurityOverview

Bases: BaseModel
Fields:

- securityDailyTradeDto: SecurityDailyTradeDto
- security: Security
- stockListedShares: float
- paidUpCapital: float
- issuedCapital: float
- marketCapitalization: float
- publicShares: int
- publicPercentage: float
- promoterShares: float
- promoterPercentage: float
- updatedDate: str
- securityId: int

### TurnoverIndex

Bases: BaseModel
Fields:

- id: int
- index: str
- change: float
- perChange: float
- currentValue: float

### ScripDetail

Bases: BaseModel
Fields:

- symbol: str
- sector: str
- Turnover: float
- transaction: int
- volume: int
- previousClose: float
- lastUpdatedDateTime: int
- name: str
- category: str
- pointChange: float
- percentageChange: float
- ltp: float

### SectorDetail

Bases: BaseModel
Fields:

- transaction: int
- volume: int
- totalTurnover: float
- turnover: TurnoverIndex
- sectorName: str

### MarketSummary

Bases: BaseModel
Fields:

- scripsDetails: Dict[str, ScripDetail]
- sectorsDetails: Dict[str, SectorDetail]

### IndexData

Bases: BaseModel
Fields:

- id: int
- auditId: Optional[int]
- exchangeIndexId: Optional[int]
- generatedTime: Optional[str]
- index: str
- close: float
- high: float
- low: float
- previousClose: float
- change: float
- perChange: float
- fiftyTwoWeekHigh: float
- fiftyTwoWeekLow: float
- currentValue: float

### NepseIndex

Bases: RootModel[Dict[str, IndexData]]
Fields: (none declared in class body)

### AllIndices

Bases: RootModel[Dict[str, IndexData]]
Fields: (none declared in class body)

### TimeValue

Bases: BaseModel
Fields:

- timestamp: int
- value: float

### TimeSeriesData

Bases: BaseModel
Fields:

- data: List[TimeValue]

## Codebase Map

Key files and roles:

- server.py: REST API server and route handlers
- socketServer.py: WebSocket server and route handlers
- mcp_server.py: MCP server, tools, prompts, and data models
- validator.py: stock/index validation and lookup utilities
- rate_limiter.py: in-memory rate limiting utilities
- updateStocksMap.py: stockmap.json updater
- quick_update.py: start server and run updater
- start_servers.py: starts all three servers
- test\_\*.py: test utilities
- Dockerfile, docker-compose.yml: containerization
- README.md, MCP_USAGE.md, VALIDATION_SUMMARY.md: existing docs

## Method Inventory

This section lists every function and method discovered in the codebase.

### mcp_server.py

Functions:

- stock_quick_lookup(symbol): Get a quick summary of a stock's current price, volume, and latest trades.
- market_sentiment_snapshot(): Get a snapshot of today's top gainers, losers, and overall market mood.
- sector_performance(sector): Analyze the performance of a specific sector today.
- company_deep_dive(symbol): Get a detailed report on a company: profile, price history, and recent trades.
- live_market_watchlist(symbols): Monitor live prices and volumes for a custom list of stocks.
- market_depth_analyzer(symbol): Analyze the current bid/ask depth for a stock (only when market is open).
- post_market_trade_explorer(symbol): Explore all trades for a stock after market close (floorsheet).
- validate_stock_symbol_prompt(symbol): Check if a stock symbol is valid and get suggestions if not.
- market_open_status(): Check if the NEPSE market is currently open or closed.
- setup_alert(symbol, type, threshold): Set up a price or volume alert for a stock (UI clients can use this to trigger notifications).
- fetch_nepse_api(endpoint): Fetch data from the NEPSE API and return parsed JSON, with endpoint-level caching.
- validate_and_return(data, model_class, is_list): Validate data against Pydantic model and return validated result.
- ping()
- get_market_status(): Get the current status of the NEPSE market.
- check_market_open(): Returns True if the NEPSE market is currently open, False if closed.
- get_market_summary(): Get the latest live NEPSE market summary including key metrics.
- get_nepse_subindex(): Get all NEPSE subindices (sector indices).
- get_nepse_index(): Get the NEPSE index and related indices.
- \_get_index_graph(endpoint, limit, page): Helper to fetch and paginate index graph data from NEPSE API.
- get_daily_nepse_index_graph(limit, page): Get daily NEPSE index graph (time series data). Supports pagination.
- get_daily_sensitive_index_graph(limit, page): Get daily Sensitive index graph (time series data). Supports pagination.
- get_daily_float_index_graph(limit, page): Get daily Float index graph (time series data). Supports pagination.
- get_daily_sensitive_float_index_graph(limit, page): Get daily Sensitive Float index graph (time series data). Supports pagination.
- get_daily_bank_subindex_graph(limit, page): Get daily Bank subindex graph (time series data). Supports pagination.
- get_daily_development_bank_subindex_graph(limit, page): Get daily Development Bank subindex graph (time series data). Supports pagination.
- get_daily_finance_subindex_graph(limit, page): Get daily Finance subindex graph (time series data). Supports pagination.
- get_daily_hotel_tourism_subindex_graph(limit, page): Get daily Hotel & Tourism subindex graph (time series data). Supports pagination.
- get_daily_hydropower_subindex_graph(limit, page): Get daily Hydropower subindex graph (time series data). Supports pagination.
- get_daily_investment_subindex_graph(limit, page): Get daily Investment subindex graph (time series data). Supports pagination.
- get_daily_life_insurance_subindex_graph(limit, page): Get daily Life Insurance subindex graph (time series data). Supports pagination.
- get_daily_manufacturing_processing_subindex_graph(limit, page): Get daily Manufacturing & Processing subindex graph (time series data). Supports pagination.
- get_daily_microfinance_subindex_graph(limit, page): Get daily Microfinance subindex graph (time series data). Supports pagination.
- get_daily_mutual_fund_subindex_graph(limit, page): Get daily Mutual Fund subindex graph (time series data). Supports pagination.
- get_daily_non_life_insurance_subindex_graph(limit, page): Get daily Non-Life Insurance subindex graph (time series data). Supports pagination.
- get_daily_others_subindex_graph(limit, page): Get daily Others subindex graph (time series data). Supports pagination.
- get_daily_trading_subindex_graph(limit, page): Get daily Trading subindex graph (time series data). Supports pagination.
- get_live_market(limit, page): Get real-time live market data for all securities with pagination support.
- paginate_list(items, limit, page): Paginate a list of items. Returns (paged_items, total, page, limit).
- get_price_volume(company, limit, page): Get price and volume data for all stocks, or filter by company name or symbol. Supports pagination.
- get_top_gainers(limit, page): Get list of top gaining stocks with pagination support.
- get_top_losers(limit, page): Get list of top losing stocks with pagination support.
- get_company_list(limit, page): Get list of all companies listed in NEPSE with pagination support.
- get_top_turnover(limit, page): Get top companies by turnover with pagination support.
- get_top_traders(limit, page): Get top traders by volume of Nepse securities with pagination support.
- get_top_transactions(limit, page): Get top transactions by value for Nepse securities with pagination support.
- get_floorsheet(limit, page): Get today's floorsheet data (all transactions) with pagination support.
- get_company_floorsheet(symbol, limit, page): Get floorsheet data for a specific company with pagination support.
- get_price_history(symbol, limit, page): Get historical price and volume data for a company with pagination support.
- get_market_depth(symbol): Get market depth (bid/ask) for a specific stock.
- get_supply_demand(limit, page): Get the current supply and demand data for the NEPSE market, with pagination support.
- validate_stock_symbol_tool(symbol): Validate if a stock symbol exists in NEPSE.
- get_company_symbol(company_name): Find stock symbol by company name. Use the first significant word of the company name for best results.
- get_company_name_from_symbol(symbol): Find company name by stock symbol.
- async health_check(request)
  Classes:
- Summary: (no custom methods declared)
- PriceVolumeItem: (no custom methods declared)
- SupplyDemand: (no custom methods declared)
- SupplyDemandData: (no custom methods declared)
- TopGainerLoser: (no custom methods declared)
- TopTradeScrip: (no custom methods declared)
- TopTurnover: (no custom methods declared)
- TopTraders: (no custom methods declared)
- TopTransactions: (no custom methods declared)
- TopTransaction: (no custom methods declared)
- MarketStatus: (no custom methods declared)
- CompanyInfo: (no custom methods declared)
- LiveMarketItem: (no custom methods declared)
- MarketIndex: (no custom methods declared)
- SubIndex: (no custom methods declared)
- TradeContract: (no custom methods declared)
- HistoricalTradeEntry: (no custom methods declared)
- MarketDepthItem: (no custom methods declared)
- MarketDepthData: (no custom methods declared)
- MarketDepthResponse: (no custom methods declared)
- SecurityDailyTradeDto: (no custom methods declared)
- InstrumentType: (no custom methods declared)
- ShareGroup: (no custom methods declared)
- SectorMaster: (no custom methods declared)
- CompanyId: (no custom methods declared)
- Security: (no custom methods declared)
- SecurityOverview: (no custom methods declared)
- TurnoverIndex: (no custom methods declared)
- ScripDetail: (no custom methods declared)
- SectorDetail: (no custom methods declared)
- MarketSummary: (no custom methods declared)
- IndexData: (no custom methods declared)
- NepseIndex: (no custom methods declared)
- AllIndices: (no custom methods declared)
- TimeValue: (no custom methods declared)
- TimeSeriesData
- TimeSeriesData.from_list(cls, raw)

### quick_update.py

Module doc: Quick update script that starts server and updates stock map in one command
Functions:

- main()
  Classes: (none)

### rate_limiter.py

Module doc: Simple Rate Limiter for NEPSE API
Functions:

- check_rate_limit(ip, endpoint): Check rate limit for HTTP requests
- check_websocket_rate_limit(ip): Check rate limit for WebSocket connections
- get_rate_limit_headers(info): Generate rate limit headers for HTTP responses
  Classes:
- SimpleRateLimiter: Simple in-memory rate limiter using sliding window approach
- SimpleRateLimiter.**init**(self)
- SimpleRateLimiter.\_get_endpoint_category(self, endpoint): Categorize endpoint to determine rate limit
- SimpleRateLimiter.\_cleanup_old_requests(self, ip, endpoint, current_time): Remove requests older than the window
- SimpleRateLimiter.\_cleanup_old_ips(self): Cleanup IPs that haven't been seen for a while
- SimpleRateLimiter.is_allowed(self, ip, endpoint): Check if request is allowed
- SimpleRateLimiter.get_stats(self): Get rate limiter statistics
- RateLimitExceeded
- RateLimitExceeded.**init**(self, info)

### server.py

Functions:

- async rate_limit_middleware(request, call_next)
- validate_stock_or_raise(symbol): Validate stock symbol and raise HTTPException if invalid
- validate_index_or_raise(index_name): Validate index name and raise HTTPException if invalid
- async health_check()
- async get_rate_limit_stats(): Get rate limiting statistics
- async validate_stock(symbol): Validate a stock symbol and return validation result
- async validate_index(index_name): Validate an index name and return validation result
- async get_validation_stats(): Get validation statistics
- async get_index()
- async get_summary()
- async \_get_summary()
- async get_nepse_index()
- async \_get_nepse_index()
- async get_live_market()
- async get_market_depth(symbol)
- async get_nepse_subindices()
- async \_get_nepse_subindices()
- async get_top_ten_trade_scrips()
- async get_top_ten_transaction_scrips()
- async get_top_ten_turnover_scrips()
- async get_supply_demand()
- async get_top_gainers()
- async get_top_losers()
- async is_nepse_open()
- async get_daily_nepse_index_graph()
- async get_daily_sensitive_index_graph()
- async get_daily_float_index_graph()
- async get_daily_sensitive_float_index_graph()
- async get_daily_bank_subindex_graph()
- async get_daily_development_bank_subindex_graph()
- async get_daily_finance_subindex_graph()
- async get_daily_hotel_tourism_subindex_graph()
- async get_daily_hydro_power_subindex_graph()
- async get_daily_investment_subindex_graph()
- async get_daily_life_insurance_subindex_graph()
- async get_daily_manufacturing_processing_subindex_graph()
- async get_daily_microfinance_subindex_graph()
- async get_daily_mutual_fund_subindex_graph()
- async get_daily_non_life_insurance_subindex_graph()
- async get_daily_others_subindex_graph()
- async get_daily_trading_subindex_graph()
- async get_daily_scrip_price_graph(symbol)
- async get_company_list()
- async get_sector_scrips()
- async get_company_details(symbol)
- async get_price_volume()
- async get_price_volume_history(symbol)
- async get_floorsheet()
- async get_floorsheet_of(symbol)
- async getSecurityList()
- async getTradeTurnoverTransactionSubindices()
- async \_getNepseSubIndices()
  Classes: (none)

### socketServer.py

Functions:

- validate_stock_or_return_error(symbol): Validate stock symbol and return error dict if invalid
- validate_index_or_return_error(index_name): Validate index name and return error dict if invalid
- async \_get_summary()
- async \_get_nepse_index()
- async \_get_nepse_subindices()
- async \_get_trade_turnover_transaction_subindices()
- async handle_route(route, params)
- async ws_listener(websocket, path)
- async start_ws_server()
  Classes: (none)

### start_servers.py

Module doc: Startup script for running both FastAPI and MCP servers
Functions: (none)
Classes:

- ServerManager
- ServerManager.**init**(self)
- ServerManager.signal_handler(self, signum, frame): Handle shutdown signals
- ServerManager.start_fastapi_server(self): Start the FastAPI server
- ServerManager.start_websocket_server(self): Start the WebSocket server
- ServerManager.start_mcp_server(self): Start the MCP server
- ServerManager.run(self): Run all servers

### test.py

Functions:

- async test_nepse()
  Classes: (none)

### test_mcp.py

Module doc: Test script for the NEPSE MCP Server
Functions:

- async test_mcp_server(): Test the MCP server functionality using FastMCP Client
- async test_tool_listing(): Test tool listing functionality using FastMCP Client
  Classes: (none)

### test_rate_limiting.py

Module doc: Rate Limiting Test Script
Functions:

- async test_http_rate_limit(): Test HTTP API rate limiting
- async test_websocket_rate_limit(): Test WebSocket rate limiting
- async test_rate_limit_stats(): Test rate limit statistics endpoint
- async test_different_endpoints(): Test rate limiting on different endpoint categories
- async main(): Main test function
  Classes: (none)

### test_update.py

Module doc: Test script for stock map updater
Functions:

- start_server(): Start the FastAPI server
- stop_server(process): Stop the FastAPI server
- async test_update(): Test the stock map update
- main(): Main test function
  Classes: (none)

### updateStocksMap.py

Module doc: NEPSE Stock Map Updater
Functions:

- async main(): Main entry point
  Classes:
- StockMapUpdater: Updates the stock map from NEPSE API endpoints
- StockMapUpdater.**init**(self, api_base_url)
- async StockMapUpdater.**aenter**(self)
- async StockMapUpdater.**aexit**(self, exc_type, exc_val, exc_tb)
- async StockMapUpdater.check_server_health(self): Check if the API server is running
- async StockMapUpdater.fetch_security_list(self): Fetch the security list from the API
- async StockMapUpdater.fetch_sector_data(self): Fetch sector data from the API
- StockMapUpdater.create_symbol_sector_map(self, sector_data): Create a reverse lookup map from symbol to sector
- StockMapUpdater.create_stock_map(self, security_data, symbol_sector_map): Create the stock map from security and sector data
- StockMapUpdater.save_stock_map(self, stock_map): Save the stock map to file
- async StockMapUpdater.update_stock_map(self): Main function to update the stock map

### validator.py

Module doc: Validation utilities for NEPSE API
Functions:

- validate_stock_symbol(symbol): Validate a stock symbol
- validate_index_name(index_name): Validate an index name
- is_valid_stock(symbol): Quick check if stock symbol is valid
- is_valid_index(index_name): Quick check if index name is valid
- find_symbol_by_company_name(company_name): Find stock symbol by company name
- find_company_name_by_symbol(symbol): Find company name by stock symbol
  Classes:
- NepseValidator: Validator for NEPSE stock symbols and index names
- NepseValidator.**init**(self)
- NepseValidator.\_load_stock_data(self): Load stock data from stockmap.json
- NepseValidator.\_load_index_names(self): Load index names from indexmap.py or define them directly
- NepseValidator.get_valid_stock_symbols(self): Get all valid stock symbols
- NepseValidator.get_valid_index_names(self): Get all valid index names
- NepseValidator.is_valid_stock_symbol(self, symbol): Check if a stock symbol is valid
- NepseValidator.is_valid_index_name(self, index_name): Check if an index name is valid
- NepseValidator.get_stock_info(self, symbol): Get stock information for a valid symbol
- NepseValidator.validate_stock_symbol(self, symbol): Validate stock symbol and return result
- NepseValidator.validate_index_name(self, index_name): Validate index name and return result
- NepseValidator.\_get_similar_symbols(self, symbol, max_suggestions): Get similar stock symbols for suggestions
- NepseValidator.get_stats(self): Get validation statistics
- NepseValidator.\_normalize_company_name(self, name): Normalize company name for matching by removing common suffixes and keeping first significant word
- NepseValidator.find_symbol_by_company_name(self, company_name): Find stock symbol by company name (fuzzy matching)
- NepseValidator.find_company_name_by_symbol(self, symbol): Find company name by stock symbol
