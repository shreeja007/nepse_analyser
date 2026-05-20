# 🔧 Swing Trading Analyser — Working Scratchpad

## Purpose
This is my living working document for the NEPSE Swing Trading Analyser project.
I'll use it to log findings, flag data issues, draft architecture, and iterate on the plan.

---

## 📖 Reference File Findings

### DOCUMENTATION.md Findings
- REST API at `http://localhost:3000` with ~20 endpoints
- WebSocket real-time feeds available
- MCP tools exist for LLM integration
- Relevant endpoints: `/market/prices`, `/market/indices`, `/market/floorsheet-transactions`, `/market/details/{symbol}`
- API serves data from the same `nepsego` MySQL database

### DATABASE_DOCUMENTATION.md Findings
- 18 tables in `nepsego` database
- Key tables for swing analysis:
  - `daily_ohlcv` (91,700 rows) — main OHLCV, BUT `open_price` is ALL ZEROS
  - `daily_prices` (1,632 rows) — reliable OHLC, limited date range
  - `live_market_snapshots` (64,799 rows) — intraday snapshots, reliable open prices
  - `company_details` (384 rows) — sector, 52W H/L, market cap
  - `securities` (753 rows) — broader coverage, sector fallback
  - `company_fundamentals` — EPS, PE, book value, quarterly
  - `dividends` — bonus/cash dividend history
  - `corporate_actions` — rights, bonus, splits with ratios
  - `floorsheet_transactions` — broker-level trade data
  - `market_indices` — NEPSE index change for market regime
  - `market_summary` — daily market-wide aggregates

### DATABASE_DATA_ANALYSIS.md Findings
- ⚠️ **CRITICAL**: `daily_ohlcv.open_price` is ALL ZEROS — must use COALESCE with `daily_prices`
- Existing analysor already uses `COALESCE(NULLIF(dp.open_price, 0), NULLIF(do.open_price, 0), do.close_price)` pattern
- `live_market_snapshots` has reliable open prices for recent dates
- `daily_prices` has only ~1,632 rows (recent dates only)
- `daily_ohlcv` has 91,700 rows (full history back to listing)
- Forward-filling zero-volume days is essential for illiquid stocks

### NEPSE_Stock_Analysis_for_Trading Research Findings
- NEPSE-calibrated RSI: 80/20 (not standard 70/30)
- ATR-based risk: SL = Entry − 1.5×ATR, T1 = Entry + 2.0×ATR, T2 = Entry + 3.5×ATR
- Momentum composite: ROC_20 (40%) + RSI_14 (30%) + VolRatio (30%)
- 5-dimension composite: Price Action (30%), Momentum (25%), Volume (20%), Sector (15%), Risk (10%)
- Ashad/Shrawan (Jun-Jul) seasonal bonus
- Circuit breaker detection: 10% moves need flagging
- Broker accumulation: asymmetry > 65 = smart money signal
- VPT divergence: price high + VPT low = bearish divergence

### Strategic_Equity_Forecasting_Architectures.md Findings
- Multi-timeframe analysis (weekly for trend, daily for entry)
- Mean-reversion vs momentum strategies
- Microstructure forensics for institutional flow detection
- Regime-conditional signal gating
- Cross-asset correlation (index ↔ stock)
- Ensemble scoring with dynamic weighting

### nepsego SQL Schema Findings
- MariaDB 10.4.32 with InnoDB engine
- Key indexes: `uniq_daily_candle(symbol, trading_date)` on daily_ohlcv
- `floorsheet_transactions` has indexes on buyer_broker_id and seller_broker_id
- `live_market_snapshots` has compound indexes on symbol+date and security_id+timestamp
- `company_fundamentals` has unique key on (symbol, fiscal_year, quarter)

---

## 🔍 Existing Analyser Scan

### analysor/ Findings
- `logic.py` (2,024 lines) — full pipeline: batch fetch → indicators → composite scoring → watchlist
- Uses `pymysql` (synchronous) with `DictCursor`
- Batch fetches ALL symbols in single queries (efficient)
- `fetch_all_ohlcv()` — LEFT JOINs daily_prices for open_price fix
- `bridge_live_candle()` — appends synthetic candle from live_market_snapshots
- `get_adjusted_series()` — backward-adjusts for corporate actions/dividends
- `forward_fill_zero_volume_days()` — fills zero-volume sessions
- Full indicator suite: RSI, MACD, ATR, Stochastic, OBV, VPT, BB, ROC, Pivot, Fib
- Signal classification: score-based → STRONG BUY/BUY/HOLD/SELL/STRONG SELL
- Watchlist: filters by liquidity, circuit, SMA200, R:R ≥ 2.0, top 10
- `html_extractor.py` — generates self-contained HTML report
- `__init__.py` — CLI entry: `python -m analysor`

### single_analyser/ Findings
- `logic.py` (1,511 lines) — single-symbol deep analysis
- Per-symbol fetchers instead of batch
- Adds: VWAP from intraday ticks, MFI, broker summary, peer comparison
- Score breakdown: Technical, Fundamental, Volume, Backtest sub-scores
- Strengths/weaknesses list generation
- `html_extractor.py` — per-symbol HTML report
- `__init__.py` — CLI: `python -m single_analyser NABIL` or `--all`

### analysor_stores/ Findings
- Persistence layer for analysis results to `nepsego_analysis` database
- `store.py`, `evaluator.py`, `reporter.py`, `config.py`
- Pattern: save analysis data + report path + elapsed time

---

## 🚨 Data Quality Issues Log

| Issue | Impact | Mitigation |
|-------|--------|------------|
| `daily_ohlcv.open_price` = 0 everywhere | Candle patterns, true range broken | COALESCE with `daily_prices.open_price` |
| `daily_prices` only ~1,632 rows | Older dates won't have real open | Fallback to `close_price` for open |
| Zero-volume days in illiquid stocks | MA/RSI distortion | Forward-fill with last active close |
| Circuit breaker days (±10%) | False indicator extremes | Detect and flag, exclude from scoring |
| Corporate actions (bonus/rights) | Price discontinuities break indicators | Backward-adjust OHLCV before calculation |
| `live_market_snapshots` lag | LTP may not reflect latest trade | Bridge candle pattern from existing code |

---

## 🏗️ Architecture — Final Design

### See implementation_plan.md for the complete architecture
_(Detailed implementation plan presented separately for user approval)_

---
