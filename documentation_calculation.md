# documentation_calculation.md

Database table + column usage by analyser (nepsego)

This document answers:

- **Which analyser reads which database tables**
- **Which columns are actually referenced** (in calculations, scoring, or report assembly)
- Includes both a **summary view** and a **detailed per-analyser breakdown**

## Notes / conventions

- Source of truth is the Python code in:
  - `analysor/`
  - `single_analyser/`
  - `swing_analyser/`
  - `broker_tracker/`
  - `master_trader/`
- Column names are aligned with `DATABASE_DOCUMENTATION.md`.
- When code uses `SELECT *`, this doc lists:
  - The **subset of columns actually referenced** by the logic module, if determinable
  - Otherwise, it marks the table as **“full-row fetched for report”** and lists the table schema’s key columns (the row is passed through to HTML/report output).
- Important data-quality rule used across analysers: **`daily_ohlcv.open_price` is frequently `0`**, so the analysers preferentially use `daily_prices.open_price` and fall back to close.

---

## Summary view

### A) Table usage matrix (direct queries)

Legend: `✓` = direct SQL query in that analyser package.

| Table                                         | analysor | single_analyser | swing_analyser | broker_tracker | master_trader |
| --------------------------------------------- | :------: | :-------------: | :------------: | :------------: | :-----------: |
| `daily_ohlcv`                                 |    ✓     |        ✓        |       ✓        |       ✓        |       ✓       |
| `daily_prices`                                |    ✓     |        ✓        |       ✓        |       ✓        |       ✓       |
| `securities`                                  |    ✓     |        ✓        |       ✓        |       ✓        |       ✓       |
| `company_details`                             |    ✓     |        ✓        |       ✓        |       ✓        |       ✓       |
| `company_fundamentals`                        |    ✓     |        ✓        |       ✓        |       —        |       ✓       |
| `corporate_actions`                           |    ✓     |        ✓        |       ✓        |       —        |       —       |
| `dividends`                                   |    ✓     |        ✓        |       ✓        |       —        |       ✓       |
| `live_market_snapshots`                       |    ✓     |        ✓        |       ✓        |       —        |       —       |
| `floorsheet_transactions`                     |    ✓     |       ✓\*       |       ✓        |       ✓        |       ✓       |
| `daily_script_price_graph`                    |    —     |        ✓        |       —        |       —        |       ✓       |
| `daily_trade_turnover_transaction_subindices` |    ✓     |        —        |       —        |       —        |       —       |
| `market_indices`                              |    ✓     |        ✓        |       ✓        |       —        |       ✓       |
| `market_summary`                              |    ✓     |      ✓\*\*      |       —        |       —        |     ✓\*\*     |
| `nepse_sub_indices`                           |    ✓     |        —        |       —        |       —        |       ✓       |
| `scrip_rankings`                              |    ✓     |        ✓        |       —        |       —        |       ✓       |
| `top_movers`                                  |    ✓     |        —        |       —        |       —        |       ✓       |
| `market_schedule`                             |    —     |        —        |       —        |       —        |       ✓       |

\* `single_analyser` has a `fetch_floorsheet()` (`SELECT *`) helper, but the main analysis flow currently uses broker aggregations instead of raw transaction rows.

\*\* `market_summary` is fetched in `single_analyser` + `master_trader`, but is not currently referenced by the scoring logic (it’s mainly used for “as-of date” and future dashboard expansion).

### B) Most reused “core” columns (quick scan)

- Price/history backbone:
  - `daily_ohlcv`: `symbol`, `trading_date`, `high_price`, `low_price`, `close_price`, `volume` (and `open_price` only as fallback)
  - `daily_prices`: `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`, `percent_change`
- Company context:
  - `company_details`: `security_name`, `sector_name`, `market_capitalization`, `stock_listed_shares`, `fifty_two_week_high`, `fifty_two_week_low`
  - `securities`: `sector_name`, `instrument_type`, `security_name`
