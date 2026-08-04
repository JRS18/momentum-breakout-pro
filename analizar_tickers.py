# -*- coding: utf-8 -*-
"""Analiza las características de los tickers originales vs el resto."""
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime

TICKERS_ORIGINALES = ['RIOT', 'AMD', 'GOOGL', 'NVDA', 'CRWD', 'AMC', 'MRNA', 'META', 'BB', 'PLTR', 'NET']
TICKERS_TODOS = [
    'NVDA', 'AMD', 'GOOGL', 'META', 'CRWD', 'PLTR', 'NET', 'AAPL', 'MSFT', 'AMZN',
    'TSLA', 'SNOW', 'DDOG', 'MDB', 'RIOT', 'MARA', 'COIN', 'AMC', 'BB', 'MRNA',
    'PFE', 'JNJ', 'UNH', 'V', 'MA', 'JPM', 'NKE', 'SBUX', 'MELI', 'SPOT', 'ABNB', 'UBER',
]

START = '2016-01-01'
END = '2025-12-31'

resultados = []

for t in TICKERS_TODOS:
    try:
        data = yf.download(t, start=START, end=END, progress=False, auto_adjust=True)
        if data.columns.nlevels > 1:
            data.columns = data.columns.get_level_values(0)
        if data.empty or len(data) < 250:
            continue

        close = data['Close'].values.flatten()
        high = data['High'].values.flatten()
        low = data['Low'].values.flatten()
        volume = data['Volume'].values.flatten()

        # CAGR total
        n_years = len(close) / 252
        cagr = ((close[-1] / close[0]) ** (1/n_years) - 1) * 100

        # Max Drawdown
        peak = close[0]
        max_dd = 0
        for c in close:
            if c > peak:
                peak = c
            dd = (peak - c) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # ATR %
        tr = np.maximum(high - low,
                        np.maximum(np.abs(high - np.roll(close, 1)),
                                   np.abs(low - np.roll(close, 1))))
        atr14 = pd.Series(tr).rolling(14).mean().values
        atr_pct_60 = np.nanmean(atr14[-60:] / close[-60:]) * 100
        atr_pct_252 = np.nanmean(atr14[-252:] / close[-252:]) * 100

        # Volatilidad anualizada (últimos 60d)
        returns = np.diff(close) / close[:-1]
        volat_60 = np.std(returns[-60:]) * np.sqrt(252) * 100
        volat_252 = np.std(returns[-252:]) * np.sqrt(252) * 100

        # Momentum
        mom20 = (close[-1] / close[-20] - 1) * 100
        mom60 = (close[-1] / close[-60] - 1) * 100
        mom120 = (close[-1] / close[-120] - 1) * 100

        # Promedio de ATR histórico (más importante que el actual)
        atr_historico = []
        for i in range(252, len(close)):
            window = close[i-252:i]
            h_window = high[i-252:i]
            l_window = low[i-252:i]
            tr_w = np.maximum(h_window - l_window,
                              np.maximum(np.abs(h_window - np.roll(window, 1)),
                                         np.abs(l_window - np.roll(window, 1))))
            atr_w = np.nanmean(tr_w[14:] / window[14:]) * 100
            atr_historico.append(atr_w)
        avg_atr_historico = np.mean(atr_historico) if atr_historico else 0

        # Volumen promedio
        avg_vol = np.mean(volume[-60:])

        # Número de veces que ATR% > 3% en los últimos 252 días
        high_vol_days = 0
        for i in range(-252, 0):
            if atr_pct_60 > 3:
                high_vol_days += 1

        es_orig = t in TICKERS_ORIGINALES

        resultados.append({
            'ticker': t, 'cagr': cagr, 'max_dd': max_dd,
            'atr_pct_60': atr_pct_60, 'atr_pct_252': atr_pct_252,
            'atr_historico': avg_atr_historico,
            'volat_60': volat_60, 'volat_252': volat_252,
            'mom20': mom20, 'mom60': mom60, 'mom120': mom120,
            'avg_vol': avg_vol,
            'es_orig': es_orig,
        })
    except Exception as e:
        pass

# Imprimir tabla ordenada por CAGR
resultados.sort(key=lambda x: x['cagr'], reverse=True)

print('=' * 110)
header = f"{'Ticker':>8} | {'CAGR%':>7} | {'MaxDD%':>7} | {'ATR60%':>7} | {'ATR252%':>8} | {'ATRh%':>7} | {'Vol60%':>7} | {'Vol252%':>8} | {'Mom20%':>7} | {'Mom60%':>7} | {'Mom120%':>8} | {'Orig':>5}"
print(header)
print('=' * 110)
for r in resultados:
    orig = '***' if r['es_orig'] else ''
    line = f"{r['ticker']:>8} | {r['cagr']:6.1f}% | {r['max_dd']:6.1f}% | {r['atr_pct_60']:6.1f}% | {r['atr_pct_252']:7.1f}% | {r['atr_historico']:6.1f}% | {r['volat_60']:6.1f}% | {r['volat_252']:7.1f}% | {r['mom20']:6.1f}% | {r['mom60']:6.1f}% | {r['mom120']:7.1f}% | {orig:>5}"
    print(line)
print('=' * 110)

# Estadísticas comparativas
orig = [r for r in resultados if r['es_orig']]
no_orig = [r for r in resultados if not r['es_orig']]

print(f"\n{'='*60}")
print("  COMPARACION: ORIGINALES vs RESTO")
print(f"{'='*60}")
for metric, key in [('ATR% (60d)', 'atr_pct_60'), ('ATR% (252d)', 'atr_pct_252'),
                     ('ATR% Historico', 'atr_historico'), ('Volatilidad 60d', 'volat_60'),
                     ('Volatilidad 252d', 'volat_252'), ('CAGR', 'cagr'), ('MaxDD', 'max_dd'),
                     ('Mom20', 'mom20'), ('Mom60', 'mom60'), ('Mom120', 'mom120')]:
    v_orig = np.mean([r[key] for r in orig])
    v_no = np.mean([r[key] for r in no_orig])
    diff = v_orig - v_no
    print(f"  {metric:>20}: Orig={v_orig:6.1f}  Resto={v_no:6.1f}  Diff={diff:+6.1f}")

# Ranking ATR histórico
print(f"\n{'='*60}")
print("  TOP 11 POR ATR% HISTORICO")
print(f"{'='*60}")
by_atr = sorted(resultados, key=lambda x: x['atr_historico'], reverse=True)
for i, r in enumerate(by_atr[:11], 1):
    orig = '***' if r['es_orig'] else ''
    print(f"  {i:2d}. {r['ticker']:>6} ATRh={r['atr_historico']:5.1f}% CAGR={r['cagr']:6.1f}% {orig}")

# Ranking ATR * CAGR (mejor risk/reward)
print(f"\n{'='*60}")
print("  TOP 11 POR ATR_H * CAGR (risk/reward)")
print(f"{'='*60}")
by_atr_cagr = sorted(resultados, key=lambda x: x['atr_historico'] * max(x['cagr'], 0), reverse=True)
for i, r in enumerate(by_atr_cagr[:11], 1):
    orig = '***' if r['es_orig'] else ''
    score = r['atr_historico'] * max(r['cagr'], 0)
    print(f"  {i:2d}. {r['ticker']:>6} Score={score:7.0f} ATRh={r['atr_historico']:5.1f}% CAGR={r['cagr']:6.1f}% {orig}")
