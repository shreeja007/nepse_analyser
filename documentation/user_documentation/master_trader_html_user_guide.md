# Master Trader HTML Report User Guide

## Purpose

This guide explains the output file `master_trader_report_YYYY-MM-DD.html` in simple language.
Use it to understand every section of the report and make cleaner, rule-based trading decisions.

This document is for normal users (not developers).

## What This Report Is

The Master Trader report is a full trading dashboard in one page:

1. It checks market condition.
2. It gives top trade opportunities.
3. It gives ready trade plans (entry, stop, targets, hold period).
4. It gives risk and confidence context.
5. It helps track open trades with hold/trim/exit signals.

## Before You Trade

Always scan these first (top to bottom):

1. Data Sources And Accuracy
2. Market Dashboard
3. Hotlist
4. Bucket plans (Short, Swing, Long)
5. Full Universe Ranking (View details)
6. Exit Signal Tracker (if you already hold positions)

## 1) Header (Top Banner)

At the top you will see:

- `Generated`: report generation time.
- `Mode`: `TRADING` or `SCREENING`.
- `Universe`: number of symbols considered.
- `Short`, `Swing`, `Long`, `Hotlist`: number of picks in each group.

How to use:

- If generated time is old, do not take aggressive entries.
- If hotlist count is very low, be selective and reduce position size.

## 2) Data Sources And Accuracy

This section is your quality checkpoint.

You will see KPIs like:

- `Accuracy Score`
- `Data Freshness`
- `Equity Zero Volume`
- `Missing vs daily_prices`
- `Bad Close Rows`
- `Processed Symbols`
- `Avg Execution Confidence`
- `A/B Data Grade Share`

You will also see the exact database tables used (for transparency), for example:

- `daily_ohlcv`
- `daily_prices`
- `live_market_snapshots`
- `floorsheet_transactions`
- `market_summary`
- `nepse_sub_indices`
- `scrip_rankings`
- `company_details`
- `company_fundamentals`
- `securities`

How to use:

1. If `Data Freshness` is `STALE`, reduce risk or wait.
2. If `Accuracy Score` is weak, avoid marginal setups.
3. If `Equity Zero Volume` or `Missing vs daily_prices` is high, trust only strongest signals.

## 3) Market Dashboard

This shows broad market context:

- `Regime`
- `Turnover`
- `Adv / Dec`
- `Transactions`
- Sector sub-index table (value and change)

How to use:

- Favor longs when regime and breadth are healthy.
- Be careful with aggressive buys when breadth is weak.

## 4) Hotlist (max 5)

This is the highest-conviction short list.

Each card shows:

- Symbol and company
- Score and action (`BUY`, `WATCH`, `AVOID`)
- Fused score, priority tier, execution confidence, data grade
- Broker state and signal bias
- Timeframes where it qualifies (`short`, `swing`, `long`)
- Broker flow stats
- Warnings (veto watch, book closure)

How to use:

1. Start your watchlist from here.
2. Prefer symbols with `BUY`, stronger fused score, and better data quality.
3. Respect warning text before entering.

## 5) Broker Heavy Buy/Sell Flow

This section summarizes broker behavior in recent sessions.

Blocks:

- `Top Accumulation (Buy Side)`
- `Top Distribution (Sell Side)`
- `Most Active Broker Flow`

Key fields:

- Buy amount, sell amount
- Buy/Sell ratio
- Signal badge (`BUY HEAVY`, `SELL HEAVY`, `TWO-WAY`, `NO FLOW`)

How to use:

- Strong accumulation can support continuation entries.
- Heavy distribution is a caution for fresh longs.
- `TWO-WAY` means mixed conviction, so require tighter risk control.

## 6) Trade Plan Sections

There are 3 plan tables:

- `Short-Term Plays (1-5 days)`
- `Swing Trades (1-2 months)`
- `Long-Term Accumulation (6+ months)`

Each row gives:

