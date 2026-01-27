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
from common.config import ENABLE_BUY_DISABLE, BUY_DISABLE_DURATION, BUY_DISABLE_LOSS_COUNT, ENABLE_LTP_LOGGER

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

    if ENABLE_BUY_DISABLE and len(engine.completed_trades) >= BUY_DISABLE_LOSS_COUNT:
        last_n = engine.completed_trades[-BUY_DISABLE_LOSS_COUNT:]
        last_trade_time = last_n[-1].get("sell_time") or last_n[-1].get("buy_time")
        last_trade_ts = None
        if last_trade_time:
            if hasattr(last_trade_time, 'timestamp'):
                last_trade_ts = last_trade_time.timestamp()
            else:
                try:
                    last_trade_ts = datetime.fromisoformat(str(last_trade_time)).timestamp()
                except:
                    last_trade_ts = None
        last_disabled_ts = None
        if last_disabled_trade_id:
            try:
                last_disabled_ts = float(last_disabled_trade_id)
            except:
                last_disabled_ts = None
        if all(t["net_pnl"] < 0 for t in last_n) and last_trade_ts and (not last_disabled_ts or last_trade_ts > last_disabled_ts):
            disabled_until = time.time() + BUY_DISABLE_DURATION
            with open(BUY_DISABLED_FILE, 'w') as f:
                json.dump({"disabled_until": disabled_until, "last_trade_id": str(last_trade_ts)}, f)
            buy_disabled = True
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