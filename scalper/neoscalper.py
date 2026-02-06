import tkinter as tk
from tkinter import ttk, messagebox
import sys, os, re, difflib
import pandas as pd
from datetime import datetime

import sys
import os

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import DEFAULT_TRADING_SYMBOL, BUY_DISABLE_DURATION, BUY_DISABLE_LOSS_COUNT, BUY_DISABLE_MAX_LOSS, BUY_DISABLE_MAX_PROFIT, PROGRESSIVE_LOSS_CONFIG, PROGRESSIVE_LOSS_CONFIG_DEFAULT, REFRESH_INTERVAL_MS, DEFAULT_TARGET, DEFAULT_SL, DEFAULT_TSL_STEP, COOL_OFF_PERIOD, REMOTE_CONFIG_URL, PROGRESSIVE_LOSS_URL
from common.utils import log_with_callback, run_bg, fetch_remote_config, fetch_remote_json, get_resource_path
from common.scrip_master import load_scrip_master_csv, find_token_for_trading_symbol
from common.orders import ensure_login as do_login, place_market_order, get_client, detect_exchange_segment, detect_strike_step
from indicator.scalping_indicator import LiveScalpingManager
from monitor.pnl_engine import PositionPnLEngine, parse_api_orders
import json
import time

BUY_DISABLED_FILE = "buy_disabled.json"

HISTORY_FILE = "symbol_history.json"

# Local imports for modules still in the scalper package
# LTP helper functions removed/unused; no import required


# ---------------------------------------------------------
# STATE
# ---------------------------------------------------------
buy_active = False  # ✅ only one BUY at a time
buy_pending = False # ⏳ Track if a BUY order is currently being placed
exit_pending = False # ⌛ Track if an EXIT order is currently being placed
active_symbol = ""  # 🏷️ The exact symbol of the current open position
buy_disabled = False  # Track if buy is disabled due to losses
last_trade_count = 0 # Track saved trades
last_display_content = "" # Cache last displayed content to prevent flickering
scalp_manager = LiveScalpingManager()
auto_mode = False   # Automated trading status
last_buy_price = 0.0 # Entry price of current active position
max_price_seen = 0.0 # Peak price for trailing SL tracking
active_trade_metadata = {} # Snapshot of indicators at entry/exit
last_exit_reason = "" # Track last exit reason for logging
last_exit_time = 0   # ⏱️ Track when the last trade ended for cool-off period
pnl_engine = PositionPnLEngine() # Shared engine for PnL tracking
market_sideways = False # Track if market is currently sideways
market_exhausted = False # Track if market is currently exhausted


# ---------------------------------------------------------
# ROOT
# ---------------------------------------------------------
root = tk.Tk()
root.title("SCALPER & MONITOR PRO")
root.geometry("850x340")
root.resizable(True, True)
root.configure(bg="#f5f5f5")
icon = tk.PhotoImage(file=get_resource_path("assets/scalper2.png"))
root.iconphoto(True, icon)

# ---------------------------------------------------------
# STYLE
# ---------------------------------------------------------
style = ttk.Style()
style.theme_use("clam")

style.configure(".", font=("Segoe UI", 11))
style.configure("TButton", padding=(6, 3))
style.configure("TEntry", padding=(6, 4))
style.configure("TFrame", background="#f5f5f5")

style.configure("Buy.TButton", background="#d1fae5", font=("Segoe UI", 11, "bold"))
style.map("Buy.TButton", background=[("active", "#a7f3d0")])

style.configure("Exit.TButton", background="#fee2e2", font=("Segoe UI", 11, "bold"))
style.map("Exit.TButton", background=[("active", "#fecaca")])

style.configure("CE.TButton", background="#e6f4ea", foreground="#166534")
style.configure("PE.TButton", background="#fdecea", foreground="#991b1b")

style.configure("Auto.TButton", background="#fef9c3")  # Default yellow-ish
style.configure("AutoOn.TButton", background="#4ade80", font=("Segoe UI", 11, "bold"))
style.configure("Sideways.TButton", background="#e5e7eb", font=("Segoe UI", 11, "bold"))
style.map("Sideways.TButton", background=[("active", "#d1d5db")])

# ---------------------------------------------------------
# MAIN LAYOUT
# ---------------------------------------------------------
main_container = ttk.Frame(root, padding=6)
main_container.pack(fill=tk.BOTH, expand=True)

# LEFT FRAME (Scalper)
frm = ttk.Frame(main_container, padding=6)
frm.pack(side="left", fill="both", expand=True)

# RIGHT FRAME (Monitor)
mon_frame = ttk.Frame(main_container, padding=6, relief="groove")
mon_frame.pack(side="right", fill="both", expand=True, padx=(10, 0))

ttk.Label(mon_frame, text="PnL Monitor", font=("Segoe UI", 12, "bold")).pack(anchor="n", pady=(0, 5))
mon_text = tk.Text(mon_frame, width=44, height=12, bg="#111827", fg="#e5e7eb", font=("Consolas", 10), state="disabled")
mon_text.pack(fill="both", expand=True)


# ---------------------------------------------------------
# SCALPER UI (Left)
# ---------------------------------------------------------
for i in range(4):
    frm.columnconfigure(i, pad=2)

# LOG BOX
log_box = tk.Text(
    frm, height=8, width=70,
    bg="#111827", fg="#e5e7eb",
    insertbackground="white",
    relief="flat",
    font=("Consolas", 10)
)
log_box.grid(row=6, column=0, columnspan=5, pady=(5, 0))

def log_cb(msg):
    def _update():
        log_box.insert(tk.END, msg + "\n")
        log_box.see(tk.END)
    root.after(0, _update)


# ---------------------------------------------------------
# SYMBOL HELPERS
# ---------------------------------------------------------

def get_underlying_index(symbol: str):
    """Maps trading symbol to its underlying index and exchange. Returns (token, exch, nickname)"""
    s = symbol.upper()
    if "NIFTY" in s:
        if "BANK" in s:
            return "Nifty Bank", "nse_cm", "BANKNIFTY"
        elif "FIN" in s:
            return "Nifty Fin Services", "nse_cm", "FINNIFTY"
        return "Nifty 50", "nse_cm", "NIFTY_50"
    elif "SENSEX" in s or "BSX" in s:
        return "SENSEX", "bse_cm", "SENSEX"
    elif "BANKEX" in s:
        return "BSE100", "bse_cm", "BANKEX"
    return None, None, None

def update_auto_strike(idx_ltp: float, idx_name: str):
    """Calculates ATM strike, applies offset, and updates UI symbol."""
    if not auto_strike_var.get() or buy_active: 
        return # Skip if manual mode or in a trade
        
    cur_sym = tr_symbol.get().strip().upper()
    if not cur_sym: return
    
    # 1. Detect Strike Step
    strike_step = detect_strike_step(cur_sym)
        
    # 2. Calculate ATM
    atm = round(idx_ltp / strike_step) * strike_step
    
    # 3. Apply Offset
    offset_str = strike_offset_var.get() # e.g. "ATM-1", "ATM", "ATM+1"
    offset_val = 0
    if "+" in offset_str:
        offset_val = int(offset_str.split("+")[1])
    elif "-" in offset_str:
        offset_val = -int(offset_str.split("-")[1])
        
    final_strike = int(atm + (offset_val * strike_step))
    
    # 4. Check if we actually need to change it
    m = re.search(r"(\d+)(CE|PE)?$", cur_sym)
    if m:
        cur_strike = int(m.group(1))
        if cur_strike != final_strike:
            new_symbol = update_symbol_strike(cur_sym, final_strike)
            tr_symbol.set(new_symbol)
            log_with_callback(log_cb, f"⚡ Auto-Strike: {idx_name} @ {idx_ltp} -> {final_strike}")

