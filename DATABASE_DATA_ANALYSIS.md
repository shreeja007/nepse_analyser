# NepseGo Database Data Analysis & Utilization Guide

> **Analysis Date**: February 23, 2026
> **Database**: `nepsego` (MariaDB/MySQL)
> **Total Tables**: 21

---

## Executive Summary

This document analyzes the actual data in the `nepsego` database and identifies:

1. **Data quality issues** (e.g., missing open prices in `daily_ohlcv`)
2. **Overlapping data** across tables
3. **Underutilized data** that can enhance analysis
4. **Recommended data sources** for different use cases

### Critical Finding: Open Price Data Issue

| Table                   | Open Price Status                       | Recommendation                  |
| ----------------------- | --------------------------------------- | ------------------------------- |
| `daily_ohlcv`           | **ALL 92,487 rows have open_price = 0** | ❌ DO NOT USE for open prices   |
| `daily_prices`          | Complete data (1,961 rows, 6 days)      | ✅ Use for recent open prices   |
| `live_market_snapshots` | Complete data (96,070 rows)             | ✅ Use for intraday open prices |

---

## Table-by-Table Data Analysis

### 1. Market Price Tables (Overlapping Data)

#### `daily_ohlcv` - Historical OHLCV Data

| Metric             | Value                                      |
| ------------------ | ------------------------------------------ |
| **Rows**           | 92,487                                     |
| **Symbols**        | 413                                        |
| **Date Range**     | 2025-02-03 → 2026-02-23 (237 trading days) |
| **Unique Columns** | `status`                                   |

**Data Quality Issues:**
| Field | Issue | Count | Percentage |
|-------|-------|-------|------------|
| `open_price` | **All zeros** | 92,487 | 100% ❌ |
| `close_price` | Zeros | 1,326 | 1.4% |
| `volume` | Zeros | 17,912 | 19.4% |

**Availability:**

- ✅ High-Low-Close prices (reliable)
- ✅ Volume/Turnover/Transaction count
- ❌ **Open price NOT available** (API limitation)

---

#### `daily_prices` - Complete Price Data

| Metric             | Value                                             |
| ------------------ | ------------------------------------------------- |
| **Rows**           | 1,961                                             |
| **Symbols**        | 365                                               |
| **Date Range**     | 2026-02-05 → 2026-02-23 (6 trading days)          |
| **Unique Columns** | `security_id`, `previous_close`, `percent_change` |

**Data Quality:** ✅ **100% Complete**
| Field | Issue | Count |
|-------|-------|-------|
| `open_price` | Zeros | 0 |
| `close_price` | Zeros | 0 |
| `volume` | Zeros | 0 |

**Columns Available:**

- `security_id` - Links to securities table
- `open_price` - **Complete data!**
- `previous_close` - Previous day's close
- `percent_change` - Pre-calculated change %

---

#### `live_market_snapshots` - Intraday Snapshots

| Metric         | Value                   |
| -------------- | ----------------------- |
| **Rows**       | 96,070                  |
| **Symbols**    | 380                     |
| **Date Range** | 2026-02-03 → 2026-02-23 |

**Data Quality:** ✅ **100% Complete open prices**

**Unique Data:**

- `snapshot_timestamp` - Exact time of each snapshot
- `fifty_two_week_high/low` - 52-week range
- `point_change` - Daily points change
- Multiple snapshots per day per stock

---

### Data Comparison: Same Stock, Same Day

```sql
-- NABIL on 2026-02-23
daily_ohlcv:  open=0.00,    high=498.60, low=493.00, close=495.40
daily_prices: open=494.50,  high=498.60, low=493.00, close=495.40
              ↑ CORRECT!
```

---

### 2. Company Information Tables (Overlapping)

#### `securities` - Master List

| Metric               | Value                                            |
| -------------------- | ------------------------------------------------ |
| **Rows**             | 753                                              |
| **Sectors**          | 13                                               |
| **Instrument Types** | 4 (Equity, Mutual Funds, Debentures, Preference) |

**Breakdown by Instrument Type:**
| Type | Count |
|------|-------|
| Equity | 470 |
| Non-Convertible Debentures | 86 |
| Mutual Funds | 58 |
| Preference Shares | 2 |
| NULL (unknown) | 137 |

**Breakdown by Sector (Top 10):**
| Sector | Count |
|--------|-------|
| Commercial Banks | 144 |
| Development Banks | 107 |
| Hydro Power | 98 |
| Finance | 80 |
| Microfinance | 71 |
| Manufacturing & Processing | 30 |
| Life Insurance | 20 |
| Non Life Insurance | 19 |
| Mutual Fund | 13 |
| Others | 11 |

---

#### `company_details` - Extended Company Info

| Metric                                 | Value |
| -------------------------------------- | ----- |
| **Rows**                               | 384   |
| **All symbols also in securities**     | Yes   |
| **Securities without company_details** | 369   |

