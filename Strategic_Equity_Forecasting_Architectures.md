
# Strategic Equity Forecasting Architectures: A Comprehensive Analysis of Database Schema Utilization for Predictive Modeling


## 1. Introduction: The Data-Driven Paradigm of Equity Valuation

The prediction of equity prices is the central problem of quantitative finance, representing a convergence of economic theory, statistical mechanics, and computational intelligence. In the modern era, the capability to forecast share prices is less dependent on subjective intuition and more reliant on the rigorous exploitation of structured data. The database schema presented for analysis—comprising time-series market data (daily_prices), corporate event registries (corporate_actions), market microstructure logs (broker_floorsheet), fundamental descriptors (fundamentals), and system integrity records (system_logs)—constitutes a "digital twin" of the market ecosystem. This report provides an exhaustive examination of the methodologies available to leverage this schema for predictive accuracy, articulating not only the how of algorithm construction but the theoretical why that validates each approach.

Financial markets are complex adaptive systems where information is processed by heterogeneous agents—from high-frequency algorithms to long-term value investors—to discover price. The Efficient Market Hypothesis (EMH) posits that prices reflect all available information, rendering prediction impossible. However, empirical evidence suggests that markets exhibit inefficiencies, behavioral biases, and information asymmetries that generate predictable patterns. By dissecting the provided database schema, we can categorize predictive methodologies into four distinct but complementary domains: Quantitative Technical Analysis (processing price/volume history), Fundamental Valuation (processing economic reality), Microstructure Forensics (processing agent behavior), and Machine Learning Synthesis (non-linear pattern recognition).

The following analysis details how every table and column in the schema serves as a critical input vector for these predictive engines. We explore the mathematical derivations of indicators, the economic logic of valuation adjustments, and the computational architectures of neural networks, providing a roadmap for transforming raw database records into actionable alpha.


## 2. Data Engineering and Normalization: The Foundation of Prediction

Before any predictive model can be deployed, the integrity and continuity of the input data must be established. The daily_prices table, containing Open, High, Low, Close, and Volume (OHLCV) data, is the primary input for most models. However, raw price data is inherently flawed for predictive purposes due to corporate actions. The corporate_actions table is therefore not merely metadata; it is the corrective lens through which the market's history must be viewed.


### 2.1 The Theoretical Necessity of Price Adjustment

Stock prices are subject to "nominal" shocks that do not reflect "real" economic changes. A predictive algorithm trained on unadjusted data will fail catastrophically. For instance, if a company executes a 2-for-1 stock split, the price of a share drops by 50% overnight. An unadjusted model interprets this as a massive crash, triggering sell signals.1 In reality, the shareholder's equity value remains constant because the number of shares held has doubled.

To maintain the statistical properties of the time series—specifically, to preserve the continuous nature of returns—historical prices must be backward-adjusted. This process creates a "Total Return" or "Adjusted" series that reflects the theoretical growth of an investment, independent of capital structure changes.2 The corporate_actions table enables the calculation of adjustment factors () which are applied multiplicatively to the daily_prices.


### 2.2 Mathematical Framework for Corporate Action Adjustments

The adjustment logic varies by the type of corporate action. The accuracy of these calculations is paramount, as even minor errors propagate through subsequent technical indicators and machine learning features.

2.2.1 Cash Dividends

When a dividend is paid, the company's market capitalization decreases by the total payout amount. The share price drops on the ex-dividend date by approximately the dividend per share ().

Mechanism: To make historical prices comparable to the current post-dividend price, we lower the past prices.


# Formula:

Where  is the closing price on the day prior to the ex-dividend date (cum-dividend).

Why it works: This adjustment ensures that the percentage drop caused by the cash payout is removed from the volatility calculation, preventing the model from learning false volatility patterns.1

2.2.2 Bonus Shares and Stock Splits

Bonus shares (stock dividends) and splits increase the number of outstanding shares while keeping the market capitalization constant. This results in a purely nominal dilution of the share price.