- Broker flow:
  - `floorsheet_transactions`: `symbol`, `trading_date`, `buyer_broker_id`, `seller_broker_id`, `buyer_broker_name`, `seller_broker_name`, `quantity`, `amount`, `rate`

---

## Detailed breakdown (per analyser)

## 1) analysor

Primary role: market-wide batch analysis + composite scoring + HTML dashboard.

### `daily_ohlcv` + `daily_prices` (open-price fix + missing-row union)

Used columns:

- `daily_ohlcv`: `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`
- `daily_prices`: `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`

How it’s used:

- Builds the full historical candle series per symbol.
- Computes indicators (SMA/EMA, RSI, MACD, ATR, Bollinger, OBV, etc.).
- Fixes unreliable `daily_ohlcv.open_price` using `daily_prices.open_price`.

### `securities`

Used columns:

- `symbol`, `instrument_type`, `sector_name`

How it’s used:

- Filters symbols to equity (or NULL instrument type, depending on module).
- Sector fallback mapping when `company_details` coverage is incomplete.

### `company_details`

Used columns:

- `symbol`, `security_name`, `sector_name`
- `fifty_two_week_high`, `fifty_two_week_low`
- `market_capitalization`, `stock_listed_shares`

How it’s used:

- Company name + sector on the report.
- 52-week context when live snapshots are missing.
- Market cap / shares for fundamental overlays.

### `live_market_snapshots`

Used columns:

- For 52W context (batch): `symbol`, `fifty_two_week_high`, `fifty_two_week_low`
- For “live LTP bridge”: `symbol`, `snapshot_timestamp`, `trading_date`, `last_traded_price`, `percent_change`, `open_price`, `high_price`, `low_price`, `total_traded_quantity`

How it’s used:

- Uses live LTP as the “display price” (matches NEPSE website).
- Optionally appends a synthetic daily candle when `daily_ohlcv` lags.

### `corporate_actions`

Used columns:

- `symbol`, `action_type`, `ratio`, `book_close_date`

How it’s used:

- Back-adjusts OHLCV series for bonus/split/rights adjustments.

### `dividends`

Used columns:

- Batch adjustment: `symbol`, `bonus_share_percent`, `cash_dividend_percent`, `book_close_date`
- Fundamental overlay: `symbol`, `cash_dividend_percent`, `book_close_date`

How it’s used:

- Back-adjusts OHLCV series (bonus + cash dividend impact).
- Computes dividend yield proxy in fundamental scoring.

### `company_fundamentals`

Used columns:

- `symbol`, `eps`, `pe_ratio`, `book_value`, `net_profit`, `fiscal_year`, `quarter`, `published_date`

How it’s used:

- Per-symbol fundamental scoring (P/E, EPS, ROE proxy, PBV proxy, net profit).

### `floorsheet_transactions`

Used columns (aggregations):

- `trading_date`, `symbol`
- `buyer_broker_id`, `buyer_broker_name`
- `seller_broker_id`, `seller_broker_name`
- `quantity`, `amount`, `rate`

How it’s used:

- Broker buy/sell concentration and asymmetry.
- Floorsheet forensics panels (top buyers/sellers, most traded symbols).

### `market_indices` (market regime + overview)

Used columns:

- Market regime: `index_name`, `date`, `change_percent`
- Overview (full row fetched for report): `id`, `index_name`, `date`, `current_value`, `change_points`, `change_percent`, `created_at`

How it’s used:

- Market regime factor (bullish/bearish/neutral) from NEPSE index.
- Market overview section in the report.

### `market_summary` (full row fetched for report)

Used columns:

- Fetched as full row for the dashboard: `trading_date`, `total_turnover`, `total_traded_shares`, `total_transactions`, `total_scrips_traded`, `total_market_cap`, `total_float_market_cap` (plus `id`, `created_at`)

How it’s used:

- Market overview/top summary section.

