# orders.py
from typing import Optional
from .utils import log_with_callback
from .config import LOT_SIZE
from .scrip_master import get_lot_size_from_scrip_master
from .neo_login import get_neo_client

_client = None

def get_client():
    global _client
    return _client

def ensure_login(log_cb=None):
    global _client
    if _client is None:
        _client = get_neo_client()
        log_with_callback(log_cb, "Neo session initialized.")
    return _client

def detect_exchange_segment(trading_symbol: str) -> str:
    s = trading_symbol.upper()
    if any(idx in s for idx in ["SENSEX", "BANKEX"]):
        return "bse_fo"
    return "nse_fo"

def detect_strike_step(trading_symbol: str) -> int:
    s = trading_symbol.upper()
    if "SENSEX" in s or "BANKEX" in s:
        return 100
    if "BANKNIFTY" in s:
        return 100
    return 50 # Nifty, Finnifty, Midcap

def place_market_order(token, lots, side, trading_symbol, log_cb=None):
    client = ensure_login(log_cb)
    
    exchange_segment = detect_exchange_segment(trading_symbol)
    lot_size = get_lot_size_from_scrip_master(trading_symbol, default=1)
    qty = int(lots) * lot_size

    log_with_callback(log_cb, f"Placing {side} market order for {qty} of {trading_symbol} ({exchange_segment})")

    try:
        resp = client.place_order(
            exchange_segment=exchange_segment,
            product="MIS",
            price="0",
            order_type="MKT",
            quantity=str(qty),
            validity="DAY",
            trading_symbol=trading_symbol,
            transaction_type="B" if side.upper() == "BUY" else "S",
            scrip_token=str(token),
            trigger_price="0",
            disclosed_quantity="0",
            market_protection="0",
            pf="N"
        )
        log_with_callback(log_cb, f"Order Response: {resp}")
        return resp
    except Exception as e:
        log_with_callback(log_cb, f"place_order ERROR: {e}")
        raise