# Mechanism: The adjustment factor is derived from the ratio of new shares to old shares.

Formula:
If the bonus ratio is  (e.g., a 1:1 bonus implies , or 100%), the new number of shares is  times the old count.

For a stock split of ratio  (e.g., 2-for-1), the factor is .

Example: For a 1:1 bonus (100%), the price halves. The factor is . Historical prices are multiplied by 0.5.4

2.2.3 Rights Issues: Complex Dilution

Rights issues are particularly critical in markets like NEPSE (Nepal Stock Exchange). They involve issuing new shares to existing shareholders at a discounted subscription price (). This action combines the mechanics of a split (increasing share count) with a capital infusion (increasing market cap).

Mechanism: The price adjustment must account for the weighted average price of the old shares and the new, cheaper shares.


# Formula:
The Theoretical Ex-Rights Price () is calculated as:

Where:

= Market price before book closure (Close price).

= Price at which rights shares are offered.

= Rights ratio (e.g., 0.25 for 25%).
The Adjustment Factor () is then:

Why it works: This formula calculates the theoretical dilution. Predictive models use this to smooth the price drop that occurs when the rights are exercised, ensuring the trend lines remain continuous rather than broken.6


## 3. Quantitative Technical Analysis: Signal Processing of Time-Series Data

Once the daily_prices data is adjusted, it becomes a candidate for Technical Analysis (TA). TA is not merely "chart reading"; it is a form of signal processing where the input signal (price/volume) is transformed to extract features related to momentum, trend, and volatility. These features serve as the primary predictive variables.


### 3.1 Time-Series Momentum and Oscillators

Momentum indicators are based on the physical law of inertia: an object in motion tends to stay in motion unless acted upon by an external force. In financial terms, a price trend tends to persist until the buying/selling pressure is exhausted.

3.1.1 Relative Strength Index (RSI)

The RSI is a momentum oscillator that measures the speed and change of price movements. It utilizes the Close column of the daily_prices table.


# Calculation Logic:

Calculate daily changes: .

Separate into Gains () and Losses (). If , . If , .

Calculate Smoothed Moving Averages (SMMA) of  and  over  periods (usually 14).

Compute Relative Strength (): .

Compute RSI:


# Predictive Application:

Mean Reversion: When RSI > 70, the asset is considered "overbought." Mathematically, this means the recent average gains are significantly larger than average losses. Statistical mean reversion suggests that such unidirectional movement is unsustainable, predicting a pull-back. Conversely, RSI < 30 predicts a bounce.8

Divergence: If price makes a higher high, but RSI makes a lower high, it indicates that the momentum of the trend is slowing despite the price increase—a powerful predictor of a reversal.

3.1.2 Moving Average Convergence Divergence (MACD)

MACD is a trend-following momentum indicator that reveals changes in the strength, direction, momentum, and duration of a trend.


# Calculation Logic:

Calculated as the difference between a fast Exponential Moving Average (EMA, usually 12-period) and a slow EMA (26-period).

A "Signal Line" is calculated as the 9-period EMA of the MACD Line.

The "Histogram" is the difference: .

Why it works: Moving averages smooth out "noise." By comparing a short-term smooth signal (12 EMA) with a long-term smooth signal (26 EMA), MACD derivatives isolate the current rate of change relative to the historical baseline. A positive crossover (MACD > Signal) implies that recent price action is accelerating upward faster than the historical average, predicting trend continuation.8


### 3.2 Volatility Analysis and Bollinger Bands

Volatility is a measure of the dispersion of returns. Predictive models use volatility not just to forecast risk, but to forecast price breakouts.

Bollinger Bands: These consist of a simple moving average (SMA) and two standard deviation () bands above and below it.

Predictive Logic (The Squeeze): Volatility is cyclical. Periods of low volatility (bands contracting or "squeezing") are statistically followed by periods of high volatility (expansion). While the bands don't predict direction, a "squeeze" in the database (calculated via sliding window variance) is a highly reliable predictor of an imminent violent move.8