### `nepse_sub_indices` (full row fetched for report)

Used columns:

- Fetched as full row for the dashboard: `sub_index_id`, `index_name`, `points_change`, `percent_change`, `current_value`, `created_at` (plus `id`)

How it’s used:

- Sector sub-index leaders/laggards and sector strength panels.

### `daily_trade_turnover_transaction_subindices`

Used columns:

- Breadth calc: `percent_change`, `created_at`
- Sector aggregation: `sector`, `turnover`, `volume`, `transaction_count`, `percent_change`

How it’s used:

- Computes market breadth (adv/dec/unchanged) from latest snapshot date.
- Builds sector turnover/volume/txn breakdown for report.

### `top_movers` (full row fetched for report)

Used columns:

- Filter/sort: `mover_type`, `trading_date`, `percent_change`
- Returned rows used for report display: `symbol`, `security_name`, `ltp`, `previous_close`, `point_change`, `percent_change` (plus ids/timestamps)

### `scrip_rankings` (full row fetched for report)

Used columns:

- Filter: `category`, `trading_date`
- Returned rows used for report display: `rank`, `symbol`, `security_name`, `metric_value`, `closing_price` (plus ids/timestamps)

---

## 2) single_analyser

Primary role: deep per-symbol analysis (technical + fundamental + broker + intraday) with one-stock HTML report.

### `daily_ohlcv` + `daily_prices` (open-price fix + missing-row union)

Used columns:

- `daily_ohlcv`: `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`
- `daily_prices`: `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`

How it’s used:

- Builds per-symbol historical candles.
- Computes indicators and backtests.

### `company_details` (`SELECT *` but subset referenced)

Referenced columns:

- Identity/context: `symbol`, `security_name`, `sector_name`, `listing_date`
- Market structure: `market_capitalization`, `stock_listed_shares`
- Ownership: `promoter_percentage`, `public_percentage`
- 52W fallback: `fifty_two_week_high`, `fifty_two_week_low`

### `securities` (`SELECT *` but subset referenced)

Referenced columns:

- `sector_name`, `security_name`

Also used in `--all` mode symbol selection:

- `instrument_type` (equity filter)

### `company_fundamentals` (`SELECT *` but subset referenced)

Referenced columns:

- `eps`, `pe_ratio`, `book_value`, `net_profit`
- `published_date`, `fiscal_year`, `quarter`

How it’s used:

- Fundamental score, PBV/ROE proxy, EPS growth.

### `dividends` (`SELECT *` but subset referenced)

Referenced columns:

- `book_close_date`
- `bonus_share_percent`, `cash_dividend_percent`

How it’s used:

- Adjusts historical candles.
- Computes dividend yield proxy (cash dividend % / current price).

### `corporate_actions` (`SELECT *` but subset referenced)

Referenced columns:

- `book_close_date`, `action_type`, `ratio`

How it’s used:

- Adjusts candles for rights/bonus/split.

### `live_market_snapshots`

Used columns:

- Latest LTP snapshot: `symbol`, `snapshot_timestamp`, `trading_date`, `last_traded_price`, `percent_change`, `open_price`, `high_price`, `low_price`, `total_traded_quantity`
- 52W snapshot helper: `fifty_two_week_high`, `fifty_two_week_low`

How it’s used:

- Uses LTP as display price and (optionally) bridges a synthetic candle.
- Provides up-to-date 52W context.

### `daily_script_price_graph`

Used columns:

- `symbol`, `unix_time`, `contract_rate`, `contract_quantity`, `created_at`

How it’s used:

- Intraday chart series.
- VWAP calculation.

### `floorsheet_transactions` (broker aggregation)

Used columns:

- Filters: `symbol`, `trading_date`
- Aggregations:
  - Buyers: `buyer_broker_id`, `buyer_broker_name`, `quantity`, `amount`
  - Sellers: `seller_broker_id`, `seller_broker_name`, `quantity`, `amount`

