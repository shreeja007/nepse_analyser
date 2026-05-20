# 🏦 Broker Tracker Analyser — Full Implementation Specification

> **Project**: NEPSE Broker Tracker Analyser
> **Role of this file**: Complete technical blueprint for implementation. Attach this to the VSCode agent alongside the prompt.
> **Database**: `nepsego` MySQL/MariaDB at `127.0.0.1:3306`
> **Language**: Python 3, following the exact same patterns as the existing `analysor/` and `single_analyser/` modules in this project.
> **Output**: CLI summary + self-contained HTML report

---

## 📁 Project Structure to Create

```
broker_tracker/
├── __init__.py          # CLI entry point
├── config.py            # DB config, thresholds, constants
├── data.py              # All DB queries and raw aggregations
├── positions.py         # Lifecycle state machine per broker-stock
├── intelligence.py      # Broker profiles and trust scores
├── signals.py           # BUY / HOLD / EXIT signal generation
└── html_report.py       # Full HTML report generator
```

Create this as a sibling directory to the existing `analysor/` and `single_analyser/` directories.

---

## 🗄️ Database Context

**Connection**: Use `pymysql` with `DictCursor`, same as the existing `analysor/logic.py`.

**Primary table**: `floorsheet_transactions` — 83,075 rows, growing daily.

```sql
-- floorsheet_transactions key columns:
trade_book_id, trading_date, contract_id,
symbol, security_id, security_name,
buyer_broker_id, buyer_broker_name,
seller_broker_id, seller_broker_name,
quantity, rate, amount
```

**Supporting tables used**:
- `daily_ohlcv` — historical OHLCV (note: `open_price` is ALL ZEROS, use `close_price` for price context)
- `daily_prices` — recent OHLC with real open prices (only ~1,632 rows, recent dates only)
- `company_details` — sector_name, market_cap, 52W H/L
- `securities` — full symbol list, sector fallback

**Broker universe**: No dedicated `brokers` table with data. Build the broker universe dynamically from:
```sql
SELECT DISTINCT buyer_broker_id AS broker_id, buyer_broker_name AS broker_name
FROM floorsheet_transactions
UNION
SELECT DISTINCT seller_broker_id, seller_broker_name
FROM floorsheet_transactions
ORDER BY broker_id
```

---

## ⚙️ config.py

```python
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'root',
    'password': '',
    'database': 'nepsego',
    'charset': 'utf8mb4',
    'cursorclass': 'DictCursor'
}

# Signal thresholds
ACCUMULATION_ASYMMETRY_THRESHOLD = 65   # % of activity that is buying = accumulation
DISTRIBUTION_ASYMMETRY_THRESHOLD = 40   # % drops below this = distributing
MIN_SESSIONS_FOR_ACCUMULATION = 3        # must be active buying for at least 3 sessions
MIN_SESSIONS_FOR_TRUST_SCORE = 5         # need at least 5 completed cycles for trust score
MIN_ACTIVITY_THRESHOLD = 2              # broker must have traded a stock in 2+ sessions to be considered active

# State machine
HOLDING_GAP_SESSIONS = 2               # sessions of inactivity before state = HOLDING
EXIT_CONFIRMATION_SESSIONS = 2         # sessions of net sell before state = EXITING

# Report
TOP_N_BROKERS_LEADERBOARD = 20
TOP_N_SIGNALS = 15
OUTPUT_DIR = 'broker_tracker_reports'
```

---

## 📊 data.py — All DB Queries

### Function: `get_db_connection()`
Standard pymysql connection using DB_CONFIG. Return connection with DictCursor.

### Function: `get_broker_universe(conn)`
Returns list of all brokers: `[{broker_id, broker_name, total_transactions, first_seen_date, last_seen_date}]`

```sql
SELECT 
    broker_id, broker_name,
    COUNT(*) AS total_transactions,
    MIN(trading_date) AS first_seen_date,
    MAX(trading_date) AS last_seen_date
FROM (
    SELECT buyer_broker_id AS broker_id, buyer_broker_name AS broker_name, trading_date
    FROM floorsheet_transactions
    UNION ALL
    SELECT seller_broker_id, seller_broker_name, trading_date
    FROM floorsheet_transactions
) combined
GROUP BY broker_id, broker_name
ORDER BY total_transactions DESC
```