### 3.3 Deep Candlestick Mining (DCM)

While traditional patterns (Doji, Hammer) are well-known, they are often subjective. Advanced research introduces "Deep Candlestick Mining," a data-mining technique applied to OHLC vectors.


# Methodology:

The OHLC data is encoded into vector representations (e.g., body length, shadow length, open-close delta).

Unsupervised learning algorithms (like K-Means or Hierarchical Clustering) group these vectors into distinct clusters based on geometric similarity.

The algorithm then analyzes the transition probabilities: Given Cluster A (a specific candle shape), what is the probability of the next price move being positive?

Why it works: This removes human bias. Instead of relying on a textbook definition of a "Hammer," the system learns the specific micro-patterns that historically precede price jumps for a specific stock or market, capturing unique volatility signatures.9


### 3.4 Volume Dynamics and Liquidity

The Volume column in daily_prices is the fuel of the market. Price movement without volume is considered "hollow" or weak.


# Volume Weighted Average Price (VWAP):

VWAP serves as a benchmark for institutional execution.


# Predictive Logic:

Confirmation: If Price rises and Volume rises, the trend is supported by broad participation (accumulation).

Anomaly: If Price rises but Volume falls (divergence), it predicts a reversal due to lack of demand.

Liquidity Analysis: In predictive models, volume is often used to weight the significance of a price signal. A "Buy" signal on low volume is assigned a low confidence score.8


## 4. Fundamental Valuation: Linking Market Price to Economic Reality

While technical analysis focuses on market price, fundamental analysis focuses on value. The schema supports this through fundamentals, listed_shares, and market_capitalization tables. The premise is that in the short run, the market is a voting machine (driven by psychology/technicals), but in the long run, it is a weighing machine (driven by fundamentals).


### 4.1 Enterprise Value and Valuation Ratios

The market_capitalization is a crude measure of size. A more sophisticated predictor is Enterprise Value (EV), which effectively treats the company as a takeover target.


# Calculation:


# Predictive Application:

EV/EBITDA: This ratio is often superior to the P/E ratio because it neutralizes differences in capital structure (debt levels) and taxation between companies. A low EV/EBITDA relative to the sector average predicts that the stock is undervalued and likely to appreciate as the market corrects this inefficiency.11

Acquirer's Multiple: Deep value investors use EV/Operating Earnings to identify stocks that are cheap relative to their core business profitability.


### 4.2 The Mechanics of P/E and EPS

The Price-to-Earnings (P/E) ratio is the standard metric for gauging market expectations.


# Formula:


# Why it works:

Mean Reversion: Sectors tend to trade within historical P/E bands. If a bank usually trades at 15x earnings but drops to 8x without a fundamental deterioration in business, the model predicts a price rise to restore the ratio.12

Growth Implication: A high P/E implies high expected growth. If the fundamentals table shows declining EPS growth while P/E remains high, the stock is a "growth trap," predicting a sharp correction (multiple compression).

PEG Ratio: To refine the P/E signal, we divide it by the earnings growth rate ().

A PEG < 1.0 suggests the stock is undervalued relative to its growth, offering a potent "Buy" signal.12


### 4.3 Market Capitalization Stratification

Using the market_capitalization table, stocks can be stratified into Large-Cap, Mid-Cap, and Small-Cap.


# Predictive Logic:

Risk/Reward Profiles: Small-cap stocks generally exhibit higher volatility (Beta) and higher growth potential. During economic expansions (bull markets), small-caps tend to outperform large-caps. During recessions, capital flees to the safety of large-caps.

Liquidity Risk: Models must adjust predictions for micro-cap stocks where listed_shares and float are low, as small orders can cause disproportionate price impact (slippage).11


### 4.4 The "Fusion" Approach: Integrating Tech and Fundamentals

Research consistently demonstrates that combining these schools of thought yields superior results.


# Methodology:

Screening (Fundamental): Use SQL to query the fundamentals table. Select stocks where  and . This identifies high-quality candidates.

