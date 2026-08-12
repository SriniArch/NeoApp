import pandas as pd
import numpy as np
from datetime import datetime
import os
import json
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """
    Abstract Base Class for all trading strategies.
    Any new strategy should inherit from this and implement 'get_signal'.
    """
    @abstractmethod
    def get_signal(self, history: pd.DataFrame) -> dict:
        pass

class ScalpingIndicator:
    """
    Utility class for common technical indicators used across strategies.
    """
    @staticmethod
    def calculate_momentum(prices: pd.Series, period: int = 14) -> pd.Series:
        if len(prices) < period:
            return pd.Series([np.nan] * len(prices))
        return prices.diff(period)

    @staticmethod
    def calculate_roc(prices: pd.Series, period: int = 12) -> pd.Series:
        if len(prices) < period:
            return pd.Series([np.nan] * len(prices))
        return prices.pct_change(periods=period) * 100

    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
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
        return prices.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_bb_width(prices: pd.Series, period: int = 20, std_dev: int = 2) -> pd.Series:
        sma = prices.rolling(window=period).mean()
        rstd = prices.rolling(window=period).std()
        upper = sma + (std_dev * rstd)
        lower = sma - (std_dev * rstd)
        return (upper - lower)

class ScalpingStrategyV1(BaseStrategy):
    """
    The default scalping strategy using EMA, ROC, and Bollinger Band expansion.
    """
    def get_signal(self, history: pd.DataFrame) -> dict:
        # Need at least 20 data points for calculations
        if len(history) < 20:
            needed = 20 - len(history)
            return {"signal": f"WAITING ({needed} pts)", "ema": 0, "roc": 0, "bb_width": 0, "rsi": 0, "momentum": 0, "pulse": False}

        prices = history['ltp'].astype(float)
        symbol = str(history['symbol'].iloc[-1]).upper()
        
        # 1. EMA (9)
        ema_series = ScalpingIndicator.calculate_ema(prices, 9)
        ema = ema_series.iloc[-1]
        
        # 2. ROC (18)
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
        
        # 4. RSI (14)
        rsi_series = ScalpingIndicator.calculate_rsi(prices, 14)
        rsi = rsi_series.iloc[-1]
        
        # 5. Momentum (14)
        momentum_series = ScalpingIndicator.calculate_momentum(prices, 14)
        momentum = momentum_series.iloc[-1]
        
        # Breakout Trigger: BBW expansion > 20% in one tick
        bb_expansion_pulse = bb_width > (prev_bbw * 1.2)
        
        # 4. Sequence
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
        if any(idx in symbol for idx in ["SENSEX", "BSX", "BANKEX"]):
            bbw_floor = 20.0
            roc_ceiling = 0.30 # Adjusted from 12.0 to be closer to NIFTY (relative to index price)
            
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
            "rsi": round(rsi, 2) if not np.isnan(rsi) else 0,
            "momentum": round(momentum, 2) if not np.isnan(momentum) else 0,
            "ltp": p_now,
            "pulse": bb_expansion_pulse,
            "exhausted": is_exhausted,
            "sideways": is_sideways,
            "trend": "UP" if up_seq else "DOWN" if down_seq else "FLAT"
        }

class RSIMomentumStrategy(BaseStrategy):
    """
    RSI and Momentum based strategy with Sustain Ticks.
    BULLISH: RSI > RSIM_RSI_UP and Momentum > RSIM_MOMENTUM for RSIM_SUSTAIN_TICKS
    BEARISH: RSI < RSIM_RSI_DOWN and Momentum < -RSIM_MOMENTUM for RSIM_SUSTAIN_TICKS
    """
    def get_signal(self, history: pd.DataFrame) -> dict:
        from common.config import RSIM_RSI_UP, RSIM_RSI_DOWN, RSIM_MOMENTUM, RSIM_SUSTAIN_TICKS

        if len(history) < 20: # Need at least 20 for BB Width
            needed = 20 - len(history)
            return {"signal": f"WAITING ({needed} pts)", "ema": 0, "roc": 0, "bb_width": 0, "rsi": 0, "momentum": 0, "pulse": False}

        prices = history['ltp'].astype(float)
        symbol = str(history['symbol'].iloc[-1]).upper()
        
        rsi_series = ScalpingIndicator.calculate_rsi(prices, 14)
        rsi = rsi_series.iloc[-1]
        
        momentum_series = ScalpingIndicator.calculate_momentum(prices, 14)
        momentum = momentum_series.iloc[-1]
        
        # Consistent Indicators for UI
        ema = ScalpingIndicator.calculate_ema(prices, 9).iloc[-1]
        roc = ScalpingIndicator.calculate_roc(prices, 18).iloc[-1]
        bb_width_series = ScalpingIndicator.calculate_bb_width(prices, 20, 2)
        bb_width = bb_width_series.iloc[-1]
        
        # Sideways / Exhausted logic
        bbw_floor = 12.0 # Default NIFTY
        roc_ceiling = 0.15 # Default NIFTY
        if any(idx in symbol for idx in ["SENSEX", "BSX", "BANKEX"]):
            bbw_floor = 20.0
            roc_ceiling = 0.30

        is_sideways = bb_width < bbw_floor
        is_exhausted = abs(roc) > roc_ceiling

        # Sustain logic (Check last N ticks)
        n = RSIM_SUSTAIN_TICKS
        num_bullish = 0
        num_bearish = 0
        
        # Check consecutive matches from newest to oldest
        for i in range(1, n + 1):
            if len(rsi_series) >= i:
                r = rsi_series.iloc[-i]
                m = momentum_series.iloc[-i]
                if not np.isnan(r) and not np.isnan(m):
                    if r > RSIM_RSI_UP and m > RSIM_MOMENTUM: num_bullish += 1
                    else: break
                else: break
        
        for i in range(1, n + 1):
            if len(rsi_series) >= i:
                r = rsi_series.iloc[-i]
                m = momentum_series.iloc[-i]
                if not np.isnan(r) and not np.isnan(m):
                    if r < RSIM_RSI_DOWN and m < -RSIM_MOMENTUM: num_bearish += 1
                    else: break
                else: break

        signal = "NEUTRAL"
        if num_bullish >= n:
            signal = "BULLISH"
        elif num_bearish >= n:
            signal = "BEARISH"
        elif num_bullish > 0:
            signal = f"CONFIRMING BULLISH ({num_bullish}/{n})"
        elif num_bearish > 0:
            signal = f"CONFIRMING BEARISH ({num_bearish}/{n})"
            
        return {
            "signal": signal,
            "ema": round(ema, 2),
            "roc": round(roc, 4),
            "bb_width": round(bb_width, 2),
            "rsi": round(rsi, 2) if not np.isnan(rsi) else 0,
            "momentum": round(momentum, 2) if not np.isnan(momentum) else 0,
            "ltp": prices.iloc[-1],
            "pulse": False,
            "exhausted": is_exhausted,
            "sideways": is_sideways,
            "trend": "UP" if momentum > 0 else "DOWN" if momentum < 0 else "FLAT"
        }

