# Analysor v3.0 — Audit, Fix & Data Mismatch Corrections

> We have reviewed the code and the live database. The architecture and logic are solid,
> but we found specific bugs in the code and critical data quality issues in the database
> that will cause silent failures or wrong outputs.
>
> Your task: re-read `logic.py` and `html_extractor.py`, verify each issue below yourself,
> then fix all of them. Do not stop until every issue is resolved and the code is clean.

---

## Part 1 — Code Bugs Found During Review

### Bug 1 🔴 — Entry Zone shows LTP twice (html_extractor.py)

**Location:** `_build_watchlist_section()` — the range card for top 3 picks.

**Problem:** The "Entry Zone" row just displays `{price}` twice instead of computing
the actual ±0.5 ATR entry zone as specified.

**Required fix:**

```
Entry Zone = price - (0.5 × ATR)  →  price + (0.5 × ATR)
```

Both the watchlist table `<td>Entry</td>` and all range cards must show this proper zone,
not just LTP. Check every place in html_extractor.py where Entry is rendered.

---

### Bug 2 🔴 — Candlestick patterns always wrong (logic.py)

**Root cause (discovered from DB analysis — see Part 2):**
`daily_ohlcv.open_price` is **0 for all 92,487 rows** — it was never collected by the API.

This means every call to `detect_candlestick_patterns(candles)` is computing:

- `o = float(c["open_price"])` → always `0.0`
- Doji: `abs(0 - close) <= 0.05 * (high - low)` → almost always FALSE or produces garbage
- Hammer: same — body calculation broken
- Bullish Engulfing: `o < pc` where `o = 0` — always triggers incorrectly

**Required fix:**
In `fetch_all_ohlcv()`, patch the open_price at load time using a LEFT JOIN:

```sql
SELECT
    do.symbol, do.trading_date,
    COALESCE(NULLIF(dp.open_price, 0), do.close_price) AS open_price,
    do.high_price, do.low_price, do.close_price, do.volume
FROM daily_ohlcv do
LEFT JOIN daily_prices dp
    ON do.symbol = dp.symbol AND do.trading_date = dp.trading_date
WHERE do.close_price > 0
ORDER BY do.symbol, do.trading_date ASC
```

This gets real open_price from `daily_prices` where available (6 recent days),
and falls back to `close_price` as a proxy for historical candles.
This is the industry-standard fallback for missing open data (open ≈ prev close).

---

### Bug 3 🟡 — Momentum composite mixes unscaled units (logic.py)

**Location:** `calc_momentum_composite()`

**Problem:** The formula `(0.4 × ROC_20) + (0.3 × RSI_14) + (0.3 × Volume_Ratio)`
mixes three different scales:

- RSI: 0–100
- ROC_20: typically ±5 to ±30
- Volume_Ratio: 0–5

RSI dominates the raw score ~10× more than the other terms, making ROC and Volume_Ratio
nearly irrelevant before min-max normalization. The ranking survives but the formula
is not what the research doc specified (equal-weighted meaningful components).

**Required fix:** Normalize each component to 0–100 before weighting:

```python
roc_norm = min(max((roc_20 + 30) / 60 * 100, 0), 100)   # ±30 ROC → 0-100
rsi_norm = rsi_14                                          # already 0-100
vr_norm  = min(vol_ratio / 5.0 * 100, 100)                # cap 5x → 0-100
raw = 0.4 * roc_norm + 0.3 * rsi_norm + 0.3 * vr_norm
```

---

### Bug 4 🟡 — Market breadth query has no date filter (logic.py)

**Location:** `market_overview()` — the breadth query on `daily_trade_turnover_transaction_subindices`

**Problem:** The table has 763 rows across multiple dates (2026-02-17 → 2026-02-23).
The query counts ALL rows with no date filter, causing advances/declines/unchanged
to be multiplied by the number of dates in the table. This produces inflated, wrong breadth numbers.

**Required fix:** Add a date filter to the latest available date:

```sql
SELECT
    SUM(CASE WHEN percent_change > 0 THEN 1 ELSE 0 END) as advances,
    SUM(CASE WHEN percent_change < 0 THEN 1 ELSE 0 END) as declines,
    SUM(CASE WHEN percent_change = 0 THEN 1 ELSE 0 END) as unchanged
FROM daily_trade_turnover_transaction_subindices
WHERE created_at >= (
    SELECT MAX(DATE(created_at))
    FROM daily_trade_turnover_transaction_subindices
)
```

---

### Bug 5 ⚪ — `fetch_all_securities()` is dead code (logic.py)

**Problem:** The function exists and queries the DB but is never called in `run_full_analysis()`.
This is harmless but wastes code clarity.

**Fix:** Either delete it, or integrate it as a fallback sector lookup (see Part 2, Issue 3 below).

---

## Part 2 — Database Data Issues (Confirmed from Live DB Analysis)

### DB Issue 1 🔴 CRITICAL — open_price = 0 everywhere in daily_ohlcv

**Confirmed fact:** All 92,487 rows in `daily_ohlcv` have `open_price = 0`.
This is an API collection limitation — the NEPSE API never returned open prices.

**Available sources for real open prices:**
| Source | Coverage | Reliability |
|--------|----------|-------------|
| `daily_prices.open_price` | 6 recent trading days, 365 symbols | ✅ 100% complete |
| `live_market_snapshots.open_price` | ~21 days, 380 symbols | ✅ 100% complete |
| Fallback: use `close_price` as open | All history | ✅ Industry standard proxy |

**This is fixed by Bug 2's patch to `fetch_all_ohlcv()` above.**

---

### DB Issue 2 🟡 — floorsheet_transactions only has 3 days of data

**Confirmed fact:** `floorsheet_transactions` covers only 2026-02-17 → 2026-02-23
(3 trading days, 211,526 rows).