Timing (Technical): For the selected subset, query daily_prices to calculate RSI. Execute a "Buy" only when  (Oversold).

Why it works: Fundamentals determine what to buy (reducing the risk of buying garbage), while technicals determine when to buy (optimizing the entry price). This dual-filter approach significantly improves the Sharpe Ratio of the predictive model.14


## 5. Market Microstructure Forensics: Analyzing the broker_floorsheet

One of the most powerful features of the provided schema is the broker_floorsheet table. In many markets (like NEPSE), broker-level transaction data is transparent. This allows for Microstructure Forensics, a method that tracks the behavior of specific market participants ("Smart Money" vs. "Dumb Money"). This is distinct from technical analysis as it analyzes who is trading, not just how much.


### 5.1 Tracking Institutional Accumulation ("Smart Money")

Institutional investors (mutual funds, portfolio managers) trade in volumes that can move the market. They often attempt to disguise their intentions by breaking large orders into smaller chunks (iceberg orders) or using specific brokers.


# Accumulation Logic: Institutions accumulate shares before a major price markup.

Metric: Net Accumulation:

By aggregating this over a rolling window (e.g., 30 days) for top brokers known to serve institutions (e.g., Broker 58 in NEPSE), we can detect net inflows.

Predictive Signal: A rising Net Accumulation curve for top brokers, especially when the share price is flat (consolidation), indicates Passive Accumulation. The institutions are absorbing all supply at a specific price level. This acts as a coiled spring; once the supply is exhausted, the price is predicted to explode upwards.16


### 5.2 Floorsheet Metrics and Divergence

Machine learning models can ingest specific features derived from the floorsheet to predict price direction.

5.2.1 The Concentration Ratio


# Definition: The percentage of total turnover handled by the top  brokers.

Why it works: High concentration often implies coordinated action or a specific entity taking a massive position. If concentration is high on the Buy side but low on the Sell side (many small sellers, one big buyer), it predicts bullish price action due to the transfer of stock from weak hands (retail) to strong hands (institutions).17

5.2.2 Weighted Average Buy Rate (WABR)


# Definition: The average price at which a broker has built their inventory.

Predictive Logic (Support/Resistance): The WABR of a major accumulator acts as a dynamic support level.

Support: If the market price approaches the WABR of a major holder, they are likely to defend their position (buy more) to prevent going "underwater" (into a loss).

Resistance: If the price is significantly above their WABR, they may start distributing (taking profit).

Underwater: If the current price is below the WABR of the largest holders, it creates a "supply overhang" as these trapped longs wait to sell at break-even.16

5.2.3 Matching Volume and Cross-Trades


# Definition: Transactions where the Buyer Broker and Seller Broker are the same.

Interpretation: While sometimes coincidental, high levels of matching volume often indicate internal transfers or "cross-trades" arranged off-market and printed on the exchange.

Prediction: A spike in matching volume often precedes major corporate announcements or changes in ownership structure, serving as a volatility warning.16


### 5.3 Divergence Analysis: Cumulative Delta

Concept: Cumulative Delta tracks the difference between aggressive buying (at Ask) and aggressive selling (at Bid).


# Signal:

Bullish Divergence: If Price is making a Lower Low, but Cumulative Delta is making a Higher Low, it indicates that although price is dropping, the aggressive selling pressure is drying up and buyers are stepping in. This is a potent reversal signal.

Bearish Divergence: Price making a Higher High while Delta makes a Lower High suggests the rally is hollow and lacks aggressive buying support.16


## 6. Machine Learning Architectures: Non-Linear Predictive Models

Traditional statistical methods (Linear Regression) assume linear relationships between variables. Financial markets, however, are inherently non-linear and chaotic. Machine Learning (ML) approaches utilize the full breadth of the schema to model these complex dependencies.


### 6.1 Feature Engineering from Schema

The raw data must be transformed into an input tensor  for ML models.


# Lag Features:  (capturing autocorrelation).


# Rolling Statistics: Rolling Mean, Rolling Variance (capturing regime changes).


