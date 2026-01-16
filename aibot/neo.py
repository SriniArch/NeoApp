import sys
import os

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.neo_login import get_neo_client
from common.orders import place_market_order, get_client
from common.scrip_master import find_token_for_trading_symbol, load_scrip_master_csv
from monitor.pnl_engine import PositionPnLEngine, parse_api_orders
import datetime
from datetime import datetime
import pandas as pd
import time

# -----------------------
# Initialize Neo API using common login
# -----------------------
try:
    load_scrip_master_csv()
    client = get_neo_client()
    print("✅ Neo Login Successful")
except Exception as e:
    print(f"❌ Login Failed: {e}")
    sys.exit(1)


instrument_tokens = [
    {"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"},
]

import time
from datetime import datetime

# =====================================================
# ASSUMPTION:
# Neo login & session already done
# You already have a valid `neo` object
# =====================================================

# ================= CONFIG =================
INDEX = "NIFTY"
STEP = 50
QTY = 50               # 1 NIFTY lot
SLEEP = 1              # seconds

# ================= STATE =================
candles = []
position = None       # {symbol, sl, target, qty}

# ================= RSI (PURE PYTHON) =================
def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff

    if losses == 0:
        return 100.0

    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))

# ================= UTILS =================
def atm_option(ltp, side):
    strike = round(ltp / STEP) * STEP
    return f"{INDEX}{strike}{side}"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ================= CANDLE BUILDER =================
def on_tick(ltp):
    now = datetime.now().replace(second=0, microsecond=0)

    if not candles or candles[-1]["time"] != now:
        candles.append({
            "time": now,
            "open": ltp,
            "high": ltp,
            "low": ltp,
            "close": ltp
        })
    else:
        c = candles[-1]
        c["high"] = max(c["high"], ltp)
        c["low"] = min(c["low"], ltp)
        c["close"] = ltp

# ================= SIGNAL ENGINE =================
def get_signal():
    if position or len(candles) < 20:
        return None

    closes = [c["close"] for c in candles]

    rsi_prev = calculate_rsi(closes[:-1])
    rsi_now = calculate_rsi(closes)

    if rsi_prev is None or rsi_now is None:
        return None

    momentum = closes[-1] - closes[-4]
    last = candles[-1]
    prev = candles[-2]

    # BUY CALL
    if rsi_prev < 60 and rsi_now > 60 and \
       last["close"] > prev["high"] and momentum > 0:
        return "CE", prev["low"]

    # BUY PUT
    if rsi_prev > 40 and rsi_now < 40 and \
       last["close"] < prev["low"] and momentum < 0:
        return "PE", prev["high"]

    return None

# ================= ORDER HANDLERS =================
DRY_RUN = True # Set to False for real trading

def buy(symbol, entry, sl):
    global position

    log(f"SIGNAL: BUY {symbol} @ {entry:.2f}")
    
    if not DRY_RUN:
        token = find_token_for_trading_symbol(symbol, log_cb=print)
        if token:
            place_market_order(token, 1, "BUY", symbol, log_cb=print)
        else:
            log(f"❌ Token not found for {symbol}")
            return

    risk = abs(entry - sl)
    target = entry + 1.5 * risk if "CE" in symbol else entry - 1.5 * risk

    position = {
        "symbol": symbol,
        "sl": sl,
        "target": target,
        "qty": QTY
    }

    log(f"BUY {symbol} | ENTRY {entry:.2f} | SL {sl:.2f} | TARGET {target:.2f}")

def sell():
    global position
    if not position: return
    
    symbol = position["symbol"]
    log(f"SIGNAL: EXIT {symbol}")

    if not DRY_RUN:
        token = find_token_for_trading_symbol(symbol, log_cb=print)
        if token:
            place_market_order(token, 1, "SELL", symbol, log_cb=print)

    position = None

# ================= MAIN LOOP =================
log("NIFTY RSI + Momentum Bot Started")

while True:
    try:
        # Fetch NIFTY spot price
        quote = client.quotes(instrument_tokens = instrument_tokens, quote_type = "all")[0]

        ltp = float(quote["ltp"])

        # Build candle
        on_tick(ltp)

        # ENTRY
        signal = get_signal()
        if signal:
            side, sl = signal
            symbol = atm_option(ltp, side)
            buy(symbol, ltp, sl)

        # EXIT
        if position:
            if ltp <= position["sl"] or ltp >= position["target"]:
                sell()

        time.sleep(SLEEP)

    except Exception as e:
        log(f"ERROR: {e}")
        time.sleep(2)
