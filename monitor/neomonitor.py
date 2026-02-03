import sys
import os

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.neo_login import get_neo_client
from common.orders import get_client, ensure_login as do_login
import datetime
from datetime import datetime
import pandas as pd
from monitor.pnl_engine import PositionPnLEngine, parse_api_orders
import json
import time
from common.config import ENABLE_BUY_DISABLE, BUY_DISABLE_DURATION, BUY_DISABLE_LOSS_COUNT, ENABLE_LTP_LOGGER, PROGRESSIVE_LOSS_CONFIG, BUY_DISABLE_MAX_PROFIT, PROGRESSIVE_LOSS_URL, REMOTE_CONFIG_URL
from common.utils import fetch_remote_config, fetch_remote_json

BUY_DISABLED_FILE = "buy_disabled.json"
buy_disabled = False

def start_ltp_logger(client):
    try:
        import threading
        from scalper.ltp import start_quotes_logger

        instrument_tokens = [
            {"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"},
            {"instrument_token": "Nifty Bank", "exchange_segment": "nse_cm"}
        ]

        _ltp_stop = threading.Event()
        _ltp_thread = threading.Thread(
            target=start_quotes_logger,
            args=(client, instrument_tokens, 'logs/ltp_quotes.csv', 10, _ltp_stop),
            daemon=True
        )
        _ltp_thread.start()
    except Exception:
        pass

# -----------------------
# Initialize Neo API using common module
# -----------------------
try:
    client = do_login()
    print("✅ Neo Login Successful")
    # Start background LTP quotes logger (writes logs/ltp_quotes.csv every 10s)
    if ENABLE_LTP_LOGGER:
        start_ltp_logger(client)
except Exception as e:
    print(f"❌ Login Failed: {e}")
    sys.exit(1)

#print(client.scrip_master())


# with open('output.json', 'w') as json_file:
#     json.dump(client.order_report(), json_file, indent=4)

