# Quantitative Analysis and Data Architecture for End-of-Day Algorithmic Trading on the Nepal Stock Exchange (NEPSE)

The Nepal Stock Exchange (NEPSE) operates as a frontier market with a distinct set of microstructural characteristics. With a market capitalization of approximately $34 billion (NPR 4.65 trillion)¹, the exchange exhibits relatively low liquidity compared to major global bourses, relies heavily on retail participation, and imposes rigid volatility controls through daily circuit breakers.² To navigate this environment, quantitative trading systems require robust, end-of-day (EOD) analytical pipelines that synthesize macro-level price action, micro-level volume profiles, and momentum metrics to project next-day probabilities.

This research report provides an exhaustive, mathematical, and architectural framework for building an EOD algorithmic trading system utilizing a relational MySQL database containing NEPSE market data. The methodology details the exact procedural logic, table interactions, mathematical formulas, and environmental adjustments required to extract actionable intelligence from both finalized daily summaries and high-frequency intraday snapshots.

---

## Database Architecture and Table Interaction Map

The foundation of any quantitative analysis lies in the structural integrity of its underlying data. The provided database relies on scheduled data scraping and ingestion, tracked via a central logging mechanism.⁴ Before mathematical models can be applied, the exact data architecture, relationship mapping, and preprocessing sequences must be established.

### Relational Schema and JOIN Logic

The analytical pipeline relies on five primary conceptual data domains, tracked as enumeration values within the database's ingestion logs.⁴ To construct a cohesive dataset for EOD analysis, these tables must be queried and joined sequentially:

1. **securities Table (Static Metadata):** This table contains static information for listed assets, including the ticker symbol, sector classification (e.g., Commercial Banks, Hydropower), and issue type.¹ It acts as the primary dimension table.

2. **daily_summary Table (Macro Data):** This table contains finalized EOD OHLCV (Open, High, Low, Close, Volume) data.⁴

3. **live_market_snapshots Table (Micro Data):** This table contains intraday price and volume data recorded at approximately two-minute intervals during active trading hours.⁴

4. **floorsheet Table (Transaction Logs):** This table contains tick-by-tick transaction logs, including buyer and seller broker IDs, quantities, and execution prices.⁵

5. **brokers Table (Participant Metadata):** This table contains metadata for market participants, mapping broker IDs to firm names and contact details.⁴

To execute the daily EOD analysis, the database must be queried using specific relational logic. The analytical script must first query the logging mechanism to ensure the current day's data ingestion is complete. It filters for records where the status indicates completion for the target trading date.⁴ If the data is partial or failed, the pipeline must halt to prevent corrupted mathematical outputs.

Once data integrity is confirmed, the primary time-series dataframe is constructed by performing an INNER JOIN between the securities table and the daily_summary table on the unique security identifier or ticker symbol. This combined dataset powers all daily technical indicators and price action analysis. For intraday volume profiling and Volume Weighted Average Price (VWAP) calculations, the securities table is joined with the live_market_snapshots table. This relationship is strictly one-to-many, requiring window functions to aggregate the two-minute intervals into unified daily metrics.⁶

### Recommended Sequence of Calculations

Because complex indicators derive their values from simpler foundational metrics, the computational sequence must strictly follow a dependency hierarchy:

1. **Data Quality and Adjustment Pass:** Execute forward-filling for missing data and apply mathematical adjustments for corporate actions.
2. **Base Price Action Extraction:** Calculate daily OHLCV, absolute price changes, and gap logic.
3. **Simple Derived Metrics:** Calculate basic Simple Moving Averages (SMAs), Exponential Moving Averages (EMAs), and True Range (TR).
4. **Complex Oscillators and Volatility Bands:** Calculate the Relative Strength Index (RSI), Moving Average Convergence Divergence (MACD), Average True Range (ATR), and Bollinger Bands using the previously calculated moving averages.
5. **Intraday Aggregation:** Parse the live_market_snapshots to construct the Volume Accumulation Profile, Point of Control (POC), and VWAP.
6. **Cross-Sectional Analysis:** Calculate sector breadth, relative momentum scoring, and index correlation (Beta) across the entire universe of stocks.
7. **Support and Resistance Topography:** Execute K-Means clustering and pivot point calculations to establish the next day's technical boundaries.
8. **Risk Management Constraints:** Calculate ATR-based position sizing and filter out assets triggering high-risk flags.

---

## Data Quality Checks and NEPSE-Specific Adjustments

Frontier markets suffer from data anomalies that will mathematically shatter technical indicators if not proactively handled. The pipeline must include rigorous validation layers before any indicator formulas are applied.

Illiquid NEPSE equities frequently experience trading sessions with zero traded volume. These days must be mathematically forward-filled. The closing price of the previous active session is carried forward as the Open, High, Low, and Close for the inactive day, while volume is strictly recorded as zero. Failing to forward-fill these gaps will cause moving average calculations and time-series arrays to misalign, creating severe data leakage.

The NEPSE implements rigid trading halts to curb excessive volatility. A 4 percent index movement within the first hour triggers a 20-minute halt, a 5 percent movement within the second hour triggers a 40-minute halt, and a 6 percent movement halts trading for the remainder of the day.² Furthermore, individual stocks are subjected to a 10 percent daily circuit limit. Days where a stock hits a circuit breaker result in artificially truncated volume and constrained price ranges. Volatility metrics, particularly the Average True Range, must apply exponential smoothing to account for these artificial volatility caps, ensuring that the algorithm does not interpret a circuit breaker day as a day of naturally low volatility.

Finally, Nepalese companies frequently distribute dividends in the form of bonus shares or issue right shares to raise capital.⁹ On the book closure date, the NEPSE artificially adjusts the stock price downward to reflect the dilution. If historical prices are not mathematically adjusted backward, the database will register a massive, artificial price crash, generating severe false sell signals across all technical indicators. The database must maintain an unadjusted column for raw execution prices and an adjusted column for continuous time-series analysis.

The historical data is adjusted backward using the following formulas:

**For Bonus Shares:**⁹

$$P_{adjusted} = \frac{P_{old}}{1 + \text{Bonus Percentage}}$$

