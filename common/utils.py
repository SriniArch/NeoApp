# utils.py
import threading
from datetime import datetime
from typing import Callable, Optional

def run_bg(fn, *a, **kw):
    """
    Run a function in a daemon background thread.
    Returns the Thread object.
    """
    t = threading.Thread(target=fn, args=a, kwargs=kw, daemon=True)
    t.start()
    return t

def log_with_callback(log_cb: Optional[Callable[[str], None]], msg: str):
    """
    A small logger helper that uses an injected log function (so modules remain UI-agnostic).
    """
    ts = datetime.now().strftime("%H:%M:%S")
    if log_cb:
        try:
            log_cb(f"[{ts}] {msg}")
            return
        except Exception:
            # fallback to print if callback fails
            pass
    print(f"[{ts}] {msg}")

def format_expiry(date_str: str) -> str:
    """Input: '25-Nov-2025' → '20251125'"""
    dt = datetime.strptime(date_str, "%d-%b-%Y")
    return dt.strftime("%Y%m%d")

def find_trading_symbol_raw(symbol: str, expiry: str, strike: int, option_type: str) -> str:
    """Constructs a basic trading symbol string."""
    day = expiry[:2]
    month = expiry[3:6].upper()
    year = expiry[-2:]
    return f"{symbol.upper()}{day}{month}{strike}{option_type.upper()}"