def update_symbol_strike(symbol: str, new_strike: int) -> str:
    s = symbol.strip().upper()
    m = re.search(r"(\d+)(CE|PE)?$", s)
    if not m:
        return s
    start, end = m.span(1)
    return s[:start] + str(new_strike) + s[end:]


def update_symbol_option(symbol: str, new_type: str) -> str:
    s = symbol.strip().upper()
    if s.endswith("CE") or s.endswith("PE"):
        return s[:-2] + new_type
    return s + new_type


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return []

def save_history(history):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except:
        pass

def update_history(event=None):
    new_val = tr_symbol.get().strip().upper()
    if not new_val: return
    
    current = list(symbol_combo["values"])
    if new_val in current:
        current.remove(new_val)
    
    current.insert(0, new_val)
    current = current[:3]
    
    symbol_combo["values"] = current
    save_history(current)
    log_with_callback(log_cb, f"History updated: {new_val}")

# 1️⃣ STRIKE UNIT (Row 0)
ttk.Label(frm, text="Strike:").grid(row=0, column=0, sticky="e", pady=5, padx=5)

def move_strike(step):
    cur_sym = tr_symbol.get().strip().upper()
    if not cur_sym: return
    m = re.search(r"(\d+)(CE|PE)?$", cur_sym)
    if not m: return
    cur_strike = int(m.group(1))
    strike_step = int(detect_strike_step(cur_sym))
    new_strike = cur_strike + (strike_step * step)
    if new_strike <= 0: return
    new_symbol = update_symbol_strike(cur_sym, new_strike)
    tr_symbol.set(new_symbol)
    log_with_callback(log_cb, f"Updated Strike: {new_strike}")

updown = ttk.Frame(frm)
updown.grid(row=0, column=1, columnspan=5, sticky="w", pady=5)
ttk.Button(updown, text="▲", width=3, command=lambda: move_strike(1)).pack(side="left", padx=1)
ttk.Button(updown, text="▼", width=3, command=lambda: move_strike(-1)).pack(side="left", padx=1)

auto_strike_var = tk.BooleanVar(value=False)
ttk.Checkbutton(updown, text="Auto", variable=auto_strike_var).pack(side="left", padx=(10, 2))

strike_offset_var = tk.StringVar(value="ATM")
offset_combo = ttk.Combobox(updown, textvariable=strike_offset_var, values=["ATM-3", "ATM-2", "ATM-1", "ATM", "ATM+1", "ATM+2", "ATM+3"], width=6, state="readonly")
offset_combo.pack(side="left", padx=2)

# 2️⃣ OPTION TYPE (Row 1)
ttk.Label(frm, text="Option:").grid(row=1, column=0, sticky="e", pady=5, padx=5)

def toggle_cepe():
    new = "PE" if opt_type.get() == "CE" else "CE"
    opt_type.set(new)
    cepe_btn.config(text=new, style="CE.TButton" if new == "CE" else "PE.TButton")
    cur = tr_symbol.get().strip()
    if cur:
        tr_symbol.set(update_symbol_option(cur, new))
        log_with_callback(log_cb, f"Updated Option: {new}")

opt_type = tk.StringVar(value="CE")
cepe_btn = ttk.Button(frm, text="CE", width=12, style="CE.TButton", command=toggle_cepe)
cepe_btn.grid(row=1, column=1, sticky="w", pady=5)

# 3️⃣ TRADE PARAMS (Row 2)
ttk.Label(frm, text="Params:").grid(row=2, column=0, sticky="e", pady=5, padx=5)
param_frame = ttk.Frame(frm)
param_frame.grid(row=2, column=1, columnspan=5, sticky="w")

lots_var = tk.StringVar(value="1")
ttk.Combobox(param_frame, textvariable=lots_var, values=["1", "2", "3", "5", "10"], width=4, state="readonly").pack(side="left", padx=2)

ttk.Label(param_frame, text="Tgt:").pack(side="left", padx=(10, 2))
target_var = tk.StringVar(value=str(DEFAULT_TARGET))
ttk.Entry(param_frame, textvariable=target_var, width=5).pack(side="left", padx=2)

ttk.Label(param_frame, text="SL:").pack(side="left", padx=(10, 2))
sl_var = tk.StringVar(value=str(DEFAULT_SL))
ttk.Entry(param_frame, textvariable=sl_var, width=5).pack(side="left", padx=2)

ttk.Label(param_frame, text="Trl:").pack(side="left", padx=(10, 2))
trail_var = tk.StringVar(value=str(DEFAULT_TSL_STEP))
ttk.Entry(param_frame, textvariable=trail_var, width=5).pack(side="left", padx=2)

# 4️⃣ SYMBOL SELECTION (Row 3)
ttk.Label(frm, text="Symbol:").grid(row=3, column=0, sticky="e", pady=5, padx=5)
tr_symbol = tk.StringVar(value=DEFAULT_TRADING_SYMBOL)
history = load_history()
symbol_combo = ttk.Combobox(frm, textvariable=tr_symbol, values=history, width=32)
symbol_combo.grid(row=3, column=1, columnspan=5, sticky="w", pady=5)
symbol_combo.bind("<Return>", update_history)

# 5️⃣ CONTROL BUTTONS (Row 4)
btn_frame = ttk.Frame(frm)
btn_frame.grid(row=4, column=0, columnspan=6, pady=(10, 2))

buy_btn = ttk.Button(
    btn_frame, text="BUY", style="Buy.TButton", width=12,
    command=lambda: run_bg(do_buy, trade_type="Manual")
)
buy_btn.pack(side="left", padx=10)

ttk.Button(
    btn_frame, text="EXIT", style="Exit.TButton", width=12,
    command=lambda: run_bg(do_exit)
).pack(side="left", padx=10)

ttk.Button(
    btn_frame, text="RESET", width=12,
    command=lambda: trigger_override()
).pack(side="left", padx=10)

auto_btn = ttk.Button(
    btn_frame, text="AUTO: OFF", width=12, style="Auto.TButton",
    command=lambda: toggle_auto_mode()
)
auto_btn.pack(side="left", padx=10)

# 5.5️⃣ STATUS BAR (Row 5)
status_frame = ttk.Frame(frm)
status_frame.grid(row=5, column=0, columnspan=6, pady=(2, 5), sticky="ew")

status_label = ttk.Label(status_frame, text="Buy Enabled", font=("Segoe UI", 10))
status_label.pack(side="left", padx=(5, 0))

position_label = ttk.Label(status_frame, text="● NO POSITION", font=("Segoe UI", 10, "bold"), foreground="gray")
position_label.pack(side="left", padx=(20, 0))

strategy_status_label = ttk.Label(status_frame, text="Strategy: Waiting...", font=("Segoe UI", 10, "bold"))
strategy_status_label.pack(side="right", padx=(0, 5))

# ---------------------------------------------------------
# LOGIC
# ---------------------------------------------------------


def is_buy_disabled():

    if os.path.exists(BUY_DISABLED_FILE):
        try:
            with open(BUY_DISABLED_FILE, 'r') as f:
                data = json.load(f)
            
            # Reset daily: If the saved date is not today, the lockout is expired.
            saved_date = data.get("date")
            today = datetime.now().strftime("%Y-%m-%d")
            if saved_date and saved_date != today:
                return False, 0, None

            remaining = data["disabled_until"] - time.time()
            if remaining > 0:
                return True, remaining, data.get("last_trade_id")
        except:
            pass
    return False, 0, None

