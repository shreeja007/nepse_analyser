# Broker Tracker — HTML Output Documentation

This document explains the **generated Broker Tracker HTML report** (the file under `broker_tracker_reports/broker_tracker_YYYY-MM-DD.html`).

It is written for **new users** who want to understand:

- what each section/table means,
- what every field/column represents,
- and how each value is calculated from floorsheet + price data.

> Scope: this is about the **report output**, not code internals.

---

## 1) What the Broker Tracker report is

The Broker Tracker report is a dashboard that reconstructs **broker-by-broker behavior** from NEPSE floorsheet history.

At a high level it:

1. Aggregates floorsheet trades by **(trading_date, symbol, broker)** separately for buyer and seller side.
2. Produces per-session broker activity (buy qty/value, sell qty/value, net).
3. Builds a simple lifecycle state machine per **(broker, symbol)** (ENTERING → ACCUMULATING → HOLDING → DISTRIBUTING → EXITING → FLAT).
4. Extracts “cycles” and computes broker “trust” scores.
5. Emits:
   - BUY/WATCH/EXIT signal tables,
   - a broker leaderboard,
   - deep-dive collapsibles per broker,
   - a stock-level broker activity summary for symbols with active signals.

Important interpretation note:

- The report tracks **broker activity**, not a single investor.
- “Position” is an inferred net position from broker buy vs sell volume; it is **not a verified holdings ledger**.

---

## 2) Data inputs (where all numbers come from)

### 2.1 Floorsheet transactions (primary source)

All buy/sell quantities and values come from the `floorsheet_transactions` table.

Each floorsheet record is assumed to provide, at minimum:

- `trading_date`
- `symbol`
- `security_name`
- `quantity`
- `amount`
- `buyer_broker_id`, `buyer_broker_name`
- `seller_broker_id`, `seller_broker_name`

The report aggregates these transactions into per-session broker totals.

### 2.2 Latest prices (for current price and unrealized P&L)

The report uses the most recent close price per symbol from `daily_ohlcv`:

- `close_price` (most recent date per symbol)

If a symbol has no close price available, **Current** price fields show `—`.

### 2.3 Sector mapping (for “Sector” columns and preferred sectors)

Sector is taken from:

1. `company_details.sector_name` (preferred), falling back to
2. `securities.sector_name`

If neither exists for a symbol, sector displays as `—`.

---

## 3) Core metrics computed per broker-symbol-session

All per-session calculations are done on the aggregated ledger for each tuple:

**Key**: `(trading_date, symbol, broker_id)`

### 3.1 Aggregated raw fields

- **Bought Qty**: sum of `quantity` where the broker is the _buyer_ for that symbol and date.
- **Bought Value**: sum of `amount` where the broker is the buyer.
- **Sold Qty**: sum of `quantity` where the broker is the _seller_.
- **Sold Value**: sum of `amount` where the broker is the seller.

Units:

- Qty is in **shares/units**.
- Values are in **NPR (Rs)**.

### 3.2 Derived activity fields

- **Net Qty**: `net_qty = bought_qty - sold_qty`
- **Total Qty**: `total_qty = bought_qty + sold_qty`

### 3.3 Asymmetry (%)

Asymmetry is a buy-vs-sell dominance ratio computed from **quantity**:

- If `total_qty == 0` (no trade that session): `asymmetry = 50.0`
- Else:  
  `asymmetry = (bought_qty / total_qty) * 100`

Interpretation:

- **100%** means broker only bought that day (no sells).
- **0%** means broker only sold that day (no buys).
- **50%** means balanced buys and sells (or no activity in synthetic holding rows).

### 3.4 Average buy/sell price for the session

- **Avg Buy**: if `bought_qty > 0` then `avg_buy_price = bought_value / bought_qty`, else `—`
- **Avg Sell**: if `sold_qty > 0` then `avg_sell_price = sold_value / sold_qty`, else `—`

---

## 4) Lifecycle states (what “State” means)

Broker Tracker assigns a lifecycle **state per (broker, symbol, date)** using a state machine driven by:

- net buying vs net selling,
- consecutive streaks,
- “quiet gaps” between trades,
- and the inferred cumulative net position.

### 4.1 Key running values

For each `(broker, symbol)`, the report maintains:

- **Consecutive net buy sessions**: increments when `net_qty > 0`, resets otherwise.
- **Consecutive net sell sessions**: increments when `net_qty < 0`, resets otherwise.
- **Cumulative Net Qty**: running sum of `net_qty` over time:
  `cumulative_net_qty(t) = Σ net_qty(session_i)`

