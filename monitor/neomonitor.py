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

# -----------------------
# Initialize Neo API using common module
# -----------------------
try:
    client = do_login()
    print("✅ Neo Login Successful")
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
    print(f"Last 5 Trades P&L → {line}")



import time

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
        print("-" * 40)
        last_trade_count = current_trade_count
        
    time.sleep(10)  # wait for 5 minutes before next fetch