def trigger_override():
    global override_until
    
    # Check if strict max-loss lockout is active
    if os.path.exists(BUY_DISABLED_FILE):
        try:
            with open(BUY_DISABLED_FILE, 'r') as f:
                data = json.load(f)
            reason = data.get("last_trade_id")
            rem = data.get("disabled_until", 0) - time.time()
            # If it's a 24-hour lockout (Hard Stop)
            if reason == "max_loss" or (reason.startswith("max_loss") and rem > 80000):
                today = datetime.now().strftime("%Y-%m-%d")
                if data.get("date") == today:
                    log_with_callback(log_cb, "⛔ HARD STOP: Max Loss limit reached. Cannot override until tomorrow.")
                    messagebox.showerror("Hard Stop", "Max Loss limit reached. Trading is disabled for the rest of the day.")
                    return
        except: pass

    if os.path.exists(BUY_DISABLED_FILE):
        try:
            os.remove(BUY_DISABLED_FILE)
            log_with_callback(log_cb, "✅ Manual RESET: Persistent lockout cleared.")
        except: pass
    else:
        log_with_callback(log_cb, "✅ Manual RESET: Buy enabled (Conditions will be re-checked).")
    update_status_label()

def toggle_auto_mode():
    global auto_mode
    auto_mode = not auto_mode
    if auto_mode:
        auto_btn.config(text="AUTO: ON", style="AutoOn.TButton")
        log_with_callback(log_cb, "🤖 Automated Mode: ENABLED")
    else:
        auto_btn.config(text="AUTO: OFF", style="Auto.TButton")
        log_with_callback(log_cb, "⭕ Automated Mode: DISABLED")


def update_status_label():
    
    disabled, remaining, reason = is_buy_disabled()
    if disabled:
        buy_btn.config(state="disabled")
        if reason.startswith("max_loss"):
            # A "Hard Stop" is defined as a lockout of 24 hours (1440 mins) or more
            # We use 86000 as a buffer for 86400 seconds (24h)
            is_static_hard_stop = (reason == "max_loss")
            is_dynamic_hard_stop = (remaining > 80000) 
            
            if is_static_hard_stop or is_dynamic_hard_stop:
                status_label.config(text="Buy Disabled - Max Loss (Hard Stop)", foreground="red")
            else:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                status_label.config(text=f"Buy Disabled - Loss Limit ({mins}:{secs:02d})", foreground="red")
        elif reason == "max_profit":
            status_label.config(text="Buy Disabled - Max Profit Reached", foreground="green")
        else:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            status_label.config(text=f"Buy Disabled - Re-enables in {mins}:{secs:02d}", foreground="red")
    else:
        # Check Cool-off period
        time_since_exit = time.time() - last_exit_time
        if time_since_exit < COOL_OFF_PERIOD:
            remaining_cool = int(COOL_OFF_PERIOD - time_since_exit)
            buy_btn.config(state="disabled")
            status_label.config(text=f"Cooling Off... ({remaining_cool}s)", foreground="#f59e0b")
        else:
            if not buy_active:
                buy_btn.config(state="normal")
                if market_sideways:
                    buy_btn.config(style="Sideways.TButton")
                    status_label.config(text="Market Sideways (Caution)", foreground="#f59e0b")
                else:
                    buy_btn.config(style="Buy.TButton")
                    status_label.config(text="Buy Enabled", foreground="green")
            else:
                # buy_active is True
                buy_btn.config(state="disabled")
                buy_btn.config(style="Buy.TButton")
                status_label.config(text="Position Active", foreground="green")
    root.after(1000, update_status_label)