**Unique Data Points:**

- `company_name` (full name vs security_name)
- `regulatory_body` (NRB, SEBON, etc.)
- `listing_date`, `trading_start_date`
- `promoter_shares`, `promoter_percentage`
- `public_shares`, `public_percentage`
- `fifty_two_week_high/low`
- `email`, `website`, `contact_person`
- `company_registration_number`

---

### 3. Fundamental Data Tables

#### `company_fundamentals` - Financial Metrics

| Metric           | Value                   |
| ---------------- | ----------------------- |
| **Rows**         | 3,331                   |
| **Symbols**      | 262                     |
| **Fiscal Years** | 9                       |
| **Date Range**   | 2021-06-14 → 2026-02-22 |

**Data Quality:**
| Field | Missing/Zero | Percentage |
|-------|--------------|------------|
| `eps` | 40 | 1.2% |
| `book_value` | 4 | 0.1% |
| `pe_ratio` | 119 | 3.6% |
| `net_profit` | 38 | 1.1% |

**Key Columns:**

- `fiscal_year` - e.g., "2025-2026"
- `quarter` - "First Quarter", "Second Quarter", etc.
- `eps` - Earnings Per Share
- `book_value` - Book Value Per Share
- `pe_ratio` - Price to Earnings Ratio
- `net_profit` - Net Profit Amount

---

#### `dividends` - Dividend History

| Metric         | Value                   |
| -------------- | ----------------------- |
| **Rows**       | 642                     |
| **Symbols**    | 178                     |
| **Date Range** | 2021-06-23 → 2026-02-23 |

**Dividend Type Breakdown:**
| Type | Records |
|------|---------|
| Bonus Share | 405 |
| Cash Dividend | 474 |

---

#### `corporate_actions` - Corporate Events

| Metric           | Value                         |
| ---------------- | ----------------------------- |
| **Rows**         | 864                           |
| **Symbols**      | 230                           |
| **Action Types** | 2 (Bonus Share, Rights Issue) |
| **Date Range**   | 2018-11-13 → 2026-02-12       |

---

### 4. Intraday/Trading Data Tables

#### `floorsheet_transactions` - Individual Trades

| Metric         | Value                            |
| -------------- | -------------------------------- |
| **Rows**       | 211,526                          |
| **Symbols**    | 363                              |
| **Date Range** | 2026-02-17 → 2026-02-23 (3 days) |

**Key Columns:**

- `trade_book_id` - Unique trade ID from NEPSE
- `contract_id` - Contract identifier
- `buyer_broker_id/name` - Buyer broker details
- `seller_broker_id/name` - Seller broker details
- `quantity`, `rate`, `amount` - Trade details

**Use Cases:**

- Broker activity analysis
- Large trade detection
- Volume weighted average price calculation
- Trade flow analysis

---

#### `daily_script_price_graph` - Intraday Price Ticks

| Metric         | Value                   |
| -------------- | ----------------------- |
| **Rows**       | 63,518                  |
| **Symbols**    | 356                     |
| **Date Range** | 2026-02-17 → 2026-02-23 |

**Key Columns:**

- `unix_time` - Timestamp of tick
- `contract_rate` - Price at tick
- `contract_quantity` - Quantity at tick

**Use Cases:**

- Intraday price charts
- Price movement analysis
- Volume profile calculation

---

#### `daily_index_graph` - Index Intraday Ticks

| Metric          | Value                   |
| --------------- | ----------------------- |
| **Rows**        | 11,031                  |
| **Index Types** | 17                      |
| **Date Range**  | 2026-02-17 → 2026-02-23 |

**Available Indices:**

- `nepse_index` - Main NEPSE Index
- `sensitive_index`, `float_index`, `sensitive_float_index`
- Sector indices: `banking_subindex`, `hydropower_subindex`, etc.

---

### 5. Market-Level Data Tables

#### `market_indices` - Daily Index Values

| Metric          | Value                                        |
| --------------- | -------------------------------------------- |
| **Rows**        | 37                                           |
| **Index Types** | 4 (NEPSE, Sensitive, Float, Sensitive Float) |

---

#### `nepse_sub_indices` - Sector Sub-Index Values

| Metric          | Value |
| --------------- | ----- |
| **Rows**        | 39    |
| **Sub-Indices** | 13    |

**Available Sub-Indices:**

- Banking SubIndex, Development Bank Index
- HydroPower Index, Finance Index
- Microfinance Index, Investment Index
- Life Insurance, Non Life Insurance
- Manufacturing And Processing
- Hotels And Tourism Index
- Mutual Fund, Others Index, Trading Index

---

#### `market_summary` - Daily Market Stats

| Metric   | Value                                  |
| -------- | -------------------------------------- |
| **Rows** | 3 (2026-02-17, 2026-02-22, 2026-02-23) |