# Floorsheet Features: Broker Concentration, Net Buy Pressure.


# Fundamental Features: P/E Ratio, Market Cap (broadcasted to daily frequency).

Target Variable (): Often defined as the direction of the price at  (Classification: Up/Down) or the log return (Regression).18


### 6.2 Long Short-Term Memory (LSTM) Networks

LSTM is a specialized Recurrent Neural Network (RNN) designed for sequence prediction. It is the state-of-the-art for financial time series.

The Vanishing Gradient Problem: Standard RNNs fail to learn long-term dependencies (e.g., an event 3 months ago affecting price today) because the error gradient decays exponentially during backpropagation.


# LSTM Architecture: LSTMs introduce a "Memory Cell" and three gates to solve this:

Forget Gate (): Decides what information from the previous cell state  is no longer relevant (e.g., "forget the volatility from the earnings announcement now that it's over").


# Input Gate (): Decides what new information () to store in the cell state.


# Output Gate (): Decides what the next hidden state  should be (the prediction).

Why it works: LSTMs can "remember" a trend established 50 days ago while simultaneously reacting to a volume spike today. Research on NEPSE data confirms LSTMs significantly outperform ARIMA and BPNN models in accuracy.15


### 6.3 Hybrid Models: EMD-LSTM

Financial data is noisy. "Noise" (random fluctuation) can confuse ML models.

Empirical Mode Decomposition (EMD): This signal processing technique decomposes the price time series into a set of "Intrinsic Mode Functions" (IMFs)—oscillations of different frequencies—and a residual trend.


# Application:

Decompose price into High-Frequency IMFs (Noise) and Low-Frequency IMFs (Trend).

Discard the high-frequency noise or model it separately.

Feed the clean trend components into the LSTM.

Result: The Akima-EMD-LSTM model has been shown to beat standard LSTMs by effectively filtering out the "jitter" of the market, focusing the neural network on the underlying structural movement.20


### 6.4 Natural Language Processing (NLP) and Sentiment Fusion

While the SQL schema focuses on structured data, snippets suggest integrating unstructured data (News, Social Media) for enhanced prediction.


# Methodology:

Ingest news headlines relevant to the stock.

Use NLP tools (VADER, TextBlob, BERT) to compute a Sentiment Score ().

Append this score to the input vector of the LSTM alongside OHLCV data.

Why it works: Markets are information processing machines. News drives sentiment, and sentiment drives price. A technical breakout accompanied by positive sentiment (High ) has a much higher probability of success than one without news support. This "Data Fusion" approach aligns with the multi-channel nature of modern trading.22


## 7. Seasonality, Sector Dynamics, and Market Cycles

The market_indices and daily_prices tables allow for the analysis of cyclical patterns and inter-sector relationships.


### 7.1 The "Ashad Effect": A Fiscal Anomaly

In the context of the Nepal Stock Exchange (NEPSE), seasonality is a dominant force, driven by the government's fiscal calendar.

The Phenomenon: July (the month of Ashad/Shrawan) is statistically the most bullish month in NEPSE history.


# Causal Mechanisms:

Capital Expenditure: The government rushes to spend the remaining development budget before the fiscal year ends in mid-July. This injects massive liquidity into the banking system, lowering interest rates and fueling stock purchases.25

Dividend Anticipation: Listed companies close their books in July. Investors accumulate shares in anticipation of strong Q4 reports and dividend declarations.

Tax Clearance: Conversely, selling pressure may occur in late June as traders liquidate assets to pay taxes, creating a "dip" that smart money buys into before the July rally.

Predictive Logic: A model incorporating a "Month-of-Year" feature or "Days-To-Fiscal-End" variable can exploit this anomaly, assigning higher probabilities to Buy signals in the June-July window.25


### 7.2 Lead-Lag Relationships and Sector Rotation

Sectors do not move in unison. They rotate based on the economic cycle.

Beta Analysis: Using market_indices, we calculate the Beta () of each sector relative to the NEPSE index.


