import sys
import os
from typing import Optional, Callable, Any, List, Dict

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.utils import run_bg, log_with_callback
from common.orders import get_client
from common.scrip_master import find_token_for_trading_symbol

def parse_quote_for_ltp(resp: Any) -> Optional[float]:
    """
    Minimal LTP extraction based on actual response formats.
    """
    try:
        # Case 1: response is list of dicts (your example)
        if isinstance(resp, list) and len(resp) > 0 and isinstance(resp[0], dict):
            d0 = resp[0]
            if "ltp" in d0:
                return float(d0["ltp"])

        # Case 2: response is dict with "data" → list of dicts (older format)
        if isinstance(resp, dict):
            data = resp.get("data")
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                d0 = data[0]
                if "ltp" in d0:
                    return float(d0["ltp"])

        return None

    except Exception:
        return None

def fetch_and_update_ltp_once(trading_symbol: str,
                             update_label_cb: Optional[Callable[[str], None]] = None,
                             log_cb: Optional[Callable[[str], None]] = None) -> None:
    """
    Fetch LTP for a trading symbol (trading_symbol is the human trading symbol like NIFTY25NOV24850CE).
    This function will attempt to resolve to instrument token via scrip_master and then call client.quotes.
    """
    try:
        tr = trading_symbol
        if not tr or tr == "Not found":
            return
        token = find_token_for_trading_symbol(tr, log_cb=log_cb)
        if not token:
            log_with_callback(log_cb, f"No token for {tr} (load scrip master first?)")
            return
        instrument_tokens = [{"instrument_token": str(token), "exchange_segment": "nse_fo"}]

        #log_with_callback(log_cb, f"Fetching LTP for {tr} (token {token})...")
        client = get_client()
        if client is None:
            log_with_callback(log_cb, "No client - not calling quotes")
            return

        try:
            resp = client.quotes(instrument_tokens=instrument_tokens, quote_type="ltp")
            #log_with_callback(log_cb, f"quotes response: {resp}")
        except Exception as e:
            log_with_callback(log_cb, f"quotes call error: {e}")
            return

        ltp = parse_quote_for_ltp(resp)
        update_label_cb(f"LTP: {ltp}")
        
    except Exception as e:
        log_with_callback(log_cb, f"fetch_and_update_ltp_once error: {e}")

def start_ltp_auto_loop(root, trading_symbol_getter: Callable[[], str],
                        update_label_cb: Optional[Callable[[str], None]] = None,
                        log_cb: Optional[Callable[[str], None]] = None,
                        interval_ms: int = 2000):
    """
    Start an LTP auto loop using tkinter's `root.after`. The function schedules
    a background fetch and re-schedules itself. It returns immediately.
    """
    def _loop():
        # schedule background fetch
        tr = trading_symbol_getter()
        run_bg(fetch_and_update_ltp_once, tr, update_label_cb, log_cb)
        root.after(interval_ms, _loop)

    # first call
    root.after(interval_ms, _loop)