**Key Columns:**

- `total_turnover` - Total market turnover
- `total_traded_shares` - Total shares traded
- `total_transactions` - Transaction count
- `total_scrips_traded` - Number of active stocks
- `total_market_cap` - Total market capitalization
- `total_float_market_cap` - Float market cap

---

#### `scrip_rankings` - Top Securities

| Metric         | Value                            |
| -------------- | -------------------------------- |
| **Rows**       | 3,001                            |
| **Symbols**    | 363                              |
| **Date Range** | 2026-02-17 → 2026-02-23 (3 days) |

**Categories:**

- `trade` - By volume traded
- `turnover` - By value traded
- `transaction` - By transaction count

---

#### `top_movers` - Gainers & Losers

| Metric         | Value                            |
| -------------- | -------------------------------- |
| **Rows**       | 956                              |
| **Date Range** | 2026-02-17 → 2026-02-23 (3 days) |

**Mover Types:**

- `gainer` - Top gaining stocks
- `loser` - Top losing stocks

---

### 6. System/Operational Tables

#### `collection_runs` - Data Collection History

| Metric   | Value |
| -------- | ----- |
| **Rows** | 749   |

**Collection Types & Status:**
| Type | Completed | Failed | Partial |
|------|-----------|--------|---------|
| floorsheet | 334 | 1 | 0 |
| live_market | 314 | 0 | 0 |
| daily_summary | 39 | 1 | 4 |
| brokers | 25 | 0 | 0 |
| securities | 27 | 0 | 4 |

---

#### `brokers` - Broker Master List

| Metric     | Value                                  |
| ---------- | -------------------------------------- |
| **Rows**   | 0                                      |
| **Status** | ⚠️ EMPTY - Data collection not working |

---

#### `market_schedule` - Trading Calendar

| Metric                   | Value                   |
| ------------------------ | ----------------------- |
| **Rows**                 | 12                      |
| **Trading Days Tracked** | 2026-02-03 → 2026-02-23 |

---

#### `system_logs` - Application Logs

| Metric   | Value |
| -------- | ----- |
| **Rows** | 1,091 |

---

#### `daily_trade_turnover_transaction_subindices` - Sector Trade Stats

| Metric         | Value                   |
| -------------- | ----------------------- |
| **Rows**       | 763                     |
| **Symbols**    | 262                     |
| **Date Range** | 2026-02-17 → 2026-02-23 |

**Key Columns:**

- `sector` - Sector name
- `turnover`, `volume`, `transaction_count`
- `ltp`, `previous_close`, `point_change`, `percent_change`

---

## Data Usage Recommendations

### For Technical Analysis

| Need                 | Primary Source             | Fallback Source         |
| -------------------- | -------------------------- | ----------------------- |
| OHLCV (without Open) | `daily_ohlcv`              | -                       |
| **Open Price**       | `daily_prices`             | `live_market_snapshots` |
| Previous Close       | `daily_prices`             | `live_market_snapshots` |
| Percent Change       | `daily_prices`             | `live_market_snapshots` |
| Intraday Prices      | `daily_script_price_graph` | `live_market_snapshots` |
| 52-Week High/Low     | `live_market_snapshots`    | `company_details`       |

### For Fundamental Analysis

| Need                     | Source                            |
| ------------------------ | --------------------------------- |
| EPS, Book Value, P/E     | `company_fundamentals`            |
| Dividend History         | `dividends`                       |
| Corporate Actions        | `corporate_actions`               |
| Sector Classification    | `securities` or `company_details` |
| Promoter/Public Holdings | `company_details`                 |

### For Market Analysis

| Need                    | Source              |
| ----------------------- | ------------------- |
| Market Index Values     | `market_indices`    |
| Sector Sub-Indices      | `nepse_sub_indices` |
| Intraday Index Movement | `daily_index_graph` |
| Market Summary Stats    | `market_summary`    |
| Top Gainers/Losers      | `top_movers`        |
| Top by Volume/Turnover  | `scrip_rankings`    |

### For Trading Activity Analysis

| Need                 | Source                     |
| -------------------- | -------------------------- |
| Individual Trades    | `floorsheet_transactions`  |
| Broker Activity      | `floorsheet_transactions`  |
| Trade Volume by Time | `daily_script_price_graph` |

---

## Data Gaps & Backfill Opportunities

### 1. Open Price Backfill

**Problem:** `daily_ohlcv` has 92,487 rows with `open_price = 0`

**Solution Options:**

| Source                    | Coverage                         | Query                        |
| ------------------------- | -------------------------------- | ---------------------------- |
| `daily_prices`            | 6 days (Feb 5, 8, 9, 11, 22, 23) | Can fill ~1,900 rows         |
| `live_market_snapshots`   | All 12+ recent days              | Can fill ~320-350 stocks/day |
| `floorsheet_transactions` | First trade of day = open        | Can derive from first trade  |

