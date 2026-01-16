from collections import defaultdict, deque
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict

# =========================
# Trade Model
# =========================
@dataclass
class Trade:
    symbol: str
    side: str          # B / S
    qty: int
    price: float
    time: datetime
    product: str       # MIS / NRML
    segment: str       # nse_cm / nse_fo / bse_fo


# =========================
# Charges Calculator (India - Approx)
# =========================
class ChargesCalculator:

    @staticmethod
    def calculate(turnover: float, segment: str) -> float:
        """
        Approx Indian charges.
        Brokerage assumed ZERO.
        """
        exch = turnover * 0.0000325
        sebi = turnover * 0.000001
        gst = 0.18 * (exch + sebi)
        stamp = turnover * 0.00015

        # STT rules
        if segment.endswith("_cm"):
            stt = turnover * 0.001        # Equity delivery sell
        else:
            stt = turnover * 0.0007       # F&O sell

        return round(stt + exch + sebi + gst + stamp, 2)


# =========================
# FIFO P&L Engine
# =========================
class PnLEngine:

    def __init__(self):
        self.positions = defaultdict(deque)
        self.realized_trades = []

    def add_trade(self, trade: Trade):
        if trade.side == "B":
            self.positions[trade.symbol].append(trade)
        elif trade.side == "S":
            self._match_sell(trade)

    def _match_sell(self, sell: Trade):
        sell_qty = sell.qty

        while sell_qty > 0 and self.positions[sell.symbol]:
            buy = self.positions[sell.symbol][0]
            matched_qty = min(buy.qty, sell_qty)

            gross_pnl = (sell.price - buy.price) * matched_qty
            turnover = (sell.price + buy.price) * matched_qty
            charges = ChargesCalculator.calculate(turnover, sell.segment)
            net_pnl = round(gross_pnl - charges, 2)

            self.realized_trades.append({
                "symbol": sell.symbol,
                "qty": matched_qty,
                "buy_price": buy.price,
                "sell_price": sell.price,
                "gross_pnl": round(gross_pnl, 2),
                "charges": charges,
                "net_pnl": net_pnl,
                "buy_time": buy.time,
                "sell_time": sell.time,
                "trade_date": sell.time.date()
            })

            buy.qty -= matched_qty
            sell_qty -= matched_qty

            if buy.qty == 0:
                self.positions[sell.symbol].popleft()

    def daily_summary(self) -> Dict:
        summary = defaultdict(lambda: {
            "trades": 0,
            "gross_pnl": 0,
            "charges": 0,
            "net_pnl": 0
        })

        for t in self.realized_trades:
            d = t["trade_date"]
            summary[d]["trades"] += 1
            summary[d]["gross_pnl"] += t["gross_pnl"]
            summary[d]["charges"] += t["charges"]
            summary[d]["net_pnl"] += t["net_pnl"]

        return summary


# =========================
# API Adapter
# =========================
def parse_api_orders(api_data: List[dict]) -> List[Trade]:
    trades = []

    for o in api_data:
        if o.get("ordSt") != "complete":
            continue

        avg_price = float(o.get("avgPrc", 0))
        if avg_price == 0:
            continue

        # Handle timestamp spacing issues safely
        ts = o["exCfmTm"].replace("  ", " ").replace(": ", ":")
        trade_time = datetime.strptime(ts, "%d-%b-%Y %H:%M:%S")

        trades.append(
            Trade(
                symbol=o["trdSym"],
                side=o["trnsTp"],
                qty=int(o["qty"]),
                price=avg_price,
                time=trade_time,
                product=o["prod"],
                segment=o["exSeg"]
            )
        )
    return trades


class PositionPnLEngine:

    def __init__(self):
        self.open_trades = {}        # key = symbol
        self.completed_trades = []

    def add_trade(self, trade: Trade):
        symbol = trade.symbol

        # BUY opens a position (per symbol)
        if trade.side == "B":
            self.open_trades[symbol] = {
                "symbol": symbol,
                "buy_price": trade.price,
                "buy_qty": trade.qty,
                "open_qty": trade.qty,
                "buy_time": trade.time,
                "gross_pnl": 0.0,
                "charges": 0.0
            }

        # SELL reduces position
        elif trade.side == "S" and symbol in self.open_trades:
            pos = self.open_trades[symbol]
            matched_qty = min(trade.qty, pos["open_qty"])

            pnl = (trade.price - pos["buy_price"]) * matched_qty
            turnover = (trade.price + pos["buy_price"]) * matched_qty
            charges = ChargesCalculator.calculate(turnover, trade.segment)

            pos["gross_pnl"] += pnl
            pos["charges"] += charges
            pos["open_qty"] -= matched_qty

            # Position fully closed
            if pos["open_qty"] == 0:
                pos["net_pnl"] = round(pos["gross_pnl"] - pos["charges"], 2)
                pos["sell_time"] = trade.time
                pos["trade_date"] = trade.time.date()

                self.completed_trades.append(pos)
                del self.open_trades[symbol]
