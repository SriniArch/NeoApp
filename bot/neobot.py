import time
from datetime import datetime, time as dtime
import sys
import os

# Allow importing from parent directory if run directly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from common.orders import ensure_login as do_login, place_market_order, get_client
from common.scrip_master import load_scrip_master_csv, find_token_for_trading_symbol
from common.config import EXPIRY_STR

# ================= CONNECT =================
# Login using shared module to ensure 'place_market_order' works
# We will initialize this in the main block
client = None

# ================= CONFIG =================
INDEX = "NIFTY"
STEP = 50
QTY = 50
DRY_RUN = True
POLL_SEC = 1

CANDLE_PERSIST_FILE = "bot_candles.json"
RSI_PERIOD = 5
STRIKE_BUFFER = 15 # Points buffer before switching ATM strike
import json


SL_PCT = 0.07
TARGET_PCT = 0.15
MAX_HOLD_SEC = 60

TRADE_START = dtime(9, 30)
TRADE_END = dtime(15, 15)

# ================= STATE =================
index_handles = []
index_candles = []
# Dual Strike Histories
option_histories = {
    "CE": {"token": None, "symbol": "", "candles": []},
    "PE": {"token": None, "symbol": "", "candles": []}
}
position = None
last_tick_price = None

def log(msg):
    try:
        t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg_str = str(msg)
        print(f"[{t}] {msg_str}")
        
        # Ensure logs dir exists
        if not os.path.exists("logs"):
            os.makedirs("logs")
            
        with open("logs/bot_activity.log", "a") as f:
            f.write(f"[{t}] {msg_str}\n")
    except: pass