**For Right Shares:**⁹

$$P_{adjusted} = \frac{P_{old} + (\text{Subscription Price} \times \text{Right Percentage})}{1 + \text{Right Percentage}}$$

---

## Price Action Analysis and Pattern Recognition

Price action serves as the leading indicator in any quantitative trading system. By analyzing the raw OHLCV data extracted from the daily_summary table, the algorithm systematically identifies market psychology, momentum shifts, and structural extremes without the lag inherent in moving averages.

### Deriving OHLCV Data

The daily OHLCV is queried directly from the daily_summary table. To ensure maximum data integrity, the EOD script mathematically verifies the daily summary against the live_market_snapshots. The daily High must equal the maximum high recorded across all intraday snapshots ( max(Snapshot_high) ), and the daily Low must equal the minimum low ( min(Snapshot_low) ). The closing price logic must adhere to prevailing NEPSE regulations; the exchange oscillates between using the absolute final traded price and a 15-minute volume-weighted average of the final minutes of trading to determine the official close.¹¹

### Algorithmic Candlestick Pattern Detection

Candlestick patterns visualize the intra-session battle between supply and demand. To detect these systematically in a Python environment, visual heuristics must be translated into rigid, boolean mathematical conditions using the daily OHLC data.¹³

#### 1. Doji (Market Indecision)

A Doji forms when the opening and closing prices are virtually identical, resulting in a candlestick with a negligible real body. This signifies a state of equilibrium between buyers and sellers and often precedes a violent breakout or trend reversal.¹⁵ Because exact decimal matches are exceedingly rare in live trading, the algorithm applies a strict threshold ratio relative to the total daily volatility.

- **Mathematical Condition:**¹⁴ `|O − C| ≤ 0.05 × (H − L)`
- **Logic:** The absolute difference between the Open and Close must be less than or equal to 5 percent of the total distance between the High and Low.

#### 2. Hammer (Bullish Reversal)

A Hammer forms at the culmination of a downtrend. It is characterized by a small real body situated at the upper extreme of the trading range, accompanied by a long lower shadow. This structure indicates that sellers drove prices lower during the session, but immense buying pressure overwhelmed them, forcing a close near the highs — a classic sign of seller exhaustion.¹⁷ To prevent false positives, the algorithm must verify the existence of a prior downtrend and measure the exact proportions of the candlestick shadows.

- **Trend Condition:** `C_{t-1} < SMA_20` (Ensures the stock was in a short-term downtrend).
- **Body Proportion Condition:** `|O − C| ≤ 0.3 × (H − L)` (Ensures the real body is small relative to the range).
- **Lower Shadow Condition:** `min(O, C) − L ≥ 2 × |O − C|` (Ensures the lower wick is at least twice the length of the real body).¹⁷
- **Upper Shadow Condition:** `H − max(O, C) ≤ 0.1 × (H − L)` (Ensures the upper wick is virtually non-existent).¹⁷

#### 3. Bullish Engulfing (Momentum Shift)

An engulfing pattern requires two consecutive days of data. A small bearish candlestick is followed by a massive bullish candlestick whose real body completely eclipses the real body of the prior day. This pattern signifies a sudden, violent shift in momentum where buyers entirely overwhelm sellers.¹⁵

- **Prior Day Condition:** `C_{t-1} < O_{t-1}` (The previous day closed lower than it opened).
- **Current Day Condition:** `C_t > O_t` (The current day closed higher than it opened).
- **Engulfing Logic:** `O_t < C_{t-1}` and `C_t > O_{t-1}` (The current open is below the previous close, and the current close is above the previous open).

### Price Change, 52-Week Proximity, and Gap Detection

To contextualize the day's price action, the system evaluates its standing relative to historical extremes and overnight sentiment shifts.

The absolute daily price change percentage defines immediate momentum and is calculated as:

$$\Delta P = \left(\frac{C_t - C_{t-1}}{C_{t-1}}\right) \times 100$$

The 52-week high ( H₅₂ ) and 52-week low ( L₅₂ ) represent the absolute maximum and minimum closing prices recorded over the preceding 252 trading days.²¹ In retail-driven markets like the NEPSE, these levels act as profound psychological barriers. The algorithm calculates the proximity to the 52-week high to identify stocks consolidating near resistance, which are prime candidates for breakout trades.²³

- **High Proximity Formula:** `P_high = ((H_52 − C_t) / H_52) × 100`
- **Interpretation:** A proximity value of ≤ 5% indicates extreme strength. If accompanied by contracting volatility and expanding volume, a breakout is statistically probable.

Gaps represent overnight shifts in macroeconomic sentiment or stock-specific news, where the price opens significantly away from the previous day's range. Given the NEPSE's market structure, significant gaps frequently occur on Sunday mornings, reflecting the accumulation of weekend geopolitical or domestic economic developments.

- **Gap Up Condition:** `O_t > H_{t-1}`
- **Gap Down Condition:** `O_t < L_{t-1}`

---

## Technical Indicators: Formulations and Table Sources

Technical indicators process raw OHLCV data through mathematical functions to smooth inherent market noise, highlight underlying trends, and identify over-extended conditions. Standard parameters (such as a 14-day RSI or a 50-day SMA) were originally calibrated for Western equity markets operating on standard five-day trading weeks. Because the NEPSE's trading calendar has historically fluctuated, these parameters require careful calibration to remain mathematically sound.²⁴

| Indicator | Table Source | Required Columns | Standard vs. NEPSE Settings |
|---|---|---|---|
| SMA / EMA | daily_summary | close | 5, 10, 20, 50, 200 Days |
| MACD | daily_summary | close | 12, 26, 9 Days |
| RSI | daily_summary | close | 14 Days (Thresholds: 80/20) |
| Bollinger Bands | daily_summary | close | 20 Days, 2 Standard Deviations |
| ATR | daily_summary | high, low, close | 14 Days |
| Stochastic | daily_summary | high, low, close | 14, 3, 3 Days |
| OBV / VPT | daily_summary | close, volume | Cumulative |
| VWAP | live_market_snapshots | high, low, close, volume | Intraday, Reset Daily |