def do_buy(trade_type="Manual"):
    global buy_active, buy_pending, active_symbol, last_buy_price, max_price_seen, active_trade_metadata, last_exit_time
    active_trade_metadata = {} # Reset at start to avoid stale data from previous trades

    disabled, remaining, reason = is_buy_disabled()
    if disabled:
        if reason.startswith("max_loss"):
            if remaining > 80000 or reason == "max_loss":
                msg = f"Buy disabled. Net loss has reached the daily hard stop limit."
            else:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                msg = f"Buy disabled due to loss reaching a progressive threshold. Re-enables in {mins} minutes {secs} seconds."
        elif reason == "max_profit":
            msg = f"Buy disabled. Net profit has exceeded the limit of {BUY_DISABLE_MAX_PROFIT}."
        else:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            msg = f"Buy disabled due to {BUY_DISABLE_LOSS_COUNT} continuous losses. Re-enables in {mins} minutes {secs} seconds."
        
        root.after(0, lambda: messagebox.showerror("Buy Disabled", msg))
        return

    if buy_active or buy_pending:
        log_with_callback(log_cb, f"BUY blocked: {'Pending' if buy_pending else 'Position'} already active")
        return

    # Check Cool-off Period
    time_since_exit = time.time() - last_exit_time
    if time_since_exit < COOL_OFF_PERIOD:
        remaining = int(COOL_OFF_PERIOD - time_since_exit)
        log_with_callback(log_cb, f"BUY blocked: Cool-off period active ({remaining}s remaining)")
        return

    tr = tr_symbol.get().strip().upper()
    if not tr:
        messagebox.showerror("Error", "Trading symbol is empty")
        return

    # 🔒 Lock entering phase
    buy_pending = True
    active_symbol = tr

    # Double check with API for open positions
    try:
        client = get_client()
        if client:
            pos_resp = client.positions()
            data = pos_resp.get("data", []) if isinstance(pos_resp, dict) else pos_resp
            if isinstance(data, list):
                for p in data:
                    if int(float(p.get("netQty", p.get("flQty", 0)))) != 0:
                        log_with_callback(log_cb, f"BUY blocked: API shows open position in {p.get('trdSym')}")
                        buy_active = True
                        return
    except Exception as e:
        log_with_callback(log_cb, f"⚠️ Position Check Error: {e}")

    tr = tr_symbol.get().strip()
    if not tr:
        messagebox.showerror("Error", "Trading symbol is empty")
        return

    # Safe UI update via root.after or immediate if called in way that allows it
    # Since do_buy is in bg, we use root.after for widget config
    root.after(0, lambda: buy_btn.config(state="disabled"))  # 🔒 disable immediately

    # Ensure client is available
    client = get_client()
    token = find_token_for_trading_symbol(tr, log_cb)
    
    # Capture current LTP for target tracking (Initial estimate)
    try:
        if client:
            exch = detect_exchange_segment(tr)
            q = client.quotes(instrument_tokens=[{"instrument_token": token, "exchange_segment": exch}], quote_type="ltp")
            ltp = 0
            if isinstance(q, list) and len(q) > 0: 
                ltp = float(q[0].get("ltp", 0))
            elif isinstance(q, dict): 
                data = q.get("data", [])
                if isinstance(data, list) and len(data) > 0:
                    ltp = float(data[0].get("ltp", 0))
            
            if ltp > 0:
                last_buy_price = ltp
                max_price_seen = ltp
                log_with_callback(log_cb, f"Initial LTP Captured: {last_buy_price}")
            else:
                log_with_callback(log_cb, "⚠️ Warning: Initial LTP capture returned 0")
    except Exception as e:
        log_with_callback(log_cb, f"⚠️ LTP Fetch Error: {e}")

    # Place order and capture response
    try:
        resp = place_market_order(token, int(lots_var.get()), "BUY", tr, log_cb)
    except Exception as e:
        log_with_callback(log_cb, f"❌ BUY ORDER ERROR: {e}")
        buy_pending = False
        active_symbol = ""
        root.after(0, lambda: buy_btn.config(state="normal"))
        return

    # 🎯 Verify if order was actually placed
    if not (isinstance(resp, dict) and "nOrdNo" in resp):
        log_with_callback(log_cb, f"❌ BUY FAILED: {resp.get('errMsg', 'Unknown Error') if isinstance(resp, dict) else 'Invalid Response'}")
        buy_pending = False
        active_symbol = ""
        root.after(0, lambda: buy_btn.config(state="normal"))
        return

    order_id = resp["nOrdNo"]

    # 🎯 Verify if order was actually COMPLETED
    is_completed = False
    status = "unknown"
    try:
        if client:
            log_with_callback(log_cb, f"Verifying completion for Order: {order_id}...")
            
            # Retry loop for order status (API can be slow)
            for attempt in range(6): # 6 attempts * 0.5s = 3s total
                time.sleep(0.5) 
                history_resp = client.order_history(order_id=order_id)
                print(f"DEBUG: Order History Response (BUY) for {order_id}: {history_resp}")
                
                # Handle both list and dict-with-data formats
                history = history_resp if isinstance(history_resp, list) else history_resp.get("data", []) if isinstance(history_resp, dict) else []
                
                if history and isinstance(history, list):
                    latest_state = history[-1]
                    status = latest_state.get("ordSt", "").lower()
                    
                    if status == "complete":
                        is_completed = True
                        for state in reversed(history):
                            # Check multiple possible keys for average price
                            avg_p = state.get("avgPrc") or state.get("buyAvgPrc") or state.get("price")
                            if avg_p and float(avg_p) > 0:
                                last_buy_price = float(avg_p)
                                max_price_seen = last_buy_price
                                break
                        break # Success!
                    elif status == "rejected":
                        reason = latest_state.get("rejReason", "Unknown Reason")
                        log_with_callback(log_cb, f"❌ BUY REJECTED: {reason}")
                        break
                    else:
                        # Continue retrying if status is not final
                        pass
                
            if not is_completed and status != "rejected":
                # Fallback: Check Order Report for this ID
                try:
                    rep = client.order_report()
                    rep_data = rep.get("data", []) if isinstance(rep, dict) else rep
                    if isinstance(rep_data, list):
                        for o in rep_data:
                            if str(o.get("nOrdNo")) == str(order_id) and str(o.get("ordSt", "")).lower() == "complete":
                                is_completed = True
                                avg_p = o.get("avgPrc") or o.get("buyAvgPrc") or o.get("price")
                                if avg_p: last_buy_price = float(avg_p)
                                break
                except: pass
                
            if not is_completed and status != "rejected":
                log_with_callback(log_cb, f"⚠️ Verification Timeout: Order {order_id} status is still {status}")
                
    except Exception as e:
        log_with_callback(log_cb, f"Verification Error: {e}")

    if not is_completed:
        # Check if we can recover from positions even if verification timed out
        try:
            pos_resp = client.positions()
            data = pos_resp.get("data", []) if isinstance(pos_resp, dict) else pos_resp
            if isinstance(data, list):
                for p in data:
                    if p.get("trdSym", "").upper() == active_symbol.upper() and int(float(p.get("netQty", 0))) != 0:
                        log_with_callback(log_cb, "🛡️ RECOVERED: Order verification timed out, but Position is open in API. Resuming...")
                        is_completed = True
                        # Check multiple keys in position data too
                        recovered_p = p.get("avgPrc") or p.get("buyAvgPrc") or p.get("buyAvg")
                        if recovered_p and float(recovered_p) > 0:
                            last_buy_price = float(recovered_p)
                        break
        except: pass

    if not is_completed:
        buy_pending = False
        active_symbol = ""
        root.after(0, lambda: buy_btn.config(state="normal"))
        return

    buy_active = True  
    buy_pending = False # Done
    
    # Capture Entry Indicators
    try:
        ind = scalp_manager.get_signal()
        active_trade_metadata = {
            "symbol": active_symbol, # Track which symbol this metadata belongs to
            "trade_type": trade_type,
            "entry_sig": ind.get("signal"),
            "entry_ema": ind.get("ema"),
            "entry_roc": ind.get("roc"),
            "entry_bbw": ind.get("bb_width"),
            "entry_time_ts": time.time(), # For time-stop
            "exit_reason": "IN_PROGRESS"
        }
    except: active_trade_metadata = {}

    tgt_pts = float(target_var.get() or 0)
    sl_pts = float(sl_var.get() or 0)
    tgt_price = round(last_buy_price + tgt_pts, 2)
    sl_price = round(last_buy_price - sl_pts, 2)

    log_with_callback(log_cb, f"🎯 Confirmed BUY Executed @ {last_buy_price}")
    log_with_callback(log_cb, f"📊 Target: {tgt_price} (+{tgt_pts}) | SL: {sl_price} (-{sl_pts})")
    log_with_callback(log_cb, f"✅ BUY completed - waiting for SELL")


def do_exit(reason="Manual"):
    global buy_active, exit_pending, active_symbol, active_trade_metadata

    # Use the symbol we actually BOUGHT, not whatever is currently in the entry box
    tr = active_symbol if active_symbol else tr_symbol.get().strip().upper()
    
    if not tr:
        log_with_callback(log_cb, "❌ EXIT Error: No active symbol tracked.")
        return
    
    if exit_pending:
        log_with_callback(log_cb, "⌛ EXIT blocked: Exit order already pending")
        return
    
    exit_pending = True
    # Capture Exit Indicators before placing order
    try:
        ind = scalp_manager.get_signal()
        active_trade_metadata.update({
            "exit_sig": ind.get("signal"),
            "exit_ema": ind.get("ema"),
            "exit_roc": ind.get("roc"),
            "exit_bbw": ind.get("bb_width"),
            "exit_reason": reason
        })
    except: pass

    token = find_token_for_trading_symbol(tr, log_cb)
    try:
        resp = place_market_order(token, int(lots_var.get()), "SELL", tr, log_cb)
    except Exception as e:
        log_with_callback(log_cb, f"❌ SELL ORDER ERROR: {e}")
        exit_pending = False
        return

    # 🎯 Verify if order was actually placed
    if not (isinstance(resp, dict) and "nOrdNo" in resp):
        log_with_callback(log_cb, f"❌ SELL FAILED: {resp.get('errMsg', 'Unknown Error') if isinstance(resp, dict) else 'Invalid Response'}")
        exit_pending = False
        return

    order_id = resp["nOrdNo"]

    # Capture Execution Price for SELL and Verify Completion
    sell_price = 0.0
    is_completed = False
    status = "unknown"
    try:
        client = get_client()
        if client:
            log_with_callback(log_cb, f"Verifying completion for SELL Order: {order_id}...")
            # Retry loop for order status (API can be slow)
            for attempt in range(6): # 6 attempts * 0.5s = 3s total
                time.sleep(0.5) 
                history_resp = client.order_history(order_id=order_id)
                print(f"DEBUG: Order History Response (SELL) for {order_id}: {history_resp}")
                
                # Handle both list and dict-with-data formats
                history = history_resp if isinstance(history_resp, list) else history_resp.get("data", []) if isinstance(history_resp, dict) else []
                
                if history and isinstance(history, list):
                    latest_state = history[-1]
                    status = latest_state.get("ordSt", "").lower()

                    if status == "complete":
                        is_completed = True
                        for state in reversed(history):
                            # Check multiple possible keys for average price
                            avg_p = state.get("avgPrc") or state.get("sellAvgPrc") or state.get("price")
                            if avg_p and float(avg_p) > 0:
                                sell_price = float(avg_p)
                                break
                        break 
                    elif status == "rejected":
                        reason = latest_state.get("rejReason", "Unknown Reason")
                        log_with_callback(log_cb, f"❌ SELL REJECTED: {reason}")
                        break
            
            if not is_completed and status != "rejected":
                # Fallback: Check Order Report for this ID
                try:
                    rep = client.order_report()
                    rep_data = rep.get("data", []) if isinstance(rep, dict) else rep
                    if isinstance(rep_data, list):
                        for o in rep_data:
                            if str(o.get("nOrdNo")) == str(order_id) and str(o.get("ordSt", "")).lower() == "complete":
                                is_completed = True
                                avg_p = o.get("avgPrc") or o.get("sellAvgPrc") or o.get("price")
                                if avg_p: sell_price = float(avg_p)
                                break
                except: pass

            if not is_completed and status != "rejected":
                log_with_callback(log_cb, f"⚠️ SELL Timeout: Order {order_id} status is still {status}")

    except Exception as e:
        log_with_callback(log_cb, f"SELL Verification Error: {e}")

    if not is_completed:
        exit_pending = False # Reset so we can try again
        return

    buy_active = False               
    exit_pending = False
    active_symbol = ""
    global last_exit_time
    last_exit_time = time.time() # Start cool-off period
    root.after(0, lambda: buy_btn.config(state="normal"))
    
    log_msg = f"🎯 Confirmed SELL Executed @ {sell_price if sell_price > 0 else 'MARKET'}"
    if reason != "Manual":
        log_msg += f" [{reason}]"
    log_with_callback(log_cb, log_msg)
    log_with_callback(log_cb, "✅ POSITION CLOSED")


