# Swing Analyser Documentation

## What it is

The swing_analyser package targets 1-2 month swing opportunities. It has two scoring systems:

- Strict swing pipeline (hard filters + setup-first selection)
- Universal ranking pipeline (scores all equities with soft penalties)

## Run Commands

- `python -m swing_analyser --mode swing`
- `python -m swing_analyser --mode rank`
- `python -m swing_analyser --mode full`

Common options:

- `--top N`
- `--min-volume N`
- `--equity N`
- `--output DIR`

## Data Inputs (DB)

Main tables:

- `daily_ohlcv`, `daily_prices`, `securities`
- `live_market_snapshots`
- `company_details`, `company_fundamentals`
- `dividends`, `corporate_actions`
- `floorsheet_transactions`
- `market_indices`

### Candle Stitching Policy (2026-04-02)

- `daily_ohlcv` is the primary source for long history.
- Missing symbol-date gaps are stitched from `daily_prices` before indicator computation.
- Open price resolution prefers `daily_prices.open_price`, then `daily_ohlcv.open_price`, then close-price proxy.
- Current-day partial candles from `daily_prices` are excluded (`trading_date < CURDATE()`).
- This avoids one-session lag in swing signals when upstream OHLCV lags.

## Core Constants

Strict swing engine:

- `RISK_PCT = 0.015`
- `ATR_SL_MULT = 1.5`
- `ATR_T1_MULT = 3.0`
- `ATR_T2_MULT = 5.0`
- `RSI_OVERBOUGHT = 80`, `RSI_OVERSOLD = 20`
- `LOW_LIQ_THRESH = 5000`
- `CIRCUIT_LIMIT = 0.10`
- `MIN_RR_RATIO = 2.0`
- `MIN_DATA_BARS = 100`
- `MAX_ATR_PCT = 8.0`

Ranking engine:

- `RANK_MIN_BARS = 60`
- `RANK_MIN_VOL = 1000`
- `HOTLIST_MIN_SCORE = 65` (and setup required)

## Calculations

### A) Strict swing composite (`run_swing_analysis`)

Base weighted formula:

- `composite = 0.25*trend + 0.20*mom + 0.20*vol + 0.15*setup + 0.10*risk + 0.10*funda`

Then adjusted:

- `composite = clamp( composite * regime_factor + seasonality_adj, 0, 100 )`

Component behavior:

- `trend`: SMA structure, weekly uptrend bonus, golden/death cross adjustment
- `mom`: RSI regime, MACD histogram, bullish MACD crossover, ROC20/ROC60
- `vol`: volume ratio, OBV trend, broker asymmetry contribution
- `setup`: confidence from detected named setup
- `risk`: ATR%, ADX weakness penalty, BB stretch penalty, 52W proximity effect
- `funda`: EPS/PE-based floor score

### B) Strict hard filters (before setup acceptance)

Symbol is skipped if:

- Candle history < 100 bars
- Low liquidity (below volume threshold)
- Circuit volatile profile
- Below SMA200 unless oversold-near-52W-low carve-out applies
- ATR% > 8
- No valid swing setup detected

Final candidate inclusion:

- Signal in `BUY` or `STRONG BUY`
- `rr_ratio >= 2.0`

### C) Universal ranking mode (`scoring.py`)

Penalty-based score for every stock (not only strict survivors), with tier mapping:

- `PRIME >= 80`
- `STRONG >= 65`
- `WATCH >= 50`
- `WEAK >= 35`
- else `AVOID`

Hotlist rule in ranking mode:

- Score >= 65 and setup present

## Data Generated

Strict mode output keys:

- `watchlist`
- `rejected`
- `setup_distribution`
- `sector_breadth`
- `regime`
- `total_universe`
- `total_processed`
- `total_analyzed`
- `total_candidates`
- `errors`
- `account_equity`
- `generation_time`

Notes:

- `total_universe`: symbols fetched into the strict-mode universe
- `total_processed`: symbols iterated in the analysis loop
- `total_analyzed`: symbols retained in `analysis_results` context (backward-compatible key)

Per watchlist item fields include:

- Setup metadata (`setup_type`, `setup_reasoning`, `all_setups`, `confidence`)
- Signals and trade levels (`signal`, `entry_zone`, `stop_loss`, `target_1`, `target_2`, `rr_ratio`, `position_size`, `hold_period`)
- Indicators, risk fields, fundamentals, and score breakdown

Ranking mode data includes:

- Universe ranking rows, tiers, and hotlist candidates
- Score components for comparison across symbols

## HTML Outputs

- Swing strict report: `swing_report_YYYY-MM-DD.html`
- Ranking/full report: `swing_ranking_YYYY-MM-DD.html`
- Output location uses `--output` if provided.

## Practical Usefulness

- Best use: medium-horizon setup hunting with risk-aware filtering.
- Why useful:
  - Strict mode gives high-quality, filtered trade candidates.
  - Ranking mode avoids blind spots by scoring every stock.
  - ATR-based sizing and R:R gating make ideas tradable, not just analytical.
  - Sector breadth and regime layers reduce false positives during weak markets.
