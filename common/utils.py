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
def fetch_remote_config(url: str, default_val: int) -> int:
    """Fetch a single integer value from a remote URL (raw text)."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            content = response.read().decode('utf-8').strip()
            return int(float(content))
    except Exception as e:
        print(f"Warning: Failed to fetch remote config from {url}: {e}")
        return default_val

def fetch_remote_json(url: str, default_val: any) -> any:
    """Fetch and parse JSON from a remote URL."""
    import urllib.request
    import json
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            content = response.read().decode('utf-8').strip()
            return json.loads(content)
    except Exception as e:
        # Silently fail or minimal log for background fetches
        return default_val
def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    import os, sys
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return os.path.join(base_path, relative_path)

def send_telegram_msg(message: str) -> None:
    """Send a message via Telegram Bot to all configured recipients."""
    try:
        # Import inside function to avoid circular dependency with config.py
        from .config import TELEGRAM_CONFIGS
        import urllib.request
        import json

        if not TELEGRAM_CONFIGS:
            return

        for config in TELEGRAM_CONFIGS:
            token = config.get("token")
            chat_id = config.get("chat_id")
            
            if not token or not chat_id:
                continue

            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }
                
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
                
                with urllib.request.urlopen(req, timeout=5) as response:
                    pass # Success
            except Exception as e:
                print(f"Failed to send to Telegram chat {chat_id}: {e}")
            
    except Exception as e:
        print(f"Failed to initialize Telegram sending: {e}")