### Simple Moving Average (SMA) and Exponential Moving Average (EMA)

Moving averages act as the primary filters for trend direction. The Simple Moving Average provides an equally weighted mean of prices over a specified window, smoothing out day-to-day fluctuations. The Exponential Moving Average applies a weighting multiplier to prioritize more recent data points, significantly reducing the mathematical lag inherent in the SMA.²⁷

**SMA Formula:**

$$SMA_n = \frac{1}{n} \sum_{i=1}^{n} C_i$$

**EMA Formula:**

$$EMA_n = \left(C_t \times \frac{2}{n+1}\right) + \left(EMA_{t-1} \times \left(1 - \frac{2}{n+1}\right)\right)$$

For the NEPSE market context, specific periodicities serve distinct functions:

- **5-Day EMA:** Represents roughly one trading week. It is highly reactive and serves as a trailing stop metric for explosive, momentum-driven swing trades.
- **10-Day & 20-Day SMA:** Represents two trading weeks and one trading month, respectively. These form the baseline for mean-reversion strategies.
- **50-Day & 200-Day SMA:** These define the long-term institutional trend.²⁸ A "Golden Cross," where the 50-day SMA crosses above the 200-day SMA, historically acts as a reliable confirmation of sustained, multi-month bull cycles on the NEPSE.

### Moving Average Convergence Divergence (MACD)

The MACD quantifies the relationship between two moving averages, serving simultaneously as a trend-following indicator and a momentum oscillator.²⁷ It is derived by subtracting the longer-term EMA from the shorter-term EMA.

- **MACD Line:** `EMA_12(C) − EMA_26(C)`
- **Signal Line:** `EMA_9(MACD Line)`
- **MACD Histogram:** `MACD Line − Signal Line`

**Interpretation for Next-Day Trades:** The absolute value of the MACD Line indicates the distance between the short and long-term averages. A positive, expanding histogram indicates accelerating bullish momentum. A crossover of the MACD Line above the Signal Line generates a mathematical buy signal.²⁷ However, in a low-liquidity environment like the NEPSE, the MACD is highly prone to generating false signals ("whipsaws") during sideways consolidations. Therefore, MACD crossovers must never be traded in isolation; they require strict volume confirmation.

### Relative Strength Index (RSI)

Developed by J. Welles Wilder, the RSI measures the velocity and magnitude of directional price movements, oscillating on a bounded scale between 0 and 100.³⁰ It effectively quantifies whether a stock is statistically overbought or oversold based on recent price history.

- **Average Gain:** The sum of all positive price changes divided by the lookback period n.
- **Average Loss:** The absolute sum of all negative price changes divided by n.
- **Relative Strength (RS):** Average Gain / Average Loss
- **RSI Formula:**

$$RSI = 100 - \left(\frac{100}{1 + RS}\right)$$

**NEPSE Calibration:** The mathematical standard utilizes a 14-period lookback, representing approximately three trading weeks, which remains structurally sound for NEPSE. However, the traditional interpretation thresholds (70 for overbought, 30 for oversold)³⁰ are profoundly sub-optimal for this specific exchange. During fierce NEPSE bull cycles, fueled by high retail speculation, stocks frequently hit the 10 percent positive circuit breaker for multiple consecutive days. This immense upside velocity forces the RSI rapidly above 70, where the stock can remain for weeks while the price continues to double. Using a 70 threshold leads to premature liquidation of highly profitable positions. Consequently, the recommended RSI thresholds for NEPSE algorithms are shifted to **80 (Overbought)** and **20 (Oversold)** to allow winning trades to run.

### Bollinger Bands

Bollinger Bands measure volatility by plotting standard deviations above and below a central moving average.²⁷ They adapt dynamically to market conditions, widening during periods of extreme volatility and contracting during periods of calm.

- **Middle Band:** `SMA_20(C)`
- **Upper Band:** `SMA_20(C) + (2 × σ_20)`
- **Lower Band:** `SMA_20(C) − (2 × σ_20)`

**Interpretation and Breakout Signals:** In standard normal distributions, 95 percent of data points fall within two standard deviations of the mean. While equity prices exhibit fat-tailed distributions, price action outside the bands remains statistically significant. The primary algorithmic trigger derived from this indicator is the **"Bollinger Squeeze."** When the NEPSE experiences a multi-week consolidation, the upper and lower bands contract tightly. If this squeeze is followed by an explosive bullish candlestick that closes strictly above the Upper Band, accompanied by a surge in traded volume, it signals the initiation of a new, high-volatility uptrend.

### Average True Range (ATR)

Also developed by Wilder, the ATR provides an absolute measure of market volatility by decomposing the entire price range of an asset for a given period.³² Unlike a simple High-Low calculation, the True Range mathematically accounts for overnight gaps, which are prevalent on the NEPSE.

**True Range (TR) is the maximum of the following three absolute values:**

1. `H_t − L_t` (Current High minus Current Low)
2. `|H_t − C_{t-1}|` (Current High minus Previous Close)
3. `|L_t − C_{t-1}|` (Current Low minus Previous Close)

**ATR Formula (Smoothed):**

$$ATR_n = \frac{(ATR_{t-1} \times (n-1)) + TR_t}{n}$$

The ATR is primarily a risk-management tool. A 14-day ATR smooths recent volatility spikes, providing the algorithm with a dynamic numerical value representing the stock's expected daily noise level. This value is strictly required for calculating intelligent, volatility-adjusted stop-loss levels.³²

### Stochastic Oscillator

The Stochastic Oscillator is a momentum indicator that compares a specific closing price to a range of its prices over a given historical window. The theory dictates that in an upward trending market, prices will close near their highs, and in a downward trending market, prices will close near their lows.

**%K Formula:**

$$\%K = \left(\frac{C_t - L_{14}}{H_{14} - L_{14}}\right) \times 100$$

**%D Formula:** `SMA_3(%K)`

**Interpretation:** The oscillator fluctuates between 0 and 100. Readings below 20 indicate extreme oversold conditions. A high-probability EOD buy signal is generated when the fast %K line crosses above the slow %D line while both are situated below the 20 threshold.

### Volume Oscillators: OBV and VPT