How it’s used:

- Computes broker concentration + asymmetry score.
- Classifies broker activity as smart money buying/selling/neutral.

### `market_indices` (`SELECT *` but subset referenced)

Referenced columns:

- `index_name`, `date`, `change_percent`

How it’s used:

- Market modifier (`NEPSE` change % influences composite score slightly).

### `market_summary`

- Fetched (`SELECT *`) as part of `fetch_market_context()`.
- Currently not referenced by scoring logic (kept for report/context expansion).

### `scrip_rankings`

Used columns:

- `symbol`, `trading_date`
- `category`, `rank`, `metric_value`, `closing_price`

How it’s used:

- Adds ranking context to the report for the selected symbol.

### Sector peers query (cross-table)

Tables/columns:

- `securities`: `sector_name`, `symbol`
- `company_details`: `sector_name`, `symbol`
- `daily_ohlcv`: `symbol`, `trading_date`, `close_price`

How it’s used:

- Fetches other symbols in the same sector with their latest close.

---

## 3) swing_analyser

Primary role: batch swing-trade scanner + composite ranking for 1–2 month holds.

### `daily_ohlcv` + `daily_prices`

Used columns:

- `daily_ohlcv`: `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`
- `daily_prices`: `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`

How it’s used:

- Full candle history and indicators.
- Same open-price fix pattern.

### `securities`

Used columns:

- `symbol`, `sector_name`, `instrument_type`

How it’s used:

- Equity-only filtering.
- Sector fallback mapping.

### `company_details`

Used columns:

- `symbol`, `security_name`, `sector_name`
- `fifty_two_week_high`, `fifty_two_week_low`
- `market_capitalization`, `stock_listed_shares`

How it’s used:

- Context + scoring modifiers.

### `live_market_snapshots`

Used columns:

- Batch 52W: `symbol`, `fifty_two_week_high`, `fifty_two_week_low`
- Latest LTP: `symbol`, `snapshot_timestamp`, `trading_date`, `last_traded_price`, `percent_change`, `open_price`, `high_price`, `low_price`, `total_traded_quantity`

How it’s used:

- Uses LTP as display/bridge price.
- Ensures freshest 52W context.

### `corporate_actions`

Used columns:

- `symbol`, `action_type`, `ratio`, `book_close_date`

### `dividends`

Used columns:

- `symbol`, `bonus_share_percent`, `cash_dividend_percent`, `book_close_date`

### `company_fundamentals` + `company_details` (join)

Used columns:

- `company_fundamentals`: `symbol`, `eps`, `pe_ratio`, `book_value`, `net_profit`, `published_date`
- `company_details`: `symbol`, `sector_name`

How it’s used:

- Fundamental stale checks and score modifiers.

### `floorsheet_transactions`

Used columns:

- `trading_date`, `symbol`, `buyer_broker_id`, `seller_broker_id`, `amount`

How it’s used:

- 30-day broker buy/sell concentration → asymmetry score.

### `market_indices`

Used columns:

- `index_name`, `date`, `change_percent`

How it’s used:

- Market regime detection and score factor.

---

## 4) broker_tracker

Primary role: broker activity reconstruction + positions + broker profile intelligence.

### `floorsheet_transactions`

Used columns:

- Identity: `trading_date`, `symbol`, `security_name`
- Broker legs:
  - `buyer_broker_id`, `buyer_broker_name`
  - `seller_broker_id`, `seller_broker_name`
- Trade data: `quantity`, `amount`

How it’s used:

- Reconstructs per-broker per-symbol ledgers.
- Builds net quantity/value, asymmetry, and lifecycle states.

### `daily_ohlcv` + `daily_prices` (latest close fallback)

Used columns:

- `symbol`, `close_price`, `trading_date`

How it’s used:

- Most recent “mark price” per symbol.
- Falls back to `daily_prices` if OHLCV is missing/invalid.

