import tkinter as tk
from tkinter import ttk, messagebox
import sys, os, re, difflib
import pandas as pd
from datetime import datetime

import sys
import os

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.utils import log_with_callback, run_bg
from common.scrip_master import load_scrip_master_csv, find_token_for_trading_symbol
from common.orders import ensure_login as do_login, place_market_order, get_client, detect_exchange_segment, detect_strike_step
from common.config import DEFAULT_TRADING_SYMBOL, ENABLE_BUY_DISABLE, BUY_DISABLE_DURATION, BUY_DISABLE_LOSS_COUNT, BUY_DISABLE_MAX_LOSS, BUY_DISABLE_MAX_PROFIT, REFRESH_INTERVAL_MS, DEFAULT_TARGET, DEFAULT_SL, DEFAULT_TSL_STEP
from indicator.scalping_indicator import LiveScalpingManager
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
buy_disabled = False  # Track if buy is disabled due to losses
last_trade_count = 0 # Track saved trades
last_display_content = "" # Cache last displayed content to prevent flickering
scalp_manager = LiveScalpingManager()
override_until = 0  # 10-min grace period for manual override
auto_mode = False   # Automated trading status
last_buy_price = 0.0 # Entry price of current active position
max_price_seen = 0.0 # Peak price for trailing SL tracking
active_trade_metadata = {} # Snapshot of indicators at entry/exit


# ---------------------------------------------------------
# ROOT
# ---------------------------------------------------------
root = tk.Tk()
root.title("SCALPER & MONITOR PRO")
root.geometry("850x380")
root.resizable(True, True)
root.configure(bg="#f5f5f5")
icon = tk.PhotoImage(file="assets/scalper2.png")
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
log_box.grid(row=20, column=0, columnspan=5, pady=(10, 0))

def log_cb(msg):
    def _update():
        log_box.insert(tk.END, msg + "\n")
        log_box.see(tk.END)
    root.after(0, _update)

# ---------------------------------------------------------
# SYMBOL HELPERS
# ---------------------------------------------------------
def get_underlying_index(symbol: str):
    """Maps trading symbol to its underlying index and exchange."""
    s = symbol.upper()
    if "NIFTY" in s:
        if "BANK" in s:
            return "Nifty Bank", "nse_cm"
        elif "FIN" in s:
            return "Nifty Fin Service", "nse_cm"
        return "Nifty 50", "nse_cm"
    elif "SENSEX" in s or "BSX" in s:
        return "SENSEX", "bse_cm"
    elif "BANKEX" in s:
        return "BANKEX", "bse_cm"
    # Fallback to symbol itself if no index match
    return None, None

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
updown.grid(row=0, column=1, columnspan=3, sticky="w", pady=5)
ttk.Button(updown, text="▲", width=6, command=lambda: move_strike(1)).pack(side="left", padx=2)
ttk.Button(updown, text="▼", width=6, command=lambda: move_strike(-1)).pack(side="left", padx=2)

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
btn_frame.grid(row=4, column=0, columnspan=6, pady=15)