# High Beta (Banking, Hydropower): Aggressive sectors that lead bull markets.


# Low Beta (Staples): Defensive sectors that hold value during downturns.28

Lead-Lag Detection: Research indicates that certain indices or large-cap sectors often "lead" the broader market.

Algorithm: Compute the Cross-Correlation Function (CCF) between the Banking Index () and the Hydro Index (). If correlation is maximized at a lag of , it implies movements in Banking predict movements in Hydro two days later. This allows for predictive arbitrage.30


## 8. System Architecture: Data Integrity and Anomaly Detection

A predictive model is only as good as its data. The system_logs and collection_runs tables are critical for Data Quality Assurance (DQA) and Anomaly Detection.


### 8.1 Ensuring Data Integrity

Real-world data pipelines are prone to errors: missing feeds, stale prices, or erroneous spikes.

Audit Logs: The system_logs table records who modified data and when. If a dividend adjustment was manually entered by an operator at an unusual time, this serves as a flag for verification.

Timestamp Monitoring: The collection_runs table tracks data ingestion latency. If the time difference between market_close and data_ingest exceeds a threshold, the data may be stale. Predictive models should have a "Circuit Breaker" to halt trading if data freshness is compromised.32


### 8.2 Anomaly Detection Algorithms

Before data is fed into a model (like an LSTM), it must pass through an Anomaly Detector.


# Technique: Isolation Forests or Autoencoders are used to detect outliers in the ingestion stream.

Scenario: If a stock price jumps 500% in one second (a "fat finger" error), an Isolation Forest will flag this as an anomaly because it isolates the point with very few splits.

Why it works: This prevents "Garbage In, Garbage Out." It ensures that the predictive model is training on valid market volatility, not database errors. Detecting anomalies in system_logs can also preemptively identify infrastructure failures that would disrupt the prediction pipeline.34


## 9. Conclusion

The prediction of share prices using the provided SQL schema is a multidisciplinary challenge that transcends simple chart reading. It requires a holistic architecture that integrates:

Rigorous Data Engineering: Utilizing corporate_actions to mathematically adjust prices, ensuring the time series reflects economic reality (Total Return) rather than nominal price shocks.

Financial Theory: Leveraging fundamentals and market_cap to anchor predictions in valuation realities (EV, P/E), exploiting the tendency of price to revert to intrinsic value.

Microstructure Forensics: Mining broker_floorsheet data to track the invisible hand of "Smart Money," utilizing concentration ratios and accumulation patterns to predict supply shocks.

Advanced Machine Learning: Deploying non-linear architectures like LSTMs and Hybrid EMD models to synthesize these disparate features, capturing the chaotic and sequential nature of market returns.

Contextual Awareness: Accounting for seasonality (Ashad Effect) and system integrity (system_logs) to refine signal accuracy and manage operational risk.

By fusing these methodologies—Technical, Fundamental, Microstructure, and Computational—into a unified predictive framework, the schema transforms from a static repository of data into a dynamic engine for generating alpha.


## 10. Summary of Predictive Methodologies



| Methodology | Primary Schema Tables | Key Predictive Concept | Why It Works (Theoretical Basis) |
| --- | --- | --- | --- |
| Price Adjustment | daily_prices, corporate_actions | Total Return Series | Economic Continuity: Eliminates artificial price drops from dividends/splits, ensuring models learn real volatility. |
| Technical Analysis | daily_prices (OHLCV) | RSI, MACD, Bollinger Bands | Mean Reversion: Prices oscillate around equilibrium; momentum persists due to market psychology (inertia). |
| Fundamental Valuation | fundamentals, market_cap | EV/EBITDA, P/E, PEG | Value Convergence: In the long run, share price tracks the earnings power and cash flow of the firm. |
| Floorsheet Forensics | broker_floorsheet | Net Accumulation, WABR | Information Asymmetry: Institutional "Smart Money" leaves footprints (volume/accumulation) that reveal future intent. |
| Deep Learning | All Tables (Fused) | LSTM, EMD-LSTM | Non-Linear Approximation: Captures complex, long-term temporal dependencies and volatility clusters invisible to linear models. |
| Seasonality | daily_prices, dates | Ashad Effect (Fiscal Year) | Structural Cycles: Government spending and tax deadlines create predictable liquidity waves. |
| Anomaly Detection | system_logs | Outlier Detection | Risk Management: Prevents model contamination by filtering out database errors and ingestion failures. |


