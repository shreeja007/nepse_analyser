"""broker_tracker.config

Configuration for the NEPSE Broker Tracker analyser.

Mirrors the sync pymysql+DictCursor pattern used in analysor/logic.py.
"""

import os

import pymysql

# ═══════════════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════════════

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "db": os.getenv("DB_DATABASE", "nepsego"),
    "user": os.getenv("DB_USERNAME", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

# Use a rolling window for activity ingestion to control runtime and memory.
ACTIVITY_LOOKBACK_DAYS = 400

# ═══════════════════════════════════════════════════════════════════════
#  SIGNAL THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════

ACCUMULATION_ASYMMETRY_THRESHOLD = 65
DISTRIBUTION_ASYMMETRY_THRESHOLD = 40
MIN_SESSIONS_FOR_ACCUMULATION = 3
MIN_SESSIONS_FOR_TRUST_SCORE = 5
MIN_ACTIVITY_THRESHOLD = 2

# BUY gate hardening constants.
BUY_MIN_BROKER_POWER_SCORE = 55.0
BUY_MIN_BCR = 0.35
BUY_WABR_PROXIMITY_PCT = 3.0
BUY_CD_ROLLING_WINDOW = 10
BUY_CD_SLOPE_WINDOW = 5
BUY_MIN_VOLUME_RATIO = 1.0

# Circuit proxy: avoid fresh buys after a near-circuit move in latest session.
CIRCUIT_DAILY_MOVE_THRESHOLD_PCT = 10.0

# Risk controls and advanced exits.
STOP_STRUCTURAL_PCT = 0.03
STOP_TIME_SESSIONS = 10
STOP_TIME_MIN_APPRECIATION_PCT = 3.0
MARKUP_EXHAUSTION_PCT = 15.0
OPPOSING_BROKER_POWER_THRESHOLD = 80.0
ABSENCE_EXIT_SESSIONS = 3

# Position sizing defaults (can be overridden by env in orchestration later if needed).
DEFAULT_PORTFOLIO_CAPITAL_RS = 1_000_000.0
POSITION_RISK_BUDGET_PCT = 0.01
POSITION_MAX_CAPITAL_PCT = 0.10
POSITION_MIN_NOTIONAL_RS = 10_000.0
POSITION_FRONT_RUN_CAP_PCT = 0.20

# Horizon sessions used for broker profile-v2 forward-return checks.
PROFILE_V2_HORIZONS = (1, 5, 10)

# Broker power score component weights (must sum to 1.0).
BROKER_POWER_WEIGHT_WIN = 0.40
BROKER_POWER_WEIGHT_ALPHA = 0.30
BROKER_POWER_WEIGHT_STEALTH = 0.20
BROKER_POWER_WEIGHT_CONCENTRATION = 0.10

# CAPM settings for risk-adjusted alpha.
CAPM_BETA_WINDOW = 60
CAPM_RISK_FREE_ANNUAL = 0.06

# Minimum completed cycles required to assign A/B/C broker tiers.
BROKER_POWER_MIN_CYCLES_FOR_TIER = 3

# Broker tier cutoffs based on broker_power_score (0-100).
BROKER_TIER_A_MIN = 75.0
BROKER_TIER_B_MIN = 55.0

# ═══════════════════════════════════════════════════════════════════════
#  STATE MACHINE
# ═══════════════════════════════════════════════════════════════════════

HOLDING_GAP_SESSIONS = 2
EXIT_CONFIRMATION_SESSIONS = 2

# Spec note: "small_threshold (e.g. < 10 shares)". We implement that as:
FLAT_QTY_THRESHOLD = 10

# ═══════════════════════════════════════════════════════════════════════
#  REPORT
# ═══════════════════════════════════════════════════════════════════════

TOP_N_BROKERS_LEADERBOARD = 20
TOP_N_SIGNALS = 15
# Display-only diversity guard: limit repeated rows from a single broker in Top-N signal tables.
MAX_SIGNALS_PER_BROKER_IN_TOP = 3
OUTPUT_DIR = "broker_tracker_reports"
