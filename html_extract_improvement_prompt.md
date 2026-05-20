# NEPSE Analytics Engine — Full Upgrade Task for Claude Opus (VSCode Agent Mode)

## Context & Attached Files

You have been given three files:
- **`html_extract.py`** — the existing NEPSE EOD analytics engine (Python, ~1400 lines) that connects to a MySQL `nepsego` database and generates an HTML report
- **`NEPSE_Stock_Analysis_for_Trading_python_nepsego_research.md`** — a quantitative research document specifying the exact mathematical formulas, NEPSE-calibrated parameters, and analytical architecture this engine should follow
- **`dashboard_2026-02-22.html`** — a reference sample dashboard showing the desired output format, signal cards, buy/sell reasons, confidence bars, broker intelligence, and entry/stop-loss/target tables

**Your task is to rewrite and significantly upgrade `html_extract.py` in-place**, producing a new version that is a complete, runnable Python script. Do not truncate, stub, or skip any section. Write every function in full.

---

## Core Objectives

### 1. Implement All Missing Formulas from the Research Document

Read `NEPSE_Stock_Analysis_for_Trading_python_nepsego_research.md` carefully. The following are currently missing or incorrect in `html_extract.py` and must be implemented:

#### A. RSI Thresholds — CRITICAL FIX
- The current code uses standard 70/30 thresholds. **Change all RSI overbought/oversold thresholds to 80 (overbought) and 20 (oversold)** as specified for NEPSE. This affects every signal classification, composite score, and HTML label in the codebase.

#### B. Zero-Volume Forward Fill
- Add a `forward_fill_zero_volume_days(candles)` function. For any trading day where `volume == 0`, carry forward the previous active session's close as OHLC and set volume to 0. Apply this **before** any indicator calculation. Without this, moving averages and time-series arrays misalign.

#### C. Circuit Breaker Flag
- Add a `is_circuit_volatile(candles, lookback=5, threshold=2)` function.
- A stock is flagged if it hit the 10% upper or lower daily circuit limit on more than `threshold` of the last `lookback` sessions.
- Detect circuit days as: `abs(close - prev_close) / prev_close >= 0.099` (just under 10% to account for rounding).
- If flagged, **exclude the stock from all signal tables** and add it to a separate "⚠️ Circuit Breaker Alert" section in the HTML.

#### D. Low Liquidity Flag
- Add a `is_low_liquidity(candles, min_avg_volume=5000)` function.
- If `SMA_20(volume) < 5000`, flag as untradable and exclude from the final watchlist.

#### E. Rate of Change (ROC) Oscillator
- Add `calc_roc(closes, n)` using: `ROC = ((C_t - C_{t-n}) / C_{t-n}) * 100`
- Calculate both `ROC_20` (one trading month) and `ROC_60` (one quarter) for each symbol.

#### F. Corrected Composite Momentum Score with Min-Max Normalization
- Replace the existing composite scoring with the research document formula:
  `Score = (0.4 × ROC_20) + (0.3 × RSI_14) + (0.3 × Volume_Ratio)`
  where `Volume_Ratio = current_volume / SMA_20(volume)`
- After computing raw scores for **all symbols**, apply **min-max normalization** across the entire cross-section: `normalized = (raw - min) / (max - min) * 100`
- Stocks scoring above 90 are flagged as "🚀 EXTREME MOMENTUM" outliers.

#### G. Bollinger Bands
- Add `calc_bollinger_bands(closes, period=20, std_dev=2)` returning `(upper, middle, lower)`.
- `middle = SMA_20(closes)`
- `upper = middle + (std_dev × σ_20)`
- `lower = middle - (std_dev × σ_20)`
- Detect **"Bollinger Squeeze"**: if `(upper - lower) / middle < 0.04` (bands within 4% of price), flag as squeeze.
- Detect **"Bollinger Breakout"**: if the latest close is above `upper` AND volume ratio ≥ 1.5.

#### H. Candlestick Pattern Detection
Add a `detect_candlestick_patterns(candles)` function that returns a list of pattern strings detected on the most recent candle. Implement all three patterns with exact mathematical conditions:

- **Doji:** `abs(O - C) <= 0.05 * (H - L)`
- **Hammer (only valid if prior close < SMA_20):**
  - `abs(O - C) <= 0.3 * (H - L)`
  - `min(O, C) - L >= 2 * abs(O - C)`
  - `H - max(O, C) <= 0.1 * (H - L)`