Works cited

Calculating Stock Price: Detailed How-To | RoboMarkets Blog, accessed February 6, 2026, https://www.robomarkets.com.cy/blog/education/calculating-stock-price-detailed-how-to/

Corporate Actions - QuantConnect.com, accessed February 6, 2026, https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-actions

A Stock Price Prediction Approach Based on Time Series Decomposition and Multi-Scale CNN using OHLCT Images - arXiv, accessed February 6, 2026, https://arxiv.org/html/2410.19291v2

How to Calculate the Impact of Bonus Shares on Your Investment, accessed February 6, 2026, https://www.shareindia.com/knowledge-center/share-market/how-to-calculate-the-impact-of-bonus-shares-on-your-investment

What is Adjusted Closing Price and How to Calculate? - Groww, accessed February 6, 2026, https://groww.in/p/adjusted-closing-price

Know about Bonus & Right Share calculation after adjustment - ShareSansar, accessed February 6, 2026, https://www.sharesansar.com/c/know-about-bonus-right-share-calculation-after-adjustment.html

This is how share price is adjusted after issuance of Bonus & - ShareSansar, accessed February 6, 2026, https://www.sharesansar.com/c/this-is-how-share-price-is-adjusted-after-issuance-of-bonus-right-share.html

What if NEPSE and SEBON decide to hide broker numbers from the floorsheet?, accessed February 6, 2026, https://nepsealpha.com/post/detail/6563/what-if-nepse-and-sebon-decide-to-hide-broker-numbers-from-the-floorsheet

Machine Learning Methods to Exploit the Predictive Power of Open, High, Low, Close (OHLC) Data - UCL Discovery - University College London, accessed February 6, 2026, https://discovery.ucl.ac.uk/id/eprint/10155501/2/AndrewDMannPhDFinal.pdf

How to Use OHLCV Data to Improve Technical Analysis in Trading | Finage Blog, accessed February 6, 2026, https://finage.co.uk/blog/how-to-use-ohlcv-data-to-improve-technical-analysis-in-trading--684007623458598454e3dd10

Market Capitalization: What It Means for Investors - Investopedia, accessed February 6, 2026, https://www.investopedia.com/terms/m/marketcapitalization.asp

Fundamental vs Technical Analysis: What Is the Difference? | IG ..., accessed February 6, 2026, https://www.ig.com/en/trading-strategies/fundamental-vs-technical-analysis--what-s-the-difference--230605

Capital Market Development and Stock Price Behaviour in Nepal, accessed February 6, 2026, https://www.nrb.org.np/contents/uploads/2022/07/vol13_art1.pdf

Technical vs. fundamental analysis - Wealthsimple, accessed February 6, 2026, https://www.wealthsimple.com/en-ca/learn/technical-vs-fundamental-analysis

Stock Market Prediction Using Machine Learning and Deep Learning Techniques: A Review, accessed February 6, 2026, https://www.mdpi.com/2673-9909/5/3/76

"Alpha Floorsheet Charts! Game Changing Charts for Traders in ..., accessed February 6, 2026, https://nepsealpha.com/post/detail/6541/alpha-floorsheet-charts-game-changing-charts-for-traders-in-nepal

(PDF) Research on stock price prediction from a data fusion perspective - ResearchGate, accessed February 6, 2026, https://www.researchgate.net/publication/372835184_Research_on_stock_price_prediction_from_a_data_fusion_perspective

Survey of feature selection and extraction techniques for stock market prediction - PMC - NIH, accessed February 6, 2026, https://pmc.ncbi.nlm.nih.gov/articles/PMC9834034/

