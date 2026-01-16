import tkinter as tk
from tkinter import ttk, messagebox
import sys, os, re, difflib
import pandas as pd

import sys
import os

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.utils import log_with_callback, run_bg
from common.scrip_master import load_scrip_master_csv, find_token_for_trading_symbol
from common.orders import ensure_login as do_login, place_market_order, get_client, detect_exchange_segment, detect_strike_step
from common.config import DEFAULT_TRADING_SYMBOL
import json

HISTORY_FILE = "symbol_history.json"

# Local imports for modules still in the scalper package
from .ltp import fetch_and_update_ltp_once, parse_quote_for_ltp


# ---------------------------------------------------------
# STATE
# ---------------------------------------------------------
buy_active = False  # ✅ only one BUY at a time
last_trade_count = 0 # Track saved trades


# ---------------------------------------------------------
# ROOT
# ---------------------------------------------------------
root = tk.Tk()
root.title("SCALPER & MONITOR PRO")
root.geometry("680x280")
root.resizable(False, False)
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
mon_text = tk.Text(mon_frame, width=32, height=10, bg="#111827", fg="#e5e7eb", font=("Consolas", 10), state="disabled")
mon_text.pack(fill="both", expand=True)


# ---------------------------------------------------------
# SCALPER UI (Left)
# ---------------------------------------------------------
for i in range(4):
    frm.columnconfigure(i, pad=2)

# LOG BOX
log_box = tk.Text(
    frm, height=5, width=44,
    bg="#111827", fg="#e5e7eb",
    insertbackground="white",
    relief="flat",
    font=("Consolas", 10)
)
log_box.grid(row=20, column=0, columnspan=4, pady=(10, 0))

def log_cb(msg):
    log_box.insert(tk.END, msg + "\n")
    log_box.see(tk.END)

# ---------------------------------------------------------
# SYMBOL HELPERS
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# STRIKE CONTROLS (Row 0)
# ---------------------------------------------------------
ttk.Label(frm, text="Strike:").grid(row=0, column=0, sticky="e", pady=2)

updown = ttk.Frame(frm)
updown.grid(row=0, column=1, sticky="w", pady=2)

def move_strike(step):
    cur_sym = tr_symbol.get().strip().upper()
    if not cur_sym:
        return

    m = re.search(r"(\d+)(CE|PE)?$", cur_sym)
    if not m:
        return

    cur_strike = int(m.group(1))
    strike_step = int(detect_strike_step(cur_sym))
    new_strike = cur_strike + (strike_step * step)

    if new_strike <= 0:
        return

    new_symbol = update_symbol_strike(cur_sym, new_strike)
    tr_symbol.set(new_symbol)
    log_with_callback(log_cb, f"Updated Symbol: {new_symbol}")

ttk.Button(updown, text="▲", width=4, command=lambda: move_strike(1)).pack(side="left", padx=1)
ttk.Button(updown, text="▼", width=4, command=lambda: move_strike(-1)).pack(side="left", padx=1)

# ---------------------------------------------------------
# CE / PE (Row 1)
# ---------------------------------------------------------
ttk.Label(frm, text="Option:").grid(row=1, column=0, sticky="e", pady=2)
opt_type = tk.StringVar(value="CE")

def toggle_cepe():
    new = "PE" if opt_type.get() == "CE" else "CE"
    opt_type.set(new)
    cepe_btn.config(text=new, style="CE.TButton" if new == "CE" else "PE.TButton")

    cur = tr_symbol.get().strip()
    if cur:
        tr_symbol.set(update_symbol_option(cur, new))
        log_with_callback(log_cb, f"Updated Symbol: {tr_symbol.get()}")

cepe_btn = ttk.Button(frm, text="CE", width=10, style="CE.TButton", command=toggle_cepe)
cepe_btn.grid(row=1, column=1, sticky="w", pady=2)

# ---------------------------------------------------------
# LOTS (Row 2)
# ---------------------------------------------------------
ttk.Label(frm, text="Lots:").grid(row=2, column=0, sticky="e", pady=2)
lots_var = tk.StringVar(value="1")

ttk.Combobox(
    frm,
    textvariable=lots_var,
    values=["1", "2", "3", "5", "10"],
    width=8,
    state="readonly"
).grid(row=2, column=1, sticky="w", pady=2)

# ---------------------------------------------------------
# TRADING SYMBOL (Row 3)
# ---------------------------------------------------------
ttk.Label(frm, text="Symbol:").grid(row=3, column=0, sticky="e", pady=2)
tr_symbol = tk.StringVar(value=DEFAULT_TRADING_SYMBOL)

history = load_history()
symbol_combo = ttk.Combobox(frm, textvariable=tr_symbol, values=history, width=23)
symbol_combo.grid(row=3, column=1, columnspan=2, sticky="w", pady=2)
symbol_combo.bind("<Return>", update_history)

# ---------------------------------------------------------
# BUY / EXIT (Row 4)
# ---------------------------------------------------------
btn_frame = ttk.Frame(frm)
btn_frame.grid(row=4, column=0, columnspan=4, pady=15)

buy_btn = ttk.Button(
    btn_frame, text="BUY", style="Buy.TButton", width=12,
    command=lambda: run_bg(do_buy)
)
buy_btn.pack(side="left", padx=10)

ttk.Button(
    btn_frame, text="EXIT", style="Exit.TButton", width=12,
    command=lambda: run_bg(do_exit)
).pack(side="left", padx=10)

# ---------------------------------------------------------
# LOGIC
# ---------------------------------------------------------