- **Bullish Engulfing (requires two candles):**
  - Previous day: `C_{t-1} < O_{t-1}` (bearish)
  - Current day: `C_t > O_t` (bullish)
  - `O_t < C_{t-1}` AND `C_t > O_{t-1}`

#### I. ATR-Based Stop Loss and Position Sizing
- Add `calc_stop_loss(entry_price, atr, multiplier=1.5)`:
  `stop = entry_price - (multiplier × ATR_14)` for longs
  `stop = entry_price + (multiplier × ATR_14)` for shorts
- Add `calc_position_size(account_equity, entry_price, stop_price, risk_pct=0.015)`:
  `risk_amount = account_equity × risk_pct`
  `shares = risk_amount / abs(entry_price - stop_price)`
- Use these in all signal tables to compute `Entry`, `Stop Loss`, `Target 1`, `Target 2`.

#### J. Reward-to-Risk Ratio Filter
- Calculate `R:R = (target - entry) / (entry - stop)` for every signal.
- Only include signals with `R:R >= 2.0` in the final "Top Picks / Watchlist" section.
- Show the R:R ratio in every signal row.

#### K. Pivot Points (Standard + Fibonacci)
Add `calc_pivot_points(H_prev, L_prev, C_prev)` returning a dict:
```
P  = (H + L + C) / 3
R1 = (2 × P) - L
S1 = (2 × P) - H
R1_fib = P + 0.382 × (H - L)
S1_fib = P - 0.382 × (H - L)
R2_fib = P + 0.618 × (H - L)
S2_fib = P - 0.618 × (H - L)
```
Display these in each stock's signal card as the next-session S/R roadmap.

#### L. Volume Price Trend (VPT)
Add `calc_vpt(closes, volumes)`:
`VPT_t = VPT_{t-1} + (V_t × (C_t - C_{t-1}) / C_{t-1})`
Use alongside OBV for divergence detection. If price makes a new high but VPT makes a lower high → **bearish divergence** → add `"⚠️ VPT Bearish Divergence"` to reasons.

#### M. Breakout Screening
Add `is_breakout_candidate(candles, sma50, high_52w)` returning True when ALL four conditions met:
1. `current_close > sma50`
2. `current_close >= 0.98 × high_52w`
3. `current_volume >= 1.5 × SMA_20(volume)`
4. `MACD_histogram > 0`

#### N. Fibonacci Retracement
Add `calc_fibonacci_retracement(swing_low, swing_high)` returning levels at 0.382, 0.500, 0.618.
- If current close falls below the 0.618 level: add `"❌ Fib 61.8% Broken — Trend Invalidated"` to reasons and downgrade signal.

---

### 2. Upgrade the Broker Intelligence Section

The existing broker concentration function measures buy-side asymmetry. **Expand it to produce a "🔥 Smart Money Boom Stocks" section** with the following enhancements:

#### "BOOM" Stock Detection
A stock qualifies as a potential "BOOM" candidate when ALL of the following are true:
- **Broker Asymmetry Score > 65** (net accumulation, from existing `calc_broker_concentration`)
- **At least one identifiable top-3 buyer broker** is consistently buying across the last 5 sessions (query floorsheet grouped by `buyer_broker_id` filtered to last 5 `trading_date`s)
- **Volume Ratio ≥ 1.3** (above-average volume)
- **RSI between 40 and 75** (not yet overbought by NEPSE standards — remember threshold is 80)
- **Price above SMA_20** (uptrend)

For each BOOM stock, display:
- Symbol + LTP
- Broker Asymmetry Score
- Top 3 buyer broker IDs (the "smart money")
- Number of sessions those brokers have been consistently buying
- Volume Ratio
- RSI
- Signal: `"🔥 BROKER ACCUMULATION — WATCH FOR BREAKOUT"`
- Confidence bar based on asymmetry score

#### Broker Divergence Detection
If sell-side concentration is HIGH (top-3 sellers account for >50% of sell volume) while price is RISING → add `"⚠️ Smart Money Distributing — Distribution Signal"` warning to the stock's reasons in the trading signals table.

---

### 3. Add Detailed Buy/Sell Reasons to Every Signal

