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
        Enhanced strategy: EMA, ROC (18-period), BB Expansion (>20%), 
        Floor Thresh (NIFTY 12.0, SENSEX 20.0)
        """
        # Need at least 20 data points for calculations
        if len(self.history) < 20:
            needed = 20 - len(self.history)
            return {"signal": f"WAITING ({needed} pts)", "ema": 0, "roc": 0, "bb_width": 0, "pulse": False}

        prices = self.history['ltp'].astype(float)
        symbol = str(self.history['symbol'].iloc[-1]).upper()
        
        # 1. EMA (9)
        ema_series = ScalpingIndicator.calculate_ema(prices, 9)
        ema = ema_series.iloc[-1]
        
        # 2. ROC (18) - Faster response to micro-trends
        roc_series = ScalpingIndicator.calculate_roc(prices, 18)
        roc = roc_series.iloc[-1]
        
        # Check if ROC is trending up over last 2 ticks
        roc_rising = False
        if len(roc_series) >= 2:
            roc_rising = roc_series.iloc[-1] > roc_series.iloc[-2] and roc_series.iloc[-1] > 0
        
        # 3. BB Width (20, 2)
        bb_width_series = ScalpingIndicator.calculate_bb_width(prices, 20, 2)
        bb_width = bb_width_series.iloc[-1]
        prev_bbw = bb_width_series.iloc[-2] if len(bb_width_series) > 1 else bb_width
        
        # Breakout Trigger: BBW expansion > 20% in one tick
        bb_expansion_pulse = bb_width > (prev_bbw * 1.2)
        
        # 4. Sequence - Reduced to 2-3 ticks for faster entry
        if len(prices) >= 2:
            last_2 = prices.iloc[-2:].tolist()
            up_seq_2 = last_2[-1] > last_2[0]
            down_seq_2 = last_2[-1] < last_2[0]
            
            up_seq_3 = False
            down_seq_3 = False
            if len(prices) >= 3:
                last_3 = prices.iloc[-3:].tolist()
                up_seq_3 = all(last_3[i] <= last_3[i+1] for i in range(len(last_3)-1)) and last_3[-1] > last_3[0]
                down_seq_3 = all(last_3[i] >= last_3[i+1] for i in range(len(last_3)-1)) and last_3[-1] < last_3[0]
                
            up_seq = up_seq_3 or up_seq_2
            down_seq = down_seq_3 or down_seq_2
        else:
            up_seq = False
            down_seq = False
        
        # Floor Thresholds
        bbw_floor = 12.0 # Default NIFTY
        roc_ceiling = 0.15 # Default NIFTY
        if "SENSEX" in symbol or "BSX" in symbol or "BANKEX" in symbol:
            bbw_floor = 20.0
            roc_ceiling = 12.0
            
        is_sideways = bb_width < bbw_floor
        is_exhausted = abs(roc) > roc_ceiling

        p_now = prices.iloc[-1]
        signal = "NEUTRAL"
        
        if is_exhausted:
            signal = "EXHAUSTED (ROC CEILING)"
        elif is_sideways:
            signal = f"SIDEWAYS (BBW {round(bb_width, 1)} < {bbw_floor})"
        elif bb_expansion_pulse:
            if p_now > ema and roc > 0 and up_seq:
                signal = "BULLISH"
            elif p_now < ema and roc < 0 and down_seq:
                signal = "BEARISH"
        
        return {
            "signal": signal,
            "ema": round(ema, 2),
            "roc": round(roc, 4),
            "roc_rising": roc_rising,
            "bb_width": round(bb_width, 2),
            "ltp": p_now,
            "pulse": bb_expansion_pulse,
            "exhausted": is_exhausted,
            "sideways": is_sideways,
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
