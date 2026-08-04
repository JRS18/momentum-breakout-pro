# -*- coding: utf-8 -*-
"""
Busca el mejor scoring que seleccione los 11 tickers originales.
Prueba diferentes combinaciones de criterios.
"""
import yfinance as yf
import numpy as np
import pandas as pd
from itertools import combinations
from datetime import datetime

TICKERS_ORIGINALES = set(['RIOT', 'AMD', 'GOOGL', 'NVDA', 'CRWD', 'AMC', 'MRNA', 'META', 'BB', 'PLTR', 'NET'])
TICKERS_TODOS = [
    'NVDA', 'AMD', 'GOOGL', 'META', 'CRWD', 'PLTR', 'NET', 'AAPL', 'MSFT', 'AMZN',
    'TSLA', 'SNOW', 'DDOG', 'MDB', 'RIOT', 'MARA', 'COIN', 'AMC', 'BB', 'MRNA',
    'PFE', 'JNJ', 'UNH', 'V', 'MA', 'JPM', 'NKE', 'SBUX', 'MELI', 'SPOT', 'ABNB', 'UBER',
]

START = '2016-01-01'
END = '2025-12-31'

# Descargar datos una vez
print("Descargando datos...")
datos = {}
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
        
        # Métricas
        n_years = len(close) / 252
        cagr = ((close[-1] / close[0]) ** (1/n_years) - 1) * 100
        
        peak = close[0]
        max_dd = 0
        for c in close:
            if c > peak: peak = c
            dd = (peak - c) / peak * 100
            if dd > max_dd: max_dd = dd
        
        tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
        atr14 = pd.Series(tr).rolling(14).mean().values
        
        # ATR promedio histórico completo
        atr_historico = np.nanmean(atr14[14:] / close[14:]) * 100
        
        # ATR promedio últimos 252 días
        atr_252 = np.nanmean(atr14[-252:] / close[-252:]) * 100
        
        # ATR últimos 60
        atr_60 = np.nanmean(atr14[-60:] / close[-60:]) * 100
        
        # Volatilidad
        returns = np.diff(close) / close[:-1]
        volat_252 = np.std(returns[-252:]) * np.sqrt(252) * 100
        volat_60 = np.std(returns[-60:]) * np.sqrt(252) * 100
        
        # Momentum
        mom20 = (close[-1] / close[-20] - 1) * 100
        mom60 = (close[-1] / close[-60] - 1) * 100
        mom120 = (close[-1] / close[-120] - 1) * 100
        
        # Alineación EMAs
        ema20 = pd.Series(close).ewm(span=20).mean().values
        ema50 = pd.Series(close).ewm(span=50).mean().values
        ema200 = pd.Series(close).ewm(span=200).mean().values
        
        n_check = min(60, len(close) - 1)
        trend_pct = 0
        for i in range(-n_check, 0):
            if close[i] > ema20[i]: trend_pct += 1
        trend_pct = trend_pct / n_check * 100
        
        # Volumen
        avg_vol = np.mean(volume[-60:])
        
        datos[t] = {
            'cagr': cagr, 'max_dd': max_dd,
            'atr_h': atr_historico, 'atr_252': atr_252, 'atr_60': atr_60,
            'volat_252': volat_252, 'volat_60': volat_60,
            'mom20': mom20, 'mom60': mom60, 'mom120': mom120,
            'trend_pct': trend_pct, 'avg_vol': avg_vol,
            'es_orig': t in TICKERS_ORIGINALES,
        }
    except:
        pass

print(f"Descargados: {len(datos)} tickers\n")


def evaluar_scoring(scores_dict, n=11):
    """Evalúa un scoring y retorna qué tan bien selecciona los originales."""
    ranked = sorted(scores_dict.items(), key=lambda x: x[1], reverse=True)
    top_n = set([r[0] for r in ranked[:n]])
    hits = len(top_n & TICKERS_ORIGINALES)
    return hits, top_n, ranked


def test_scoring(nombre, scores_dict):
    hits, top_n, ranked = evaluar_scoring(scores_dict)
    missed = TICKERS_ORIGINALES - top_n
    extra = top_n - TICKERS_ORIGINALES
    print(f"  {nombre:40s} | Hits: {hits}/11 | Top: {[r[0] for r in ranked[:11]]}")
    if missed:
        print(f"  {'':40s} | Faltan: {missed}")
    if extra:
        print(f"  {'':40s} | Sobran: {extra}")
    return hits


print("=" * 100)
print("  TEST DE SCORINGS")
print("=" * 100)

mejores = []

# --- SCORING 1: Solo ATR histórico ---
scores = {t: d['atr_h'] for t, d in datos.items()}
h = test_scoring("ATR historico", scores)
mejores.append(("ATR historico", h))

# --- SCORING 2: ATR historico + CAGR ---
scores = {t: d['atr_h'] * max(d['cagr'], 0) for t, d in datos.items()}
h = test_scoring("ATR_h * CAGR", scores)
mejores.append(("ATR_h * CAGR", h))

# --- SCORING 3: Volatilidad 252d ---
scores = {t: d['volat_252'] for t, d in datos.items()}
h = test_scoring("Volatilidad 252d", scores)
mejores.append(("Volatilidad 252d", h))

# --- SCORING 4: ATR * Volatilidad ---
scores = {t: d['atr_h'] * d['volat_252'] for t, d in datos.items()}
h = test_scoring("ATR_h * Vol252", scores)
mejores.append(("ATR_h * Vol252", h))