class LiveScalpingManager:
    """
    Manages live LTP data and delegates indicator calculations to a Strategy.
    """
    def __init__(self, strategy: BaseStrategy = None, max_history: int = 5000, storage_dir: str = "logs"):
        self.max_history = max_history
        self.storage_dir = storage_dir
        self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol'])
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.current_symbol = None
        self.storage_file = None
        # Default to V1 if no strategy provided
        self.strategy = strategy or ScalpingStrategyV1()
    
    def _update_storage_path(self, symbol: str, date_str: str):
        safe_symbol = symbol.replace(" ", "_").upper()
        self.storage_file = os.path.join(self.storage_dir, f"{safe_symbol}_{date_str}.csv")

    def add_ltp(self, ltp: float, symbol: str):
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        symbol = str(symbol).strip().upper()
        
        if symbol != self.current_symbol or today_str != self.current_date:
            self.current_symbol = symbol
            self.current_date = today_str
            self._update_storage_path(symbol, today_str)
            self.load_from_file()
            # If still empty or wrong symbol, re-init
            if self.history.empty or str(self.history.iloc[-1].get('symbol', '')).upper() != symbol:
                self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol', 'signal', 'ema', 'roc', 'bb_width', 'rsi', 'momentum', 'trend'])

        # 1. Temporarily add the row to calculate indicators
        new_row = {
            'timestamp': now.isoformat(), 
            'ltp': ltp, 
            'symbol': symbol
        }
        
        # We need a temp history to calculate the signal before permanently adding it
        temp_df = pd.concat([self.history, pd.DataFrame([new_row])], ignore_index=True)
        
        # 2. Calculate indicators for this new state
        try:
            indicators = self.strategy.get_signal(temp_df)
            # Add indicator results to our row
            new_row.update({
                'signal': indicators.get('signal'),
                'ema': indicators.get('ema'),
                'roc': indicators.get('roc'),
                'bb_width': indicators.get('bb_width'),
                'rsi': indicators.get('rsi'),
                'momentum': indicators.get('momentum'),
                'trend': indicators.get('trend'),
                'pulse': indicators.get('pulse'),
                'exhausted': indicators.get('exhausted'),
                'sideways': indicators.get('sideways')
            })
        except:
            pass # Fallback to LTP only if calculation fails

        # 3. Permanently add the enriched row
        self.history = pd.concat([self.history, pd.DataFrame([new_row])], ignore_index=True)
        
        if len(self.history) > self.max_history:
            self.history = self.history.iloc[-self.max_history:]
            
        self.save_to_file()
            
    def get_signal(self) -> dict:
        """Delegates calculation to the injected strategy."""
        return self.strategy.get_signal(self.history)

    def save_to_file(self):
        try:
            if self.storage_file:
                os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
                self.history.to_csv(self.storage_file, index=False)
        except: pass

    def load_from_file(self):
        if self.storage_file and os.path.exists(self.storage_file):
            try: 
                self.history = pd.read_csv(self.storage_file)
            except: 
                self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol', 'signal', 'ema', 'roc', 'bb_width', 'rsi', 'momentum', 'trend'])
        else:
            self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol', 'signal', 'ema', 'roc', 'bb_width', 'rsi', 'momentum', 'trend'])

    def reset(self):
        self.history = pd.DataFrame(columns=['timestamp', 'ltp', 'symbol'])
        if self.storage_file and os.path.exists(self.storage_file):
            try: os.remove(self.storage_file)
            except: pass