# ================= CANDLE BUILDER =================
def save_candles():
    """Serialize and save index and option candles to disk."""
    try:
        data = {
            "index": index_candles,
            "ce": option_histories["CE"],
            "pe": option_histories["PE"]
        }
        # Deep copy to stringify times
        def stringify(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, dict):
                return {k: stringify(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [stringify(i) for i in obj]
            return obj
            
        with open(CANDLE_PERSIST_FILE, "w") as f:
            json.dump(stringify(data), f)
    except Exception as e:
        # log(f"⚠️ Error saving candles: {e}")
        pass

def load_candles():
    """Load index and option candles from disk."""
    global index_candles, option_histories
    if os.path.exists(CANDLE_PERSIST_FILE):
        try:
            with open(CANDLE_PERSIST_FILE, "r") as f:
                data = json.load(f)
            
            # Load Index
            new_idx = []
            for d in data.get("index", []):
                d["time"] = datetime.fromisoformat(d["time"])
                if d["time"].date() == datetime.now().date():
                    new_idx.append(d)
            index_candles = new_idx
            
            # Load Options
            for side in ["CE", "PE"]:
                stored = data.get(side.lower(), {})
                if stored.get("candles"):
                    new_opt = []
                    for d in stored["candles"]:
                        d["time"] = datetime.fromisoformat(d["time"])
                        if d["time"].date() == datetime.now().date():
                            new_opt.append(d)
                    if new_opt:
                        option_histories[side] = {
                            "token": stored.get("token"),
                            "symbol": stored.get("symbol"),
                            "candles": new_opt
                        }

            log(f"📥 Restored {len(index_candles)} index, {len(option_histories['CE']['candles'])} CE, {len(option_histories['PE']['candles'])} PE candles")
        except Exception as e:
            log(f"⚠️ Error loading candles: {e}")

def atm_option(spot, side):
    strike = int(round(spot / STEP) * STEP)
    return f"{INDEX}{EXPIRY_STR}{strike}{side}"

# ================= RSI =================
def calculate_rsi(closes, period=RSI_PERIOD):
    if len(closes) < period + 1:
        return None

    gains = losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    
    if losses == 0: return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - (100.0 / (1.0 + rs))

def update_candles(candle_list, ltp, label, auto_save=False):
    now = datetime.now().replace(second=0, microsecond=0)

    if not candle_list or candle_list[-1]["time"] != now:
        if candle_list and label == "INDEX":
             prev = candle_list[-1]
             rsi_val = calculate_rsi([c['close'] for c in candle_list])
             rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "0.0"
             log(f"🕯 {label} CLOSED {prev['time'].strftime('%H:%M')} | C:{prev['close']} RSI:{rsi_str}")
        
        candle_list.append({
            "time": now, "open": ltp, "high": ltp, "low": ltp, "close": ltp
        })
    else:
        c = candle_list[-1]
        c["high"] = max(c["high"], ltp)
        c["low"] = min(c["low"], ltp)
        c["close"] = ltp
    
    if auto_save:
        save_candles()

def get_atm_tokens(index_price):
    """Calculate and return tokens/symbols for CE and PE ATM."""
    ce_sym = atm_option(index_price, "CE")
    pe_sym = atm_option(index_price, "PE")
    
    ce_token = find_token_for_trading_symbol(ce_sym)
    pe_token = find_token_for_trading_symbol(pe_sym)
    
    return {
        "CE": {"token": ce_token, "symbol": ce_sym},
        "PE": {"token": pe_token, "symbol": pe_sym}
    }

# ================= HYBRID ENTRY =================
def check_entry(index_ltp):
    global last_tick_price, position

    if position or len(index_candles) < (RSI_PERIOD + 2):
        return
        
    now = datetime.now().time()
    if not (TRADE_START <= now <= TRADE_END):
        return

    # Index Trend (RSI)
    closes = [c["close"] for c in index_candles] 
    rsi_bias = calculate_rsi(closes)
    if rsi_bias is None: return

    # Check breakouts for both CE and PE
    for side in ["CE", "PE"]:
        hist = option_histories[side]["candles"]
        if not hist: continue
        
        live_opt_ltp = hist[-1]["close"]
        
        # Log when we are in the RSI zone for a signal
        if (side == "CE" and rsi_bias > 55) or (side == "PE" and rsi_bias < 45):
            if len(hist) < 2:
                if int(time.time()) % 10 <= 1:
                    log(f"🔎 {side} RSI OK ({rsi_bias:.1f}) but waiting for data (Candles: {len(hist)})")
                continue
            
            prev_opt = hist[-2]
            # Regular update every few seconds to show what we are waiting for
            if int(time.time()) % 5 <= 1:
                log(f"🔎 {side} Analysis | LTP: {live_opt_ltp:.2f} | Need Breakout: {prev_opt['high']:.2f} | RSI: {rsi_bias:.1f}")
            
            if side == "CE" and rsi_bias > 60 and live_opt_ltp > prev_opt["high"]:
                buy("CE", index_ltp)
                break
            elif side == "PE" and rsi_bias < 40 and live_opt_ltp > prev_opt["high"]:
                buy("PE", index_ltp)
                break


# ================= ORDER HANDLERS =================
def buy(side, index_price):
    global position

    symbol = atm_option(index_price, side)
    
    # ------------------- EXECUTION -------------------
    log(f"⚡ SIGNAL: {side} @ Index {index_price:.2f}")
    
    if DRY_RUN:
        # Fetch the actual premium price even in DRY RUN for accurate simulation
        token = find_token_for_trading_symbol(symbol, log_cb=lambda x: None)
        price = 100.0 # fallback if token not found
        if token:
            try:
                q = client.quotes([{"instrument_token": str(token), "exchange_segment": "nse_fo"}], quote_type="ltp")
                price = float(q[0]["ltp"])
            except: 
                log(f"⚠️ Could not fetch live premium for {symbol}, using fallback 100")
        
        sl = round(price * (1 - SL_PCT), 2)
        target = round(price * (1 + TARGET_PCT), 2)
        
        position = {
            "symbol": symbol,
            "token": token or "SIM_TOKEN",
            "entry": price,
            "sl": sl,
            "target": target,
            "entry_time": datetime.now()
        }
        log(f"🚧 DRY RUN: Simulating BUY {symbol} @ Premium {price:.2f} | SL {sl:.2f} | Tgt {target:.2f}")
    else:
        token = find_token_for_trading_symbol(symbol, log_cb=log)
        if token:
            log(f"🚀 EXECUTING BUY for {symbol}")
            try:
                # Get the actual premium LTP
                opt_quote = client.quotes([{"instrument_token": str(token), "exchange_segment": "nse_fo"}], quote_type="ltp")
                premium_entry = float(opt_quote[0]["ltp"])
                
                # Calculate SL/Target on Premium
                sl = premium_entry * (1 - SL_PCT)
                target = premium_entry * (1 + TARGET_PCT)
                
                place_market_order(token, 1, "BUY", symbol, log_cb=log) 
                
                position = {
                    "symbol": symbol,
                    "token": token,
                    "entry": premium_entry,
                    "sl": sl,
                    "target": target,
                    "entry_time": datetime.now()
                }
                log(f"🟢 POSITION OPEN: {symbol} | Premium {premium_entry:.2f} | SL {sl:.2f} | Tgt {target:.2f}")
            except Exception as e:
                log(f"❌ EXECUTION FAILED: {e}")
        else:
            log(f"❌ TOKEN NOT FOUND for {symbol}")

def sell(exit_price, reason):
    global position
    if not position: return

    symbol = position["symbol"]
    pnl = (exit_price - position["entry"]) * QTY
    log(f"⚡ SIGNAL: EXIT {symbol} | {reason} | PnL {pnl:.2f}")

    if not DRY_RUN:
        try:
            place_market_order(position["token"], 1, "SELL", symbol, log_cb=log)
        except Exception as e:
            log(f"❌ EXIT FAILED: {e}")
    else:
        log(f"🚧 DRY RUN: Would execute SELL {symbol} Qty {QTY}")

    position = None

# ================= MAIN LOOP =================
if __name__ == "__main__":
    client = do_login()
    if not client:
        log("❌ Login failed. Exiting.")
        sys.exit(1)

    load_scrip_master_csv(log_cb=log)
    load_candles()
    
    # instrument token for Nifty Spot (NSE Index)
    # Note: Kotak Neo usually uses instrument_token "26000" or similar for Nifty 50
    instrument_tokens = [{"instrument_token": "26000", "exchange_segment": "nse_fo"}]
    
    log(f"✅ BOT STARTED | Mode: {'DRY RUN' if DRY_RUN else 'REAL MONEY'} | Qty: {QTY}")

    while True:
        try:
            # Prepare watchlist
            tokens_to_fetch = instrument_tokens.copy()
            
            # Determine ATM if we have a reference price
            if last_tick_price:
                std_strike = int(round(last_tick_price / STEP) * STEP)
                if not hasattr(check_entry, 'last_strike'):
                    new_strike = std_strike
                else:
                    dist = abs(last_tick_price - check_entry.last_strike)
                    # Only switch if price moves beyond half-step + buffer
                    if dist > (STEP/2 + STRIKE_BUFFER):
                        new_strike = std_strike
                        log(f"📍 Price {last_tick_price:.1f} moved too far from {check_entry.last_strike}. Switching ATM.")
                    else:
                        new_strike = check_entry.last_strike
                
                # Initialize/Update ATM if strike changed
                if not hasattr(check_entry, 'last_strike') or check_entry.last_strike != new_strike:
                    check_entry.last_strike = new_strike
                    atms = get_atm_tokens(last_tick_price)
                    ce_token = find_token_for_trading_symbol(atms["CE"]["symbol"], log_cb=lambda x: None)
                    pe_token = find_token_for_trading_symbol(atms["PE"]["symbol"], log_cb=lambda x: None)
                    
                    if option_histories["CE"]["symbol"] != atms["CE"]["symbol"]:
                        log(f"🔄 ATM CE: {atms['CE']['symbol']} (Token: {ce_token})")
                        option_histories["CE"] = {"token": ce_token, "symbol": atms["CE"]["symbol"], "candles": []}
                    if option_histories["PE"]["symbol"] != atms["PE"]["symbol"]:
                        log(f"🔄 ATM PE: {atms['PE']['symbol']} (Token: {pe_token})")
                        option_histories["PE"] = {"token": pe_token, "symbol": atms["PE"]["symbol"], "candles": []}

            # Build final tokens list for this tick
            idx_in_quotes = 0
            ce_idx = -1
            pe_idx = -1
            pos_idx = -1
            
            current_idx = 1
            if option_histories["CE"]["token"]:
                tokens_to_fetch.append({"instrument_token": str(option_histories["CE"]["token"]), "exchange_segment": "nse_fo"})
                ce_idx = current_idx
                current_idx += 1
            if option_histories["PE"]["token"]:
                tokens_to_fetch.append({"instrument_token": str(option_histories["PE"]["token"]), "exchange_segment": "nse_fo"})
                pe_idx = current_idx
                current_idx += 1
            
            if position and position.get("token"):
                tokens_to_fetch.append({"instrument_token": str(position["token"]), "exchange_segment": "nse_fo"})
                pos_idx = current_idx
                current_idx += 1

            if int(time.time()) % 10 <= 1:
                # log(f"💓 Heartbeat | Watchlist: {len(tokens_to_fetch)} | Index: {last_tick_price}")
                pass

            # log("DEBUG: calling client.quotes...")
            try:
                quotes = client.quotes(instrument_tokens=tokens_to_fetch, quote_type="all")
            except Exception as qe:
                log(f"❌ client.quotes CRASHED: {qe} | Payload: {tokens_to_fetch}")
                time.sleep(2)
                continue
                
            if not quotes or len(quotes) == 0:
                if int(time.time()) % 30 <= 1:
                    log(f"⚠️ Empty quotes received for watchlist (size: {len(tokens_to_fetch)})")
                time.sleep(1)
                continue
                
            # 1. Update Index
            try:
                index_ltp = float(quotes[0]["ltp"])
            except (IndexError, KeyError) as e:
                log(f"❌ Error parsing Index quote: {e} | Quotes: {quotes}")
                time.sleep(1)
                continue
            last_tick_price = index_ltp
            update_candles(index_candles, index_ltp, "INDEX", auto_save=True)
            
            # 2. Update ATM Option candles
            if ce_idx != -1 and ce_idx < len(quotes):
                update_candles(option_histories["CE"]["candles"], float(quotes[ce_idx]["ltp"]), "CE")

            if pe_idx != -1 and pe_idx < len(quotes):
                update_candles(option_histories["PE"]["candles"], float(quotes[pe_idx]["ltp"]), "PE")

            check_entry(index_ltp)

            # 3. Monitor Position
            if position and pos_idx != -1 and pos_idx < len(quotes):
                opt_ltp = float(quotes[pos_idx]["ltp"])
                pnl = (opt_ltp - position["entry"]) * QTY
                if int(time.time()) % 10 == 0:
                     log(f"⏳ MONITOR: {position['symbol']} (Token: {position['token']}) @ {opt_ltp:.2f} | PnL: {pnl:.2f} | Tgt: {position['target']:.2f} SL: {position['sl']:.2f}")

                if opt_ltp <= position["sl"] or opt_ltp >= position["target"]:
                    sell(opt_ltp, "SL/TARGET")
                elif (datetime.now() - position["entry_time"]).seconds >= MAX_HOLD_SEC:
                    sell(opt_ltp, "TIME EXIT")

            time.sleep(POLL_SEC)

        except Exception as e:
            log(f"⚠️ ERROR in main loop: {e}")
            time.sleep(2)