# ---------------------------------------------------------
# MONITOR LOGIC
# ---------------------------------------------------------

def color_pnl(val):
    if val > 0: return "green"
    if val < 0: return "#ff4444"
    return "white"

def update_monitor_ui():
    """Background worker to fetch and process PnL data."""
    global pnl_engine, active_symbol, last_buy_price, max_price_seen, buy_active, last_trade_count, active_trade_metadata
    try:
        client = get_client()
        if not client:
            return

        # 1. POSITION SYNC (Source of Truth)
        try:
            pos_resp = client.positions()
            data = pos_resp.get("data", []) if isinstance(pos_resp, dict) else pos_resp
            has_open_pos = False
            if isinstance(data, list):
                if data:
                    print(f"DEBUG: Raw Position Response: {data[0]}")
                for p in data:
                    # 🛡️ BSE FO Fallback: If netQty is missing, calculate from fills
                    fl_buy = float(p.get("flBuyQty", 0))
                    fl_sell = float(p.get("flSellQty", 0))
                    qty = int(float(p.get("netQty", fl_buy - fl_sell)))
                    
                    if qty != 0:
                        has_open_pos = True
                        # 🛡️ AUTO-RECOVERY from positions API (Source of Truth)
                        if not active_symbol or last_buy_price <= 0:
                             active_symbol = p.get("trdSym", "").upper()
                             # Check multiple possible keys for average price in positions
                             recovered_p = p.get("avgPrc") or p.get("buyAvgPrc") or p.get("buyAvg")
                             
                             # BSE Fallback: Price = BuyAmt / flBuyQty
                             if not recovered_p or float(recovered_p) == 0:
                                 buy_amt = float(p.get("buyAmt", 0))
                                 if fl_buy > 0: recovered_p = buy_amt / fl_buy
                             
                             last_buy_price = float(recovered_p or 0)
                             if last_buy_price > 0:
                                log_with_callback(log_cb, f"🔄 Recovered Position from API: {active_symbol} @ {last_buy_price}")
                        break
            
            buy_active = has_open_pos
            
            # Update UI Indicator
            if buy_active:
                root.after(0, lambda: position_label.config(text="● POSITION OPEN", foreground="#ef4444"))
            else:
                root.after(0, lambda: position_label.config(text="● NO POSITION", foreground="#6b7280"))
        except Exception as pe:
             log_with_callback(log_cb, f"⚠️ Position Sync Error: {pe}")
        
        # 2. ORDER PROCESSING & STATS
        report = client.order_report()
        # Handle both list and dict-with-data formats
        report_data = report.get("data", []) if isinstance(report, dict) else report
        
        if report_data and isinstance(report_data, list):
            # Refreshed engine with latest data
            new_engine = PositionPnLEngine()
            trades = parse_api_orders(report_data)
            trades.sort(key=lambda x: x.time)
            for t in trades:
                new_engine.add_trade(t)
            # Enrich completed trades
            if len(new_engine.completed_trades) > last_trade_count:
                for i in range(last_trade_count, len(new_engine.completed_trades)):
                    trade = new_engine.completed_trades[i]
                    if active_trade_metadata:
                        # Only clear/apply metadata if it belongs to THIS symbol
                        if trade['symbol'] == active_trade_metadata.get("symbol"):
                            trade.update(active_trade_metadata)
                            active_trade_metadata = {} 
                        elif not trade.get('entry_sig') and not active_symbol:
                            # Fallback cleanup only if no new trade is active
                            trade.update(active_trade_metadata)
                            active_trade_metadata = {}
                
                # Save ONLY the new trades to CSV (Appended)
                new_trades = new_engine.completed_trades[last_trade_count:]
                save_trades_to_csv(new_trades)
                last_trade_count = len(new_engine.completed_trades)
            
            pnl_engine = new_engine
            process_buy_disable_logic(pnl_engine)

        # 2.1 Calculate Stats using persistent engine
        completed = pnl_engine.completed_trades
        pnls = [round(t["net_pnl"]) for t in completed]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        win_rate = round((wins / len(pnls) * 100), 1) if pnls else 0.0
        
        gross = round(sum(t["gross_pnl"] for t in completed), 2)
        net = round(sum(t["net_pnl"] for t in completed), 2)
        charges = round(sum(t["charges"] for t in completed), 2)
        
        last_str = " | ".join(str(p) for p in pnls[-5:])

        lines = [
            f"Trades: {len(completed)}",
            f"W/L   : {wins}/{losses} ({win_rate}%)",
            "-" * 20,
            f"Gross PnL: {gross}",
            f"Net PnL  : {net}",
            f"Charges  : {charges}",
            "-" * 20,
            f"Recent: {last_str}"
        ]
        
        try:
            th = pnl_engine.trading_hours_summary()
            lines.append(f"Avg/hr    : {th['avg_per_hour']}")
        except: pass

        # 3. Handle LTP for Indicators (Use Index instead of Option)
        tr_current_ui = tr_symbol.get().strip().upper()
        # Use active_symbol if we have one, otherwise UI symbol
        tr_for_quote = active_symbol if (buy_active and active_symbol) else tr_current_ui
        idx_token, idx_exch, idx_name = get_underlying_index(tr_for_quote)
        
        idx_ltp = 0
        if idx_token:
            try:
                # Fetch Index LTP
                quote_resp = client.quotes(instrument_tokens=[{"instrument_token": idx_token, "exchange_segment": idx_exch}], quote_type="ltp")
                
                if isinstance(quote_resp, list) and len(quote_resp) > 0:
                    idx_ltp = float(quote_resp[0].get("ltp", 0))
                elif isinstance(quote_resp, dict):
                    # Handle both {'data': [...]} and direct dict formats
                    data = quote_resp.get("data", [])
                    if isinstance(data, list) and len(data) > 0:
                        idx_ltp = float(data[0].get("ltp", 0))
                    elif "ltp" in quote_resp:
                        idx_ltp = float(quote_resp.get("ltp", 0))
                
                if idx_ltp > 0:
                    scalp_manager.add_ltp(idx_ltp, idx_name)
                    # 🚀 AUTO STRIKE SELECTION
                    update_auto_strike(idx_ltp, idx_name)
                else:
                    log_with_callback(log_cb, f"⚠️ Warning: Index fetch for {idx_name} returned 0. Using fallback.")
            except Exception as e:
                log_with_callback(log_cb, f"⚠️ Index Quote Error ({idx_name}): {e}")
        
        # Fallback Indicator Data: If index quote failed OR no index mapping, 
        # use the Option LTP to keep the manager "Warm" and moving.
        if not idx_token or idx_ltp <= 0:
            try:
                token = find_token_for_trading_symbol(tr_current_ui)
                if token:
                    exch = detect_exchange_segment(tr_current_ui)
                quote_resp = client.quotes(instrument_tokens=[{"instrument_token": token, "exchange_segment": exch}], quote_type="ltp")
                
                ltp = 0
                if isinstance(quote_resp, list) and len(quote_resp) > 0:
                    ltp = float(quote_resp[0].get("ltp", 0))
                elif isinstance(quote_resp, dict):
                    data = quote_resp.get("data", [])
                    if isinstance(data, list) and len(data) > 0:
                        ltp = float(data[0].get("ltp", 0))
                
                if ltp > 0:
                    scalp_manager.add_ltp(ltp, tr_current_ui)
            except: pass
        
        indicator_data = scalp_manager.get_signal()
        sig = indicator_data['signal']
        
        global market_sideways, market_exhausted
        market_sideways = indicator_data.get("sideways", False)
        market_exhausted = indicator_data.get("exhausted", False)

        if sig == "BULLISH":
            trade_status = "📈 BULLISH SETUP"
            trade_color = "#10b981" # Emerald Green
        elif sig == "BEARISH":
            trade_status = "📉 BEARISH SETUP"
            trade_color = "#10b981" # Emerald Green
        elif market_sideways:
            trade_status = "⏸️ MARKET SIDEWAYS"
            trade_color = "#f97316" # Orange
        elif market_exhausted:
            trade_status = "⚠️ MARKET EXHAUSTED"
            trade_color = "#ef4444" # Red
        elif sig == "NEUTRAL":
            trade_status = "⚖️ NEUTRAL / WAITING"
            trade_color = "#6b7280" # Gray
        elif "WAITING" in sig:
            # Extract (N pts) info
            pts_info = sig.split("WAITING")[1] if "WAITING" in sig else ""
            trade_status = f"⏳ WARMING UP{pts_info}"
            trade_color = "#6b7280" # Gray
        else:
            trade_status = f"🔍 {sig}"
            trade_color = "#ef4444" # Red
            
        # Expansion Pulse Detection Feedback
        if indicator_data.get("pulse"):
            trade_status = f"⚡ {trade_status} (PULSE DETECTED)"
            trade_color = "#3b82f6" # Bright Blue

        # 🎯 AUTOMATIC TARGET EXIT LOGIC
        if buy_active and not exit_pending:
            cur_ltp = 0
            
            # 🛡️ RECOVER STATE if buy_active is true but we lost the price/symbol
            # (Already recovered from API above, this is a safety fallback)
            if not active_symbol or last_buy_price <= 0:
                for sym, pos_list in pnl_engine.open_trades.items():
                    if pos_list:
                        active_symbol = sym
                        last_buy_price = pos_list[0]['buy_price']
                        log_with_callback(log_cb, f"🔄 Recovered Position from Engine: {active_symbol} @ {last_buy_price}")
                        break

            if last_buy_price <= 0:
                log_with_callback(log_cb, "⚠️ Warning: Position active but entry price is 0. Exit logic skipped.")
            else:
                try:
                    # Check price of the symbols we bought
                    tr_to_exit = active_symbol if active_symbol else tr_current_ui
                    option_token = find_token_for_trading_symbol(tr_to_exit)
                    option_exch = detect_exchange_segment(tr_to_exit)
                    
                    q = client.quotes(instrument_tokens=[{"instrument_token": option_token, "exchange_segment": option_exch}], quote_type="ltp")
                    if isinstance(q, list) and len(q) > 0: 
                        cur_ltp = float(q[0].get("ltp", 0))
                    elif isinstance(q, dict): 
                        data = q.get("data", [])
                        if isinstance(data, list) and len(data) > 0:
                            cur_ltp = float(data[0].get("ltp", 0))
                except Exception as qe:
                    log_with_callback(log_cb, f"⚠️ Quote Fetch/Parse Error: {qe}")
            
            if cur_ltp > 0:
                global max_price_seen
                profit = cur_ltp - last_buy_price
                target = float(target_var.get() or 0)
                initial_sl = float(sl_var.get() or 0)
                trail_step = float(trail_var.get() or 0)
                
                # Update Max Price for Trailing
                if cur_ltp > max_price_seen:
                    max_price_seen = cur_ltp
                
                # Calculate Effective SL
                # If trail is > 0, we move the SL up by the profit peak amount
                trail_gain = 0
                if trail_step > 0:
                    trail_gain = max_price_seen - last_buy_price
                
                effective_sl_pts = initial_sl - trail_gain
                
                lines.append("-" * 20)
                lines.append(f"Position: {profit:+.2f} pts")
                lines.append(f"Tgt: {target:.1f} | SL: {effective_sl_pts:.1f} {'(Trl)' if trail_gain > 0 else ''}")
                
                if auto_mode:
                    print(f"DEBUG: Track Exit | {active_symbol} | LTP: {cur_ltp} | Profit: {profit:+.2f} | Tgt: {target} | SL: {-effective_sl_pts:.2f}")

                if auto_mode and profit >= target:
                    log_with_callback(log_cb, f"🎯 TARGET REACHED ({profit:+.2f} pts). Exiting...")
                    run_bg(do_exit, reason="Target")
                    return
                elif auto_mode and profit <= -effective_sl_pts:
                    log_with_callback(log_cb, f"🛑 STOP LOSS HIT ({profit:+.2f} pts). Exiting...")
                    run_bg(do_exit, reason="SL")
                    return
                elif auto_mode and active_trade_metadata.get("symbol") == active_symbol:
                    # REFINED EXIT LOGIC:
                    # 1. ROC Decay Exit: > 25% drop from peak
                    # 2. BBW Contraction (current < entry)
                    # 3. Time-Stop (20s)
                    # 4. Dynamic Trailing SL: BE+0.5 at 3pts profit
                    
                    e_bbw = active_trade_metadata.get("entry_bbw", 0)
                    e_roc = active_trade_metadata.get("entry_roc", 0)
                    e_ts = active_trade_metadata.get("entry_time_ts", 0)
                    cur_bbw = indicator_data.get("bb_width", 0)
                    cur_roc = indicator_data.get("roc", 0)
                    duration = time.time() - e_ts if e_ts > 0 else 0

                    # Track Peak ROC for decay exit
                    peak_roc = active_trade_metadata.get("peak_roc", abs(e_roc))
                    if abs(cur_roc) > peak_roc:
                        peak_roc = abs(cur_roc)
                        active_trade_metadata["peak_roc"] = peak_roc
                    
                    exit_needed = False
                    exit_reason = ""
                    
                    # 1. ROC Decay Exit (>25% drop from peak)
                    if peak_roc > 0 and abs(cur_roc) < (peak_roc * 0.75):
                        exit_needed = True
                        exit_reason = "ROC Decay (>25%)"
                    
                    # 2. BBW Contraction (Indicating squeeze)
                    elif cur_bbw < e_bbw:
                        exit_needed = True
                        exit_reason = "BBW Contraction"
                    
                    # 3. Time-Stop (20s)
                    elif duration > 20:
                        exit_needed = True
                        exit_reason = "Time-Stop (20s)"
                    
                    # 4. Dynamic Trailing SL: BE+0.5 at 3pts profit
                    if not exit_needed:
                        if profit >= 3.0:
                            if not active_trade_metadata.get("tsl_active"):
                                active_trade_metadata["tsl_active"] = True
                                log_with_callback(log_cb, "🛡️ Trailing SL: Locked at BE + 0.5 pts")
                        
                        if active_trade_metadata.get("tsl_active") and profit < 0.5:
                            exit_needed = True
                            exit_reason = "Trailing SL (BE+0.5)"
                    
                    if exit_needed:
                        log_with_callback(log_cb, f"🛡️ AUTO EXIT: {exit_reason} detected ({profit:+.2f} pts). Exiting...")
                        run_bg(do_exit, reason=exit_reason)
                        return 
        
        lines.append("-" * 20)
        lines.append(f"Source: {idx_name or tr_for_quote}")

        # Update Scalper UI Strategy Label
        root.after(0, lambda: strategy_status_label.config(text=f"Strategy: {trade_status}", foreground=trade_color))

        # 🤖 AUTO MODE LOGIC
        if auto_mode and not buy_active and not buy_pending:
            tr = tr_symbol.get().strip().upper()
            is_ce = tr.endswith("CE")
            is_pe = tr.endswith("PE")
            
            should_buy = False
            mismatch_msg = ""
            
            if sig == "BULLISH":
                if is_ce: should_buy = True
                elif is_pe: mismatch_msg = "Market is BULLISH, but a PUT (PE) is selected. Skipping..."
            elif sig == "BEARISH":
                if is_pe: should_buy = True
                elif is_ce: mismatch_msg = "Market is BEARISH, but a CALL (CE) is selected. Skipping..."

            if should_buy:
                # Extra Step 3 Check: Price not more than 5 points above/below EMA
                ema = indicator_data.get("ema", 0)
                cur_p = indicator_data.get("ltp", 0)
                proximity_ok = False
                if sig == "BULLISH" and cur_p <= (ema + 5): proximity_ok = True
                elif sig == "BEARISH" and cur_p >= (ema - 5): proximity_ok = True
                
                if not proximity_ok:
                    log_with_callback(log_cb, f"⚠️ AUTO: {sig} signal detected, but price ({cur_p}) is too far from EMA ({ema}). Skipping...")
                    should_buy = False

            if should_buy:
                # Check if buy is actually allowed (not disabled)
                disabled, _, reason = is_buy_disabled()
                if not disabled:
                    log_with_callback(log_cb, f"🤖 AUTO: {sig} signal matched with {tr}. Placing BUY...")
                    run_bg(do_buy, trade_type="Auto")
                else:
                    # Log why it didn't trade if disabled
                    pass # Status label already shows this
            elif mismatch_msg:
                # Log the mismatch skip once per signal change to avoid log spam
                # We can use a simple state check if needed, but for now log it.
                log_with_callback(log_cb, f"⚠️ AUTO: {mismatch_msg}")

        # 4. Render on Main Thread

        # 5. Render on Main Thread
        root.after(0, lambda: render_monitor_display(lines, net, gross))

    except Exception as e:
        log_with_callback(log_cb, f"Monitor Error: {e}")
    finally:
        # Schedule next update correctly
        root.after(REFRESH_INTERVAL_MS, lambda: run_bg(update_monitor_ui))
        
        # Periodically refresh remote config (every 5 minutes)
        if not hasattr(update_monitor_ui, "last_config_refresh"):
            update_monitor_ui.last_config_refresh = 0
            
        if time.time() - update_monitor_ui.last_config_refresh > 300:
            global BUY_DISABLE_MAX_LOSS, PROGRESSIVE_LOSS_CONFIG
            
            # Refresh Max Loss
            new_limit = fetch_remote_config(REMOTE_CONFIG_URL, BUY_DISABLE_MAX_LOSS)
            if new_limit != BUY_DISABLE_MAX_LOSS:
                BUY_DISABLE_MAX_LOSS = new_limit
                log_with_callback(log_cb, f"🔄 Max Loss Limit updated from remote: {BUY_DISABLE_MAX_LOSS}")
            
            # Refresh Progressive Config
            new_prog = fetch_remote_json(PROGRESSIVE_LOSS_URL, PROGRESSIVE_LOSS_CONFIG)
            if new_prog != PROGRESSIVE_LOSS_CONFIG:
                PROGRESSIVE_LOSS_CONFIG = new_prog
                log_with_callback(log_cb, "🔄 Progressive Loss Config updated from remote.")
                
            update_monitor_ui.last_config_refresh = time.time()