**Impact on code:**

- `calc_broker_concentration()` queries `INTERVAL 30 DAY` — returns valid data but only reflects 3 days, not 30. The 30-day window is correct code; it just means the score is based on available data.
- `find_boom_stocks()` requires buyers to appear in ≥3 sessions across `INTERVAL 10 DAY`. With only 3 days available, this filter is extremely tight — very few stocks will qualify as BOOM.

**Required fix:**

- Reduce the `consistent_buyer` threshold dynamically based on actual available days:

```python
# Query how many distinct trading dates are available
available_days_row = qone(conn, """
    SELECT COUNT(DISTINCT trading_date) as day_count
    FROM floorsheet_transactions
    WHERE trading_date >= DATE_SUB(
        (SELECT MAX(trading_date) FROM floorsheet_transactions), INTERVAL 10 DAY)
""")
available_days = int(available_days_row.get("day_count") or 1)
# Require consistent buying in at least 50% of available days (min 1)
min_sessions = max(1, available_days // 2)
consistent_buyer = any(b["sessions"] >= min_sessions for b in buyers)
```

- Also in `calc_broker_concentration()`, log a warning if fewer than 10 days are available so the user knows the score is based on limited data.
- Add a note in the HTML BOOM section: "Based on X days of floorsheet data" so traders know the confidence level.

---

### DB Issue 3 🟡 — company_details only covers 384 of 753 securities

**Confirmed fact:** 384 companies have `company_details` records. 369 securities do not.
This means `all_details.get(sym, {})` returns `{}` for ~47% of symbols, causing:

- `sector_name` to be empty string → sector scoring fails
- `fifty_two_week_high/low` to be 0 → Fibonacci and proximity calculations fall back to computed values (which is fine but should be explicit)

**Required fix:** Use `securities` table as a fallback for sector lookup.
Currently `fetch_all_securities()` exists but is never called. Integrate it:

In `run_full_analysis()`, add:

```python
all_securities = fetch_all_securities(conn)  # {symbol: {sector_name, ...}}
```

In `analyze_all_symbols()`, change sector lookup to:

```python
det = all_details.get(sym, {})
sector = (det.get("sector_name") or
          all_securities.get(sym, {}).get("sector_name") or "")
```

The `securities` table has 753 symbols with sector_name — far better coverage.

---

### DB Issue 4 🟡 — 52-week high/low: live_market_snapshots is more reliable

**Confirmed fact:** `live_market_snapshots` has `fifty_two_week_high` and `fifty_two_week_low`
for 380 symbols with confirmed accurate data. `company_details` has it for 384 symbols
but may be stale (updated less frequently).

**Required fix:** Add a batch fetch of latest 52W high/low from `live_market_snapshots`
as a higher-priority source. In `fetch_all_company_details()` or a new function:

```python
def fetch_52w_from_snapshots(conn):
    rows = q(conn, """
        SELECT symbol,
               MAX(fifty_two_week_high) as hi52,
               MIN(fifty_two_week_low)  as lo52
        FROM live_market_snapshots
        WHERE fifty_two_week_high > 0
        GROUP BY symbol
    """)
    return {r["symbol"]: r for r in rows}
```

Then in `analyze_all_symbols()`, use snapshot 52W data first, fall back to company_details,
fall back to computed from OHLCV series.

---

### DB Issue 5 ⚪ — securities table contains non-equity instruments

**Confirmed fact:** Of 753 securities, only 470 are Equity. The rest are:

- 86 Non-Convertible Debentures
- 58 Mutual Funds
- 2 Preference Shares
- 137 NULL/unknown type

Trading signal analysis on debentures and mutual funds is meaningless (different pricing mechanics,
no technical patterns, different liquidity profiles).

**Required fix:** In `fetch_all_ohlcv()`, join to `securities` and filter to equity only:

```sql
SELECT do.symbol, do.trading_date, ...
FROM daily_ohlcv do
LEFT JOIN daily_prices dp ON do.symbol = dp.symbol AND do.trading_date = dp.trading_date
JOIN securities s ON do.symbol = s.symbol
WHERE do.close_price > 0
  AND (s.instrument_type = 'Equity' OR s.instrument_type IS NULL)
ORDER BY do.symbol, do.trading_date ASC
```

This removes debentures and mutual funds from all technical analysis while keeping
symbols with NULL instrument_type (unknown) to avoid dropping valid equity stocks.

---

## Summary Checklist for Opus

Before finishing, verify every item:

- [ ] `fetch_all_ohlcv()` does a LEFT JOIN with `daily_prices` to get real open_price — fallback to close_price
- [ ] `fetch_all_ohlcv()` filters to equity-only via JOIN to `securities`
- [ ] Candlestick patterns now use real open prices — test logic with non-zero open values
- [ ] Entry Zone in watchlist table AND range cards shows `price ± 0.5 × ATR` — not LTP twice
- [ ] `calc_momentum_composite()` normalizes ROC/RSI/VolRatio to 0-100 before weighting
- [ ] Market breadth query filters to latest date only — advances/declines no longer inflated
- [ ] `find_boom_stocks()` uses dynamic `min_sessions` based on available floorsheet days
- [ ] `calc_broker_concentration()` logs/displays how many days of floorsheet data were used
- [ ] BOOM stocks HTML section shows "Based on X days of data" disclaimer
- [ ] `fetch_all_securities()` is now called in `run_full_analysis()` and used as sector fallback
- [ ] New `fetch_52w_from_snapshots()` batch function added and used with correct priority order
- [ ] `fetch_all_securities()` dead code issue resolved (either integrated or explicitly removed)
- [ ] All existing functionality preserved — no regressions

Rewrite only what is necessary to fix the above. Do not restructure working code.