### 4.2 Synthetic HOLDING rows (important)

If there is a long enough gap in trading activity for a broker-symbol, the report inserts **at most one synthetic “HOLDING trigger” row** to make the timeline more readable.

- These synthetic rows have `net_qty = 0`, `bought_qty = 0`, `sold_qty = 0`, `asymmetry = 50`, and no avg prices.
- They are **included** in the _timeline transitions_.
- They are **excluded** from the _Position History_ table (which is “Trades only”).

### 4.3 Thresholds used

These are the defaults used by the report:

- **MIN_SESSIONS_FOR_ACCUMULATION**: 3
- **HOLDING_GAP_SESSIONS**: 2
- **EXIT_CONFIRMATION_SESSIONS**: 2
- **FLAT_QTY_THRESHOLD**: 10 shares

### 4.4 State definitions (rules)

The state is computed from the current session and the running context:

1. **FLAT** (takes priority once position is near zero)

- If `abs(cumulative_net_qty) < 10` → `FLAT`

2. If `net_qty > 0` (net buy day)

- If consecutive net buy sessions ≥ 3 → **ACCUMULATING**
- Else → **ENTERING**

3. If `net_qty <= 0` and `cumulative_net_qty > 0` (broker still has net long position)

- If “quiet gap” is detected and `net_qty == 0` → **HOLDING**
- Else if consecutive net sell sessions ≥ 2 and `net_qty < 0` → **EXITING**
- Else → **DISTRIBUTING**

4. Otherwise

- **FLAT**

Practical interpretation:

- **ENTERING**: starting to buy, but not yet a sustained streak.
- **ACCUMULATING**: sustained net buying across sessions.
- **HOLDING**: position exists, but no meaningful trading for a while.
- **DISTRIBUTING**: selling begins while position is still net long.
- **EXITING**: selling is sustained and likely closing out.
- **FLAT**: position is near zero (or net not long).

---

## 5) Cycles, win rate, and broker trust

### 5.1 What is a “cycle”

A **cycle** is detected per `(broker, symbol)` timeline.

Cycle definition:

- The broker-symbol timeline must reach **ACCUMULATING at least once**, and then later return to **FLAT**.

That is considered one “completed cycle”.

### 5.2 Entry price and exit price used for cycle win/loss

Within the cycle segment:

- **Entry price**: first available of:
  - `avg_buy_price`, else
  - `cumulative_avg_cost` (cumulative buy value / cumulative buy qty)

- **Exit price**: last available `avg_sell_price` in the segment.

Cycle outcome:

- **Win** if `exit_price > entry_price` (only if both are available).

### 5.3 Avg hold (sessions)

For a completed cycle segment:

- Finds the first session in the segment that is `ENTERING` or `ACCUMULATING`.
- Finds the first session later that is `DISTRIBUTING` or `EXITING`.
- **Hold sessions** is the distance between those two indices.

The report displays broker-level **Avg hold (sessions)** as the average of those hold sessions across all completed cycles.

### 5.4 Trust label and trust score

A broker is:

- **UNRATED** if `completed_cycles < 5`.

Otherwise, trust score is a weighted score (0–100-ish scale) built from:

- Win rate (40%)
- Consistency / sample size growth (30% + 20%)
- Recency (10%) based on last 3 cycles

The score is:

- `win_rate_score = win_rate * 100 * 0.40`
- `consistency_score = min(completed_cycles/20, 1) * 100 * 0.30`
- `sample_score = min(completed_cycles/50, 1) * 100 * 0.20`
- `recency_score = recent_win_rate * 100 * 0.10`

`trust = win_rate_score + consistency_score + sample_score + recency_score`

Label mapping:

- `< 40` → LOW
- `< 70` → MEDIUM
- `≥ 70` → HIGH

### 5.5 Data maturity badge

The report also shows a “data maturity” badge in deep dives:

- LOW if completed cycles < 3
- MEDIUM if completed cycles < 10
- HIGH otherwise

Additionally, a **top banner** “Data maturity: LOW” appears when the report contains fewer than **30 trading sessions** of floorsheet history.

---

## 6) Report sections and field-by-field reference

### 6.1 Header

- Title: “NEPSE Broker Tracker”
- Subtitle: “Broker accumulation/distribution lifecycle + signals”