def process_buy_disable_logic(engine):
    # 1. Daily Stats
    completed = engine.completed_trades
    net_pnl = sum(t.get("net_pnl", 0) for t in completed)
    loss_amount = -net_pnl
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Load highest threshold hit today to prevent "downgrading" lockouts
    current_label = None
    highest_threshold_hit = 0
    disabled_until_ts = 0
    if os.path.exists(BUY_DISABLED_FILE):
        try:
            with open(BUY_DISABLED_FILE, 'r') as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    current_label = data.get("last_trade_id")
                    highest_threshold_hit = data.get("highest_threshold", 0)
                    disabled_until_ts = data.get("disabled_until", 0)
        except: pass

    # Find the single highest applicable threshold
    app_t = 0
    app_d = 0
    for threshold, duration_mins in PROGRESSIVE_LOSS_CONFIG:
        if loss_amount >= threshold:
            app_t = threshold
            app_d = duration_mins
            break
            
    # Handle Recovery: If we improved below the highest threshold hit earlier
    if highest_threshold_hit > 0 and loss_amount < highest_threshold_hit:
        log_with_callback(log_cb, f"📈 Recovery Detected: Net Loss {net_pnl:.2f} is improving (Previous worst: {highest_threshold_hit}).")
        # Clear lockout immediately as losses are reducing
        with open(BUY_DISABLED_FILE, 'w') as f:
            json.dump({"disabled_until": 0, "last_trade_id": "recovery", "date": today_str, "highest_threshold": app_t}, f)
        log_with_callback(log_cb, "✅ Recovery: Buying re-enabled as losses are reducing.")
        return

    # Handle New/Higher Lockout
    if app_t > 0:
        label = f"max_loss_{app_t}"
        if app_t > highest_threshold_hit or (app_t == highest_threshold_hit and current_label != label):
            disabled_until_ts = time.time() + (app_d * 60)
            with open(BUY_DISABLED_FILE, 'w') as f:
                json.dump({"disabled_until": disabled_until_ts, "last_trade_id": label, "date": today_str, "highest_threshold": app_t}, f)
            dur_str = f"{app_d} mins" if app_d < 1440 else "tomorrow"
            log_with_callback(log_cb, f"⚠️ LOCKOUT: Loss {loss_amount:.2f} hit {app_t}. Buy disabled for {dur_str}.")
        return

    if net_pnl >= BUY_DISABLE_MAX_PROFIT:
        if current_label != "max_profit":
             disabled_until_ts = time.time() + 86400 # 24 hours
             with open(BUY_DISABLED_FILE, 'w') as f:
                 json.dump({"disabled_until": disabled_until_ts, "last_trade_id": "max_profit", "date": today_str}, f)
             log_with_callback(log_cb, f"SUCCESS: Net Profit {net_pnl} exceeds limit {BUY_DISABLE_MAX_PROFIT}. Buy disabled until tomorrow.")
        return

    # 3. Check for NEW Consecutive Loss Lockout
    if len(completed) >= BUY_DISABLE_LOSS_COUNT:
        last_n = completed[-BUY_DISABLE_LOSS_COUNT:]
        # Use a unique ID for this set of losses to avoid re-triggering same lockout
        last_trade_time = last_n[-1].get("sell_time") or last_n[-1].get("buy_time")
        last_trade_ts = str(last_trade_time.timestamp()) if hasattr(last_trade_time, 'timestamp') else str(last_trade_time)
        
        if all(t.get("net_pnl", 0) < 0 for t in last_n) and last_trade_ts != current_label:
            disabled_until_ts = time.time() + BUY_DISABLE_DURATION
            with open(BUY_DISABLED_FILE, 'w') as f:
                json.dump({"disabled_until": disabled_until_ts, "last_trade_id": last_trade_ts, "date": today_str}, f)
            log_with_callback(log_cb, f"INFO: Buy disabled for {BUY_DISABLE_DURATION // 60} mins due to {BUY_DISABLE_LOSS_COUNT} losses.")
            return

    # 4. Check for Static Re-enable (Time passed or new day)
    if os.path.exists(BUY_DISABLED_FILE):
        try:
            # Check if lockout should be lifted based on time
            if time.time() >= disabled_until_ts:
                # Lockout time expired. We only clear it if we are also not currently in a threshold.
                if app_t == 0:
                    # UPDATE file instead of deleting, to keep the last_trade_id memory
                    with open(BUY_DISABLED_FILE, 'r') as f:
                        data = json.load(f)
                    data["disabled_until"] = 0 
                    with open(BUY_DISABLED_FILE, 'w') as f:
                        json.dump(data, f)
                    log_with_callback(log_cb, f"✅ Lockout expired ({current_label}). Buy re-enabled.")
                return

            # Special recovery check for Max Profit
            if current_label == "max_profit" and net_pnl < BUY_DISABLE_MAX_PROFIT:
                os.remove(BUY_DISABLED_FILE)
                log_with_callback(log_cb, "✅ Profit Recovery: Buy re-enabled.")
                return

        except Exception as e:
            log_with_callback(log_cb, f"DEBUG: Re-enable check failed: {e}")