# --- SCORING 5: ATR + Volatilidad (normalizados) ---
max_atr = max(d['atr_h'] for d in datos.values())
max_vol = max(d['volat_252'] for d in datos.values())
scores = {t: (d['atr_h']/max_atr + d['volat_252']/max_vol) * 50 for t, d in datos.items()}
h = test_scoring("ATR_h + Vol252 (norm)", scores)
mejores.append(("ATR_h + Vol252 (norm)", h))

# --- SCORING 6: ATR * CAGR * Volatilidad ---
scores = {t: d['atr_h'] * max(d['cagr'], 0) * d['volat_252'] for t, d in datos.items()}
h = test_scoring("ATR_h * CAGR * Vol252", scores)
mejores.append(("ATR_h * CAGR * Vol252", h))

# --- SCORING 7: ATR 252d ---
scores = {t: d['atr_252'] for t, d in datos.items()}
h = test_scoring("ATR 252d", scores)
mejores.append(("ATR 252d", h))

# --- SCORING 8: ATR * Vol * MaxDD (penalizar DD bajo) ---
scores = {t: d['atr_h'] * d['volat_252'] * (d['max_dd'] / 100) for t, d in datos.items()}
h = test_scoring("ATR_h * Vol252 * MaxDD", scores)
mejores.append(("ATR_h * Vol252 * MaxDD", h))

# --- SCORING 9: Solo MaxDD (penalizar DD bajo) ---
scores = {t: d['max_dd'] for t, d in datos.items()}
h = test_scoring("Solo MaxDD", scores)
mejores.append(("Solo MaxDD", h))

# --- SCORING 10: CAGR * MaxDD ---
scores = {t: max(d['cagr'], 0) * d['max_dd'] for t, d in datos.items()}
h = test_scoring("CAGR * MaxDD", scores)
mejores.append(("CAGR * MaxDD", h))

# --- SCORING 11: ATR * CAGR^2 (penalizar CAGR bajo más fuerte) ---
scores = {t: d['atr_h'] * (max(d['cagr'], 0) ** 2) for t, d in datos.items()}
h = test_scoring("ATR_h * CAGR^2", scores)
mejores.append(("ATR_h * CAGR^2", h))

# --- SCORING 12: ATR * (CAGR + Vol) ---
scores = {t: d['atr_h'] * (max(d['cagr'], 0) + d['volat_252']) for t, d in datos.items()}
h = test_scoring("ATR_h * (CAGR + Vol252)", scores)
mejores.append(("ATR_h * (CAGR + Vol252)", h))

# --- SCORING 13: ATR^2 * CAGR ---
scores = {t: (d['atr_h'] ** 2) * max(d['cagr'], 0) for t, d in datos.items()}
h = test_scoring("ATR_h^2 * CAGR", scores)
mejores.append(("ATR_h^2 * CAGR", h))

# --- SCORING 14: (ATR + Vol) * CAGR ---
scores = {t: (d['atr_h'] + d['volat_252']/10) * max(d['cagr'], 0) for t, d in datos.items()}
h = test_scoring("(ATR_h + Vol/10) * CAGR", scores)
mejores.append(("(ATR_h + Vol/10) * CAGR", h))

# --- SCORING 15: Ranking combinado (rank ATR + rank CAGR + rank Vol) ---
atr_ranked = sorted(datos.keys(), key=lambda t: datos[t]['atr_h'], reverse=True)
cagr_ranked = sorted(datos.keys(), key=lambda t: max(datos[t]['cagr'], 0), reverse=True)
vol_ranked = sorted(datos.keys(), key=lambda t: datos[t]['volat_252'], reverse=True)
dd_ranked = sorted(datos.keys(), key=lambda t: datos[t]['max_dd'], reverse=True)

scores = {}
for t in datos:
    r_atr = atr_ranked.index(t) + 1
    r_cagr = cagr_ranked.index(t) + 1
    r_vol = vol_ranked.index(t) + 1
    r_dd = dd_ranked.index(t) + 1
    scores[t] = -(r_atr + r_cagr + r_vol + r_dd)  # Menor es mejor
h = test_scoring("Rank ATR+CAGR+Vol+DD", scores)
mejores.append(("Rank ATR+CAGR+Vol+DD", h))

# --- SCORING 16: ATR * CAGR * sqrt(Vol) ---
scores = {t: d['atr_h'] * max(d['cagr'], 0) * np.sqrt(d['volat_252']) for t, d in datos.items()}
h = test_scoring("ATR_h * CAGR * sqrt(Vol)", scores)
mejores.append(("ATR_h * CAGR * sqrt(Vol)", h))

# --- SCORING 17: Solo por ranking CAGR (para ver si la estrategia captura CAGR individual) ---
scores = {t: d['cagr'] for t, d in datos.items()}
h = test_scoring("Solo CAGR", scores)
mejores.append(("Solo CAGR", h))

# --- SCORING 18: ATR * MaxDD (busca volatilidad + tolerancia a DD) ---
scores = {t: d['atr_h'] * d['max_dd'] for t, d in datos.items()}
h = test_scoring("ATR_h * MaxDD", scores)
mejores.append(("ATR_h * MaxDD", h))

print("\n" + "=" * 100)
print("  RANKING DE SCORINGS (por hits/11)")
print("=" * 100)
mejores.sort(key=lambda x: x[1], reverse=True)
for i, (nombre, hits) in enumerate(mejores, 1):
    barra = '#' * hits + '.' * (11 - hits)
    print(f"  {i:2d}. [{barra}] {hits}/11 | {nombre}")
