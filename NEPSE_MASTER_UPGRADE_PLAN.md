# 🚀 NEPSE Master Upgrade Plan: Next-Generation Trading Intelligence

After a deep analysis of the current `NepseAPI-Unofficial` architecture, your existing SQL database schemas, and the specific structural advantages of the Nepal Stock Exchange (NEPSE), I have designed a comprehensive master plan to take this project from a "Rules-Based Screener" to an **Institutional-Grade AI Trading Engine**.

The NEPSE market is unique. Unlike global markets dominated by high-frequency algorithms, NEPSE is heavily influenced by **broker syndicates, retail sentiment, and liquidity constraints**. To give our users the ultimate edge, we must move beyond traditional indicators (like RSI and MACD) and leverage machine learning to track "Smart Money".

Below is the 5-Phase Master Plan for our users to get the maximum benefit from the system.

---

## Phase 1: Machine Learning Price Prediction (Beyond Rigid Rules)
Currently, our `swing_analyser` uses hardcoded rules (e.g., if price > SMA50, score + 10). While effective, these rules are rigid and don't adapt to changing market dynamics.

* **The Upgrade:** Train an XGBoost or Random Forest machine learning model on our historical `daily_ohlcv` and `company_fundamentals` data.
* **How it works:** Instead of relying on a static "Score of 75", the model will ingest 50+ features (volume spikes, PE ratios, moving averages) and output a exact probability percentage: *"There is an 82% probability this stock will rise by 5% in the next 10 days."*
* **Implementation Step:** We will create a new `ml_predictor/` module that extracts historical data, trains a model, and integrates the probability score into the `master_trader` report.

## Phase 2: Graph-Based "Smart Money" Tracker (Advanced Floorsheet)
NEPSE's greatest public data asset is the **Floorsheet**, which shows exactly which broker bought from which broker. Currently, we only calculate basic "broker asymmetry" (buy vs sell volume).

* **The Upgrade:** Build a Graph Analysis Engine using the `networkx` library to map the relationships between brokers.
* **How it works:** We will detect **"Circular Trading"** and **"Coordinated Accumulation."** If Brokers 58, 34, and 45 are quietly passing shares of a specific hydropower stock between each other while absorbing retail selling, the graph engine will flag this as a "Whale Accumulation Alert."
* **Implementation Step:** Upgrade the `broker_tracker` to build daily directed graphs of trade flows and score stocks based on institutional hoarding behavior.

## Phase 3: Modern Portfolio Optimization (Risk Parity)
The `master_trader` currently gives users a list of stocks to buy and suggests allocating a flat percentage (e.g., 2% risk) to each. 

* **The Upgrade:** Implement Markowitz Efficient Frontier (Modern Portfolio Theory) algorithms.
* **How it works:** If the system recommends 3 Bank stocks and 1 Hydropower stock, buying all 3 banks is highly risky because their prices move together (high correlation). The portfolio optimizer will analyze historical correlations and suggest precise capital allocations (e.g., "Put 40% in Stock A, 15% in Stock B, and 45% in Stock C to mathematically minimize your risk of loss").
* **Implementation Step:** Add a `portfolio_optimizer/` module that runs after `swing_analyser` to group the "Hotlist" stocks into an optimal, diversified basket.

## Phase 4: Real-Time Execution Alerts (Telegram Bot Integration)
Currently, users have to manually run `python -m master_trader` and read an HTML report. In trading, speed is everything.

* **The Upgrade:** Build an asynchronous Telegram or Discord Bot hooked directly into our `socketServer.py` (Live Market WebSocket).
* **How it works:** Users can message the bot: `/alert NABIL breakout`. As soon as NABIL crosses its resistance line on high volume during live market hours, the bot instantly sends a push notification to the user's phone: 🚨 *"NABIL Breakout Detected! Vol: 200% above average. Entry zone reached."*
* **Implementation Step:** Create an `alerts_engine/` running alongside the WebSocket server, utilizing the `python-telegram-bot` framework.

## Phase 5: The Vectorized Backtesting Engine (The Truth Machine)
Users need to trust the system before risking their capital. While we have a forward-testing `evaluator`, we do not have a robust historical backtester.

* **The Upgrade:** Build a fast, vectorized backtesting engine using `pandas` and `numpy`.
* **How it works:** We will simulate our trading rules over the past 5 years of NEPSE data. The engine will output a highly detailed performance report: Maximum Drawdown, Win Rate, Sharpe Ratio, and Profit Factor. 
* **Implementation Step:** Build `backtester.py`. This will mathematically prove to users that following the AI's signals is profitable over the long term, building immense trust in the product.

---

## Conclusion
By executing these 5 phases, the system will evolve from a simple data aggregator into an intelligent, institutional-grade quant system built specifically for the unique mechanics of the Nepal Stock Exchange.
