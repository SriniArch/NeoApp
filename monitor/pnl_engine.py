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
        raw_status = str(o.get("ordSt", ""))
        status = raw_status.lower()
        if status not in ["complete", "completed", "filled"]:
            continue

        # Try multiple price keys for BSE/SENSEX compatibility
        avg_price = float(o.get("avgPrc") or o.get("buyAvgPrc") or o.get("sellAvgPrc") or 0)
        
        # Fallback: Calculate from Amount and Qty
        if avg_price == 0:
            try:
                amt = float(o.get("buyAmt") or o.get("sellAmt") or 0)
                # Use filled qty primarily for price calculation if avgPrc is 0
                f_qty = float(o.get("flQty") or o.get("flBuyQty") or o.get("flSellQty") or o.get("qty") or 0)
                if f_qty > 0: avg_price = amt / f_qty
            except: pass

        if avg_price == 0:
            continue

        # Flexible Timestamp Parsing
        trade_time = datetime.now()
        # BSE often uses hsUpTm or updRecvTm
        ts_raw = str(o.get("exCfmTm", "") or o.get("ordTm", "") or o.get("updRecvTm", "") or o.get("hsUpTm", ""))
        if ts_raw:
            ts = ' '.join(ts_raw.split())
            # FIX: Corrected %Y/%m/%d format
            formats = ["%d-%b-%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"]
            for fmt in formats:
                try:
                    trade_time = datetime.strptime(ts, fmt)
                    break
                except: continue

        # Normalize side to B / S
        side = str(o.get("trnsTp", "")).upper()
        if "BUY" in side or side == "B": side = "B"
        elif "SELL" in side or side == "S": side = "S"
        else: side = side[0] if side else "B" # Fallback to first char

        # Quantity: Prefer filled quantity (flQty) for completed trades
        q_val = o.get("flQty") or o.get("qty") or o.get("flBuyQty") or o.get("flSellQty") or 0
        try:
            qty = int(float(str(q_val)))
        except:
            qty = 0

        if qty == 0:
            continue

        trade = Trade(
            symbol=str(o.get("trdSym", "")).strip().upper(),
            side=side,
            qty=qty,
            price=avg_price,
            time=trade_time,
            product=str(o.get("prod", "MIS")),
            segment=str(o.get("exSeg", ""))
        )
        trades.append(trade)
        print(f"DEBUG: Parsed Trade - {trade.side} {trade.qty} {trade.symbol} @ {trade.price} ({trade.time})")
    return trades


class PositionPnLEngine:

    def __init__(self):
        self.open_trades = defaultdict(deque)        # key = symbol, value = deque of open positions
        self.completed_trades = []

    def add_trade(self, trade: Trade):
        symbol = trade.symbol.strip().upper()

        # BUY opens or adds to a position (per symbol)
        if trade.side == "B":
            self.open_trades[symbol].append({
                "symbol": symbol,
                "buy_price": trade.price,
                "buy_qty": trade.qty,
                "open_qty": trade.qty,
                "buy_time": trade.time,
                "gross_pnl": 0.0,
                "charges": 0.0
            })

        # SELL reduces position using FIFO
        elif trade.side == "S" and self.open_trades.get(symbol):
            sell_qty = trade.qty
            
            while sell_qty > 0 and self.open_trades[symbol]:
                pos = self.open_trades[symbol][0]
                matched_qty = min(sell_qty, pos["open_qty"])

                pnl = (trade.price - pos["buy_price"]) * matched_qty
                turnover = (trade.price + pos["buy_price"]) * matched_qty
                charges = ChargesCalculator.calculate(turnover, trade.segment)

                pos["gross_pnl"] += pnl
                pos["charges"] += charges
                pos["open_qty"] -= matched_qty
                sell_qty -= matched_qty

                # Position fully closed for this buy lot
                if pos["open_qty"] == 0:
                    pos["net_pnl"] = round(pos["gross_pnl"] - pos["charges"], 2)
                    pos["sell_price"] = trade.price
                    pos["sell_time"] = trade.time
                    pos["trade_date"] = trade.time.date()

                    self.completed_trades.append(pos)
                    self.open_trades[symbol].popleft()
                    print(f"DEBUG: Trade Completed - {symbol} PnL: {pos['net_pnl']}")
            
            if not self.open_trades[symbol]:
                del self.open_trades[symbol]

    def hourly_summary(self, for_date=None) -> Dict[str, int]:
        """
        Return a dict of hourly trade counts for the given date.
        Keys are labeled like '09:00-10:00'. If `for_date` is None,
        uses today's date.
        """
        counts = defaultdict(int)

        if for_date is None:
            for_date = datetime.now().date()

        for t in self.completed_trades:
            st = t.get("sell_time")
            if not st:
                continue
            if st.date() != for_date:
                continue
            counts[st.hour] += 1

        # Build labeled dict for all 24 hours
        hourly = {}
        for h in range(24):
            label = f"{h:02d}:00-{(h+1)%24:02d}:00"
            hourly[label] = counts.get(h, 0)

        return hourly

    def trading_hours_summary(self, start_time="09:15", end_time="15:30", slot_minutes=60, for_date=None) -> Dict:
        """
        Compute trade counts for consecutive slots between `start_time` and `end_time`.
        Default trading window is 09:15 to 15:30. Slots are `slot_minutes` long.

        Returns a dict with:
          - 'slots': Ordered dict label -> count (labels like '09:15-10:15')
          - 'total_trades': int
          - 'total_hours': float (hours)
          - 'avg_per_hour': float
        """
        from datetime import datetime, date, time, timedelta
        from collections import OrderedDict

        if for_date is None:
            for_date = datetime.now().date()

        # parse start/end times
        sh, sm = map(int, start_time.split(":"))
        eh, em = map(int, end_time.split(":"))

        start_dt = datetime.combine(for_date, time(sh, sm))
        end_dt = datetime.combine(for_date, time(eh, em))

        # Build slots
        slots = OrderedDict()
        cur = start_dt
        delta = timedelta(minutes=slot_minutes)
        while cur < end_dt:
            nxt = min(cur + delta, end_dt)
            label = f"{cur.strftime('%H:%M')}-{nxt.strftime('%H:%M')}"
            slots[label] = 0
            cur = nxt

        total = 0
        for t in self.completed_trades:
            st = t.get("sell_time")
            if not st:
                continue
            if st.date() != for_date:
                continue

            # find slot
            for label in slots:
                parts = label.split("-")
                s_part = datetime.combine(for_date, datetime.strptime(parts[0], "%H:%M").time())
                e_part = datetime.combine(for_date, datetime.strptime(parts[1], "%H:%M").time())
                if s_part <= st < e_part:
                    slots[label] += 1
                    total += 1
                    break

        total_hours = (end_dt - start_dt).total_seconds() / 3600.0
        avg_per_hour = round((total / total_hours) if total_hours > 0 else 0.0, 2)

        return {
            "slots": slots,
            "total_trades": total,
            "total_hours": round(total_hours, 2),
            "avg_per_hour": avg_per_hour
        }
