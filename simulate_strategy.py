
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

def simulate_strategy(file_path):
    if not os.path.exists(file_path):
        print(f"File {file_path} not found")
        return

    with open(file_path, 'r') as f:
        data = json.load(f)
    
    df = pd.DataFrame(data)
    df['ltp'] = df['ltp'].astype(float)
    
    prices = df['ltp']
    df['ema'] = ScalpingIndicator.calculate_ema(prices, 9)
    df['roc'] = ScalpingIndicator.calculate_roc(prices, 12)
    df['bb_width'] = ScalpingIndicator.calculate_bb_width(prices, 20, 2)
    
    signals = []
    
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
        else:
            sig = "SIDEWAYS"
            
        if sig in ["BULLISH", "BEARISH"]:
            signals.append({
                "index": i,
                "timestamp": df.iloc[i]['timestamp'],
                "ltp": p_now,
                "signal": sig
            })
            
    return signals, df

signals, df = simulate_strategy('logs/NIFTY_50_2026-01-23.json')

if signals:
    print(f"Total Signals Found: {len(signals)}")
    # Simplify by grouping continuous signals
    distinct_signals = []
    if signals:
        last_sig = signals[0]
        distinct_signals.append(last_sig)
        for s in signals[1:]:
            if s['signal'] != last_sig['signal'] or (s['index'] - last_sig['index'] > 5):
                distinct_signals.append(s)
                last_sig = s
    
    print("\nDistinct Trades Simulated:")
    for s in distinct_signals:
        # Look ahead for outcome (rough estimate: next 12 ticks / 1 min)
        idx = s['index']
        entry_price = s['ltp']
        max_favorable = 0
        max_adverse = 0
        
        future_prices = df['ltp'].iloc[idx+1:idx+13]
        if not future_prices.empty:
            if s['signal'] == "BULLISH":
                max_favorable = future_prices.max() - entry_price
                max_adverse = entry_price - future_prices.min()
            else:
                max_favorable = entry_price - future_prices.min()
                max_adverse = future_prices.max() - entry_price
                
        print(f"Time: {s['timestamp']} | Sig: {s['signal']} | Price: {entry_price} | Max Gain: {max_favorable:.2f} | Max Drawdown: {max_adverse:.2f}")
else:
    print("No Allowed to Trade signals found in the history.")
