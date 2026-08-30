import time
from typing import Dict, List, Optional, Tuple

from common.orders import detect_exchange_segment, ensure_login, place_market_order
from common.scrip_master import find_token_for_trading_symbol, get_lot_size_from_scrip_master, load_scrip_master_csv


_SYMBOLS_LOADED = False


def _ensure_symbols_loaded() -> None:
    global _SYMBOLS_LOADED
    if not _SYMBOLS_LOADED:
        load_scrip_master_csv()
        _SYMBOLS_LOADED = True


def _normalize_list_payload(payload) -> List[dict]:
    if isinstance(payload, dict):
        data = payload.get("data", [])
        return data if isinstance(data, list) else []
    if isinstance(payload, list):
        return payload
    return []


def _get_open_positions(client) -> List[dict]:
    return _normalize_list_payload(client.positions())


def _has_open_derivative_position(positions: List[dict]) -> Tuple[bool, Optional[str]]:
    for p in positions:
        sym = str(p.get("trdSym", "")).upper()
        exch = str(p.get("exch", "")).lower()
        fl_buy = float(p.get("flBuyQty", 0) or 0)
        fl_sell = float(p.get("flSellQty", 0) or 0)
        qty = int(float(p.get("netQty", fl_buy - fl_sell) or 0))
        if qty == 0:
            continue
        if "-EQ" in sym:
            continue
        if "fo" in exch or any(x in sym for x in ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY", "BANKEX"]):
            return True, sym
    return False, None


def _is_order_completed(client, order_id: str) -> Tuple[bool, str, Optional[float]]:
    status = "unknown"
    exec_price = None

    for _ in range(6):
        time.sleep(0.5)
        history = _normalize_list_payload(client.order_history(order_id=order_id))
        if not history:
            continue
        latest = history[-1]
        status = str(latest.get("ordSt", "")).lower()
        if status == "complete":
            for state in reversed(history):
                avg_p = state.get("avgPrc") or state.get("buyAvgPrc") or state.get("sellAvgPrc") or state.get("price")
                if avg_p and float(avg_p) > 0:
                    exec_price = float(avg_p)
                    break
            return True, status, exec_price
        if status == "rejected":
            return False, status, None

    # Fallback on order report
    rep_data = _normalize_list_payload(client.order_report())
    for o in rep_data:
        if str(o.get("nOrdNo", "")) == str(order_id):
            status = str(o.get("ordSt", "")).lower()
            if status == "complete":
                avg_p = o.get("avgPrc") or o.get("buyAvgPrc") or o.get("sellAvgPrc") or o.get("price")
                exec_price = float(avg_p) if avg_p else None
                return True, status, exec_price
            return False, status, None

    return False, status, exec_price


def _convert_quantity_to_lots(trading_symbol: str, quantity: int) -> int:
    lot_size = max(int(get_lot_size_from_scrip_master(trading_symbol, default=1)), 1)
    lots = round(abs(quantity) / lot_size)
    return max(1, int(lots))


def execute_market_action(trading_symbol: str, lots: int, action: str, enforce_single_position: bool = True) -> Dict:
    _ensure_symbols_loaded()
    client = ensure_login()

    symbol = trading_symbol.strip().upper()
    token = find_token_for_trading_symbol(symbol)
    if not token:
        # one retry after refresh
        load_scrip_master_csv()
        token = find_token_for_trading_symbol(symbol)

    if not token:
        raise ValueError(f"Token not found for symbol: {symbol}")

    side = "BUY" if action.upper() == "BUY" else "SELL"

    positions = _get_open_positions(client)
    has_pos, pos_sym = _has_open_derivative_position(positions)

    if side == "BUY" and enforce_single_position and has_pos:
        raise ValueError(f"Buy blocked: existing open position detected ({pos_sym})")

    # For EXIT/SELL, if explicit symbol has no open qty, try to infer from live positions.
    selected_symbol = symbol
    selected_lots = int(lots)
    if side == "SELL":
        target_pos = None
        for p in positions:
            sym = str(p.get("trdSym", "")).upper()
            if sym == symbol:
                target_pos = p
                break
        if not target_pos and has_pos:
            # fallback to first open derivative position
            for p in positions:
                sym = str(p.get("trdSym", "")).upper()
                fl_buy = float(p.get("flBuyQty", 0) or 0)
                fl_sell = float(p.get("flSellQty", 0) or 0)
                qty = int(float(p.get("netQty", fl_buy - fl_sell) or 0))
                if qty != 0 and "-EQ" not in sym:
                    target_pos = p
                    break

        if target_pos:
            selected_symbol = str(target_pos.get("trdSym", symbol)).upper()
            fl_buy = float(target_pos.get("flBuyQty", 0) or 0)
            fl_sell = float(target_pos.get("flSellQty", 0) or 0)
            net_qty = int(float(target_pos.get("netQty", fl_buy - fl_sell) or 0))
            selected_lots = _convert_quantity_to_lots(selected_symbol, net_qty)
            token = find_token_for_trading_symbol(selected_symbol) or token
        elif enforce_single_position:
            raise ValueError("Exit blocked: no open derivative position found")

    resp = place_market_order(token=token, lots=selected_lots, side=side, trading_symbol=selected_symbol)
    if not (isinstance(resp, dict) and resp.get("nOrdNo")):
        err = resp.get("errMsg") if isinstance(resp, dict) else "Invalid order response"
        raise ValueError(f"Order failed: {err}")

    order_id = str(resp.get("nOrdNo"))
    completed, status, exec_price = _is_order_completed(client, order_id)

    return {
        "symbol": selected_symbol,
        "lots": selected_lots,
        "side": side,
        "order_id": order_id,
        "completed": completed,
        "status": status,
        "execution_price": exec_price,
        "raw": resp,
        "exchange_segment": detect_exchange_segment(selected_symbol),
    }
