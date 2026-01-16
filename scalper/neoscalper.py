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


# ---------------------------------------------------------
# ROOT
# ---------------------------------------------------------
root = tk.Tk()
root.title("SCALPER PRO")
root.geometry("340x260")
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

style.configure("Buy.TButton", background="#d1fae5", font=("Segoe UI", 11, "bold"))
style.map("Buy.TButton", background=[("active", "#a7f3d0")])

style.configure("Exit.TButton", background="#fee2e2", font=("Segoe UI", 11, "bold"))
style.map("Exit.TButton", background=[("active", "#fecaca")])

style.configure("CE.TButton", background="#e6f4ea", foreground="#166534")
style.configure("PE.TButton", background="#fdecea", foreground="#991b1b")

# ---------------------------------------------------------
# FRAME
# ---------------------------------------------------------
frm = ttk.Frame(root, padding=6)
frm.pack(fill=tk.BOTH, expand=True)

for i in range(4):
    frm.columnconfigure(i, pad=2)

# ---------------------------------------------------------
# LOG
# ---------------------------------------------------------
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
# TOP BUTTONS REMOVED
# ---------------------------------------------------------
# (Login, Load Master, Refresh ATM removed for auto-login)

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
# AUTO STARTUP
# ---------------------------------------------------------
def startup_sequence():
    log_with_callback(log_cb, "🚀 Starting Auto-Login Sequence...")
    try:
        do_login(log_cb)
        load_scrip_master_csv(log_cb=log_cb)
        log_with_callback(log_cb, "✅ Startup Complete")
    except Exception as e:
        log_with_callback(log_cb, f"❌ Startup Failed: {e}")

root.after(500, lambda: run_bg(startup_sequence))
root.mainloop()