### Function: `get_all_broker_activity(conn)`
**This is the core query.** Returns the FULL aggregated activity for every broker × symbol × trading_date combination across ALL history. No date filter.

```sql
SELECT
    trading_date,
    symbol,
    security_name,
    buyer_broker_id   AS broker_id,
    buyer_broker_name AS broker_name,
    SUM(CASE WHEN buyer_broker_id = buyer_broker_id THEN quantity ELSE 0 END) AS bought_qty,
    SUM(CASE WHEN buyer_broker_id = buyer_broker_id THEN amount ELSE 0 END)   AS bought_value,
    0 AS sold_qty,
    0 AS sold_value
FROM floorsheet_transactions
GROUP BY trading_date, symbol, buyer_broker_id, buyer_broker_name

UNION ALL

SELECT
    trading_date,
    symbol,
    security_name,
    seller_broker_id   AS broker_id,
    seller_broker_name AS broker_name,
    0, 0,
    SUM(quantity) AS sold_qty,
    SUM(amount)   AS sold_value
FROM floorsheet_transactions
GROUP BY trading_date, symbol, seller_broker_id, seller_broker_name
```

> **Note to implementer**: After fetching this, aggregate in Python using pandas groupby on `(broker_id, symbol, trading_date)` summing all four qty/value columns. This gives you the clean per-broker-per-stock-per-day ledger.

**Derived columns to compute in Python after fetch:**
```python
df['net_qty'] = df['bought_qty'] - df['sold_qty']
df['total_qty'] = df['bought_qty'] + df['sold_qty']
df['asymmetry'] = (df['bought_qty'] / df['total_qty'] * 100).where(df['total_qty'] > 0, 50)
df['avg_buy_price'] = (df['bought_value'] / df['bought_qty']).where(df['bought_qty'] > 0, None)
df['avg_sell_price'] = (df['sold_value'] / df['sold_qty']).where(df['sold_qty'] > 0, None)
```

### Function: `get_latest_prices(conn)`
Get the most recent close price for each symbol for P&L context:
```sql
SELECT symbol, close_price, trading_date
FROM daily_ohlcv
WHERE (symbol, trading_date) IN (
    SELECT symbol, MAX(trading_date) FROM daily_ohlcv GROUP BY symbol
)
```

### Function: `get_company_sector_map(conn)`
```sql
SELECT symbol, sector_name, market_capitalization, fifty_two_week_high, fifty_two_week_low
FROM company_details
```

---

## 🔄 positions.py — Lifecycle State Machine

### Lifecycle States (enum or constants)
```python
STATES = {
    'INACTIVE':      'INACTIVE',       # Never traded this stock
    'ENTERING':      'ENTERING',       # 1-2 sessions of net buy
    'ACCUMULATING':  'ACCUMULATING',   # 3+ sessions consistent net buy
    'HOLDING':       'HOLDING',        # Net long but went quiet (2+ sessions no trade)
    'DISTRIBUTING':  'DISTRIBUTING',   # Started net selling
    'EXITING':       'EXITING',        # Heavy net sell, position collapsing fast
    'FLAT':          'FLAT',           # Cumulative position back near zero
}
```

### Function: `compute_broker_stock_positions(activity_df)`

Input: The aggregated broker-activity DataFrame from data.py.

For each unique `(broker_id, symbol)` pair:

1. **Sort sessions by `trading_date` ascending.**

2. **Compute `cumulative_net_qty`** — running sum of `net_qty` over time. This is the reconstructed position.

3. **Compute `cumulative_avg_cost`** — weighted average cost of all buy transactions up to that session. Formula:
   ```
   cumulative_cost = sum(bought_value) / sum(bought_qty) up to that session
   ```

4. **Assign `session_state`** using this logic (in order of priority):

   ```
   IF cumulative_net_qty == 0 AND total sessions == 0:
       → INACTIVE

   IF cumulative_net_qty <= small_threshold (e.g. < 10 shares):
       → FLAT (they've exited)

   IF net_qty > 0:
       IF consecutive_net_buy_sessions >= MIN_SESSIONS_FOR_ACCUMULATION:
           → ACCUMULATING
       ELSE:
           → ENTERING

   IF net_qty <= 0 AND cumulative_net_qty > 0:
       IF sessions_since_last_trade >= HOLDING_GAP_SESSIONS:
           → HOLDING
       ELIF consecutive_net_sell_sessions >= EXIT_CONFIRMATION_SESSIONS:
           → EXITING
       ELSE:
           → DISTRIBUTING

   IF net_qty <= 0 AND cumulative_net_qty <= 0:
       → FLAT
   ```