### 6.2 Data Summary card

This summarizes the dataset used to generate the report.

Fields:

- **Date range**: min and max `trading_date` found in aggregated floorsheet activity.
- **Generated**: report generation timestamp.
- **Brokers tracked**: count of distinct brokers observed in floorsheet history.
- **Stocks covered**: number of distinct symbols in the activity ledger.
- **Total transactions**: total row count of `floorsheet_transactions`.
- **Trading sessions**: number of unique `trading_date` values in the activity ledger.

### 6.3 Signals (BUY / WATCH / EXIT)

Signals are “attention lists” derived from the current lifecycle state and recent behavior.

#### 6.3.1 BUY Signals table

Columns:

- **Symbol**: security symbol.
- **Broker**: `broker_id — broker_name`.
- **Trust**: broker trust label/score (HIGH/MEDIUM/LOW/UNRATED).
- **Sessions**: trailing consecutive count of **ACCUMULATING** sessions (trade sessions only).
- **Avg Buy**: last available `avg_buy_price` in recent trade sessions (not necessarily cycle-average).
- **Current**: latest close price from `daily_ohlcv`.
- **Move %**: percent change of current price relative to the cycle entry price:
  `((current_price / entry_price) - 1) * 100`
- **Asym**: asymmetry (%) from the most recent trade session.
- **Strength**: STRONG / MODERATE / WEAK (rules below).

A row appears as BUY when, at the latest session summary:

- Current state is **ACCUMULATING**
- latest asymmetry is above 65
- cumulative net qty is still growing vs previous trade session
- price move since entry is within ±8% (avoid late chases)
- sessions traded is at least 2

#### 6.3.2 WATCH Signals table

Columns are the same as BUY.

A row appears as WATCH when:

- Current state is **ENTERING**
- latest asymmetry > 60
- and the broker is either trusted (>50 trust score) or UNRATED (allowed for discovery)

Why “Sessions” can be 0 in WATCH:

- It counts **ACCUMULATING** streak; ENTERING typically has 0 accumulating sessions.

#### 6.3.3 EXIT Signals table

Columns:

- **Symbol**
- **Broker**
- **Trust**
- **State Changed**: “YES” if the state just transitioned into DISTRIBUTING/EXITING from a non-distribution state.
- **Qty Remaining**: `cumulative_net_qty` (net long shares remaining).
- **Avg Buy**: last available `avg_buy_price` (if available).
- **Current**: latest close price.
- **P&L If Held**: a rough mark-to-market value:
  `(current_price - avg_buy_price) * cumulative_net_qty`

An EXIT candidate is flagged if _any_ of these exit triggers are true:

- State changed into DISTRIBUTING/EXITING
- Asymmetry dropped sharply (was >65, now <40)
- Quantity dropped significantly (current < 70% of two-trades-ago)

The row is only emitted as EXIT if the current state is **DISTRIBUTING** or **EXITING**.

#### 6.3.4 Signal strength

Signal strength is a heuristic label based on trust + asymmetry + accumulating sessions.

Interpretation:

- STRONG typically means high trust and strong buy dominance or sustained accumulation.
- MODERATE and WEAK are lower confidence.

### 6.4 Broker Leaderboard

This table ranks brokers (1..N) in the order the report sorts them.

Sorting rule:

- Brokers with a trust score rank above UNRATED brokers.
- Within rated brokers: higher trust first, then more completed cycles, then higher trade value.
- Within UNRATED: higher total trade value first.

Columns:

- **Rank**: row number after sorting.
- **Broker**: `broker_id — broker_name`.
- **Trust**: HIGH/MEDIUM/LOW/UNRATED with score when available.
- **Win Rate**: `win_cycles / completed_cycles` (shown only when rated).
- **Cycles**: completed cycles count.
- **Avg Hold**: average hold sessions (see Cycle section).
- **Preferred Sectors**: top 3 sectors by total traded value.
- **Accumulating**: list of symbols where the broker is currently in ACCUMULATING state.
- **Distributing**: list of symbols where the broker is currently in DISTRIBUTING or EXITING.

### 6.5 Per-Broker Deep Dives

This section contains a collapsible panel per broker.

#### 6.5.1 Collapsible header

Shows:

- **Broker {id} — name**
- **(X stocks)**: how many unique symbols that broker traded in the dataset.
- **Trust badge**
- **Data maturity badge**

#### 6.5.2 Summary card