**Recommended Backfill Query:**

```sql
-- Fill from daily_prices (where available)
UPDATE daily_ohlcv do
JOIN daily_prices dp ON do.symbol = dp.symbol AND do.trading_date = dp.trading_date
SET do.open_price = dp.open_price
WHERE do.open_price = 0;

-- Fill from live_market_snapshots (for remaining)
UPDATE daily_ohlcv do
JOIN (
  SELECT symbol, trading_date, MAX(open_price) as open_price
  FROM live_market_snapshots
  WHERE open_price > 0
  GROUP BY symbol, trading_date
) lms ON do.symbol = lms.symbol AND do.trading_date = lms.trading_date
SET do.open_price = lms.open_price
WHERE do.open_price = 0;
```

---

### 2. Missing Company Details

**Problem:** 369 securities have no `company_details` record

**Impact:** Missing regulatory info, promoter holdings, contact details

**Recommendation:** Run company details collection for missing securities

---

### 3. Empty Brokers Table

**Problem:** `brokers` table has 0 rows but schema exists

**Impact:** Cannot map broker IDs to names without lookup

**Note:** Broker names ARE stored in `floorsheet_transactions` directly

---

### 4. Limited Historical Intraday Data

**Problem:** Intraday data (`daily_script_price_graph`, `daily_index_graph`) only available from 2026-02-17

**Impact:** Cannot analyze historical intraday patterns

---

## Consolidated View: Complete Data for Analysis

To get the most complete OHLCV data, use this approach:

```sql
-- Complete OHLCV view combining best data sources
CREATE OR REPLACE VIEW complete_ohlcv AS
SELECT
    do.symbol,
    do.trading_date,
    COALESCE(
        NULLIF(dp.open_price, 0),
        NULLIF(do.open_price, 0),
        (SELECT MAX(lms.open_price) FROM live_market_snapshots lms
         WHERE lms.symbol = do.symbol AND lms.trading_date = do.trading_date)
    ) as open_price,
    do.high_price,
    do.low_price,
    do.close_price,
    do.volume,
    do.turnover,
    do.transaction_count,
    COALESCE(dp.previous_close,
        LAG(do.close_price) OVER (PARTITION BY do.symbol ORDER BY do.trading_date)
    ) as previous_close,
    dp.percent_change
FROM daily_ohlcv do
LEFT JOIN daily_prices dp ON do.symbol = dp.symbol AND do.trading_date = dp.trading_date;
```

---

## Quick Reference: Best Table for Each Data Point

| Data Point        | Best Table                 | Notes                 |
| ----------------- | -------------------------- | --------------------- |
| Historical OHLCV  | `daily_ohlcv`              | Except open_price     |
| Open Price        | `daily_prices`             | Most reliable         |
| Previous Close    | `daily_prices`             | Pre-calculated        |
| Percent Change    | `daily_prices`             | Pre-calculated        |
| Intraday Prices   | `daily_script_price_graph` | Tick-level            |
| Company Info      | `company_details`          | Most complete         |
| Securities List   | `securities`               | Master list (753)     |
| Fundamentals      | `company_fundamentals`     | 262 symbols           |
| Dividends         | `dividends`                | 178 symbols           |
| Corporate Actions | `corporate_actions`        | 230 symbols           |
| Floorsheet        | `floorsheet_transactions`  | 3 days currently      |
| Market Index      | `market_indices`           | Daily close           |
| Index Intraday    | `daily_index_graph`        | 17 indices            |
| Top Movers        | `top_movers`               | Daily gainers/losers  |
| Volume Leaders    | `scrip_rankings`           | By trade/turnover/txn |

---

## Action Items

### Immediate

1. ❌ **Stop using `daily_ohlcv.open_price`** - Always 0
2. ✅ **Use `daily_prices.open_price`** for recent data
3. ✅ **Use `live_market_snapshots.open_price`** for intraday

### Short-term

1. Run backfill script to populate `daily_ohlcv.open_price` from available sources
2. Investigate why `brokers` table is empty
3. Expand `daily_prices` collection to daily operation

### Long-term

1. Create unified view combining best data sources
2. Add data quality monitoring
3. Implement historical data backfill from NEPSE historical API

---

## Database Statistics Summary

| Category         | Tables | Total Rows   |
| ---------------- | ------ | ------------ |
| Price Data       | 3      | 190,408      |
| Company Info     | 2      | 1,137        |
| Fundamentals     | 3      | 4,837        |
| Trading Activity | 3      | 278,046      |
| Market Data      | 4      | 11,109       |
| System           | 4      | 2,603        |
| **TOTAL**        | **21** | **~488,000** |

---

_Generated by database analysis on 2026-02-23_