In low-liquidity frontier markets, price action can occasionally be manipulated by small, strategic orders. However, cumulative volume represents institutional capital flow, which cannot be hidden. Volume oscillators track this accumulation and distribution.

**On-Balance Volume (OBV):** A cumulative total of volume that adds volume on up days and subtracts it on down days.

- If `C_t > C_{t-1}`, then `OBV_t = OBV_{t-1} + V_t`
- If `C_t < C_{t-1}`, then `OBV_t = OBV_{t-1} − V_t`
- If `C_t = C_{t-1}`, then `OBV_t = OBV_{t-1}`

**Volume Price Trend (VPT):** A more nuanced alternative to OBV that scales the volume addition or subtraction by the percentage change in the share price, ensuring that a 10 percent up day contributes more positively to the trend than a 1 percent up day.

$$VPT_t = VPT_{t-1} + \left(V_t \times \frac{C_t - C_{t-1}}{C_{t-1}}\right)$$

**Algorithmic Interpretation:** The primary utility of OBV and VPT lies in divergence detection. If a NEPSE stock forms a higher high in price, but the OBV forms a lower high, it indicates a bearish divergence. Smart money is distributing shares into retail demand, and the price rally lacks fundamental liquidity support, warning the algorithm to tighten stop-losses.

### Volume Weighted Average Price (VWAP)

The VWAP represents the true average price a stock traded at throughout the day, weighted by the volume transacted at each price level.⁶ VWAP is inherently an intraday metric that resets at the beginning of each trading session. However, EOD algorithms utilize the final EOD VWAP value to determine if a stock closed at a "fair" price relative to the day's total liquidity.

VWAP cannot be calculated from the daily_summary table; it requires granular tick or snapshot data. The algorithm must query the live_market_snapshots table for all records associated with a specific date and symbol.

**Formula:**

$$VWAP = \frac{\sum_{i=1}^{n}(\text{Typical Price}_i \times V_i)}{\sum_{i=1}^{n} V_i}$$

- **Typical Price Calculation:** For each two-minute snapshot row, `Typical Price = (H_i + L_i + C_i) / 3`
- **SQL Logic Integration:** The calculation relies on window functions to maintain a running cumulative total throughout the trading day.⁶
  - `SUM(Typical_Price * Volume) OVER (PARTITION BY symbol ORDER BY run_timestamp)` divided by `SUM(Volume) OVER (PARTITION BY symbol ORDER BY run_timestamp)`.⁶

If the absolute final closing price in the daily_summary is significantly higher than the final calculated VWAP, it indicates aggressive, late-day institutional buying, providing a bullish tailwind for the following session.

---

## Volume Analysis and Accumulation Profiling

Volume analysis prevents the execution of trades based on "ghost movements" — price shifts unsupported by underlying liquidity. Analyzing volume provides mathematical confirmation of the validity of a price breakout.

### Detecting Unusual Volume Spikes

Comparing absolute volume totals across different sectors is inherently flawed. A million shares traded in a highly liquid commercial bank is standard, whereas a hundred thousand shares in a tightly held microfinance stock represents a massive anomaly. Therefore, volume must be analyzed dynamically on a relative basis.

**Volume Ratio Formula:**

$$VR = \frac{V_t}{SMA_{20}(V)}$$

**Algorithmic Logic:** The algorithm calculates a 20-day simple moving average of volume. It then divides the current day's volume by this baseline. A Volume Ratio ≥ 2.0 signifies that the current session transacted at least 200 percent of its average liquidity.²³ If this massive relative volume spike coincides with a positive price breakout through resistance, the algorithm flags it as high-conviction institutional accumulation.

### Volume Trend Calculation

Beyond daily spikes, assessing whether liquidity is generally expanding or contracting across a multi-week period provides critical context. The algorithm calculates the slope of the linear regression line applied to the daily volume totals over n periods (typically 5, 10, or 20 days). A positively sloped volume trend line during a period of tight price consolidation suggests quiet accumulation, heavily foreshadowing a bullish breakout.

### Intraday Volume Accumulation Profile (Volume by Price)

While traditional volume histograms plotted on the X-axis reveal *when* trades occurred, the Volume Profile plots volume on the Y-axis to reveal *where* (at what exact price levels) trades occurred.³⁵ This is the most powerful tool for identifying hidden intraday support and resistance levels.³⁶ Constructing this profile requires parsing the millions of rows within the live_market_snapshots table.

**Procedural Logic for Algorithmic Construction:**

1. **Data Isolation:** Query all live_market_snapshots for a given symbol on a specific trading_date.
2. **Binning Mechanism:** Identify the absolute High and absolute Low from the snapshots. Divide this total daily range into N equal horizontal price intervals, known as bins (e.g., 20 or 30 bins).³⁸
3. **Volume Distribution:** Iterate sequentially through every two-minute snapshot. Allocate the traded volume of that snapshot into the price bin that encompasses the snapshot's execution price.³⁸
4. **Point of Control (POC) Identification:** Scan the bins to identify the single price tier containing the highest accumulated volume. This price level represents the intraday fair value where the maximum consensus was reached between buyers and sellers.³⁵
5. **Value Area (VA) Calculation:** The Value Area represents the price range where 70 percent of the total daily volume occurred, statistically mirroring one standard deviation in a normal distribution.³⁷ Starting from the POC bin, the algorithm compares the volume of the bin immediately above to the volume of the bin immediately below. It adds the higher volume bin to the Value Area.³⁵ This process repeats iteratively, expanding outward from the POC, until the cumulative volume of the included bins reaches 70 percent of the daily total. The highest and lowest price boundaries of this area become the **Value Area High (VAH)** and **Value Area Low (VAL)**.

**Next-Day Trading Implications:** The Volume Profile dictates next-day positional bias.³⁹ If a stock closes the session strongly above the VAH, it signifies an imbalance; buyers aggressively accepted higher prices and rejected the intraday fair value. The algorithm biases long. Conversely, if the stock opens the next day within the confines of the previous day's Value Area, statistical probability dictates the price will chop sideways and gravitate back toward the POC.

---

## Sector and Index Analysis

