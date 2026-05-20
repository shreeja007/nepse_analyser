"""
Configuration for socket live data operations
"""

# WebSocket Server Configuration
WEBSOCKET_SERVER = "ws://localhost:5555"
WEBSOCKET_TIMEOUT = 10  # seconds
WEBSOCKET_CONNECT_TIMEOUT = 10  # seconds

# Monitoring Configuration
DEFAULT_SYMBOLS = ["NABIL", "NICA", "DDBL", "FOWAD", "CYCL"]
POLLING_INTERVAL = 5  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
RETRY_BACKOFF_MULTIPLIER = 2
MAX_CONSECUTIVE_FAILURES_WARN = 3
MAX_POINTS_PER_SYMBOL = 500

# Data Storage
EXPORT_FORMAT = "json"  # or "csv"
DATA_DIR = "live_data_exports"

# Rate Limiting (server-side, but good to know)
MAX_REQUESTS_PER_MINUTE = 60

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = "socket_live_data.log"

# Dataframe Structure for floorsheet analysis
FLOORSHEET_COLUMNS = [
    "contract_id",
    "buy_broker",
    "sell_broker",
    "quantity",
    "rate",
    "amount",
    "timestamp"
]
