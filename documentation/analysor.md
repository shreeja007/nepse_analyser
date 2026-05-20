# Analysor Documentation

## What it is

The analysor package is the full-market NEPSE analytics engine. It batch-processes all equity symbols, computes technical and risk metrics, applies multi-factor scoring, and generates a consolidated HTML report.

## Run Command

- `python -m analysor`

## Data Inputs (DB)

Primary tables used:

- `daily_ohlcv` + `daily_prices` (OHLCV with open-price correction)
- `securities` (equity filtering, sector/instrument)
- `live_market_snapshots` (live LTP, 52W values, synthetic candle bridging)
- `company_details`
- `company_fundamentals`
- `dividends`
- `corporate_actions`
- `floorsheet_transactions`
- `market_summary`
- `market_indices`
- `nepse_sub_indices`
- `daily_trade_turnover_transaction_subindices`
- `top_movers`
- `scrip_rankings`

### Candle Stitching Policy (2026-04-02)

- Base candles come from `daily_ohlcv`.
- If a symbol-date exists in `daily_prices` but is missing in `daily_ohlcv`, that row is appended before indicator calculations.
- The merge uses `daily_prices.open_price` first; if unavailable/zero, fallback is `daily_ohlcv.open_price`, then close-price proxy.
- Current-day partial `daily_prices` candles are excluded (`trading_date < CURDATE()`).
- Goal: prevent one-day lag in indicators when `daily_prices` updates earlier than `daily_ohlcv`.

## Core Constants and Risk Rules

- `RISK_PCT = 0.015`
- `ATR_SL_MULT = 1.5`
- `ATR_T1_MULT = 2.0`
- `ATR_T2_MULT = 3.5`
- `RSI_OVERBOUGHT = 80`, `RSI_OVERSOLD = 20`
- `LOW_LIQ_THRESH = 5000`
- `CIRCUIT_LIMIT = 0.099`
- `MIN_RR_RATIO = 2.0`

## Calculations

### 1) Price/indicator stack

Per symbol (after adjustments and optional live-candle bridge):

- SMA/EMA, RSI, MACD, ATR, Stochastic, OBV trend, VPT divergence, ROC
- Bollinger bands and squeeze detection
- ADX, VWAP-related context, pivots/fibonacci, candlestick patterns

### 2) Composite score (5 dimensions)

Raw score formula:

- `composite_raw = 0.30*pa_score + 0.25*mom_score + 0.20*vol_score + 0.15*sect_score + 0.10*risk_score`

Dimension logic:

- `pa_score` (trend structure, pattern bonus, 52W proximity bonus)
- `mom_score` (ROC component, RSI mapping from 20-80, MACD histogram sign)
- `vol_score` (volume ratio uplift + OBV rising/falling adjustment)
- `sect_score` (sector breadth percent above SMA50)
- `risk_score` (ATR% and volatility penalties)

Adjustments:

- Market regime multiplier: multiply by regime factor
- Seasonality: add bonus/penalty (Ashad/Shrawan bonus, post-festive penalty)
- Final normalization: min-max normalization to 0-100 across universe

### 3) Watchlist gating

A stock is excluded if any is true:

- Circuit-volatile
- Low liquidity
- Price below SMA200
- `rr_ratio < 2.0`
- Signal not in `BUY` or `STRONG BUY`

Final watchlist:

- Sorted by composite descending
- Top 10 returned

### 4) BOOM stock logic

BOOM-style accumulation flag uses broker forensics plus momentum context:

- Broker asymmetry threshold above 65
- Consistency sessions threshold based on floorsheet window
- `vol_ratio >= 1.3`
- RSI in healthy momentum band
- Price above short trend baseline (SMA20)

## Data Generated

Main return payload keys from `run_full_analysis()`:

- `overview`
- `regime`
- `watchlist`
- `circuit_alerts`
- `trading_signals`
- `boom_stocks`
- `strong_picks`
- `momentum`
- `fundamentals`
- `technicals`
- `sectors`
- `sector_breadth`
- `risk`
- `gainers_losers`
- `dividends_actions`
- `floorsheet`
- `rankings`
- `research`
- `all_analysis`
- `floorsheet_days`

Per-symbol analysis data (inside `all_analysis`) includes:

- Price/volume metrics and trend signals
- Indicator values
- Signal, confidence, R:R, stop/targets, position size
- Composite sub-scores and final composite
- Risk flags (liquidity/circuit)

## HTML Output

- Report writer generates: `py_analyser_report_YYYY-MM-DD.html`
- Output goes to selected output directory if provided; otherwise default project location.
- Dashboard is multi-tab (14 sections) covering watchlist, signals, momentum, fundamentals, sectors, risk, floorsheet, rankings, and research insights.

## Practical Usefulness

- Best use: next-session preparation across the full market.
- Why useful:
  - Converts many raw indicators into one normalized comparable score.
  - Enforces risk discipline by hard filters and minimum R:R.
  - Adds market-regime and seasonality context automatically.
  - Combines technical and broker-flow intelligence for better priority ranking.
- Typical workflow:
  1. Start from `watchlist` and `trading_signals`.
  2. Validate entries with `risk` and circuit alerts.
  3. Use `boom_stocks` and floorsheet sections for conviction confirmation.
