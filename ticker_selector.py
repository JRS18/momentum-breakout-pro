# -*- coding: utf-8 -*-
"""
Scoring final: combina volatilidad + CAGR positivo + MaxDD alto
para seleccionar los 11 tickers que maximizan CAGR del portafolio.
"""
import json
import os
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

RUTA = os.path.dirname(os.path.abspath(__file__))

UNIVERSE_CEDEARS = {
    # Crypto miners (high ATR, high volatility)
    'NBIS': {'ratio': 27, 'sector': 'Crypto'},
    'RGTI': {'ratio': 2, 'sector': 'Crypto'},
    'IREN': {'ratio': 12, 'sector': 'Crypto'},
    'RIOT': {'ratio': 3, 'sector': 'Crypto'},
    'HUT': {'ratio': 5, 'sector': 'Crypto'},
    'COIN': {'ratio': 27, 'sector': 'Crypto'},
    'MSTR': {'ratio': 20, 'sector': 'Crypto'},
    'IBIT': {'ratio': 10, 'sector': 'Crypto'},
    # Fintech / Growth
    'UPST': {'ratio': 5, 'sector': 'Fintech'},
    'PLTR': {'ratio': 3, 'sector': 'Tech'},
    'ALAB': {'ratio': 44, 'sector': 'Tech'},
    'NET': {'ratio': 5, 'sector': 'Tech'},
    'MDB': {'ratio': 5, 'sector': 'Tech'},
    'ARM': {'ratio': 27, 'sector': 'Tech'},
    'DDOG': {'ratio': 5, 'sector': 'Tech'},
    'SNOW': {'ratio': 30, 'sector': 'Tech'},
    'CRWD': {'ratio': 79, 'sector': 'Tech'},
    'SE': {'ratio': 32, 'sector': 'Tech'},
    # Big Tech
    'NVDA': {'ratio': 24, 'sector': 'Tech'},
    'AMD': {'ratio': 3, 'sector': 'Tech'},
    'TSLA': {'ratio': 15, 'sector': 'Tech'},
    'META': {'ratio': 24, 'sector': 'Tech'},
    'AAPL': {'ratio': 20, 'sector': 'Tech'},
    'MSFT': {'ratio': 30, 'sector': 'Tech'},
    'AMZN': {'ratio': 144, 'sector': 'Tech'},
    'GOOGL': {'ratio': 58, 'sector': 'Tech'},
    # Health
    'MRNA': {'ratio': 5, 'sector': 'Health'},
    'LLY': {'ratio': 56, 'sector': 'Health'},
    'UNH': {'ratio': 33, 'sector': 'Health'},
    'PFE': {'ratio': 4, 'sector': 'Health'},
    # Finance
    'JPM': {'ratio': 15, 'sector': 'Finance'},
    'V': {'ratio': 18, 'sector': 'Finance'},
    'MA': {'ratio': 33, 'sector': 'Finance'},
    # Consumer
    'MELI': {'ratio': 120, 'sector': 'Consumer'},
    'NKE': {'ratio': 12, 'sector': 'Consumer'},
    'SBUX': {'ratio': 12, 'sector': 'Consumer'},
}


def download_data(ticker, start, end):
    data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if data.columns.nlevels > 1:
        data.columns = data.columns.get_level_values(0)
    return data


