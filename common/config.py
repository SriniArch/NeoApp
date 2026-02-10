# config.py
import os
from dotenv import load_dotenv
from common.utils import fetch_remote_config, fetch_remote_json, get_resource_path

load_dotenv(get_resource_path(".env"))

CONSUMER_KEY = os.getenv("CONSUMER_KEY")
MOBILE = os.getenv("MOBILE")
UCC = os.getenv("UCC")
TOTP_SECRET = os.getenv("TOTP_SECRET")
MPIN = os.getenv("MPIN")
LOT_SIZE = int(os.getenv("NIFTY_LOT_SIZE", "75"))

# Scrip Master constants
NSE_SCRIP_MASTER_PATH = get_resource_path(os.getenv("NSE_SCRIP_MASTER_PATH", "nse_fo.csv"))
BSE_SCRIP_MASTER_PATH = get_resource_path(os.getenv("BSE_SCRIP_MASTER_PATH", "bse_fo.csv"))
DEFAULT_TRADING_SYMBOL = ""
EXPIRY_STR = "26120" # YYMDD format (e.g. 26120 for 20th Jan 2026)

# Buy disable feature
BUY_DISABLE_LOSS_COUNT = 3  # Number of continuous losses to disable buying
BUY_DISABLE_DURATION = 120  # seconds
ENABLE_BUY_DISABLE = True   # Enable/Disable the lockout feature

# Progressive Loss Lockout (Loss amount, Duration in minutes)
# Once a threshold is hit, buying is disabled for the specified duration.
PROGRESSIVE_LOSS_CONFIG_DEFAULT = [
    (2501, 1440), # >2500 loss -> Hard stop (24 hours)
    (2500, 30),   # 2500 loss -> 30 minutes
    (2000, 20),   # 2000 loss -> 20 minutes
    (1500, 15),   # 1500 loss -> 15 minutes
    (1000, 10),   # 1000 loss -> 10 minutes
    (500, 5),     # 500 loss -> 5 minutes
]

# Remote config for Maximum Loss (Higher friction to cheat)
# Replace these URLs with your own private GitHub Gist (Raw) URLs
REMOTE_CONFIG_URL = os.getenv("REMOTE_CONFIG_URL", "https://gist.githubusercontent.com/SriniArch/a81d5c68cdb91a432225b26833bef01d/raw/gistfile1.txt")
PROGRESSIVE_LOSS_URL = os.getenv("PROGRESSIVE_LOSS_URL", "https://gist.githubusercontent.com/SriniArch/0a485812216952d95e0dfc02f5e8a018/raw/progressive_loss.json")

PROGRESSIVE_LOSS_CONFIG = fetch_remote_json(PROGRESSIVE_LOSS_URL, PROGRESSIVE_LOSS_CONFIG_DEFAULT)

BUY_DISABLE_MAX_LOSS = 2501 # Final hard stop if not covered by progressive config
BUY_DISABLE_MAX_PROFIT = 2500 # Disable buying if net profit exceeds this amount
COOL_OFF_PERIOD = 10 # seconds; minimum gap between trades

# Per-trade default risk management
NIFTY_CONFIG = {
    "target": 2,
    "sl": 1.5,
    "tsl": 1,
    "pt": 1
}

SENSEX_CONFIG = {
    "target": 5,
    "sl": 4,
    "tsl": 2,
    "pt": 2
}

DEFAULT_TARGET = NIFTY_CONFIG["target"]
DEFAULT_SL = NIFTY_CONFIG["sl"]
DEFAULT_TSL_STEP = NIFTY_CONFIG["tsl"]
DEFAULT_TP_TSL = NIFTY_CONFIG["pt"]

# LTP Logger feature
ENABLE_LTP_LOGGER = False

# Capital Tracking
INITIAL_CAPITAL_DEFAULT = 8000.0  # Initial capital if no history exists
CAPITAL_HISTORY_FILE = "capital_history.csv"
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", INITIAL_CAPITAL_DEFAULT))
CAPITAL_TOPUP = 0.0 # One-time adjustment (Add money: +5000, Withdraw: -5000)

# UI & Strategy refresh interval in milliseconds
REFRESH_INTERVAL_MS = 1000
