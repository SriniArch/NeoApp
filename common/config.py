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
DEFAULT_TRADING_SYMBOL = "SENSEX2610184900PE"
EXPIRY_STR = "26120" # YYMDD format (e.g. 26120 for 20th Jan 2026)