### `company_details`

Used columns:

- `symbol`, `sector_name`, `market_capitalization`, `fifty_two_week_high`, `fifty_two_week_low`

How it’s used:

- Sector mapping + context for broker signals.

### `securities`

Used columns:

- `symbol`, `sector_name`, `instrument_type`

How it’s used:

- Sector fallback for symbols not present in `company_details`.

---

## 5) master_trader

Primary role: orchestration + “master” report that combines:

- Direct DB dashboards / health metrics
- Broker tracker intelligence
- Outputs from `single_analyser` and `swing_analyser`

### `market_schedule`

Used columns:

- `trading_date`, `is_trading_day`

How it’s used:

- Determines expected “as-of” market date for data freshness checks.

### `daily_ohlcv` + `daily_prices` + `securities` (data health)

Used columns:

- `daily_ohlcv`: `symbol`, `trading_date`, `open_price`, `close_price`, `volume`
- `daily_prices`: `symbol`, `trading_date`, `close_price`, `percent_change`
- `securities`: `symbol`, `instrument_type`

How it’s used:

- Data freshness + missing-row checks (daily_prices vs daily_ohlcv).
- Market breadth (adv/dec/unchanged) from `daily_prices.percent_change`.

### `market_indices`

Used columns:

- Date inference: `date`, `index_name`
- Index regime/series: `change_percent`, `current_value`

How it’s used:

- NEPSE regime and relative-strength comparisons.

### `market_summary`

Used columns:

- Date inference: `trading_date`
- Full row is fetched (`SELECT *`) for the dashboard payload, but is not currently referenced by report rendering.

### `nepse_sub_indices`

Used columns:

- `index_name`, `points_change`, `percent_change`, `current_value`, `created_at`

How it’s used:

- Sector leadership / laggard context in master dashboard.

### `top_movers`

Used columns:

- `symbol`, `trading_date`, `mover_type`

How it’s used:

- Builds “gainer streak” counts for momentum context.

### `daily_script_price_graph`

Used columns:

- `symbol`, `contract_rate`, `contract_quantity`, `created_at`

How it’s used:

- Intraday VWAP map (market-wide) used as a floor context signal.

### `company_fundamentals` + `company_details` (sector valuation)

Used columns:

- `company_fundamentals`: `symbol`, `pe_ratio`, `published_date`
- `company_details`: `symbol`, `sector_name`

How it’s used:

- Sector average P/E for valuation context.

### `scrip_rankings`

Used columns:

- `category`, `trading_date`, `symbol`, `rank`, `metric_value`

How it’s used:

- Turnover rank context (used in scoring/selection logic).

### `dividends`

Used columns:

- `symbol`, `book_close_date`, `bonus_share_percent`, `cash_dividend_percent`

How it’s used:

- Upcoming book-closure map and estimated post-dividend drop proxy.

### `floorsheet_transactions`

Used columns:

- Window discovery: `trading_date`
- Flow aggregations: `symbol`, `buyer_broker_id`, `seller_broker_id`, `quantity`, `amount`

How it’s used:

- Weighted average broker rate (WABR) style calculations.
- Broker flow intensity/dominance and consistency metrics.

### Indirect dependencies (through orchestrated analysers)

`master_trader` also calls into:

- `single_analyser` (see its table/column list above)
- `swing_analyser` (see its table/column list above)
- `broker_tracker` (see its table/column list above)

---

## Appendix: “SELECT \*” inventory (where used)

- analysor:
  - `market_summary`, `market_indices`, `nepse_sub_indices`, `top_movers`, `scrip_rankings`
- single_analyser:
  - `company_details`, `securities`, `company_fundamentals`, `dividends`, `corporate_actions`, `market_indices`, `market_summary`
- master_trader:
  - `market_summary`

If you want, I can add a second appendix that lists **every possible column in those tables** (verbatim schema) and marks each column as **Used / Not used / Unknown** per analyser.
