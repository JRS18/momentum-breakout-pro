# -*- coding: utf-8 -*-
"""
Estrategia Momentum Breakout - Swing Trading
Entra en tendencias fuertes, se queda con trailing stops amplios
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class SignalType(Enum):
    BUY = "COMPRA"
    SELL = "VENTA"
    HOLD = "MANTENER"


@dataclass
class Signal:
    ticker: str
    signal_type: SignalType
    date: datetime
    price: float
    reason: str
    stop_loss: float = 0.0
    take_profit: float = 0.0
    atr: float = 0.0
    confidence: float = 0.0


class MomentumBreakoutStrategy:
    """
    Trend-following con breakout de volumen.
    
    Entrada: Precio cruza EMA21 + RSI > 50 + MACD positivo + volumen surge
    Salida: Trailing stop 3x ATR + take profit 4x riesgo
    """

    def __init__(self, config: dict):
        self.config = config

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        c = df['Close']

        # EMAs
        df['EMA_8'] = c.ewm(span=8, adjust=False).mean()
        df['EMA_21'] = c.ewm(span=21, adjust=False).mean()
        df['EMA_50'] = c.ewm(span=50, adjust=False).mean()
        df['EMA_200'] = c.ewm(span=200, adjust=False).mean()

        # ATR
        hl = df['High'] - df['Low']
        hc = np.abs(df['High'] - df['Close'].shift())
        lc = np.abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(window=14).mean()

        # RSI
        delta = c.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['RSI'] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

        # Volume
        df['Vol_MA'] = df['Volume'].rolling(window=20).mean()
        df['Vol_Ratio'] = df['Volume'] / (df['Vol_MA'] + 1)

        # Breakout levels
        df['High_20'] = df['High'].rolling(window=20).max()
        df['Low_20'] = df['Low'].rolling(window=20).min()

        # Momentum
        df['ROC_10'] = c.pct_change(periods=10) * 100

        # Trend strength
        df['Trend_Score'] = (
            (c > df['EMA_8']).astype(int) +
            (c > df['EMA_21']).astype(int) +
            (c > df['EMA_50']).astype(int) +
            (c > df['EMA_200']).astype(int)
        )

        return df

    def generate_signal(self, df: pd.DataFrame, ticker: str,
                        position: Optional[Dict] = None) -> Optional[Signal]:
        if len(df) < 210:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        date = df.index[-1]

        if position is None:
            return self._check_entry(df, last, prev, ticker, date)
        else:
            return self._check_exit(df, last, ticker, date, position)

    def _check_entry(self, df, last, prev, ticker, date) -> Optional[Signal]:
        c = self.config

        # Filtro 1: Tendencia alcista (dos caminos)
        trend_up = (last['Close'] > last['EMA_50'] and last['EMA_50'] > last['EMA_200']) or \
                   (last['Close'] > last['EMA_21'] and last['EMA_21'] > last['EMA_50'] and last['Trend_Score'] >= 3)
        if not trend_up:
            return None

        # Filtro 2: RSI
        if last['RSI'] > 80 or last['RSI'] < 35:
            return None

        # Filtro 3: MACD positivo y acelerando
        if last['MACD_Hist'] <= 0:
            return None
        if prev['MACD_Hist'] > 0 and last['MACD_Hist'] < prev['MACD_Hist']:
            return None

        # Filtro 4: Precio sobre EMA8
        if last['Close'] <= last['EMA_8']:
            return None

        # Filtro 5: Volumen
        if last['Vol_Ratio'] < 1.0:
            return None

        # Filtro 6: Trend score >= 3
        if last['Trend_Score'] < 3:
            return None

        # Stops
        atr = last['ATR']
        stop = last['Close'] - (atr * c.get('atr_stop_mult', 2.5))
        risk = last['Close'] - stop
        tp = last['Close'] + (risk * c.get('tp_ratio', 3.0))

        reason = (f"TREND BREAK | Close: {last['Close']:.2f} > EMA21: {last['EMA_21']:.2f} | "
                  f"RSI: {last['RSI']:.1f} | MACD: {last['MACD_Hist']:.4f} | "
                  f"Vol: {last['Vol_Ratio']:.1f}x | TrendScore: {last['Trend_Score']}")

        return Signal(
            ticker=ticker, signal_type=SignalType.BUY,
            date=date, price=last['Close'], reason=reason,
            stop_loss=stop, take_profit=tp, atr=atr
        )

    def _check_exit(self, df, last, ticker, date, position) -> Optional[Signal]:
        entry_price = position['entry_price']
        entry_atr = position.get('entry_atr', last['ATR'])

        # Trailing stop
        current_atr = last['ATR']
        new_stop = last['Close'] - (current_atr * self.config.get('atr_trail_mult', 3.0))
        current_stop = max(position.get('current_stop', 0), new_stop)

        # Take profit
        tp = position.get('take_profit', float('inf'))

        stop_hit = last['Close'] < current_stop
        tp_hit = last['Close'] >= tp

        # RSI de reversal extremo
        rsi_reversal = last['RSI'] < 25 and last['MACD_Hist'] < 0

        if stop_hit or tp_hit or rsi_reversal:
            if tp_hit:
                reason = f"TAKE PROFIT | Close: {last['Close']:.2f} | Entry: {entry_price:.2f}"
            elif stop_hit:
                reason = f"TRAILING STOP | Close: {last['Close']:.2f} | Stop: {current_stop:.2f}"
            else:
                reason = f"RSI REVERSAL | RSI: {last['RSI']:.1f} | MACD: {last['MACD_Hist']:.4f}"

            return Signal(
                ticker=ticker, signal_type=SignalType.SELL,
                date=date, price=last['Close'], reason=reason, atr=last['ATR']
            )

        # Actualizar trailing stop en position
        position['current_stop'] = current_stop
        position['take_profit'] = tp

        return None
