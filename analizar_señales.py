# -*- coding: utf-8 -*-
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

tickers = ['NBIS', 'RGTI', 'IREN', 'RIOT', 'HUT', 'UPST', 'ALAB', 'PLTR']

end = datetime.now()
start = end - timedelta(days=400)

print("=" * 80)
print("  ANALISIS DE TICKERS - CUAL ESTA CERCA DE COMPRA?")
print("=" * 80)

for t in tickers:
    try:
        df = yf.download(t, start=start.strftime('%Y-%m-%d'), end=end.strftime('%Y-%m-%d'), progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df['EMA_8'] = df['Close'].ewm(span=8, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
        
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        
        df['Vol_Avg'] = df['Volume'].rolling(20).mean()
        df['Vol_Ratio'] = df['Volume'] / df['Vol_Avg']
        
        df['Trend_Score'] = 0
        df.loc[df['Close'] > df['EMA_50'], 'Trend_Score'] += 1
        df.loc[df['EMA_50'] > df['EMA_200'], 'Trend_Score'] += 1
        df.loc[df['Close'] > df['EMA_8'], 'Trend_Score'] += 1
        df.loc[df['RSI'] > 50, 'Trend_Score'] += 1
        df.loc[df['MACD_Hist'] > 0, 'Trend_Score'] += 1
        
        last = df.iloc[-1]
        precio = float(last['Close'])
        
        c1 = precio > float(last['EMA_50'])
        c2 = float(last['EMA_50']) > float(last['EMA_200'])
        c3 = 35 < float(last['RSI']) < 80
        c4 = float(last['MACD_Hist']) > 0
        c5 = precio > float(last['EMA_8'])
        c6 = float(last['Vol_Ratio']) >= 1.0
        c7 = int(last['Trend_Score']) >= 3
        
        cumulative = c1 + c2 + c3 + c4 + c5 + c6 + c7
        
        if cumulative == 7:
            status = "LISTO PARA COMPRA"
        elif cumulative >= 5:
            status = "CERCA"
        else:
            status = "LEJOS"
        
        ok = "[OK]"
        fail = "[--]"
        
        print("")
        print(f"  {t:6s} | ${precio:.2f} | Score: {cumulative}/7 | {status}")
        print(f"    Close>EMA50:  {ok if c1 else fail}  ${precio:.2f} vs ${float(last['EMA_50']):.2f}")
        print(f"    EMA50>EMA200: {ok if c2 else fail}  ${float(last['EMA_50']):.2f} vs ${float(last['EMA_200']):.2f}")
        print(f"    RSI 35-80:    {ok if c3 else fail}  RSI={float(last['RSI']):.1f}")
        print(f"    MACD>0:       {ok if c4 else fail}  MACD_Hist={float(last['MACD_Hist']):.4f}")
        print(f"    Close>EMA8:   {ok if c5 else fail}  ${precio:.2f} vs ${float(last['EMA_8']):.2f}")
        print(f"    Volumen>1x:   {ok if c6 else fail}  Vol={float(last['Vol_Ratio']):.2f}x")
        print(f"    Trend>=3:     {ok if c7 else fail}  Score={int(last['Trend_Score'])}/5")
    except Exception as e:
        print(f"\n  {t}: ERROR - {e}")
