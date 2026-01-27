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
        Using the new strategy: 9-Tick EMA, ROC, BB Width, and 2nd Tick Sequence.
        """
        if len(self.history) < 20:
            needed = 20 - len(self.history)
            return {"signal": f"WAITING ({needed} pts)", "ema": 0, "roc": 0, "bb_width": 0}

        prices = self.history['ltp'].astype(float)
        
        # 1. EMA (9) - Micro trend
        ema = ScalpingIndicator.calculate_ema(prices, 9).iloc[-1]
        
        # 2. Price Velocity (ROC 12)
        roc = ScalpingIndicator.calculate_roc(prices, 12).iloc[-1]
        
        # 3. BB Width (20, 2) - Filter sideways trap
        bb_width = ScalpingIndicator.calculate_bb_width(prices, 20, 2).iloc[-1]
        
        # 4. 2-Tick Sequence confirmation
        # Check direction of last 3 ticks (now, prev, prev2)
        p_now = prices.iloc[-1]
        p_prev = prices.iloc[-2]
        p_prev2 = prices.iloc[-3]
        
        up_seq = (p_now > p_prev > p_prev2)
        down_seq = (p_now < p_prev < p_prev2)
        
        # Logic thresholds
        # BB Width threshold: If width is too low (e.g., < 0.05% of price), it's sideways
        # We use a relative threshold (0.02% of current price as a base volatility filter)
        vol_threshold = p_now * 0.0002 
        is_volatile = bb_width > vol_threshold

        signal = "NEUTRAL"
        if is_volatile:
            if p_now > ema and roc > 0 and up_seq:
                signal = "BULLISH"
            elif p_now < ema and roc < 0 and down_seq:
                signal = "BEARISH"
        else:
            signal = "SIDEWAYS (TRAP)"
        
        return {
            "signal": signal,
            "ema": round(ema, 2),
            "roc": round(roc, 4),
            "bb_width": round(bb_width, 2),
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
        if os.path.exists(self.storage_file):
            try: os.remove(self.storage_file)
            except: pass
