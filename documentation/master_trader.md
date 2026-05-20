# Master Trader Documentation

## What it is

The master_trader package is a coordinator layer that fuses data and logic from swing_analyser and single_analyser, then classifies symbols into timeframe buckets (short, swing, long, hotlist) and emits actionable trade plans.

## Run Command

- `python -m master_trader`

Important options:

- `--equity N`
- `--quick`
- `--output DIR`
- `--track SYMBOL[,SYMBOL...]`
- `--allow-stale-data`

## Data Inputs (DB)

Market and universe inputs:

- `daily_ohlcv`, `daily_prices`
- `market_summary`, `market_indices`, `market_schedule`
- `nepse_sub_indices`
- `top_movers`
- `daily_script_price_graph` (VWAP map)
- `scrip_rankings`
- `company_details`, `company_fundamentals`
- `dividends`, `corporate_actions`
- `live_market_snapshots`
- `floorsheet_transactions`

It also reuses fetchers/indicator helpers from:

- `single_analyser.logic`
- `swing_analyser.logic`
- `swing_analyser.scoring`

Data freshness note:

- Universe candle inputs inherited from shared analyzers now stitch missing symbol-date gaps from `daily_prices` when `daily_ohlcv` lags (excluding `CURDATE()` partial candles).

## Core Calculations

### 1) Unified score enrichment

A final master score is assembled as:

- `final_score = clamp(universal_score + rs_bonus + sector_bonus + turnover_bonus, 0, 100)`

Where:

- `universal_score` comes from swing universal scoring
- `rs_bonus` comes from relative strength deltas
- `sector_bonus` comes from sector leadership and RSI percentile context
- `turnover_bonus` comes from turnover leadership context

### 2) BOOM accumulation flag

Flag requires all major conditions:

- Broker asymmetry > 65
- Consistent top-buyer sessions >= dynamic minimum from floorsheet window
- `vol_ratio >= 1.3`
- RSI in 40 to 80 range
- Price at/above SMA20
- Consistency window available

### 3) Bucket classification logic

Implemented in classifier:

Short bucket (1-5 day style):

- Leadership condition: top-mover streak or high volume ratio or high turnover rank
- RSI in 52-72
- Price above VWAP
- Not too close to 52W high (headroom)
- Sector RSI percentile minimum

Swing bucket:

- Score >= 65
- Setup detected
- Weekly uptrend true
- R:R >= 2
- Sector RSI percentile threshold

Long bucket:

- P/E below sector average
- Positive EPS and dividend history
- P/B floor condition (`< 1.5` when available)
- Fundamental score >= 60

Hotlist bucket:

- Score >= 75
- Setup present
- BOOM flag true or broker asymmetry > 55

### 4) Trade plan construction

Per bucket plan contains:

- Entry zone
- Stop loss
- Targets (`target_1`, `target_2`, `target_3`)
- R:R ratio
- Position size from: `position_size = (equity * risk_pct) / risk_per_share`
- Hold window, time stop, explicit exit conditions

### 5) Tracking verdict engine (`--track`)

Tracked symbols get verdicts:

- `EXIT` if stop touched or invalidation triggers fire
- `TRIM` if T1 reached or deterioration signals appear
- `HOLD` otherwise

Signals considered include:

- RSI divergence
- OBV flip down
- VPT bearish divergence
- Close below SMA20
- Broker flow flip (prior strong to recent weak asymmetry)
- Long-book fundamental invalidation (EPS <= 0 or PE > 40)

## Data Generated

`run_master_pipeline()` returns:

- `generated_at`
- `mode`
- `trading_mode`
- `equity`
- `quick`
- `market`
- `broker_flow`
- `meta`
- `hotlist`
- `short_plans`
- `swing_plans`
- `long_plans`
- `ranking`
- `tracked`

Notable structures:

- `hotlist` rows include selected plans per timeframe and broker-flow context fields
- `ranking` contains enriched per-symbol analytics used for classification
- `tracked` contains verdict flags and trigger notes per tracked symbol

## HTML Output

- Report filename: `master_trader_report_YYYY-MM-DD.html`
- Written to `--output` directory if provided; otherwise project root.

## Practical Usefulness

- Best use: unified decision desk for multi-horizon trading.
- Why useful:
  - Reduces tool switching by merging screening, setup detection, and plan generation.
  - Produces bucket-specific plans (short/swing/long) from one universe pass.
  - Adds tracking verdicts for open positions, not just fresh ideas.