def trade_statistics(completed_trades):
    pnls = [round(t["net_pnl"]) for t in completed_trades]

    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)

    return {
        "no_of_trades": len(completed_trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round((wins / len(pnls)) * 100, 2) if pnls else 0.0,
    }

def color_pnl(pnl):
    if pnl > 0:
        return f"\033[92m{pnl}\033[0m"   # Green
    elif pnl < 0:
        return f"\033[91m{pnl}\033[0m"   # Red
    else:
        return f"\033[90m{pnl}\033[0m"   # Grey


def print_last_5_trades_inline(completed_trades):
    pnls = [round(t["net_pnl"]) for t in completed_trades][-5:]
    line = " | ".join(color_pnl(p) for p in pnls)
    print(f"Recent: {line}")



last_trade_count = 0

while True:
    # 1️⃣ Fetch latest order book from broker
    response = client.order_report()  # <-- YOUR API CALL

    # 2️⃣ Recalculate P&L fresh
    engine = PositionPnLEngine()
    trades = parse_api_orders(response["data"])
    trades.sort(key=lambda x: x.time)

    # Periodic Config Refresh (Every 5 mins)
    if not hasattr(engine, "last_config_refresh"):
        # We need a persistent way to track this in the script
        pass # Better to use a global or a local var outside the loop

    # Reset every few iterations or use time
    if 'last_config_refresh' not in globals():
        global last_config_refresh
        last_config_refresh = 0
    
    if time.time() - last_config_refresh > 300:
        global PROGRESSIVE_LOSS_CONFIG
        new_prog = fetch_remote_json(PROGRESSIVE_LOSS_URL, PROGRESSIVE_LOSS_CONFIG)
        if new_prog != PROGRESSIVE_LOSS_CONFIG:
            PROGRESSIVE_LOSS_CONFIG = new_prog
            print("🔄 Progressive Loss Config updated from remote.")
        last_config_refresh = time.time()

    for t in trades:
        engine.add_trade(t)

    # Check for buy disable due to losses
    # Only trigger if new trades have been added since last disable
    last_disabled_trade_id = None
    if os.path.exists(BUY_DISABLED_FILE):
        try:
            with open(BUY_DISABLED_FILE, 'r') as f:
                data = json.load(f)
            last_disabled_trade_id = data.get("last_trade_id")
        except:
            pass

    today_str = datetime.now().strftime("%Y-%m-%d")
    if ENABLE_BUY_DISABLE:
        # 1. Progressive Loss Check
        net_pnl = sum(t["net_pnl"] for t in engine.completed_trades)
        loss_amount = -net_pnl
        for threshold, duration_mins in PROGRESSIVE_LOSS_CONFIG:
            if loss_amount >= threshold:
                label = f"max_loss_{threshold}"
                if last_disabled_trade_id != label:
                    disabled_until = time.time() + (duration_mins * 60)
                    with open(BUY_DISABLED_FILE, 'w') as f:
                        json.dump({"disabled_until": disabled_until, "last_trade_id": label, "date": today_str}, f)
                    duration_str = f"{duration_mins} mins" if duration_mins < 1440 else "tomorrow"
                    print(f"WARNING: Net Loss {net_pnl} hit threshold {threshold}. Buy disabled for {duration_str}.")
                break # Only highest

        # 2. Max Profit Check
        if net_pnl >= BUY_DISABLE_MAX_PROFIT:
             if last_disabled_trade_id != "max_profit":
                disabled_until = time.time() + 86400
                with open(BUY_DISABLED_FILE, 'w') as f:
                    json.dump({"disabled_until": disabled_until, "last_trade_id": "max_profit", "date": today_str}, f)
                print(f"SUCCESS: Net Profit {net_pnl} hit target {BUY_DISABLE_MAX_PROFIT}. Buy disabled until tomorrow.")

        # 3. Consecutive Loss Check
        if len(engine.completed_trades) >= BUY_DISABLE_LOSS_COUNT:
            last_n = engine.completed_trades[-BUY_DISABLE_LOSS_COUNT:]
            last_trade_time = last_n[-1].get("sell_time") or last_n[-1].get("buy_time")
            last_trade_ts = None
            if last_trade_time:
                last_trade_ts = str(last_trade_time.timestamp()) if hasattr(last_trade_time, 'timestamp') else str(last_trade_time)
            
            if all(t["net_pnl"] < 0 for t in last_n) and last_trade_ts != last_disabled_trade_id:
                disabled_until = time.time() + BUY_DISABLE_DURATION
                with open(BUY_DISABLED_FILE, 'w') as f:
                    json.dump({"disabled_until": disabled_until, "last_trade_id": last_trade_ts, "date": today_str}, f)
                print(f"Buy disabled for {BUY_DISABLE_DURATION // 60} minutes due to {BUY_DISABLE_LOSS_COUNT} continuous losses.")

    # Check if time to re-enable
    if os.path.exists(BUY_DISABLED_FILE):
        try:
            with open(BUY_DISABLED_FILE, 'r') as f:
                data = json.load(f)
            if time.time() > data["disabled_until"]:
                os.remove(BUY_DISABLED_FILE)
                buy_disabled = False
                print("Buy re-enabled.")
        except:
            pass

    current_trade_count = len(engine.completed_trades)

    # ✅ Print ONLY if trade count changed
    if current_trade_count != last_trade_count:
        # 3️⃣ Compute stats
        stats = trade_statistics(engine.completed_trades)

        gross_sum = round(sum(t["gross_pnl"] for t in engine.completed_trades), 2)
        net_sum   = round(sum(t["net_pnl"]   for t in engine.completed_trades), 2)

        print_last_5_trades_inline(engine.completed_trades)
        print("No of trades :", stats["no_of_trades"])
        print("Wins         :", stats["wins"])
        print("Losses       :", stats["losses"])
        print("Win rate %   :", stats["win_rate"])
        print("Gross P&L    :", gross_sum)
        print("Net P&L      :", net_sum)
        print("Approx Charges:", stats["no_of_trades"] * 5)  # assuming avg 100 per trade
        # (Hourly counts removed per user preference)

        print("-" * 40)
        last_trade_count = current_trade_count
        
    time.sleep(10)  