def save_trades_to_csv(trades_to_log):
    if not trades_to_log:
        return
    try:
        import csv
        os.makedirs("logs", exist_ok=True)
        filename = f"logs/trades_{datetime.now().strftime('%Y-%m-%d')}.csv"
        
        # Check existing Buy IDs in file to avoid logical duplicates
        existing_buy_ids = set()
        file_exists = os.path.exists(filename)
        if file_exists:
            try:
                with open(filename, "r") as r:
                    reader = csv.DictReader(r)
                    for row in reader:
                        bid = row.get("Buy ID")
                        if bid: existing_buy_ids.add(bid)
            except: pass

        with open(filename, "a", newline="") as f:
            headers = ["Symbol", "Trade Type", "Date", "Buy Time", "Sell Time", "Qty", "Buy Price", "Sell Price", "Gross PnL", "Charges", "Net PnL", 
                       "Buy ID", "Sell ID", "Order Source", "Exit Reason", "E_Sig", "E_EMA", "E_ROC", "E_BBW", "X_Sig", "X_EMA", "X_ROC", "X_BBW"]
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            
            logged_count = 0
            for t in trades_to_log:
                # Skip if already in file
                bid = str(t.get("buy_order_id", ""))
                if bid in existing_buy_ids:
                    continue
                
                # Combine Buy and Sell sources for display
                b_src = t.get("order_source", "NA")
                s_src = t.get("sell_order_source", "NA")
                combined_src = f"B:{b_src} | S:{s_src}"
                if b_src == s_src: combined_src = b_src

                row = {
                    "Symbol": t["symbol"],
                    "Trade Type": t.get("trade_type", "Manual"),
                    "Date": t.get("trade_date"),
                    "Buy Time": t.get("buy_time"),
                    "Sell Time": t.get("sell_time"),
                    "Qty": t.get("buy_qty"),
                    "Buy Price": t.get("buy_price"),
                    "Sell Price": t.get("sell_price"),
                    "Gross PnL": t.get("gross_pnl"),
                    "Charges": t.get("charges"),
                    "Net PnL": t.get("net_pnl"),
                    "Buy ID": bid,
                    "Sell ID": t.get("sell_order_id"),
                    "Order Source": combined_src,
                    "Exit Reason": t.get("exit_reason", "Manual/API"),
                    "E_Sig": t.get("entry_sig", "N/A"),
                    "E_EMA": t.get("entry_ema", "N/A"),
                    "E_ROC": t.get("entry_roc", "N/A"),
                    "E_BBW": t.get("entry_bbw", "N/A"),
                    "X_Sig": t.get("exit_sig", "N/A"),
                    "X_EMA": t.get("exit_ema", "N/A"),
                    "X_ROC": t.get("exit_roc", "N/A"),
                    "X_BBW": t.get("exit_bbw", "N/A")
                }
                writer.writerow(row)
                logged_count += 1
                
        if logged_count > 0:
            log_with_callback(log_cb, f"📝 {logged_count} new trades logged to {filename}")
    except Exception as e:
        log_with_callback(log_cb, f"CSV Error: {e}")

