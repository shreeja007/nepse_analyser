# Single Analyser Documentation

## What it is

The single_analyser package performs deep analysis for one symbol (or all symbols in batch mode). It extends the core indicator set with intraday charting, VWAP context, detailed strengths/weaknesses, and a full score breakdown.

## Run Commands

- Single symbol: `python -m single_analyser SYMBOL`
- Multiple symbols: `python -m single_analyser SYMBOL1 SYMBOL2 ...`
- All symbols: `python -m single_analyser --all`
- Optional output directory via CLI output flag in module entrypoint.

## Data Inputs (DB)

Main tables:

- `daily_ohlcv`, `daily_prices`
- `company_details`, `securities`, `company_fundamentals`
- `dividends`, `corporate_actions`
- `live_market_snapshots`
- `daily_script_price_graph` (intraday ticks)
- `floorsheet_transactions`
- `market_indices`, `market_summary`
- `scrip_rankings`

### Candle Stitching Policy (2026-04-02)

- Base history uses `daily_ohlcv`.
- Missing symbol-date candles are backfilled from `daily_prices` when not present in `daily_ohlcv`.
- Open price preference: `daily_prices.open_price`, then `daily_ohlcv.open_price`, then close-price proxy.
- Current-session partial `daily_prices` rows are excluded (`trading_date < CURDATE()`).
- This removes stale one-day lag in technical indicators when `daily_prices` has newer data.

## Core Constants

- `RISK_PCT = 0.015`
- `ATR_SL_MULT = 1.5`
- `ATR_T1_MULT = 2.0`
- `ATR_T2_MULT = 3.5`
- `RSI_OVERBOUGHT = 80`, `RSI_OVERSOLD = 20`
- `LOW_LIQ_THRESH = 5000`
- `CIRCUIT_LIMIT = 0.099`
- `MIN_RR_RATIO = 2.0`

## Calculations

### 1) Signal and confidence

Signal class uses technical triggers (trend, RSI, MACD, crossovers, Bollinger position, volume, stoch, breakout candidate).

Confidence starts from base by signal class, then adds context bonuses:

- Extreme RSI zone
- Large MACD histogram magnitude
- Volume surge
- OBV trend confirmation
- MA crossover presence
- Broker asymmetry extremes

### 2) Score breakdown

#### Technical score (30% weight)

Trend structure baseline + RSI positioning + MACD direction + bullish crossover + pattern bonuses + 52W proximity bonus.

#### Fundamental score (35% weight)

Points from:

- P/E zone
- EPS band
- PBV estimate
- Dividend yield
- ROE

#### Volume score (15% weight)

Based on:

- Volume ratio uplift/drag
- OBV trend
- MFI zone adjustments

#### Backtest/risk proxy score (20% weight)

Based on:

- ATR%
- 20-day volatility
- max drawdown
- R:R quality

### 3) Final composite

Base formula:

- `base = 0.30*tech_score + 0.35*fund_score + 0.15*vol_score + 0.20*bt_score`

Modifiers:

- `broker_mod = +5` if asymmetry > 65, `-5` if < 35
- `market_mod = +5` if NEPSE change > 1%, `-5` if < -1%
- `sector_mod = 0` (reserved)

Final:

- `composite = clamp(base + broker_mod + market_mod + sector_mod, 0, 100)`

## Data Generated

Per-symbol analysis payload includes:

- Core identity: symbol, company name, sector
- Indicators and structures: SMA/EMA/RSI/MACD/ATR/Stochastic/OBV/VPT/ROC/BB/ADX/VWAP/pivots/fib/patterns
- Trade framework: signal, confidence, trend, risk_level, stop_loss, target1, target2, rr_ratio, position_size
- Score framework: `tech_score`, `fund_score`, `vol_score`, `bt_score`, `composite`, modifiers
- Risk flags: `circuit_flag`, `liquidity_flag`
- Narrative arrays: `strengths`, `weaknesses`
- Chart data: `price_chart`, `intraday_chart`
- Context blocks: `broker_summary`, `company_info`, `market`, `ranking`, `sector_peers`, `dividend_history`
- Metadata: `total_candles`, `data_days`

## HTML Outputs

- Per-symbol report: `{SYMBOL}_analysis_YYYY-MM-DD.html`
- All-symbol combined report: `py_analyser_all_stocks_analysis_YYYY-MM-DD.html`

## Storage Side Effects

The CLI attempts best-effort DB persistence via analysor_stores integration:

- Single mode: save single analysis record
- All mode: save batch analysis records

## Practical Usefulness

- Best use: decision-quality review before placing or resizing a trade in one stock.
- Why useful:
  - Produces both numeric scoring and readable strengths/weaknesses.
  - Blends intraday and daily context (VWAP + historical indicators).
  - Outputs are presentation-ready (single report per stock or market-wide batch report).
