# config.py
from dotenv import load_dotenv
import os

load_dotenv()

CONSUMER_KEY = os.getenv("CONSUMER_KEY")
MOBILE = os.getenv("MOBILE")
UCC = os.getenv("UCC")
TOTP_SECRET = os.getenv("TOTP_SECRET")
MPIN = os.getenv("MPIN")
LOT_SIZE = int(os.getenv("NIFTY_LOT_SIZE", "75"))

# Scrip Master constants
NSE_SCRIP_MASTER_PATH = os.getenv("NSE_SCRIP_MASTER_PATH", "nse_fo.csv")
BSE_SCRIP_MASTER_PATH = os.getenv("BSE_SCRIP_MASTER_PATH", "bse_fo.csv")
DEFAULT_TRADING_SYMBOL = ""
EXPIRY_STR = "26120" # YYMDD format (e.g. 26120 for 20th Jan 2026)

# Buy disable feature
ENABLE_BUY_DISABLE = True
BUY_DISABLE_LOSS_COUNT = 3  # Number of continuous losses to disable buying
BUY_DISABLE_DURATION = 120  # seconds
BUY_DISABLE_MAX_LOSS = 500   # Disable buying if net loss exceeds this amount
BUY_DISABLE_MAX_PROFIT = 1000 # Disable buying if net profit exceeds this amount
RESET_OVERRIDE_DURATION = 600  # seconds; manual RESET enables buy for this long (default 10 min)
COOL_OFF_PERIOD = 10 # seconds; minimum gap between trades

# Per-trade default risk management
DEFAULT_TARGET = 10.0
DEFAULT_SL = 5
DEFAULT_TSL_STEP = 3.0 # Points move required to trail SL (0 to disable)

# LTP Logger feature
ENABLE_LTP_LOGGER = False

# UI & Strategy refresh interval in milliseconds
REFRESH_INTERVAL_MS = 1000