def render_monitor_display(lines, net_val, gross_val):
    global last_display_content
    current_content = "\n".join(lines)
    if current_content == last_display_content and last_display_content != "":
        return
    
    mon_text.config(state="normal")
    mon_text.delete("1.0", tk.END)
    
    for line in lines:
        if line.startswith("Recent:"):
            mon_text.insert(tk.END, "Recent: ")
            parts = line.split("Recent: ")[1].split(" | ")
            for i, p in enumerate(parts):
                if not p: continue
                try:
                    val = float(p)
                    tag = "green" if val > 0 else "red" if val < 0 else None
                except: tag = None
                mon_text.insert(tk.END, p, tag)
                if i < len(parts) - 1: mon_text.insert(tk.END, " | ")
            mon_text.insert(tk.END, "\n")
        else:
            tag = None
            if line.startswith("Net"): tag = "green" if net_val > 0 else "red"
            elif line.startswith("Gross"): tag = "green" if gross_val > 0 else "red"
            elif "Allowed to Trade" in line: tag = "green"
            elif "Dont Trade" in line: tag = "red"
            mon_text.insert(tk.END, line + "\n", tag)
            
    mon_text.tag_config("green", foreground="#4ade80")
    mon_text.tag_config("red", foreground="#f87171")
    mon_text.config(state="disabled")
    last_display_content = current_content

# ---------------------------------------------------------
# AUTO STARTUP
# ---------------------------------------------------------
def startup_sequence():
    log_with_callback(log_cb, "🚀 Starting Auto-Login Sequence...")
    try:
        do_login(log_cb)
        load_scrip_master_csv(log_cb=log_cb)
        log_with_callback(log_cb, "✅ Startup Complete")
        
        # Start Monitor First Run
        root.after(2000, lambda: run_bg(update_monitor_ui))
        
    except Exception as e:
        log_with_callback(log_cb, f"❌ Startup Failed: {e}")

root.after(500, lambda: run_bg(startup_sequence))
update_status_label()
root.mainloop()