The NEPSE operates heavily on macroeconomic sector rotation. Liquidity behaves like a current, surging into Hydropower, rotating to Development Banks, and subsequently settling into Commercial Banks based on regulatory news and quarterly earnings cycles. EOD analysis must quantify these capital flows mathematically.

### Sector-Wise Performance and Breadth

The securities table maps every listed ticker to a specific sub-index (e.g., BANKINGIND, HYDROPOWIND, FINANCEIND).¹ The algorithm isolates daily performance metrics by grouping calculations across these specific sectors.

- **Gainers vs. Losers Ratio:** For each sector, the algorithm iterates through the constituents, counting the number of advancing stocks ( C_t > C_{t-1} ) and the number of declining stocks.

$$\text{Breadth Ratio} = \frac{\text{Advances}}{\text{Declines}}$$

  - A ratio consistently > 1.5 over several days indicates strong, unified sector-wide bullish breadth, suggesting the sector is experiencing a massive inflow of institutional capital.

- **Sector SMA Breadth Indicator:** The algorithm calculates the percentage of total stocks within a specific sector that are currently trading above their respective 50-day SMAs. If this metric forcefully crosses from below 50 percent to above 50 percent, the sector is mathematically confirmed to be in a primary uptrend.²⁸

### Beta (β) Calculation and Correlation

Beta provides a mathematical measurement of a specific stock's historical volatility and systematic risk relative to the overall NEPSE benchmark index.⁴¹ Understanding Beta is crucial for portfolio construction; in a rapidly rising NEPSE environment, high Beta stocks mathematically amplify returns, while in a bearish market, they catastrophically accelerate losses.⁴⁴

**Beta Formula:**

$$\beta = \frac{\text{Covariance}(R_s, R_m)}{\text{Variance}(R_m)}$$

- Where R_s represents the daily percentage return of the individual stock.
- Where R_m represents the daily percentage return of the NEPSE index.⁴²

**Calculation Sequence:** The algorithm extracts 252 days (one year) of daily returns for both the target stock and the benchmark index. It calculates the covariance matrix between the two arrays and divides by the variance of the index returns.⁴¹

**Interpretation:**
- A β = 1.0 indicates perfect correlation with market volatility.
- A β = 1.5 indicates the stock is 50 percent more volatile than the NEPSE index.⁴¹
- Historically, defensive investors in Nepal favor commercial banks (β < 1), while aggressive retail traders target volatile hydropower or finance stocks (β > 1.5).⁴⁴

---

## Momentum and Screening Metrics

The purpose of mathematical screening is to objectively reduce the universe of 250+ NEPSE-listed equities down to a highly concentrated, statistically advantageous daily watchlist, stripping away human emotion.

### Rate of Change (ROC)

The Rate of Change oscillator provides a pure mathematical measure of momentum, plotting the percentage change in price between the current closing price and the price n periods in the past.

**ROC Formula:**

$$ROC = \left(\frac{C_t - C_{t-n}}{C_{t-n}}\right) \times 100$$

- By executing the ROC calculation with n = 20 (approximately one trading month) and n = 60 (one quarter), the system screens out slow-moving assets, isolating the market's medium-term momentum leaders.

### Momentum Score Formulation and Ranking

To rank stocks cross-sectionally, the algorithm utilizes a composite momentum score. This normalizes disparate price, velocity, and volume metrics into a single, easily comparable integer.

**Scoring Equation:**

$$\text{Score} = (0.4 \times ROC_{20}) + (0.3 \times RSI_{14}) + (0.3 \times \text{Volume Ratio})$$

Because absolute values for these metrics vary wildly, the algorithm applies min-max scaling across the entire cross-section of the market, forcing the final score to reside on a standardized scale from 0 to 100. Stocks scoring above 90 are flagged as extreme momentum outliers.

### Breakout Identification Logic

A true technical breakout occurs when an asset breaches a formidable, historical resistance level, propelled by a surge in institutional volume.²³ Catching these breakouts is the core objective of trend-following algorithms.

**Algorithmic Breakout Screening Rules:**

1. `C_t > SMA_50` — Validates the stock is in an established primary uptrend.
2. `C_t ≥ 0.98 × H_52` — Price is consolidating within a tight 2 percent margin of its 52-week high.²³
3. `V_t ≥ 1.5 × SMA_20(V)` — A massive surge in volume confirms the breakout is genuine, not a low-liquidity anomaly.²³
4. `MACD_hist > 0` — Ensures immediate short-term momentum is aligned positively.

---

## Support and Resistance Topography

Support and resistance (S/R) levels represent psychological and structural zones where the equilibrium between supply and demand has historically collapsed. Accurate mapping of these zones dictates the trade architecture: where to enter, where to exit, and where to abort.

### Pivot Points (Standard and Fibonacci)

Pivot points are mathematically derived leading indicators. Unlike moving averages that lag behind price action, pivot points use the previous day's OHLC data to project exact numerical S/R levels for the *next* trading session.

**Standard Pivots:**

$$\text{Pivot Point (P)} = \frac{H_{t-1} + L_{t-1} + C_{t-1}}{3}$$

$$\text{Resistance 1 (R1)} = (2 \times P) - L_{t-1}$$

$$\text{Support 1 (S1)} = (2 \times P) - H_{t-1}$$

**Fibonacci Pivots:** This variation replaces linear multipliers with the golden ratio sequence found in natural growth patterns, widely utilized by institutional algorithms.

$$R1_{fib} = P + 0.382 \times (H_{t-1} - L_{t-1})$$

$$S1_{fib} = P - 0.382 \times (H_{t-1} - L_{t-1})$$

$$R2_{fib} = P + 0.618 \times (H_{t-1} - L_{t-1})$$

### Fibonacci Retracement

Fibonacci retracements are applied when a stock experiences a massive, uninterrupted rally and inevitably begins to pull back. The retracement levels calculate hidden support zones where the algorithm expects buying pressure to re-emerge.

The algorithm identifies the absolute swing low ( L_swing ) that initiated the rally and the absolute swing high ( H_swing ) that capped it. It then calculates the critical pullback thresholds:

$$\text{Key Support Levels} = L_{swing} + [0.382, 0.500, 0.618] \times (H_{swing} - L_{swing})$$