def do_buy():
    global buy_active

    if buy_active:
        log_with_callback(log_cb, "BUY blocked: position already open")
        return

    tr = tr_symbol.get().strip()
    if not tr:
        messagebox.showerror("Error", "Trading symbol is empty")
        return

    buy_btn.config(state="disabled")  # 🔒 disable immediately

    token = find_token_for_trading_symbol(tr, log_cb)
    place_market_order(token, int(lots_var.get()), "BUY", tr, log_cb)

    buy_active = True  # ✅ BUY position now active
    log_with_callback(log_cb, "BUY completed – waiting for SELL")


def do_exit():
    global buy_active

    tr = tr_symbol.get().strip()
    if not tr:
        messagebox.showerror("Error", "Trading symbol is empty")
        return

    token = find_token_for_trading_symbol(tr, log_cb)
    place_market_order(token, int(lots_var.get()), "SELL", tr, log_cb)

    buy_active = False               # ✅ position closed
    buy_btn.config(state="normal")   # 🔓 BUY enabled again
    log_with_callback(log_cb, "SELL completed – BUY enabled")


# ---------------------------------------------------------
# MONITOR LOGIC
# ---------------------------------------------------------
from monitor.pnl_engine import PositionPnLEngine, parse_api_orders

def color_pnl(val):
    if val > 0: return "green"
    if val < 0: return "#ff4444"
    return "white"

def update_monitor_ui():
    try:
        client = get_client() # Get authenticated client
        if not client:
            return

        report = client.order_report()
        if not report or not report.get("data"):
            # log_cb("Monitor: No data in order report")
            return

        engine = PositionPnLEngine()
        trades = parse_api_orders(report["data"])
        trades.sort(key=lambda x: x.time)

        for t in trades:
            engine.add_trade(t)
        
        # Calculate stats
        completed = engine.completed_trades
        pnls = [round(t["net_pnl"]) for t in completed]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        win_rate = round((wins / len(pnls) * 100), 1) if pnls else 0.0
        
        gross = round(sum(t["gross_pnl"] for t in completed), 2)
        net = round(sum(t["net_pnl"] for t in completed), 2)
        charges = round(sum(t["charges"] for t in completed), 2)
        
        # Last 5 trades
        last_5 = pnls[-5:]
        last_str = " | ".join(str(p) for p in last_5)

        # Build display text
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
        
        # Save to CSV if new trades
        global last_trade_count
        if len(completed) != last_trade_count:
            try:
                import csv
                from datetime import datetime
                
                date_str = datetime.now().strftime("%Y-%m-%d")
                filename = f"logs/trades_{date_str}.csv"
                existing = os.path.exists(filename)
                
                # We overwrite/append logic. Since we have FULL list, 
                # safer is to overwrite OR append only new?
                # Simplest: Overwrite the daily file with the current full list to avoid dupes/complex merge
                with open(filename, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Symbol", "Date", "Buy Time", "Sell Time", "Qty", "Buy Price", "Sell Price", "Gross PnL", "Charges", "Net PnL"])
                    
                    for t in completed:
                        writer.writerow([
                            t["symbol"],
                            t.get("trade_date", ""),
                            t.get("buy_time", ""),
                            t.get("sell_time", ""),
                            t.get("buy_qty", 0),
                            t.get("buy_price", 0),
                            # Sell price is not stored directly in position dict? 
                            # We can infer or just store what we have.
                            # Net PnL = (Sell - Buy) * Qty - Charges
                            # Sell = (Net + Charges)/Qty + Buy
                            # Let's check pnl_engine key structure.
                            # It has 'buy_price', 'gross_pnl', 'charges', 'net_pnl'.
                            # Sell Average = Buy Price + (Gross PnL / Qty)
                            t.get("buy_price", 0) + (t.get("gross_pnl", 0) / t.get("buy_qty", 1)),
                            t.get("gross_pnl", 0),
                            t.get("charges", 0),
                            t.get("net_pnl", 0)
                        ])
                
                log_with_callback(log_cb, f"💾 Saved {len(completed)} trades to {filename}")
                last_trade_count = len(completed)
            except Exception as e:
                log_with_callback(log_cb, f"Save CSV Error: {e}")

        # Colorize Net PnL line
        mon_text.config(state="normal")
        mon_text.delete("1.0", tk.END)
        
        for line in lines:
            if line.startswith("Recent:"):
                # Handle Recent line specially to color code individual values
                mon_text.insert(tk.END, "Recent: ")
                # Extract the numbers part: "Recent: 50 | -20 | 100" -> "50 | -20 | 100"
                parts = line.split("Recent: ")[1].split(" | ")
                
                for i, p in enumerate(parts):
                    if not p: continue
                    try:
                        val = float(p)
                        tag = "green" if val > 0 else "red" if val < 0 else None
                    except:
                        tag = None
                    
                    mon_text.insert(tk.END, p, tag)
                    if i < len(parts) - 1:
                        mon_text.insert(tk.END, " | ")
                
                mon_text.insert(tk.END, "\n")
            
            else:
                # Handle other lines normally
                tag = None
                if line.startswith("Net"):
                    tag = "green" if net > 0 else "red"
                elif line.startswith("Gross"):
                     tag = "green" if gross > 0 else "red"
                
                mon_text.insert(tk.END, line + "\n", tag)
            
        mon_text.tag_config("green", foreground="#4ade80")
        mon_text.tag_config("red", foreground="#f87171")
        mon_text.config(state="disabled")

    except Exception as e:
        log_with_callback(log_cb, f"Monitor Error: {e}")
        pass
    
    # Schedule next update
    root.after(5000, lambda: run_bg(update_monitor_ui))

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
root.mainloop()
