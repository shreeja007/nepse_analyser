# Documentation: Logic Updates & Signal Accuracy Fixes (20 May 2026)

## 1. The Real-World Problem

We received feedback from users that the analysis engine was providing "opposite" buy/sell signals. Specifically:
* When the overall market was performing poorly, the system was sometimes overly optimistic, generating `BUY` signals.
* Conversely, when stocks were heavily crashed (oversold) and reaching rock bottom, the system was telling users to `SELL`, causing panic selling at the worst possible time.
* As a result, the end-of-day analysis reports felt unhelpful and backwards to traders relying on the system.

## 2. Why We Made These Changes

To fix this, we needed to address the root causes of the engine's behavior:
1. **Overly Sensitive Market Context:** The engine was looking at single-day market movements. A random 1% green day during a larger bear market would trick the system into applying a "Bullish" multiplier to all stocks, artificially inflating their scores and causing fake `BUY` signals.
2. **Multiplicative Scoring:** The market trend was multiplying the base scores (e.g., base score × 1.1). This caused borderline stocks to swing wildly into `BUY` or `SELL` territory just because the market had a slight hiccup.
3. **Rigid Momentum Rules:** The system used rigid thresholds for indicators like the RSI (always using 80 for Overbought and 20 for Oversold). In a strong bear market, a stock might never reach 20 before bouncing, and in a bull market, it might stay above 80 for weeks. 
4. **Punishing Crashed Stocks:** A stock that had crashed heavily (e.g., RSI of 25) but hadn't quite crossed the magic "20" threshold was being graded with a negative "timing" score, pushing the final signal into a `SELL`.
5. **Echo Chamber Scoring:** All indicators (trend, momentum, volume) were being summed together into one giant pot. If a stock was falling, all indicators agreed it was falling, creating an echo chamber that resulted in a `STRONG SELL` right at the support line.

## 3. What Features Changed (The Solution)

To resolve the "opposite signal" problem, we implemented five core logic upgrades across the `analysor`, `swing_analyser`, and `single_analyser` modules:

### A. 10-Day Rolling Market Trend
Instead of reacting to single-day market bumps, the system now calculates a **10-day moving average** of the NEPSE index. The market regime (Strong Bull, Bullish, Neutral, Bearish, Strong Bear) is now decided by sustained, multi-day momentum. A random green day will no longer flip the entire system.

### B. Additive Regime Adjustments
We replaced the multiplicative scoring with **additive point adjustments** (e.g., +2 points for a bullish market, -2 for bearish). This ensures that the market context gently nudges a stock's score, rather than violently swinging a `HOLD` into a `BUY`.

### C. Dynamic RSI Thresholds
The "Overbought" and "Oversold" thresholds now adapt to the market regime:
* **Strong Bull Market:** Oversold line moves up (e.g., 30). Stocks don't drop as deep in bull markets.
* **Strong Bear Market:** Oversold line moves down (e.g., 15). You need a deeper crash to consider it truly "cheap".
* **Neutral Market:** Standard 80/20 rules apply.

### D. "Approaching Oversold" Safety Zones
We introduced buffer zones for timing. If a stock is in a massive downtrend but is *approaching* the oversold line (e.g., within 10 points of the threshold), the system now recognizes that it is "getting cheap." Instead of issuing a `SELL`, it upgrades the timing score, resulting in a `HOLD`. This prevents the system from telling users to sell at the absolute bottom.

### E. Dual-Axis Classification & Confidence Penalties
We separated the final decision matrix into two distinct axes: **Trend** (Is the stock generally moving up or down?) and **Timing** (Is today a good day to enter/exit?). 
Additionally, if indicators contradict each other (e.g., the price is rising, but the volume is dropping), the system now applies a **Confidence Penalty**. This ensures users can trust the "Confidence %" attached to the signal—if the confidence is low, the setup is risky and contradictory.

## Conclusion

These changes shift the engine from being a reactionary script to a much more conservative, realistic trading assistant. By strictly propagating these rules across all analysis modules, the system now heavily favors `HOLD` signals, completely eliminating the fake `BUY` signals in downtrends and the panic `SELL` signals at market bottoms.