Fields:

- **Completed cycles**: count of completed broker-symbol cycles (see cycles definition).
- **Win rate**: win ratio (only meaningful when rated).
- **Avg hold (sessions)**: average hold sessions across cycles.
- **Avg buy size**: average of per-session `bought_value` for sessions where `bought_qty > 0`.

#### 6.5.3 Preferred Sectors card

- Shows the top 3 sectors by total traded value for that broker.

#### 6.5.4 Current Focus card

- **Accumulating**: symbols where current state is ACCUMULATING.
- **Distributing**: symbols where current state is DISTRIBUTING or EXITING.

#### 6.5.5 Position History table (Trades only)

This table loads dynamically when you expand a broker.

Columns:

- **Date**: trading session date.
- **Symbol**
- **Sector**
- **Bought**: session `bought_qty`.
- **Sold**: session `sold_qty`.
- **Net**: session `net_qty`.
- **Cumulative**: running `cumulative_net_qty`.
- **Avg Buy**: session `avg_buy_price`.
- **Avg Sell**: session `avg_sell_price`.
- **Asym**: session `asymmetry`.
- **State**: computed lifecycle state.
- **Unrealized P&L**: rough mark-to-market using latest close:
  `(current_price - cumulative_avg_cost) * cumulative_net_qty` (only when cumulative net qty > 0)

Important limitations of Unrealized P&L:

- `cumulative_avg_cost` is computed from **cumulative buys only** (buy value / buy qty) and does not perform inventory accounting when sells happen.
- Treat it as a directional indicator, not an accounting-grade P&L.

#### 6.5.6 State Transition Timeline

Shows, per symbol, only the **state change points**:

Format:

- `SYMBOL: [STATE YYYY-MM-DD] → [STATE YYYY-MM-DD] → ...`

Notes:

- HOLDING can appear here because the timeline includes synthetic holding trigger rows.

### 6.6 Stock-Level Broker Activity (Only symbols with active signals)

This section is a quick view of which brokers are currently accumulating/distributing for the symbols that appear in BUY/WATCH/EXIT.

Columns:

- **Symbol**
- **Current Price**: latest close from `daily_ohlcv`.
- **Brokers Accumulating**: broker IDs whose latest state for this symbol is ACCUMULATING.
- **Brokers Distributing**: broker IDs whose latest state is DISTRIBUTING or EXITING.
- **Net Sentiment**: `(#accumulating brokers) - (#distributing brokers)`, clamped to the range [-5, +5].

Interpretation:

- Positive sentiment means more brokers are in accumulation than distribution.
- Negative sentiment means the opposite.
- It is **not weighted** by volume/value (each broker counts as 1).

---

## 7) How missing values are shown

The report uses `—` for “not available”, commonly when:

- the symbol has no latest close price,
- there was no buy (so Avg Buy is empty),
- there was no sell (so Avg Sell is empty),
- a P&L value cannot be computed.

---

## 8) Quick interpretation cheatsheet

- **Asym ~ 100%** + **ACCUMULATING** for multiple sessions → broker is persistently net buying.
- **Cumulative** growing steadily → broker’s inferred net position is increasing.
- **State changed** into DISTRIBUTING/EXITING → broker started net selling after being net long.
- **EXIT signal** → distribution behavior is detected; check if cumulative qty is dropping.
- **Trust HIGH** with many cycles → broker behavior historically produced “wins” under this cycle definition.

---

## 9) Common “why does this look weird?” answers

- **WATCH shows Sessions = 0**: Sessions counts ACCUMULATING streak; ENTERING often has 0.
- **Current price is `—`**: no close price found for that symbol in `daily_ohlcv`.
- **Unrealized P&L is blank**: requires current price + positive cumulative net qty + a cumulative avg cost.
- **Cumulative is negative**: the broker sold more than bought (net short-ish in the ledger); state logic often collapses to FLAT in such cases.

---

## 10) Glossary

- **Session**: one trading day (`trading_date`).
- **Broker-symbol**: a pair `(broker_id, symbol)` tracked over time.
- **Net Qty**: bought qty minus sold qty for that broker-symbol-session.
- **Cumulative Net Qty**: running net total across sessions.
- **Asymmetry**: buy dominance percentage by quantity.
- **Cycle**: a full accumulation episode that returns to FLAT after ACCUMULATING at least once.
- **Trust**: a heuristic score derived from historical cycle outcomes and sample size.