5. **Compute `unrealized_pnl`** using latest price:
   ```python
   unrealized_pnl = (current_price - cumulative_avg_cost) * cumulative_net_qty
   unrealized_pnl_pct = ((current_price / cumulative_avg_cost) - 1) * 100
   ```

6. **Return a positions DataFrame** with one row per `(broker_id, symbol, trading_date)` including all derived fields, plus a **summary row** with the latest state for each broker-stock pair.

### Function: `get_state_transitions(positions_df)`
For each `(broker_id, symbol)`, extract the list of state transitions with dates. This powers the "story arc" section of the HTML report.

Example output:
```
Broker 47 in NABIL:
  2026-02-05 → ENTERING  (bought 500 @ 490)
  2026-02-06 → ACCUMULATING (total 1200 @ avg 491.5)
  2026-02-09 → HOLDING (quiet 2 sessions)
  2026-02-11 → DISTRIBUTING (sold 400)
  2026-02-12 → EXITING (sold 600, position near zero)
  2026-02-13 → FLAT
```

---

## 🧠 intelligence.py — Broker Profiles & Trust Scores

### Function: `build_broker_profiles(positions_df, activity_df, sector_map)`

For each broker, compute:

```python
profile = {
    'broker_id': int,
    'broker_name': str,
    'total_stocks_traded': int,          # unique symbols ever traded
    'total_volume_bought': int,
    'total_volume_sold': int,
    'total_value_bought': float,
    'total_value_sold': float,
    'preferred_sectors': list,           # top 3 sectors by value traded
    'avg_position_size_rs': float,       # avg Rs value of a buy position
    'completed_cycles': int,             # positions that went ACCUMULATING → FLAT
    'win_cycles': int,                   # of completed cycles, price was higher at exit than entry
    'win_rate': float,                   # win_cycles / completed_cycles (None if < MIN_SESSIONS_FOR_TRUST_SCORE)
    'avg_hold_sessions': float,          # avg sessions from ENTERING to DISTRIBUTING
    'data_maturity': str,                # 'LOW' / 'MEDIUM' / 'HIGH' based on completed_cycles
    'currently_accumulating': list,      # symbols currently in ACCUMULATING state
    'currently_distributing': list,      # symbols currently in DISTRIBUTING/EXITING state
    'trust_score': float,                # 0–100, see formula below
    'trust_label': str,                  # 'UNRATED' / 'LOW' / 'MEDIUM' / 'HIGH'
}
```

### Trust Score Formula

```python
def compute_trust_score(profile):
    if profile['completed_cycles'] < MIN_SESSIONS_FOR_TRUST_SCORE:
        return None, 'UNRATED'

    win_rate_score    = profile['win_rate'] * 100 * 0.40
    consistency_score = min(profile['completed_cycles'] / 20, 1.0) * 100 * 0.30
    sample_score      = min(profile['completed_cycles'] / 50, 1.0) * 100 * 0.20
    # recency: were their last 3 cycles wins?
    recency_score     = (recent_win_rate) * 100 * 0.10

    trust = win_rate_score + consistency_score + sample_score + recency_score

    label = 'LOW' if trust < 40 else 'MEDIUM' if trust < 70 else 'HIGH'
    return round(trust, 1), label
```

### Data Maturity Label

```python
def get_data_maturity(completed_cycles):
    if completed_cycles < 3:   return 'LOW'      # not enough to trust
    if completed_cycles < 10:  return 'MEDIUM'
    return 'HIGH'
```

Always display this in the report with a warning when `LOW` so the user knows the score is early-stage.

---

## 📡 signals.py — Signal Generation

### Function: `generate_signals(positions_df, broker_profiles, latest_prices)`

Returns a signals DataFrame, one row per actionable signal today.