buy_btn = ttk.Button(
    btn_frame, text="BUY", style="Buy.TButton", width=12,
    command=lambda: run_bg(do_buy)
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

status_label = ttk.Label(frm, text="Buy Enabled", font=("Segoe UI", 10))
status_label.grid(row=5, column=0, columnspan=6, pady=(5, 0))

strategy_status_label = ttk.Label(frm, text="Strategy: Waiting...", font=("Segoe UI", 10, "bold"))
strategy_status_label.grid(row=6, column=0, columnspan=6, pady=(0, 5))

# ---------------------------------------------------------
# LOGIC
# ---------------------------------------------------------


def is_buy_disabled():
    if override_until > time.time():
        return False, 0, "override"

    if not ENABLE_BUY_DISABLE:
        return False, 0, None
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
    override_until = time.time() + 600  # 10 minutes
    if os.path.exists(BUY_DISABLED_FILE):
        try:
            os.remove(BUY_DISABLED_FILE)
            log_with_callback(log_cb, "✅ Manual Override: Persistent lockout cleared.")
        except: pass
    else:
        log_with_callback(log_cb, "✅ Manual Override: Buy enabled for 10 minutes.")
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
    if not ENABLE_BUY_DISABLE:
        status_label.config(text="Buy Disable Feature Disabled", foreground="black")
        if not buy_active:
            buy_btn.config(state="normal")
        root.after(1000, update_status_label)
        return
    
    disabled, remaining, reason = is_buy_disabled()
    if reason == "override":
        rem_override = int(override_until - time.time())
        mins = rem_override // 60
        secs = rem_override % 60
        status_label.config(text=f"Override Active: {mins}:{secs:02d} remaining", foreground="#2563eb")
        buy_btn.config(state="normal")
    elif disabled:
        buy_btn.config(state="disabled")
        if reason == "max_loss":
            status_label.config(text="Buy Disabled - Max Loss Exceeded", foreground="red")
        elif reason == "max_profit":
            status_label.config(text="Buy Disabled - Max Profit Reached", foreground="green")
        else:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            status_label.config(text=f"Buy Disabled - Re-enables in {mins}:{secs:02d}", foreground="red")
    else:
        if not buy_active:
            buy_btn.config(state="normal")
        status_label.config(text="Buy Enabled", foreground="green")
    root.after(1000, update_status_label)


def do_buy():
    global buy_active
    global last_buy_price

    disabled, remaining, reason = is_buy_disabled()
    if disabled:
        if reason == "max_loss":
            msg = f"Buy disabled. Net loss has exceeded the limit of {BUY_DISABLE_MAX_LOSS}."
        elif reason == "max_profit":
            msg = f"Buy disabled. Net profit has exceeded the limit of {BUY_DISABLE_MAX_PROFIT}."
        else:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            msg = f"Buy disabled due to {BUY_DISABLE_LOSS_COUNT} continuous losses. Re-enables in {mins} minutes {secs} seconds."
        
        root.after(0, lambda: messagebox.showerror("Buy Disabled", msg))
        return

    if buy_active:
        log_with_callback(log_cb, "BUY blocked: position already open")
        return

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
            if isinstance(q, list) and len(q) > 0: ltp = float(q[0].get("ltp", 0))
            elif isinstance(q, dict): ltp = float(q.get("data", [{}])[0].get("ltp", 0))
            
            last_buy_price = ltp
            global max_price_seen
            max_price_seen = ltp
            log_with_callback(log_cb, f"Initial LTP Captured: {last_buy_price}")
    except: pass

    # Place order and capture response
    resp = place_market_order(token, int(lots_var.get()), "BUY", tr, log_cb)

    # 🎯 Verify if order was actually placed
    if not (isinstance(resp, dict) and "nOrdNo" in resp):
        log_with_callback(log_cb, f"❌ BUY FAILED: {resp.get('errMsg', 'Unknown Error') if isinstance(resp, dict) else 'Invalid Response'}")
        root.after(0, lambda: buy_btn.config(state="normal"))
        return

    order_id = resp["nOrdNo"]

    # 🎯 Verify if order was actually COMPLETED
    is_completed = False
    try:
        if client:
            log_with_callback(log_cb, f"Verifying completion for Order: {order_id}...")
            # Fetch history to check status and avg price
            history = client.order_history(order_id=order_id)
            if history and isinstance(history, list):
                # Check most recent state
                latest_state = history[-1]
                status = latest_state.get("ordSt", "").lower()
                
                if status == "complete":
                    is_completed = True
                    for state in reversed(history):
                        avg_prc = state.get("avgPrc")
                        if avg_prc and float(avg_prc) > 0:
                            last_buy_price = float(avg_prc)
                            max_price_seen = last_buy_price
                            break
                elif status == "rejected":
                    reason = latest_state.get("rejReason", "Unknown Reason")
                    log_with_callback(log_cb, f"❌ BUY REJECTED: {reason}")
                else:
                    log_with_callback(log_cb, f"⚠️ BUY Status: {status}")
    except Exception as e:
        log_with_callback(log_cb, f"Verification Error: {e}")

    if not is_completed:
        root.after(0, lambda: buy_btn.config(state="normal"))
        return

    buy_active = True  # ✅ BUY position now active
    
    # Capture Entry Indicators
    global active_trade_metadata
    try:
        ind = scalp_manager.get_signal()
        active_trade_metadata = {
            "entry_sig": ind.get("signal"),
            "entry_ema": ind.get("ema"),
            "entry_roc": ind.get("roc"),
            "entry_bbw": ind.get("bb_width"),
            "exit_reason": "IN_PROGRESS"
        }
    except: active_trade_metadata = {}

    log_with_callback(log_cb, f"✅ BUY completed at {last_buy_price} – waiting for SELL")


def do_exit(reason="Manual"):
    global buy_active
    global active_trade_metadata

    tr = tr_symbol.get().strip()
    if not tr:
        messagebox.showerror("Error", "Trading symbol is empty")
        return

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
    resp = place_market_order(token, int(lots_var.get()), "SELL", tr, log_cb)
    
    # 🎯 Verify if order was actually placed
    if not (isinstance(resp, dict) and "nOrdNo" in resp):
        log_with_callback(log_cb, f"❌ SELL FAILED: {resp.get('errMsg', 'Unknown Error') if isinstance(resp, dict) else 'Invalid Response'}")
        return

    order_id = resp["nOrdNo"]

    # Capture Execution Price for SELL and Verify Completion
    sell_price = 0.0
    is_completed = False
    try:
        client = get_client()
        if client:
            time.sleep(0.5) # Small buffer for exchange confirmation
            history = client.order_history(order_id=order_id)
            if history and isinstance(history, list):
                latest_state = history[-1]
                status = latest_state.get("ordSt", "").lower()

                if status == "complete":
                    is_completed = True
                    for state in reversed(history):
                        avg_prc = state.get("avgPrc")
                        if avg_prc and float(avg_prc) > 0:
                            sell_price = float(avg_prc)
                            break
                elif status == "rejected":
                    reason = latest_state.get("rejReason", "Unknown Reason")
                    log_with_callback(log_cb, f"❌ SELL REJECTED: {reason}")
    except: pass

    if not is_completed:
        # If sell failed, we are still buy_active!
        return

    buy_active = False               # ✅ position closed
    root.after(0, lambda: buy_btn.config(state="normal"))   # 🔓 BUY enabled again
    
    log_msg = f"✅ SELL completed @ {sell_price if sell_price > 0 else 'MARKET'}"
    if reason != "Manual":
        log_msg += f" [{reason}]"
    log_with_callback(log_cb, log_msg)


# ---------------------------------------------------------
# MONITOR LOGIC
# ---------------------------------------------------------
from monitor.pnl_engine import PositionPnLEngine, parse_api_orders

def color_pnl(val):
    if val > 0: return "green"
    if val < 0: return "#ff4444"
    return "white"

def update_monitor_ui():
    """Background worker to fetch and process PnL data."""
    try:
        client = get_client()
        if not client:
            return

        report = client.order_report()
        if not report or not report.get("data"):
            return

        engine = PositionPnLEngine()
        trades = parse_api_orders(report["data"])
        trades.sort(key=lambda x: x.time)

        for t in trades:
            engine.add_trade(t)
        
        # 0. Enrich completed trades with metadata if needed
        global last_trade_count, active_trade_metadata
        if len(engine.completed_trades) > last_trade_count:
            # We have a NEW completed trade. Tag the most recent one with our metadata.
            latest = engine.completed_trades[-1]
            if active_trade_metadata:
                latest.update(active_trade_metadata)
                active_trade_metadata = {} # Clear for next trade
        
        # 1. Buy Disable Logic (Keep in worker for performance)
        process_buy_disable_logic(engine)

        # 2. Calculate Stats
        completed = engine.completed_trades
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
            th = engine.trading_hours_summary()
            lines.append(f"Avg/hr    : {th['avg_per_hour']}")
        except: pass

        # 3. Handle LTP for Indicators (Use Index instead of Option)
        tr = tr_symbol.get().strip()
        idx_symbol, idx_exch = get_underlying_index(tr)
        
        if idx_symbol:
            try:
                # Fetch Index LTP
                quote_resp = client.quotes(instrument_tokens=[{"instrument_token": idx_symbol, "exchange_segment": idx_exch}], quote_type="ltp")
                
                idx_ltp = 0
                if isinstance(quote_resp, list) and len(quote_resp) > 0:
                    idx_ltp = float(quote_resp[0].get("ltp", 0))
                elif isinstance(quote_resp, dict):
                    data = quote_resp.get("data", [])
                    if isinstance(data, list) and len(data) > 0:
                        idx_ltp = float(data[0].get("ltp", 0))
                
                if idx_ltp > 0:
                    scalp_manager.add_ltp(idx_ltp, idx_symbol)
            except Exception as e:
                log_with_callback(log_cb, f"Index Quote Error: {e}")
        elif tr:
            # Fallback to Option LTP if no index mapping
            token = find_token_for_trading_symbol(tr)
            if token:
                exch = detect_exchange_segment(tr)
                quote_resp = client.quotes(instrument_tokens=[{"instrument_token": token, "exchange_segment": exch}], quote_type="ltp")
                
                ltp = 0
                if isinstance(quote_resp, list) and len(quote_resp) > 0:
                    ltp = float(quote_resp[0].get("ltp", 0))
                elif isinstance(quote_resp, dict):
                    data = quote_resp.get("data", [])
                    if isinstance(data, list) and len(data) > 0:
                        ltp = float(data[0].get("ltp", 0))
                
                if ltp > 0:
                    scalp_manager.add_ltp(ltp, tr)
        
        indicator_data = scalp_manager.get_signal()
        sig = indicator_data['signal']
        
        if sig in ["BULLISH", "BEARISH"]:
            trade_status = "Allowed to Trade"
            trade_color = "green"
        elif "WAITING" in sig:
            trade_status = f"Dont Trade ({sig})"
            trade_color = "black"
        else:
            trade_status = "Dont Trade"
            trade_color = "red"

        # 🎯 AUTOMATIC TARGET EXIT LOGIC
        if buy_active and last_buy_price > 0:
            # Check price of the symbols we bought
            token = find_token_for_trading_symbol(tr)
            exch = detect_exchange_segment(tr)
            q = client.quotes(instrument_tokens=[{"instrument_token": token, "exchange_segment": exch}], quote_type="ltp")
            cur_ltp = 0
            if isinstance(q, list) and len(q) > 0: cur_ltp = float(q[0].get("ltp", 0))
            elif isinstance(q, dict): cur_ltp = float(q.get("data", [{}])[0].get("ltp", 0))
            
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
                
                if auto_mode and profit >= target:
                    log_with_callback(log_cb, f"🎯 TARGET REACHED ({profit:+.2f} pts). Exiting...")
                    run_bg(do_exit, reason="Target")
                elif auto_mode and profit <= -effective_sl_pts:
                    log_with_callback(log_cb, f"🛑 STOP LOSS HIT ({profit:+.2f} pts). Exiting...")
                    run_bg(do_exit, reason="SL")
        
        lines.append("-" * 20)
        lines.append(f"Source: {idx_symbol or tr}")

        # Update Scalper UI Strategy Label
        root.after(0, lambda: strategy_status_label.config(text=f"Strategy: {trade_status}", foreground=trade_color))

        # 🤖 AUTO MODE LOGIC
        if auto_mode and not buy_active:
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
                # Check if buy is actually allowed (not disabled)
                disabled, _, reason = is_buy_disabled()
                if not disabled:
                    log_with_callback(log_cb, f"🤖 AUTO: {sig} signal matched with {tr}. Placing BUY...")
                    run_bg(do_buy)
                else:
                    # Log why it didn't trade if disabled
                    pass # Status label already shows this
            elif mismatch_msg:
                # Log the mismatch skip once per signal change to avoid log spam
                # We can use a simple state check if needed, but for now log it.
                log_with_callback(log_cb, f"⚠️ AUTO: {mismatch_msg}")

        # 4. Save to CSV
        save_trades_to_csv(completed)

        # 5. Render on Main Thread
        root.after(0, lambda: render_monitor_display(lines, net, gross))

    except Exception as e:
        log_with_callback(log_cb, f"Monitor Error: {e}")
    finally:
        # Schedule next update correctly
        root.after(REFRESH_INTERVAL_MS, lambda: run_bg(update_monitor_ui))

def process_buy_disable_logic(engine):
    if not ENABLE_BUY_DISABLE:
        return

    # 1. Load current lockout state from file
    current_trade_id_in_file = None
    lockout_active = False
    if os.path.exists(BUY_DISABLED_FILE):
        try:
            with open(BUY_DISABLED_FILE, 'r') as f:
                data = json.load(f)
                current_trade_id_in_file = data.get("last_trade_id")
                lockout_active = time.time() < data.get("disabled_until", 0)
        except: pass

    # 2. Check for Max Loss/Profit Lockout
    completed = engine.completed_trades
    net_pnl = sum(t["net_pnl"] for t in completed)
    today_str = datetime.now().strftime("%Y-%m-%d")

    if net_pnl <= -BUY_DISABLE_MAX_LOSS:
        if current_trade_id_in_file != "max_loss":
             disabled_until = time.time() + 86400 # 24 hours
             with open(BUY_DISABLED_FILE, 'w') as f:
                 json.dump({"disabled_until": disabled_until, "last_trade_id": "max_loss", "date": today_str}, f)
             log_with_callback(log_cb, f"CRITICAL: Net Loss {net_pnl} exceeds limit {BUY_DISABLE_MAX_LOSS}. Buy disabled until tomorrow.")
        return

    if net_pnl >= BUY_DISABLE_MAX_PROFIT:
        if current_trade_id_in_file != "max_profit":
             disabled_until = time.time() + 86400 # 24 hours
             with open(BUY_DISABLED_FILE, 'w') as f:
                 json.dump({"disabled_until": disabled_until, "last_trade_id": "max_profit", "date": today_str}, f)
             log_with_callback(log_cb, f"SUCCESS: Net Profit {net_pnl} exceeds limit {BUY_DISABLE_MAX_PROFIT}. Buy disabled until tomorrow.")
        return

    # 3. Check for NEW Consecutive Loss Lockout
    if len(completed) >= BUY_DISABLE_LOSS_COUNT:
        last_n = completed[-BUY_DISABLE_LOSS_COUNT:]
        # Use a unique ID for this set of losses to avoid re-triggering same lockout
        last_trade_time = last_n[-1].get("sell_time") or last_n[-1].get("buy_time")
        last_trade_ts = str(last_trade_time.timestamp()) if hasattr(last_trade_time, 'timestamp') else str(last_trade_time)
        
        if all(t["net_pnl"] < 0 for t in last_n) and last_trade_ts != current_trade_id_in_file:
            disabled_until = time.time() + BUY_DISABLE_DURATION
            with open(BUY_DISABLED_FILE, 'w') as f:
                json.dump({"disabled_until": disabled_until, "last_trade_id": last_trade_ts, "date": today_str}, f)
            log_with_callback(log_cb, f"INFO: Buy disabled for {BUY_DISABLE_DURATION // 60} mins due to {BUY_DISABLE_LOSS_COUNT} losses.")
            return

    # 4. Check for Re-enable (Time passed, new day, or limit changed)
    if os.path.exists(BUY_DISABLED_FILE):
        try:
            # Check lockout state again to ensure we have latest from file
            with open(BUY_DISABLED_FILE, 'r') as f:
                data = json.load(f)
            
            saved_date = data.get("date")
            reason = data.get("last_trade_id")
            disabled_until_ts = data.get("disabled_until", 0)
            
            # Reset if new day
            if saved_date != today_str:
                os.remove(BUY_DISABLED_FILE)
                log_with_callback(log_cb, "INFO: Buy limits reset for the new day.")
                return

            # Check if lockout should be lifted
            lockout_expired = time.time() >= disabled_until_ts
            pnl_recovered = False
            
            if reason == "max_profit" and net_pnl < BUY_DISABLE_MAX_PROFIT:
                pnl_recovered = True
            elif reason == "max_loss" and net_pnl > -BUY_DISABLE_MAX_LOSS:
                pnl_recovered = True

            if (lockout_expired or pnl_recovered) and disabled_until_ts > 0:
                data["disabled_until"] = 0
                with open(BUY_DISABLED_FILE, 'w') as f:
                    json.dump(data, f)
                
                msg = "INFO: Buy re-enabled."
                if pnl_recovered:
                    msg = f"INFO: Buy re-enabled (PnL {net_pnl:.2f} within new limits)."
                log_with_callback(log_cb, msg)
        except Exception as e:
            log_with_callback(log_cb, f"DEBUG: Re-enable check failed: {e}")

def save_trades_to_csv(completed):
    global last_trade_count
    if len(completed) == last_trade_count:
        return
    try:
        import csv
        os.makedirs("logs", exist_ok=True)
        filename = f"logs/trades_{datetime.now().strftime('%Y-%m-%d')}.csv"
        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            headers = ["Symbol", "Date", "Buy Time", "Sell Time", "Qty", "Buy Price", "Sell Price", "Gross PnL", "Charges", "Net PnL", 
                       "Exit Reason", "E_Sig", "E_EMA", "E_ROC", "E_BBW", "X_Sig", "X_EMA", "X_ROC", "X_BBW"]
            writer.writerow(headers)
            for t in completed:
                row = [
                    t["symbol"], t.get("trade_date"), t.get("buy_time"), t.get("sell_time"), t.get("buy_qty"), 
                    t.get("buy_price"), t.get("sell_price"), t.get("gross_pnl"), t.get("charges"), t.get("net_pnl"),
                    t.get("exit_reason", "N/A"),
                    t.get("entry_sig", "N/A"), t.get("entry_ema", "N/A"), t.get("entry_roc", "N/A"), t.get("entry_bbw", "N/A"),
                    t.get("exit_sig", "N/A"), t.get("exit_ema", "N/A"), t.get("exit_roc", "N/A"), t.get("exit_bbw", "N/A")
                ]
                writer.writerow(row)
        last_trade_count = len(completed)
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