- The **0.618 (61.8%) retracement level** serves as the ultimate failure threshold. If the algorithm detects a daily close below the 61.8% level, the preceding uptrend is mathematically invalidated, and the stock is removed from long-biased watchlists.

### Historical Price Clustering (K-Means Machine Learning)

Traditional support and resistance lines are inherently subjective, prone to human error, and often based on singular, random price spikes. To remove this bias, the algorithm deploys machine learning to identify structural zones where NEPSE prices have historically congested.⁴⁶

**Mathematical Logic and Execution:**

1. **Data Extraction:** Extract a continuous array of daily closing prices over a rolling 252-day period.
2. **Algorithm Initialization:** Apply a 1-dimensional K-Means clustering algorithm from a machine learning library.⁴⁶
3. **Clustering Mechanics:** The algorithm partitions the thousands of closing prices into K distinct sets (clusters). It does this by randomly assigning K centroids, assigning each price point to the nearest centroid, and iteratively recalculating the centroid as the mean of the assigned points until the positions stabilize.⁴⁸ This process minimizes the within-cluster sum of squares, mathematically known as inertia.⁵⁰
4. **Parameter Optimization:** Selecting the correct number of clusters (K) is critical. Setting K too high generates noise; setting it too low generates unusable, massive ranges.⁴⁶ The algorithm tests multiple values of K and plots the resulting inertia. Using the **"elbow point" method**, the optimal K for a single stock is typically identified as 4 or 5.⁴⁶
5. **Output:** The final derived centroids represent mathematically validated, high-density historical support and resistance zones. If a stock drops into a lower cluster centroid, it represents a high-probability mean-reversion buy zone.

---

## Risk Metrics and Capital Preservation

Mathematical risk management is the only mechanism that guarantees long-term survival in highly volatile frontier markets. An algorithm with mediocre entries but flawless risk management will outperform an algorithm with flawless entries but nonexistent risk parameters.

### Position Sizing using ATR-Based Stop Loss

Static percentage stop-losses (e.g., arbitrarily exiting a trade if it drops 5 percent) are mathematically irrational. They fail entirely because they do not account for a specific asset's inherent baseline volatility.³³ A 5 percent stop on a highly volatile, low-float NEPSE microfinance stock will be prematurely triggered by standard intraday noise. Conversely, a 5 percent stop on a rigid, high-cap commercial bank exposes too much capital to unnecessary risk. The Average True Range (ATR) normalizes this volatility across all assets.³²

**Dynamic Stop Loss Calculation:** The algorithm places the stop-loss order a specific multiple of the ATR below the entry price, placing it mathematically outside the threshold of normal market noise.³²

$$\text{Stop Price} = \text{Entry Price} - (1.5 \times ATR_{14})$$

**Position Sizing Execution:** The total number of shares to purchase is reverse-engineered from the total account equity and the user's defined risk tolerance (never risking more than 1% to 2% of total equity on a single trade).³³

$$\text{Risk Amount} = \text{Total Account Equity} \times 0.015$$

$$\text{Shares to Purchase} = \frac{\text{Risk Amount}}{\text{Entry Price} - \text{Stop Price}}$$

### Reward-to-Risk Ratio

Before the algorithm clears a stock for the final watchlist, the projected exit target must mathematically justify the required risk.⁵²

**Ratio Formula:**

$$\text{R:R} = \frac{\text{Target Price} - \text{Entry Price}}{\text{Entry Price} - \text{Stop Price}}$$

- The Target Price is objectively derived from the next historical K-Means resistance cluster centroid or the Fibonacci R2 pivot level. The algorithm strictly requires a minimum acceptable ratio of **2.0** (risking 1 unit of capital to secure 2 units of profit) to approve the trade.⁵²

### Identifying High-Risk Flags

The algorithmic pipeline acts as a harsh gatekeeper, applying binary boolean flags to permanently reject un-tradable or overly dangerous stocks before they corrupt the final watchlist.

1. **Low Liquidity Flag:** If `SMA_20(Volume)` falls below an absolute threshold of 5,000 shares, the stock is flagged as untradable. Entering this stock guarantees massive slippage, where the spread between the bid and ask prices will instantly consume the projected profit margin.

2. **Circuit Volatility Flag:** The NEPSE's 10 percent circuit breaker mechanism artificially distorts price action.³ If a stock has slammed into the upper or lower circuit limit on more than two of the last five trading sessions, its probability distribution is violently non-normal. The algorithm sets a boolean flag to True, suspending all automated analysis on the asset until volatility normalizes.

---

## Final Stock Scoring and Watchlist Logic

To execute precise, premeditated trades when the NEPSE opens at 11:00 AM the following day, the algorithm must synthesize the dozens of isolated mathematical indicators detailed above into a unified, actionable watchlist. This is achieved through a weighted composite scoring system.

### Composite Score Weights

A multi-factor model evaluates each surviving stock across five analytical dimensions, assigning a normalized score from 0–100.

| Analytical Dimension | Weight | Primary Indicators Utilized | Logic for Weight Allocation |
|---|---|---|---|
| **Price Action & Trend** | 30% | SMA Alignments, Candlesticks, 52W Proximity | The dominant trend dictates probability. Trading against a primary trend in the NEPSE is statistically inferior and heavily penalized. |
| **Momentum Velocity** | 25% | ROC, RSI, MACD Histogram | Captures the raw speed of the trend. High momentum is critical for ensuring capital is not tied up in stagnant, sideways swing trades. |
| **Volume & Liquidity** | 20% | Volume Ratio, OBV, Volume Profile (POC) | Volume confirms the validity of price. High momentum coupled with anemic volume is flagged as a false signal and downgraded. |
| **Sector Strength** | 15% | Sector Breadth, Gainers/Losers Ratio | Incorporates the "rising tide" effect. A mediocre stock in a rapidly strengthening sector will often outperform a strong stock in a dying sector. |
| **Risk & Structure** | 10% | ATR distance, K-Means Support Proximity | Mildly penalizes stocks that are extended too far above structural support or possess erratic, untradable volatility profiles. |

