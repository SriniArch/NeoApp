import pandas as pd
import numpy as np
from datetime import datetime
import os
import json

class ScalpingIndicator:
    """
    A collection of indicators specialized for scalping, 
    focusing on momentum and trend strength.
    """
    
    @staticmethod
    def calculate_momentum(prices: pd.Series, period: int = 14) -> pd.Series:
        """
        Calculates the Momentum Indicator.
        Momentum = current price - price n periods ago.
        """
        if len(prices) < period:
            return pd.Series([np.nan] * len(prices))
        
        return prices.diff(period)

    @staticmethod
    def calculate_roc(prices: pd.Series, period: int = 12) -> pd.Series:
        """
        Calculates the Rate of Change (ROC).
        ROC = ((current price / price n periods ago) - 1) * 100.
        """
        if len(prices) < period:
            return pd.Series([np.nan] * len(prices))
        
        return prices.pct_change(periods=period) * 100

    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculates the Relative Strength Index (RSI)."""
        if len(prices) < period:
            return pd.Series([np.nan] * len(prices))
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def calculate_ema(prices: pd.Series, period: int = 9) -> pd.Series:
        """Calculates Exponential Moving Average."""
        return prices.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_bb_width(prices: pd.Series, period: int = 20, std_dev: int = 2) -> pd.Series:
        """Calculates Bollinger Band Width."""
        sma = prices.rolling(window=period).mean()
        rstd = prices.rolling(window=period).std()
        upper = sma + (std_dev * rstd)
        lower = sma - (std_dev * rstd)
        return (upper - lower)

class LiveScalpingManager:
    """
    Manages live LTP data and calculates indicators in real-time.
    Supports persistence to avoid cold starts on restart.
    """
    def __init__(self, max_history: int = 5000, storage_dir: str = "logs"):
        self.max_history = max_history
        self.storage_dir = storage_dir
        self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol'])
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.current_symbol = None
        self.storage_file = None
    
    def _update_storage_path(self, symbol: str, date_str: str):
        """Generates sanitized filename: logs/SYMBOL_YYYY-MM-DD.json"""
        safe_symbol = symbol.replace(" ", "_").upper()
        self.storage_file = os.path.join(self.storage_dir, f"{safe_symbol}_{date_str}.json")

    def add_ltp(self, ltp: float, symbol: str):
        """Append new LTP, maintain history size and save."""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        symbol = str(symbol).strip().upper()
        
        # Check if we need to switch files (Symbol change or Date change)
        if symbol != self.current_symbol or today_str != self.current_date:
            self.current_symbol = symbol
            self.current_date = today_str
            self._update_storage_path(symbol, today_str)
            
            # Load existing history for this specific symbol/day if it exists
            self.load_from_file()
            
            # If still empty after load (new file), create empty DF
            if self.history.empty or self.history.iloc[-1]['symbol'] != symbol:
                self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol'])

        new_row = {'timestamp': now.isoformat(), 'ltp': ltp, 'symbol': symbol}
        self.history = pd.concat([self.history, pd.DataFrame([new_row])], ignore_index=True)
        
        if len(self.history) > self.max_history:
            self.history = self.history.iloc[-self.max_history:]
        
        self.save_to_file()
            
    def get_signal(self) -> dict:
        """
        Calculate indicators on current history and return signal + values.
        Enhanced strategy: EMA, ROC (rising, 30-period), BB Width > 15.0, 7-tick sequence.
        """
        # Need at least 30 data points for ROC(30)
        if len(self.history) < 30:
            needed = 30 - len(self.history)
            return {"signal": f"WAITING ({needed} pts)", "ema": 0, "roc": 0, "bb_width": 0, "roc_rising": False}

        prices = self.history['ltp'].astype(float)
        
        # 1. EMA (9)
        ema_series = ScalpingIndicator.calculate_ema(prices, 9)
        ema = ema_series.iloc[-1]
        
        # 2. ROC (30) - Extended period for smoother trend detection
        roc_series = ScalpingIndicator.calculate_roc(prices, 30)
        roc = roc_series.iloc[-1]
        
        # Check if ROC is trending up over last 3 ticks (relaxed from 5 strict)
        roc_rising = False
        if len(roc_series) >= 3:
            r_vals = roc_series.iloc[-3:].tolist()
            roc_rising = r_vals[-1] > r_vals[0] and r_vals[-1] > 0
        
        # 3. BB Width (20, 2)
        bb_width_series = ScalpingIndicator.calculate_bb_width(prices, 20, 2)
        bb_width = bb_width_series.iloc[-1]
        
        # 4. Sequence - Relaxed to 4 ticks and allows equality as long as net gain
        if len(prices) >= 4:
            last_4 = prices.iloc[-4:].tolist()
            up_seq = all(last_4[i] <= last_4[i+1] for i in range(len(last_4)-1)) and last_4[-1] > last_4[0]
            down_seq = all(last_4[i] >= last_4[i+1] for i in range(len(last_4)-1)) and last_4[-1] < last_4[0]
        else:
            up_seq = False
            down_seq = False
        
        # Strategy Logic: BBW > 10.0 (Relaxed from 15.0), ROC exhaustion filter
        is_volatile = bb_width > 10.0
        roc_exhausted = abs(roc) > 10.0  # Avoid buying at spike peaks

        p_now = prices.iloc[-1]
        signal = "NEUTRAL"
        if is_volatile and not roc_exhausted:
            if p_now > ema and roc > 0 and roc_rising and up_seq:
                signal = "BULLISH"
            elif p_now < ema and roc < 0 and not roc_rising and down_seq: # Falling ROC for bearish
                signal = "BEARISH"
        elif roc_exhausted:
            signal = "EXHAUSTED (ROC TOO HIGH)"
        else:
            signal = f"SIDEWAYS (BBW {round(bb_width, 1)} < 10.0)"
        
        return {
            "signal": signal,
            "ema": round(ema, 2),
            "roc": round(roc, 4),
            "roc_rising": roc_rising,
            "bb_width": round(bb_width, 2),
            "ltp": p_now,
            "trend": "UP" if up_seq else "DOWN" if down_seq else "FLAT"
        }

    def save_to_file(self):
        """Save history to local JSON file."""
        try:
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            self.history.to_json(self.storage_file, orient='records')
        except:
            pass

    def load_from_file(self):
        """Load history from local JSON file."""
        if self.storage_file and os.path.exists(self.storage_file):
            try:
                self.history = pd.read_json(self.storage_file)
            except:
                self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol'])
        else:
            self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol'])

    def reset(self):
        """Clear history."""
        self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol'])
        if self.storage_file and os.path.exists(self.storage_file):
            try: os.remove(self.storage_file)
            except: pass