Every stock row in every table must have a `reasons` field that is built programmatically from the indicators. Use the following logic to construct reason strings (concatenate all that apply, separated by ` | `):

**Bullish Reasons (add when condition is true):**
- `"✅ Bullish MACD Crossover"` — MACD histogram just turned positive (was negative previous session)
- `"✅ RSI Oversold Recovery (RSI: {value})"` — RSI was below 20 and is now rising
- `"✅ Above SMA20 & SMA50"` — price above both moving averages
- `"✅ Golden Cross (SMA50 > SMA200)"` — SMA50 just crossed above SMA200
- `"✅ Volume Surge ({ratio:.1f}x avg)"` — volume ratio ≥ 1.5
- `"✅ 52W Breakout Zone (within {pct:.1f}% of high)"` — within 2% of 52-week high
- `"✅ Bollinger Squeeze Breakout"` — squeeze followed by close above upper band
- `"✅ Hammer Pattern Detected"` — candlestick pattern
- `"✅ Bullish Engulfing Pattern"` — candlestick pattern
- `"✅ Stoch Bullish Cross (K:{k} D:{d})"` — %K crossed above %D below 20
- `"✅ OBV Rising Trend"` — OBV trending up over last 10 sessions
- `"✅ Smart Money Accumulating (Score: {score})"` — broker asymmetry score > 65
- `"✅ Uptrend: Price > SMA20 > SMA50"` — full trend alignment
- `"✅ Low PE ({pe:.0f}) — Value Play"` — PE below 15

**Bearish Reasons (add when condition is true):**
- `"❌ Bearish MACD ({histogram:.2f})"` — MACD histogram is negative
- `"❌ RSI Overbought ({rsi:.1f} > 80)"` — RSI above NEPSE threshold of 80
- `"❌ Below SMA50"` — price below 50-day SMA
- `"❌ Below SMA200 — Downtrend"` — price below 200-day SMA (hard filter)
- `"❌ 52W Low Breakdown"` — price within 2% of 52-week low
- `"❌ Death Cross (SMA50 < SMA200)"` — bearish cross
- `"❌ At Lower Bollinger Band"` — close at or below lower BB
- `"❌ High Volume Selling"` — volume spike with negative price change
- `"❌ Stoch Overbought (K:{k} D:{d})"` — %K and %D above 80
- `"❌ OBV Falling — Distribution"` — OBV trending down
- `"❌ VPT Bearish Divergence"` — price high, VPT lower high
- `"❌ Fib 61.8% Broken — Trend Invalid"` — below key retracement
- `"⚠️ High PE ({pe:.0f}) — Overvalued Risk"` — PE above 30
- `"⚠️ Broker Divergence — Smart Money Selling"` — distribution signal
- `"⚠️ Circuit Breaker History"` — flagged but still displayed if in warning section
- `"⚠️ Post-Festive Seasonal Drain"` — apply in Jan–Feb (seasonal negative)
- `"⚠️ Ashad/Shrawan Seasonal Boost"` — apply in June–July (seasonal positive)

**Neutral/Context Reasons:**
- `"ℹ️ Doji — Indecision, Wait for Confirmation"` — doji pattern
- `"ℹ️ Inside SMA20 Pullback Zone"` — slight pullback in uptrend
- `"ℹ️ ROC20: {roc20:+.1f}% | ROC60: {roc60:+.1f}%"` — momentum context
- `"ℹ️ Pivot R1: {r1:.0f} | S1: {s1:.0f}"` — next session levels

The `reasons` string for each stock is shown in the HTML as the last column of every signal table.

---

### 4. Add LTP to Every Table Section