### Watchlist Output and Algorithmic Sequence Execution

The end-to-end execution of the Python algorithm operates autonomously each evening following the closure of the NEPSE.

1. **Data Ingestion and Validation:** The script queries the MySQL nepsego database, verifying that both the daily_summary and live_market_snapshots arrays are fully populated for the completed trading day.⁴

2. **Corporate Action Sanitization:** The script executes backward adjustments on the OHLC data for any newly executed bonus or right share distributions, ensuring continuous time-series integrity.⁹

3. **Metric Calculation Pass:** The system calculates the extensive array of moving averages, momentum oscillators, volume thresholds, and VWAP metrics across the entire cross-section of the exchange.

4. **Hard Filtering:** Stocks triggering the Low Liquidity Flag, the Circuit Volatility Flag, or currently trading below their 200-day SMA are instantly purged from the active array to preserve computational efficiency.

5. **Scoring and Ranking:** The weighted composite scoring formula is applied to the surviving universe of equities. The list is sorted in descending order.

6. **Target Generation:** For the top five ranked equities, the script dynamically calculates the precise ATR-based Stop Loss level, the K-Means Resistance Target, and the exact share position size based on the predetermined account equity risk parameters.

The final output is a clean, prioritized, and mathematically rigorous roadmap. By synthesizing macroeconomic trend data with microstructural volume profiling, the pipeline strips away the behavioral noise inherent in frontier markets, providing an objective architecture for next-day execution on the Nepal Stock Exchange.

---

## Works Cited