**BUY signal criteria (ALL must be true):**
```
1. broker current state == ACCUMULATING
2. asymmetry in most recent session > ACCUMULATION_ASYMMETRY_THRESHOLD (65)
3. cumulative_net_qty is growing (not plateauing)
4. price has moved less than 8% since broker started entering (early stage)
5. stock has been traded in at least MIN_ACTIVITY_THRESHOLD sessions by this broker
```

**WATCH signal criteria:**
```
1. broker current state == ENTERING (early, not yet confirmed accumulation)
2. asymmetry > 60 in current session
3. trust_score > 50 OR 'UNRATED' (give benefit of doubt to unrated brokers with good current pattern)
```

**EXIT signal criteria (ANY is sufficient):**
```
1. broker state transitions to DISTRIBUTING or EXITING
2. asymmetry drops below DISTRIBUTION_ASYMMETRY_THRESHOLD (40) after being above 65
3. cumulative_net_qty dropped more than 30% in last 2 sessions
```

**Signal output columns:**
```python
signal = {
    'signal_type': 'BUY' | 'WATCH' | 'EXIT',
    'symbol': str,
    'broker_id': int,
    'broker_name': str,
    'broker_trust_score': float,
    'broker_trust_label': str,
    'current_state': str,
    'sessions_accumulating': int,
    'cumulative_net_qty': int,
    'avg_buy_price': float,
    'current_price': float,
    'price_move_since_entry_pct': float,
    'latest_asymmetry': float,
    'signal_strength': 'STRONG' | 'MODERATE' | 'WEAK',   # based on trust + asymmetry combo
    'signal_date': date,
}
```

---

## 🌐 html_report.py — HTML Report

Generate a **single self-contained HTML file** (all CSS + JS inline, no external dependencies). Follow the same pattern as `analysor/html_extractor.py` in this project.

### Report Sections

---

#### Section 1: Header & Market Context
- Report generation timestamp
- Total brokers tracked
- Total unique stocks in floorsheet
- Date range of data
- Total transactions analysed
- ⚠️ Data maturity warning banner if floorsheet history < 30 days

---

#### Section 2: 🚨 Active Signals (Top of Report)
Three cards/tables:

**BUY Signals** (green)
| Symbol | Broker | Trust | Sessions Accumulating | Avg Buy Price | Current Price | Move % | Asymmetry | Strength |

**WATCH Signals** (yellow)
Same columns.

**EXIT Signals** (red)
| Symbol | Broker | Trust | State Changed | Cumulative Qty Remaining | Avg Buy Price | Current Price | P&L if held |

---

#### Section 3: 🏆 Broker Leaderboard
Table of all brokers ranked by trust score (or by total value traded if UNRATED):

| Rank | Broker | Trust Score | Win Rate | Completed Cycles | Avg Hold | Preferred Sectors | Currently Accumulating | Currently Distributing |

Trust label badges: 🟢 HIGH / 🟡 MEDIUM / 🔴 LOW / ⚪ UNRATED

---

#### Section 4: Per-Broker Deep Dives
Collapsible section for each broker. Inside each broker section:

**Sub-section 4a: Broker Summary Card**
- Name, ID, trust score, win rate, data maturity
- Preferred sectors, avg position size
- Currently accumulating: [list of symbols]
- Currently distributing: [list of symbols]

**Sub-section 4b: Full Position History Table**
One row per `(symbol, trading_date)` the broker was active. Columns:
```
Date | Symbol | Sector | Bought Qty | Sold Qty | Net Qty | Cumulative Net | 
Avg Buy Price | Avg Sell Price | Asymmetry % | State | Unrealized P&L
```
Color-code rows: green = ACCUMULATING, yellow = ENTERING/HOLDING, red = DISTRIBUTING/EXITING, grey = FLAT.

**Sub-section 4c: State Transition Timeline**
Simple list showing the lifecycle arc for each stock this broker has traded:
```
NABIL:  [ENTERING 2/5] → [ACCUMULATING 2/6] → [HOLDING 2/9] → [DISTRIBUTING 2/11] → [FLAT 2/13]
NIMB:   [ENTERING 2/8] → [ACCUMULATING 2/11] ← CURRENT
```

---

#### Section 5: 📊 Stock-Level Broker Activity
For each stock that has active signals, show which brokers are on which side:

| Symbol | Current Price | Brokers Accumulating | Brokers Distributing | Net Broker Sentiment |

Net Broker Sentiment = (count accumulating - count distributing) on a -5 to +5 scale. A stock where 3 brokers are accumulating and 0 distributing gets +3 — very bullish.

---

### HTML Styling Guidelines
- Dark theme preferred (consistent with existing analysers in project — check `analysor/html_extractor.py` for exact color palette and style)
- Mobile-friendly with responsive tables
- Collapsible sections using vanilla JS (no external libraries)
- Color scheme: 
  - BUY/Accumulating: `#00c853` (green)
  - WATCH/Entering: `#ffd600` (yellow)
  - EXIT/Distributing: `#f44336` (red)
  - HOLDING: `#42a5f5` (blue)
  - FLAT: `#9e9e9e` (grey)
- Sort all tables by most significant first (strongest signal, highest trust, etc.)

---

## 🖥️ CLI Output (`__init__.py`)

When run as `python -m broker_tracker`:

```
============================================================
  NEPSE BROKER TRACKER — [date] [time]
============================================================

📊 DATA SUMMARY
  Brokers tracked   : 52
  Stocks covered    : 387
  Total transactions: 83,075
  Date range        : 2026-02-05 → 2026-02-17
  ⚠ Data maturity   : LOW (< 30 days of history)

🚨 BUY SIGNALS (3)
  NABIL   — Broker 47 (Mero Lagani)   | ACCUMULATING 5 sessions | Asym: 78% | Trust: UNRATED
  NIMB    — Broker 12 (NMB Sec)       | ACCUMULATING 3 sessions | Asym: 71% | Trust: UNRATED
  UPPER   — Broker 31 (Sunrise Sec)   | ACCUMULATING 4 sessions | Asym: 69% | Trust: UNRATED

👁 WATCH SIGNALS (5)
  [list]

⚠ EXIT SIGNALS (2)
  [list]

📄 HTML report saved: broker_tracker_reports/broker_tracker_2026-02-17.html
============================================================
```

---

## 🔧 Implementation Notes

1. **Performance**: Fetch all floorsheet data once at the start, do all aggregations in pandas in-memory. Do not make repeated DB queries per broker. One big fetch → all computation in Python.

2. **Pandas pattern**: The main DataFrame after aggregation will have shape `(broker_id, symbol, trading_date)` as a multi-level structure. Use `.groupby(['broker_id', 'symbol']).apply(compute_lifecycle)` to run the state machine.

3. **Null handling**: Many brokers appear on only one side of trades (only buying or only selling on a given day). Ensure `sold_qty = 0` (not NaN) when a broker only appears as buyer, and vice versa.

4. **Output directory**: Create `broker_tracker_reports/` at project root if it doesn't exist.

5. **HTML file naming**: `broker_tracker_{YYYY-MM-DD}.html` using today's date.

6. **Existing code reference**: Study `analysor/logic.py` and `analysor/html_extractor.py` thoroughly before coding. Reuse DB connection pattern, OHLCV fetch pattern, and HTML template structure exactly.

7. **Edge cases to handle**:
   - Broker who only sells (never appears as buyer) — valid, shows distribution-only behavior
   - Stocks with zero volume days in ohlcv — don't crash, just skip price context
   - Broker names with special characters (Nepali names) — use utf8mb4 throughout

---

## ✅ Delivery Checklist

- [ ] `broker_tracker/__init__.py` — CLI runner with summary output
- [ ] `broker_tracker/config.py` — all constants, DB config
- [ ] `broker_tracker/data.py` — all DB fetch functions
- [ ] `broker_tracker/positions.py` — state machine + cumulative position logic
- [ ] `broker_tracker/intelligence.py` — broker profiles + trust scores
- [ ] `broker_tracker/signals.py` — BUY/WATCH/EXIT signal generation
- [ ] `broker_tracker/html_report.py` — full HTML report generator
- [ ] HTML report includes all 5 sections described above
- [ ] CLI summary prints to terminal on run
- [ ] Report saves to `broker_tracker_reports/` directory
- [ ] All data fetched in bulk (no per-broker DB loops)
- [ ] State machine handles all 7 lifecycle states
- [ ] Trust scores show UNRATED + data maturity warning when data is thin