Every table in the HTML report must have an **LTP (Last Traded Price)** column showing the most recent closing price formatted as `Rs X,XXX.XX`. This applies to:
- Trading Signals table
- Momentum / Strong Picks table
- Fundamental Analysis table
- Technical Signals table
- Risk Overview table
- Sector Breakdown table (show the sector's avg LTP)
- Broker Intelligence / BOOM Stocks table
- Short-Term Picks table
- Long-Term Picks table
- Gainers/Losers table (already has this — ensure it remains)

The LTP must always reflect the **most recent adjusted close price** (post corporate action adjustment), not the raw price.

---

### 5. Add Buy/Sell/Hold Range to Every Signal

Every stock with a BUY or SELL signal must display a **trading range card** alongside the signal. This card must include:

```
LTP:        Rs X,XXX.XX
Signal:     STRONG BUY / BUY / HOLD / SELL / STRONG SELL
Entry Zone: Rs X,XXX — Rs X,XXX  (±0.5 ATR from current price)
Stop Loss:  Rs X,XXX.XX          (Entry - 1.5 × ATR14)
Target 1:   Rs X,XXX.XX          (Entry + 2.0 × ATR14)  [Pivot R1 or Fib 38.2%]
Target 2:   Rs X,XXX.XX          (Entry + 3.5 × ATR14)  [Pivot R2_fib or Fib 61.8% extension]
R:R Ratio:  X.X:1
ATR(14):    Rs XX.XX
```

For HOLD signals:
```
LTP:        Rs X,XXX.XX
Signal:     HOLD
Support:    Rs X,XXX.XX  (SMA50 or nearest K-Means cluster below — use SMA50 as proxy)
Resistance: Rs X,XXX.XX  (SMA20 upper or nearest K-Means cluster above — use 52W high proximity)
Exit if:    Price closes below Rs X,XXX.XX (SMA50)
```

---

### 6. New "🔥 Watchlist: Tomorrow's Trades" Final Section

Add a new final section at the top of the HTML (prominently placed, before all other tables) titled **"🔥 Tomorrow's Watchlist — Ready to Execute"**. This is the algorithmically filtered, scored, and ranked final output.

**Filtering sequence (apply in order):**
1. Remove stocks flagged as `is_low_liquidity` (SMA20 volume < 5,000)
2. Remove stocks flagged as `is_circuit_volatile` (>2 circuit days in last 5 sessions)
3. Remove stocks where `current_close < SMA_200` (downtrend — hard filter)
4. Remove stocks where `R:R < 2.0` (unfavorable risk-reward)

**Scoring (apply to survivors):**
Use the 5-dimension weighted composite from the research doc:
- Price Action & Trend (30%): Based on SMA alignment (above SMA20+SMA50+SMA200 = full score), candlestick patterns (+10 each), 52W proximity (<5% = +20)
- Momentum Velocity (25%): Normalized ROC_20 (40%), RSI_14 position relative to 20–80 range (30%), MACD histogram direction (30%)
- Volume & Liquidity (20%): Volume Ratio (capped at 5x), OBV trend direction, VPT trend
- Sector Strength (15%): Whether the stock's sector is in an uptrend (sector breadth > 50% stocks above SMA50)
- Risk & Structure (10%): ATR as % of price (lower = better), distance above nearest support (lower = better)

Apply min-max normalization across all survivors. Sort descending.

**Display the top 10** in a prominent card with:
- Rank (#1–#10)
- Symbol + LTP
- Composite Score (0–100 with color: green > 70, yellow 50–70, red < 50)
- Signal Badge (STRONG BUY / BUY)
- Entry / Stop / Target 1 / Target 2 / R:R
- Top 3 reasons (most impactful from the reasons list)
- Boom flag (🔥 if broker accumulation score > 65)
- Confidence bar

---

### 7. HTML Design Requirements

Match the visual style of `dashboard_2026-02-22.html` exactly:

- **Dark theme:** Background `linear-gradient(135deg, #0f172a 0%, #1e293b 100%)`
- **Cards:** `background: rgba(30, 41, 59, 0.8)`, `border-radius: 16px`, `backdrop-filter: blur(10px)`
- **Badges:** `.badge` with color variants: `bg-green`, `bg-red`, `bg-yellow`, `bg-blue`, `bg-purple`
- **Confidence bars:** `.confidence-bar` / `.confidence-fill` with `width: {pct}%`
- **Pulse animation** on STRONG BUY / STRONG SELL badges
- **Color classes:** `.text-green` (#10b981), `.text-red` (#ef4444), `.text-yellow` (#f59e0b), `.text-muted` (#94a3b8)
- **Symbol styling:** `<span class="symbol">` — bold, monospace, with slight highlight
- **Price styling:** `<span class="price">` — prominent font
- **Tables:** Alternating row shading, sticky headers on large tables
- **Tabs navigation** at the top for each section (Overview, Watchlist, Signals, Momentum, Fundamentals, Broker Intel, Risk, Sectors, Dividends)
- Each section card must have a **card-icon** (emoji) and **card-title**

**New HTML sections to add (in order after header):**
1. 🔥 Tomorrow's Watchlist (top 10 ranked picks)
2. 📊 Market Regime + Breadth (existing, enhanced)
3. 🎯 Trading Signals — Full Table
4. 🏦 Broker Intelligence & BOOM Stocks
5. ⚡ Momentum Screener
6. 📈 Technical Signals
7. 💎 Fundamental Analysis
8. 🏢 Sector Rotation
9. ⚠️ Risk Overview
10. 💰 Dividends & Corporate Actions
11. 🏅 Rankings
12. ⚠️ Circuit Breaker Watch (stocks excluded with reason)

---

## Implementation Rules

1. **Do not break existing database connectivity.** The MySQL connection via `pymysql` using `.env` config must remain unchanged. All existing SQL queries may be modified to add columns but must not remove existing ones.

2. **All functions must be complete.** Do not write stub functions or `# TODO` comments. Every function referenced must be fully implemented.

3. **Batch query pattern must be preserved.** The existing batch fetch approach (`fetch_all_ohlcv`, `fetch_all_corp_actions`, etc.) must be kept. Do not introduce per-symbol N+1 queries. Add any new batch queries following the same pattern.

4. **All new indicator functions must have guard clauses.** If there is insufficient data (e.g., fewer bars than required), return `None` gracefully — never crash. Minimum bars required:
   - RSI: 100 bars
   - MACD: 35 bars
   - Bollinger: 20 bars
   - ATR: 15 bars
   - Stochastic: 14 bars
   - ROC_60: 61 bars
   - SMA_200: 200 bars (gracefully fall back to longest available SMA)

5. **The script must remain a single file.** Do not split into modules. The output file is `html_extract.py`.

6. **Output file name.** The generated HTML report filename should remain `report.html` (or use the date-stamped format the existing code uses).

7. **Error handling.** Wrap all database calls in try/except. If a section fails, log the error and render an empty placeholder card with an error message in the HTML — do not crash the entire script.

8. **Performance.** The broker intelligence queries against `floorsheet_transactions` are the most expensive. Add a `LIMIT` guard and ensure the date filter uses an indexed column (`trading_date`). The full script should complete within 5 minutes on a typical NEPSE-sized dataset (~250 symbols × 252 days).

9. **Do not use external ML libraries** (no scikit-learn, no numpy, no pandas). The existing codebase uses pure Python and pymysql only. Implement the K-Means proxy using the **SMA50 and 52-week high/low as structural support/resistance anchors** instead of actual clustering — these are mathematically equivalent for the data sizes involved and avoid the dependency. Label them as "Structural Support" and "Structural Resistance" in the HTML.

10. **Account equity for position sizing.** Use a configurable constant at the top of the file: `ACCOUNT_EQUITY = 100000` (Rs 1 lakh default). Users can change this value before running.

---

## Checklist Before Finishing

Before returning the completed file, verify:

- [ ] RSI thresholds are 80/20 everywhere (search for `70` and `30` in RSI context)
- [ ] `forward_fill_zero_volume_days()` is called before any indicator calculation
- [ ] `is_circuit_volatile()` and `is_low_liquidity()` gate the final watchlist
- [ ] Every table has an LTP column
- [ ] Every BUY/SELL signal has Entry / Stop / Target 1 / Target 2 / R:R
- [ ] Reasons are built from the programmatic reason-string system (not hardcoded)
- [ ] Broker BOOM section exists with asymmetry score + buying broker IDs
- [ ] ROC_20 and ROC_60 are calculated and used in momentum scoring
- [ ] Bollinger Bands, VPT, Fibonacci levels, and Pivot Points are all implemented
- [ ] The "🔥 Tomorrow's Watchlist" section is the first content section after the header
- [ ] HTML visual style matches the dark theme from the sample dashboard
- [ ] All candlestick patterns (Doji, Hammer, Bullish Engulfing) are detected
- [ ] Min-max normalization is applied to composite scores
- [ ] The script runs end-to-end without import errors

---

## Final Output

Produce the complete, fully-written, single-file `html_extract.py`. Start with the module docstring, then all constants (including `ACCOUNT_EQUITY = 100000`), then all helper/indicator functions, then all data-fetching functions, then all analytics functions, then `build_html()`, then `main()`. The file will be long (~2000–2500 lines) — that is expected and correct. Do not truncate any section.