1. Nepal Stock Exchange - Wikipedia, accessed February 23, 2026, https://en.wikipedia.org/wiki/Nepal_Stock_Exchange
2. Second Negative Circuit in Nepse - News, accessed February 23, 2026, https://news.nepsetrading.com/second-negative-circuit-in-nepse?lang=en
3. NEPSE Implements Circuit Breakers as Index Surges by 4%, Triggers Temporary Trading Halt For 20 Minutes - ShareSansar, accessed February 23, 2026, https://www.sharesansar.com/newsdetail/nepse-implements-circuit-breakers-as-index-surges-by-4-triggers-temporary-trading-halt-for-20-minutes-2025-10-09
4. nepsego.sql
5. NEPSE Floorsheet - Kaggle, accessed February 23, 2026, https://www.kaggle.com/datasets/shivaharisubedi/nepse-floorsheet
6. Volume weighted average price (VWAP) - QuestDB, accessed February 23, 2026, https://questdb.com/docs/cookbook/sql/finance/vwap/
7. Volume Weighted Average Price (VWAP) in SQL - QuestDB - YouTube, accessed February 23, 2026, https://www.youtube.com/watch?v=LGKedM0afzs
8. NEPSE closes early after third circuit break halts trading for the day - The Himalayan Times, accessed February 23, 2026, https://thehimalayantimes.com/business/nepse-closes-early-after-third-circuit-break-halts-trading-for-the-day
9. This is how share price is adjusted after issuance of Bonus & Right Share, accessed February 23, 2026, https://www.sharesansar.com/c/this-is-how-share-price-is-adjusted-after-issuance-of-bonus-right-share.html
10. bonus share practices in nepalese corporate firms, accessed February 23, 2026, https://elibrary.tucl.edu.np/bitstreams/3634d22f-7f1c-4dd8-a583-54dea5bef971/download
11. NEPSE to Reintroduce Last Traded Price as Closing Price from Tuesday - ShareSansar, accessed February 23, 2026, https://www.sharesansar.com/newsdetail/nepse-to-reintroduce-last-traded-price-as-closing-price-from-tuesday-2025-09-21
12. NEPSE Reverts to Old Rule on Closing Prices - New Business Age, accessed February 23, 2026, https://newbusinessage.com/news/45541/nepse-reverts-to-old-rule-on-closingprices/
13. Quantitative Analysis of Algorithmic Candlestick Pattern for CAPITALCOM:GOLD by MarkitTick - TradingView, accessed February 23, 2026, https://www.tradingview.com/chart/GOLD/u4ZB7dqb-Quantitative-Analysis-of-Algorithmic-Candlestick-Pattern/
14. A Guide to Identifying Candlestick Patterns in Python using Ta-Lib and Custom Formulas, accessed February 23, 2026, https://blog.stackademic.com/a-guide-to-identifying-candlestick-patterns-in-python-using-ta-lib-and-custom-formulas-1b6ff4b0670f
15. How to Read Candlestick Charts: A Complete Guide for Traders - Dukascopy Bank SA, accessed February 23, 2026, https://www.dukascopy.com/swiss/english/marketwatch/articles/how-to-read-candlestick-charts/
16. 16 Candlestick Patterns Every Trader Should Know - IG International, accessed February 23, 2026, https://www.ig.com/en/trading-strategies/16-candlestick-patterns-every-trader-should-know-180615
17. Understanding 7 Candlestick Patterns In Stock Market - ICICI Direct, accessed February 23, 2026, https://www.icicidirect.com/ilearn/technical-analysis/articles/technical-analysis-using-candlesticks
18. 38 Candlestick Patterns for Pro Traders - Bullish And Bearish Chart Patterns - Groww, accessed February 23, 2026, https://groww.in/blog/candlestick-patterns
19. Multiple candlestick patterns part 1: Engulfing & more - Zerodha, accessed February 23, 2026, https://zerodha.com/varsity/chapter/multiple-candlestick-patterns-part-1/
20. Bullish Candlestick Patterns: How to Read, Identify, and Trade with Confidence, accessed February 23, 2026, https://blog.quantinsti.com/bullish-candlestick-patterns/
21. The Importance of the 52-Week High And Low - A Complete Guide - Earn2Trade, accessed February 23, 2026, https://www.earn2trade.com/blog/52-week-high-and-low/
22. 52 Week High Low (Less Than 2 Minutes) - Finance Strategists - YouTube, accessed February 23, 2026, https://www.youtube.com/watch?v=3TSh4uzJNS0
23. 52-Week High-Low/Average Volume/Volume Breakout Strategy - Medium, accessed February 23, 2026, https://medium.com/@redsword_23261/52-week-high-low-average-volume-volume-breakout-strategy-bcefcd9ea6c6
24. NEPSE to open on Friday - Nepal News, accessed February 23, 2026, https://english.nepalnews.com/s/business/nepse-to-open-on-friday/
25. NEPSE trading duration extended till 4 PM; New timings effective from Chaitra 02, 2076, accessed February 23, 2026, https://www.sharesansar.com/newsdetail/nepse-trading-duration-extended-till-4-pm-new-timings-effective-from-chaitra-02-2076
26. NEPSE to Remain Closed for Two Days as Government Declares Public Holiday for Gyalpo Lhosar And Prajatantra Diwas - ShareSansar, accessed February 23, 2026, https://www.sharesansar.com/newsdetail/nepse-to-remain-closed-for-two-days-as-government-declares-public-holiday-for-gyalpo-lhosar-and-prajatantra-diwas-2026-02-18
27. NEPSE Technical Analysis Cheat Sheet - Scribd, accessed February 23, 2026, https://www.scribd.com/document/560346105/Technical-Analysis-Cheat-Sheet
28. Most Accurate Market indicator for traders in Nepal - Nepse Alpha, accessed February 23, 2026, https://nepsealpha.com/post/detail/6713/most-accurate-market-indicator-for-traders-in-nepal
29. How to Use NEPSE Alpha Chart Features for Smarter Trading, accessed February 23, 2026, https://www.fanruan.com/ko-kr/blog/use-nepse-alpha-chart-features-for-smarter-trading
30. Performance Evaluation of Technical Analysis in the Nepalese Stock Market: Implications for Investment Strategies - Semantic Scholar, accessed February 23, 2026, https://pdfs.semanticscholar.org/4740/4970379ced84340cc9f14b5a9652af039bfc.pdf
31. NEPSE in Bollinger Bands - AIMS Press, accessed February 23, 2026, https://www.aimspress.com/article/doi/10.3934/NAR.2021023?viewType=HTML
32. Average True Range (ATR) Indicator & Strategies - AvaTrade, accessed February 23, 2026, https://www.avatrade.com/education/technical-analysis-indicators-strategies/atrindicator-strategies
33. ATR Based Position Sizing Calculator - Google Sites, accessed February 23, 2026, https://sites.google.com/view/indicatorsoftrades/atr-based-position-sizing-calculator
34. How to Use Volume-Weighted Indicators in Trading - Charles Schwab, accessed February 23, 2026, https://www.schwab.com/learn/story/how-to-use-volume-weighted-indicators-trading
35. Volume profile indicators: basic concepts - TradingView, accessed February 23, 2026, https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/
36. Advanced Day Trading Strategies Using Volume Profile - TradingSim, accessed February 23, 2026, https://www.tradingsim.com/blog/advanced-day-trading-strategies-using-volume-profile
37. Volume Profile Explained The #1 Tool for Day Trading & Chart Analysis In 2 Minutes!, accessed February 23, 2026, https://www.youtube.com/watch?v=aib8Fj1R9Rg
38. VWAP Volume Profile [BigBeluga] - TradingView, accessed February 23, 2026, https://pl.tradingview.com/script/4v1ExKvr-VWAP-Volume-Profile-BigBeluga/
39. Volume Profile Trading Strategies: Key Levels & Trade Setups - TrendSpider, accessed February 23, 2026, https://trendspider.com/learning-center/volume-profile-strategies/
40. Best way I can explain how I use volume profile - Reddit, accessed February 23, 2026, https://www.reddit.com/r/Daytrading/comments/1fd1t3m/best_way_i_can_explain_how_i_use_volume_profile/
41. CMC Markets - Stock Beta, accessed February 23, 2026, https://www.cmcmarkets.com/en-gb/shares/stock-beta
42. What is Beta in Finance? Formula & Examples - CFI, accessed February 23, 2026, https://corporatefinanceinstitute.com/resources/valuation/what-is-beta-guide/
43. What is Beta in Finance & How to Calculate It - Valutico, accessed February 23, 2026, https://valutico.com/what-is-beta-and-how-do-you-calculate-beta/
44. Whether you are a trader or an investor: beta can be the measure of risk for you! - ShareSansar, accessed February 23, 2026, https://www.sharesansar.com/newsdetail/whether-you-are-a-trader-or-an-investor-beta-can-be-the-measure-of-risk-for-you
45. INVESTING IN SHARES OF COMMERCIAL BANKS IN NEPAL: AN ASSESSMENT OF RETURN AND RISK ELEMENTS, accessed February 23, 2026, https://www.nrb.org.np/red/no_14investing_in_shares_of_commercial_banks/
46. Using K-means Clustering to Create Support and Resistance - Towards Data Science, accessed February 23, 2026, https://towardsdatascience.com/using-k-means-clustering-to-create-support-and-resistance-b13fdeeba12/
47. Calculating Support & Resistance in Python using K-Means Clustering - αlphαrithms, accessed February 23, 2026, https://www.alpharithms.com/calculating-support-resistance-in-python-using-kmeans-clustering-101517/
48. Lorentzian Key Support and Resistance Level Detector [mishy] - TradingView, accessed February 23, 2026, https://www.tradingview.com/script/39jnMQjE-Lorentzian-Key-Support-and-Resistance-Level-Detector-mishy/
49. K-Means Clustering: The Future of Pinpointing Support and Resistance? - lambdalearner, accessed February 23, 2026, https://lambdalearner.com/picking-support-and-resistance-levels-with-k-means/
50. Using Machine Learning to programmatically determine Stock Support and Resistance Levels - Medium, accessed February 23, 2026, https://medium.com/@judopro/using-machine-learning-to-programmatically-determine-stock-support-and-resistance-levels-9bb70777cf8e
51. 5 Position Sizing Methods for High-Volatility Trades - LuxAlgo, accessed February 23, 2026, https://www.luxalgo.com/blog/5-position-sizing-methods-for-high-volatility-trades/
52. ATR/ADV/RISK Based Position Sizing Calculator - Reddit, accessed February 23, 2026, https://www.reddit.com/r/Daytrading/comments/1gpy56b/atradvrisk_based_position_sizing_calculator/
