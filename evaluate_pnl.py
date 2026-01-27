
import pandas as pd
import numpy as np
import json
import os

class ScalpingIndicator:
    @staticmethod
    def calculate_roc(prices, period=12):
        return prices.pct_change(periods=period) * 100
    @staticmethod
    def calculate_ema(prices, period=9):
        return prices.ewm(span=period, adjust=False).mean()
    @staticmethod
    def calculate_bb_width(prices, period=20, std_dev=2):
        sma = prices.rolling(window=period).mean()
        rstd = prices.rolling(window=period).std()
        upper = sma + (std_dev * rstd)
        lower = sma - (std_dev * rstd)
        return (upper - lower)

def simulate_and_evaluate(file_path, target=10, stop_loss=10):
    with open(file_path, 'r') as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df['ltp'] = df['ltp'].astype(float)
    prices = df['ltp']
    df['ema'] = ScalpingIndicator.calculate_ema(prices, 9)
    df['roc'] = ScalpingIndicator.calculate_roc(prices, 12)
    df['bb_width'] = ScalpingIndicator.calculate_bb_width(prices, 20, 2)
    
    results = []
    last_signal_idx = -100
    
    for i in range(20, len(df)):
        p_now = df.iloc[i]['ltp']
        p_prev = df.iloc[i-1]['ltp']
        p_prev2 = df.iloc[i-2]['ltp']
        ema = df.iloc[i]['ema']
        roc = df.iloc[i]['roc']
        bb_width = df.iloc[i]['bb_width']
        
        up_seq = (p_now > p_prev > p_prev2)
        down_seq = (p_now < p_prev < p_prev2)
        vol_threshold = p_now * 0.0002
        is_volatile = bb_width > vol_threshold
        
        sig = "NEUTRAL"
        if is_volatile:
            if p_now > ema and roc > 0 and up_seq:
                sig = "BULLISH"
            elif p_now < ema and roc < 0 and down_seq:
                sig = "BEARISH"
        
        # Take trade if signal present and not in cooldown (to avoid double counting same move)
        if sig in ["BULLISH", "BEARISH"] and (i - last_signal_idx > 12):
            last_signal_idx = i
            entry = p_now
            outcome = 0
            
            # Future window (next 60 ticks / 5 mins approx)
            future = df['ltp'].iloc[i+1:i+61]
            for f_val in future:
                if sig == "BULLISH":
                    if f_val >= entry + target:
                        outcome = target
                        break
                    if f_val <= entry - stop_loss:
                        outcome = -stop_loss
                        break
                else: # BEARISH
                    if f_val <= entry - target:
                        outcome = target
                        break
                    if f_val >= entry + stop_loss:
                        outcome = -stop_loss
                        break
            
            # If time expires, take current pnl
            if outcome == 0 and not future.empty:
                last_val = future.iloc[-1]
                outcome = (last_val - entry) if sig == "BULLISH" else (entry - last_val)
            
            results.append(outcome)
            
    return results

file = 'logs/NIFTY_50_2026-01-23.json'
results = simulate_and_evaluate(file, target=5, stop_loss=5) # Tight scalping
wins = sum(1 for r in results if r > 0)
losses = sum(1 for r in results if r < 0)
total_pnl = sum(results)

print(f"Strategy Simulation (Target 5, SL 5):")
print(f"Total Trades: {len(results)}")
print(f"Wins: {wins} | Losses: {losses}")
print(f"Win Rate: {(wins/len(results)*100):.1f}%" if results else "N/A")
print(f"Estimated Points Profit: {total_pnl:.2f}")
print(f"Estimated Cash Profit (1 lot/25 qty): {total_pnl * 25:.2f}")