- `Entry Zone`
- `Stop`
- `T1`, `T2`, `T3`
- `R:R`
- `Broker Flow`
- `Hold`
- `Why Included`
- `Exit Plan`

In trading mode, you may also see `Size` (position size suggestion).

How to use:

1. Enter only near entry zone.
2. Place stop immediately.
3. Do not take setups with weak R:R compared to your rules.
4. Use `Why Included` and `Exit Plan` before placing orders.

## 7) Why These Stocks (Inside Each Plan Section)

Use the `View` button in plan sections.

You get expanded explainability cards with:

- Selection criteria (`PASS`, `FAIL`, `INFO`)
- Setup reasoning
- Why buy
- Why sell or trim risk
- Risk snapshot (fused score, execution confidence, data quality, volatility, drawdown, veto reasons)
- Broker flow details (top buyers/sellers, intensity, trust, maturity)

How to use:

- This is the best place to validate a setup before committing capital.

## 8) Full Universe Ranking

This is the broad ranked list of all candidates.

Columns include:

- Score and fused score
- Priority tier
- Execution confidence
- Data quality
- Broker alignment
- Action
- Tier and setup
- Sector rank and sector RSI
- Turnover rank and volume ratio
- Broker asymmetry and broker flow

Use `View` on any row to open deep modal details.

## 9) Ranking Modal (Deep Detail)

When you click `View` in full ranking, you get advanced diagnostics:

- Selection criteria by bucket
- Setup reasoning
- Why buy / why sell
- Decision intelligence:
  - Fused score
  - Opportunity score
  - Safety multiplier
  - Explicit penalties
  - Component contributions
- Risk snapshot:
  - Active buckets
  - R:R
  - Entry/stop/target ranges
  - Sector rank
  - Volatility and drawdown
- Broker block:
  - Buy/sell amount
  - Buy/sell ratio
  - Flow intensity
  - Lifecycle state
  - Signal strength
  - Trust and maturity
  - Top brokers

How to use:

- Use this modal before larger position sizes or borderline setups.

## 10) Exit Signal Tracker

This section is for existing/open positions.

Fields:

- `Verdict`: `HOLD`, `TRIM`, `EXIT`, or `DATA_UNAVAILABLE`
- `Broker Flow (Recent/Prior)`
- `Conf Decay`
- `State Shift`
- `Exit Meta`
- `Trigger Notes`

How to use:

1. `EXIT`: close position according to your execution policy.
2. `TRIM`: reduce risk, partially book, or tighten stop.
3. `HOLD`: keep plan active but continue monitoring.

## Badge Meanings

### Action badge

- `BUY`: strongest actionable bias.
- `WATCH`: setup is incomplete or moderate quality.
- `AVOID`: avoid fresh entry unless context changes.

### Broker flow badge

- `BUY HEAVY`: buy pressure dominant.
- `SELL HEAVY`: sell pressure dominant.
- `TWO-WAY`: mixed flow.
- `NO FLOW`: no clear broker flow edge.

## Practical Daily Workflow (Simple)

1. Open latest master trader HTML report.
2. Check Data Sources And Accuracy first.
3. Check Market Dashboard for broad risk-on/risk-off tone.
4. Build shortlist from Hotlist + top rows in plan sections.
5. Open `View` for each candidate and confirm:
   - acceptable entry and stop,
   - acceptable R:R,
   - acceptable data quality,
   - no critical veto warnings.
6. Enter only when price is in entry zone.
7. Track open trades with Exit Signal Tracker.
8. Review again after next report update.

## Risk Rules You Should Keep

- Never enter without a stop.
- Never increase size on weak data quality.
- Avoid forcing trades when quality metrics are poor.
- Respect `EXIT` and `TRIM` signals for risk control.
- Keep per-trade risk capped by your plan.

## Important Note

This report is a decision-support tool, not guaranteed profit.
Final execution responsibility is always with the trader.
Discipline and risk management matter more than any single score.