def calcular_metricas(ticker):
    """Calcula todas las métricas de un ticker."""
    try:
        end = datetime.now()
        start = end - timedelta(days=800)  # ~3 años para métricas robustas
        data = download_data(ticker, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        
        if data.empty or len(data) < 250:
            return None
        
        close = data['Close'].values.flatten()
        high = data['High'].values.flatten()
        low = data['Low'].values.flatten()
        volume = data['Volume'].values.flatten()
        
        # CAGR
        n_years = len(close) / 252
        cagr = ((close[-1] / close[0]) ** (1/n_years) - 1) * 100
        
        # Max Drawdown
        peak = close[0]
        max_dd = 0
        for c in close:
            if c > peak: peak = c
            dd = (peak - c) / peak * 100
            if dd > max_dd: max_dd = dd
        
        # ATR%
        tr = np.maximum(high - low,
                        np.maximum(np.abs(high - np.roll(close, 1)),
                                   np.abs(low - np.roll(close, 1))))
        atr14 = pd.Series(tr).rolling(14).mean().values
        atr_h = np.nanmean(atr14[14:] / close[14:]) * 100
        
        # Volatilidad anualizada
        returns = np.diff(close) / close[:-1]
        volat = np.std(returns) * np.sqrt(252) * 100
        
        return {
            'ticker': ticker,
            'cagr': cagr,
            'max_dd': max_dd,
            'atr_h': atr_h,
            'volat': volat,
        }
    except:
        return None


def scoring_compuesto(metrics):
    """
    Scoring que combina:
    1. Volatilidad alta (ATR%) → más oportunidades de swing
    2. CAGR positivo → el stock sube a largo plazo
    3. MaxDD alto → tolerancia a caídas (necesario para ATR alto)
    4. Penalización fuerte por CAGR negativo
    """
    cagr = metrics['cagr']
    atr = metrics['atr_h']
    volat = metrics['volat']
    max_dd = metrics['max_dd']
    
    # Score base: ATR * Volatilidad (busca stocks con movimiento)
    score = atr * volat / 10
    
    # Bonus por CAGR positivo
    if cagr > 0:
        score *= (1 + cagr / 100)
    else:
        # Penalización fuerte por CAGR negativo
        score *= 0.1
    
    # Bonus por MaxDD alto (necesario para tener ATR alto)
    if max_dd > 70:
        score *= 1.2
    elif max_dd > 50:
        score *= 1.0
    
    return score


def seleccionar_tickers(n_seleccionados=11):
    """Selecciona los mejores tickers con scoring compuesto."""
    print("=" * 60)
    print("  SELECCION DINAMICA - SCORING COMPUESTO")
    print("=" * 60)
    print(f"  Evaluando {len(UNIVERSE_CEDEARS)} CEDEARs...")
    
    resultados = []
    for ticker in UNIVERSE_CEDEARS.keys():
        print(f"  {ticker}...", end=" ", flush=True)
        m = calcular_metricas(ticker)
        if m:
            score = scoring_compuesto(m)
            m['score'] = score
            resultados.append(m)
            print(f"CAGR={m['cagr']:5.1f}% ATR={m['atr_h']:4.1f}% Vol={m['volat']:4.0f}% DD={m['max_dd']:4.0f}% Score={score:.0f}")
        else:
            print("Sin datos")
    
    resultados.sort(key=lambda x: x['score'], reverse=True)
    seleccionados = resultados[:n_seleccionados]
    
    print(f"\n{'='*60}")
    print(f"  TOP {n_seleccionados}:")
    print(f"{'='*60}")
    for i, r in enumerate(seleccionados, 1):
        print(f"  {i:2d}. {r['ticker']:6s} | Score: {r['score']:7.0f} | CAGR: {r['cagr']:5.1f}% | ATR: {r['atr_h']:4.1f}% | Vol: {r['volat']:4.0f}%")
    
    return seleccionados


def generar_configuracion(tickers_seleccionados):
    tickers = [t['ticker'] for t in tickers_seleccionados]
    ratios = {}
    for t in tickers_seleccionados:
        if t['ticker'] in UNIVERSE_CEDEARS:
            ratios[t['ticker']] = UNIVERSE_CEDEARS[t['ticker']]['ratio']
    
    return {
        'tickers': tickers,
        'ratios': ratios,
        'fecha_seleccion': datetime.now().strftime('%Y-%m-%d'),
    }


def guardar_seleccion(config):
    path = os.path.join(RUTA, 'seleccion_tickers.json')
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"\n[OK] Guardado en: {path}")
    return path


def cargar_seleccion():
    path = os.path.join(RUTA, 'seleccion_tickers.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def ejecutar_seleccion(n=11):
    seleccionados = seleccionar_tickers(n_seleccionados=n)
    config = generar_configuracion(seleccionados)
    guardar_seleccion(config)
    return config


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', type=int, default=11)
    args = parser.parse_args()
    ejecutar_seleccion(args.n)