Enhancing OHLC Data with Timing Features: A Machine Learning Evaluation - arXiv, accessed February 6, 2026, https://arxiv.org/html/2509.16137v1

Prediction of Complex Stock Market Data Using an Improved Hybrid EMD-LSTM Model, accessed February 6, 2026, https://www.mdpi.com/2076-3417/13/3/1429

Stock Market Prediction in Nepali Stock Market using Machine Learning Model - Nepal Journals Online, accessed February 6, 2026, https://www.nepjol.info/index.php/kjse/article/download/69290/52884

Stock Price Movement Prediction Using Sentiment Analysis and CandleStick Chart Representation - PMC, accessed February 6, 2026, https://pmc.ncbi.nlm.nih.gov/articles/PMC8659448/

Predicting the Direction of NEPSE Index Movement with News Headlines Using Machine Learning - MDPI, accessed February 6, 2026, https://www.mdpi.com/2225-1146/12/2/16

Research on stock price prediction from a data fusion perspective - AIMS Press, accessed February 6, 2026, https://www.aimspress.com/article/doi/10.3934/DSFE.2023014?viewType=HTML

JULY, “The most dominating and statistically significant bullish month in the history of Nepal Stock Market'' - Nepse Alpha, accessed February 6, 2026, https://nepsealpha.com/post/detail/403/july-the-most-dominating-and-statistically-significant-bullish-month-in-the-history-of-nepal-stock-market

Fiscal Year and Festive Effects on Market Price Movements: A Guide to Trading Strategies at Nepal Stock Exchange, accessed February 6, 2026, https://www.nepjol.info/index.php/pravaha/article/view/76887/58848

Why the month of July is the platter of hope for Nepalese investors? Why does market usually make its high during the July? - || ShareSansar ||, accessed February 6, 2026, https://www.sharesansar.com/newsdetail/why-the-month-of-july-is-the-platter-of-hope-for-nepalese-investors-why-does-market-usually-make-its-high-during-the-july

How to Calculate the Beta of a Stock - Nasdaq, accessed February 6, 2026, https://www.nasdaq.com/articles/how-calculate-beta-stock

Sudurpaschim Spectrum, Volume-2, Issue-1, July 2024, 172-192 Market Risk and Cross-section of Expected Stock Returns Abstract Th - Nepal Journals Online, accessed February 6, 2026, https://www.nepjol.info/index.php/sudurpaschim/article/download/69505/53025

An alternative approach to investigating lead-lag relationships between stock and stock index futures markets - CentAUR, accessed February 6, 2026, https://centaur.reading.ac.uk/35968/1/35968.pdf

A Multi-market Comparison of the Intraday Lead–Lag Relations Among Stock Index-Based Spot, Futures and Options - PubMed Central, accessed February 6, 2026, https://pmc.ncbi.nlm.nih.gov/articles/PMC9107071/

Audit Logging: A Comprehensive Guide - Splunk, accessed February 6, 2026, https://www.splunk.com/en_us/blog/learn/audit-logs.html

Why Data Integrity is Key to ML Monitoring | Fiddler AI Blog, accessed February 6, 2026, https://www.fiddler.ai/blog/why-data-integrity-is-key-to-ml-monitoring

System Anomaly Prediction - SAP Support Portal, accessed February 6, 2026, https://support.sap.com/en/alm/sap-focused-run/expert-portal/system-anomaly-prediction.html

STAGE framework: A stock dynamic anomaly detection and trend prediction model based on graph attention network and sparse spatiotemporal convolutional network - Research journals - PLOS, accessed February 6, 2026, https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0318939

Building a Real-Time Anomaly Detection Pipeline for Stock Trading Data with Redpanda and Quix | by Shijun Ju | Medium, accessed February 6, 2026, https://medium.com/@jushijun/building-a-real-time-anomaly-detection-pipeline-for-stock-trading-data-with-redpanda-and-quix-83da5a013599
