# Broker Tracker Documentation

## What it is
The broker_tracker package reconstructs broker behavior from floorsheet flows, infers accumulation/distribution lifecycle states, computes broker trust metrics, and generates actionable symbol-level signal lists.

## Run Command
- `python -m broker_tracker`

## Data Inputs (DB)
Primary tables:
- `floorsheet_transactions` (core source)
- `daily_ohlcv` (latest closes)
- `company_details` (company/sector context)
- `securities` (sector/instrument context)

## Configuration Thresholds
From config:
- `ACCUMULATION_ASYMMETRY_THRESHOLD = 65`
- `DISTRIBUTION_ASYMMETRY_THRESHOLD = 40`
- `MIN_SESSIONS_FOR_ACCUMULATION = 3`
- `MIN_SESSIONS_FOR_TRUST_SCORE = 5`
- `MIN_ACTIVITY_THRESHOLD = 2`
- `HOLDING_GAP_SESSIONS = 2`
- `EXIT_CONFIRMATION_SESSIONS = 2`
- `FLAT_QTY_THRESHOLD = 10`
- `TOP_N_BROKERS_LEADERBOARD = 20`
- `TOP_N_SIGNALS = 15`

## Calculations
### 1) Broker-symbol flow reconstruction
For each broker and symbol over recent sessions:
- Aggregate buy quantity/value and sell quantity/value
- Compute net quantity flow per session and cumulatively
- Build buy/sell asymmetry context

### 2) Position/lifecycle state machine
Lifecycle states are inferred using net-flow progression and persistence windows:
- Entering accumulation
- Holding/continuation
- Distribution/exit transitions

Controls:
- Flat quantity threshold to identify near-flat inventory
- Gap and confirmation session rules to avoid noisy flips

### 3) Trust scoring
Trust score uses behavior consistency over minimum sessions:
- Activity frequency
- Accumulation vs distribution quality
- Transition reliability
- Persistence and follow-through characteristics

### 4) Signal generation
Signal engine ranks opportunities by combined evidence from:
- Symbol accumulation/distribution state
- Broker asymmetry and consistency
- Trust profile support
- Market activity sufficiency checks

Typical outputs include high-conviction BUY/WATCH/EXIT-style signal rows and supporting rationale fields.

## Data Generated
Pipeline outputs include:
- Broker leaderboard metrics
- Broker profiles (including trust score and transition stats)
- Broker-symbol reconstructed position/state snapshots
- Signal lists (top N for report)
- Sector/company context enrichment for signal readability

## HTML Output
- Output directory: `broker_tracker_reports`
- Report filename pattern: `broker_tracker_YYYY-MM-DD.html`

## Practical Usefulness
- Best use: smart-money confirmation layer before entering or trimming positions.
- Why useful:
  - Detects accumulation/distribution footprints hidden in raw trade tape.
  - Distinguishes random flow from consistent broker behavior through trust scoring.
  - Provides an orthogonal view to price-only indicators, improving conviction filtering.
