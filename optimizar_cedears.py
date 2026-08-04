# -*- coding: utf-8 -*-
"""
Optimización con universe completo de CEDEARs BYMA.
Selecciona 10 tickers con mejor CAGR y menor MaxDD.
"""
import json
import os
import re
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

RUTA = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(RUTA, 'strategies', 'strategy_config.py')

# Universe completo de CEDEARs BYMA - ratios verificadas + sector para diversificacion
UNIVERSE = {
    # Tech
    'AAPL': {'ratio': 20, 'sector': 'Tech'}, 'MSFT': {'ratio': 30, 'sector': 'Tech'},
    'AMZN': {'ratio': 144, 'sector': 'Tech'}, 'NVDA': {'ratio': 24, 'sector': 'Tech'},
    'GOOGL': {'ratio': 58, 'sector': 'Tech'}, 'META': {'ratio': 24, 'sector': 'Tech'},
    'TSLA': {'ratio': 15, 'sector': 'Tech'}, 'AMD': {'ratio': 3, 'sector': 'Tech'},
    'INTC': {'ratio': 5, 'sector': 'Tech'}, 'AVGO': {'ratio': 39, 'sector': 'Tech'},
    'CRM': {'ratio': 18, 'sector': 'Tech'}, 'CSCO': {'ratio': 5, 'sector': 'Tech'},
    'ORCL': {'ratio': 3, 'sector': 'Tech'}, 'QCOM': {'ratio': 11, 'sector': 'Tech'},
    'TXN': {'ratio': 5, 'sector': 'Tech'}, 'ADBE': {'ratio': 44, 'sector': 'Tech'},
    'NOW': {'ratio': 172, 'sector': 'Tech'}, 'PANW': {'ratio': 50, 'sector': 'Tech'},
    'CRWD': {'ratio': 79, 'sector': 'Tech'}, 'NET': {'ratio': 5, 'sector': 'Tech'},
    'SNOW': {'ratio': 30, 'sector': 'Tech'}, 'PLTR': {'ratio': 3, 'sector': 'Tech'},
    'MDB': {'ratio': 5, 'sector': 'Tech'}, 'SPOT': {'ratio': 28, 'sector': 'Tech'},
    'DDOG': {'ratio': 5, 'sector': 'Tech'}, 'ARM': {'ratio': 27, 'sector': 'Tech'},
    'MRVL': {'ratio': 14, 'sector': 'Tech'}, 'MU': {'ratio': 5, 'sector': 'Tech'},
    'AMAT': {'ratio': 5, 'sector': 'Tech'}, 'LRCX': {'ratio': 56, 'sector': 'Tech'},
    'ASML': {'ratio': 146, 'sector': 'Tech'}, 'SMH': {'ratio': 50, 'sector': 'Tech'},
    # Crypto (volatiles, maximo limite por sector)
    'RIOT': {'ratio': 3, 'sector': 'Crypto'}, 'COIN': {'ratio': 27, 'sector': 'Crypto'},
    'MSTR': {'ratio': 20, 'sector': 'Crypto'}, 'IBIT': {'ratio': 10, 'sector': 'Crypto'},
    'NBIS': {'ratio': 27, 'sector': 'Crypto'}, 'RGTI': {'ratio': 2, 'sector': 'Crypto'},
    'IREN': {'ratio': 12, 'sector': 'Crypto'}, 'KEEL': {'ratio': 5, 'sector': 'Crypto'},
    'HUT': {'ratio': 5, 'sector': 'Crypto'},
    # Health
    'LLY': {'ratio': 56, 'sector': 'Health'}, 'JNJ': {'ratio': 15, 'sector': 'Health'},
    'UNH': {'ratio': 33, 'sector': 'Health'}, 'PFE': {'ratio': 4, 'sector': 'Health'},
    'ABBV': {'ratio': 10, 'sector': 'Health'}, 'MRNA': {'ratio': 5, 'sector': 'Health'},
    'NVO': {'ratio': 7, 'sector': 'Health'}, 'TMO': {'ratio': 22, 'sector': 'Health'},
    'ABT': {'ratio': 4, 'sector': 'Health'}, 'DHR': {'ratio': 54, 'sector': 'Health'},
    # Finance
    'JPM': {'ratio': 15, 'sector': 'Finance'}, 'V': {'ratio': 18, 'sector': 'Finance'},
    'MA': {'ratio': 33, 'sector': 'Finance'}, 'GS': {'ratio': 13, 'sector': 'Finance'},
    'MS': {'ratio': 10, 'sector': 'Finance'}, 'BRKB': {'ratio': 22, 'sector': 'Finance'},
    'AXP': {'ratio': 15, 'sector': 'Finance'}, 'C': {'ratio': 3, 'sector': 'Finance'},
    'BAC': {'ratio': 10, 'sector': 'Finance'}, 'SCHW': {'ratio': 13, 'sector': 'Finance'},
    # Consumer
    'MELI': {'ratio': 120, 'sector': 'Consumer'}, 'NKE': {'ratio': 12, 'sector': 'Consumer'},
    'SBUX': {'ratio': 12, 'sector': 'Consumer'}, 'MCD': {'ratio': 24, 'sector': 'Consumer'},
    'COST': {'ratio': 48, 'sector': 'Consumer'}, 'TJX': {'ratio': 22, 'sector': 'Consumer'},
    'ROST': {'ratio': 41, 'sector': 'Consumer'}, 'HD': {'ratio': 32, 'sector': 'Consumer'},
    'LOW': {'ratio': 10, 'sector': 'Consumer'}, 'TGT': {'ratio': 24, 'sector': 'Consumer'},
    'WMT': {'ratio': 18, 'sector': 'Consumer'},
    # Energy
    'XOM': {'ratio': 10, 'sector': 'Energy'}, 'CVX': {'ratio': 16, 'sector': 'Energy'},
    'COP': {'ratio': 25, 'sector': 'Energy'}, 'EOG': {'ratio': 10, 'sector': 'Energy'},
    # Industrial
    'CAT': {'ratio': 20, 'sector': 'Industrial'}, 'DE': {'ratio': 40, 'sector': 'Industrial'},
    'UNP': {'ratio': 20, 'sector': 'Industrial'}, 'HON': {'ratio': 8, 'sector': 'Industrial'},
    'RTX': {'ratio': 5, 'sector': 'Industrial'}, 'LMT': {'ratio': 20, 'sector': 'Industrial'},
    'BA': {'ratio': 24, 'sector': 'Industrial'}, 'GE': {'ratio': 8, 'sector': 'Industrial'},
    # ETFs
    'SPY': {'ratio': 60, 'sector': 'ETF'}, 'QQQ': {'ratio': 20, 'sector': 'ETF'},
    'IWM': {'ratio': 10, 'sector': 'ETF'}, 'XLK': {'ratio': 46, 'sector': 'ETF'},
    'XLE': {'ratio': 2, 'sector': 'ETF'},
    # Otros growth / internacionales
    'SE': {'ratio': 32, 'sector': 'Tech'}, 'BABA': {'ratio': 9, 'sector': 'Consumer'},
    'JD': {'ratio': 4, 'sector': 'Consumer'}, 'PDD': {'ratio': 25, 'sector': 'Consumer'},
    'NIO': {'ratio': 4, 'sector': 'Tech'}, 'RBLX': {'ratio': 2, 'sector': 'Tech'},
    'ABNB': {'ratio': 15, 'sector': 'Consumer'}, 'UBER': {'ratio': 2, 'sector': 'Tech'},
    'UPST': {'ratio': 5, 'sector': 'Fintech'}, 'ALAB': {'ratio': 44, 'sector': 'Fintech'},
}


def set_tickers(tickers):
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    tickers_str = str(tickers)
    content = re.sub(
        r"TICKERS\s*=\s*\[.*?\]",
        f"TICKERS = {tickers_str}",
        content, flags=re.DOTALL
    )
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(content)


def run_backtest():
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, 'run_backtest.py'],
        capture_output=True, text=True, cwd=RUTA, timeout=300
    )
    output = result.stdout + result.stderr
    cagr = max_dd = None
    for line in output.split('\n'):
        if 'CAGR:' in line and 'realista' not in line:
            try: cagr = float(line.split('CAGR:')[1].strip().replace('%', ''))
            except: pass
        if 'Max Drawdown' in line:
            try: max_dd = float(line.split('Max Drawdown')[1].strip().replace('%', ''))
            except: pass
    if cagr is None or max_dd is None:
        import glob
        files = sorted(glob.glob(os.path.join(RUTA, 'reports', 'BACKTESTING_REPORT_*.xlsx')))
        if files:
            try:
                df = pd.read_excel(files[-1], sheet_name='RESUMEN EJECUTIVO')
                for i, row in df.iterrows():
                    v0 = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
                    v1 = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ''
                    if v0.strip() == 'CAGR': cagr = float(v1.replace('%', '').replace(',', ''))
                    if 'Max Drawdown' in v0: max_dd = float(v1.replace('%', ''))
            except: pass
    return cagr, max_dd


def optimizar():
    print("=" * 70)
    print("  OPTIMIZACION - UNIVERSE COMPLETO CEDEARs BYMA")
    print(f"  {len(UNIVERSE)} CEDEARs en el universe")
    print("=" * 70)

    # Fase 1: Descargar datos en batch
    print("\n  Fase 1: Descargando datos...")
    tickers_list = list(UNIVERSE.keys())
    
    # Descargar todos de una vez
    data = yf.download(tickers_list, start='2016-01-01', end='2025-12-31',
                       progress=True, auto_adjust=True, threads=True)
    
    returns_all = {}
    scores = {}
    for t in tickers_list:
        try:
            if data.columns.nlevels > 1 and t in data.columns.get_level_values(1):
                close = data['Close'][t].dropna()
                high = data['High'][t].dropna()
                low = data['Low'][t].dropna()
            else:
                continue
                
            if len(close) < 250:
                continue
                
            close_vals = close.values
            high_vals = high.values
            low_vals = low.values
            
            n_years = len(close_vals) / 252
            if n_years < 0.5:
                continue
                
            cagr = ((close_vals[-1] / close_vals[0]) ** (1/n_years) - 1) * 100
            
            # ATR
            tr = np.maximum(high_vals - low_vals,
                           np.maximum(np.abs(high_vals - np.roll(close_vals, 1)),
                                     np.abs(low_vals - np.roll(close_vals, 1))))
            atr14 = pd.Series(tr).rolling(14).mean().values
            atr_h = np.nanmean(atr14[14:] / close_vals[14:]) * 100
            
            # Volatilidad y Sharpe
            returns = pd.Series(close_vals).pct_change().dropna().values
            volat = np.std(returns) * np.sqrt(252) * 100
            sharpe = np.mean(returns) / (np.std(returns) + 1e-9) * np.sqrt(252)
            
            # Max DD
            peak = close_vals[0]
            max_dd = 0
            for c in close_vals:
                if c > peak: peak = c
                dd = (peak - c) / peak * 100
                if dd > max_dd: max_dd = dd
            
            # Score de CONSISTENCIA: premia Sharpe y CAGR, PENALIZA MaxDD y volatilidad extrema
            score = sharpe * (1 + cagr / 100)
            # Penalizacion por drawdown: a menor MaxDD mejor consistencia
            if max_dd > 70:
                score *= 0.4
            elif max_dd > 50:
                score *= 0.7
            elif max_dd > 30:
                score *= 0.9
            # ATR moderado: suficiente movimiento para swing sin ser ruleta
            if atr_h < 1.5 or atr_h > 8:
                score *= 0.85  # muy quieto o demasiado loco
            # Penalizacion leve por volatilidad extrema (>120%)
            if volat > 120:
                score *= 0.8
            
            scores[t] = {'score': score, 'cagr': cagr, 'atr': atr_h,
                        'volat': volat, 'dd': max_dd, 'sharpe': sharpe,
                        'ratio': UNIVERSE[t]['ratio'], 'sector': UNIVERSE[t]['sector']}
            returns_all[t] = returns
        except Exception as e:
            pass
    
    if not scores:
        print("  Error: no se obtuvieron datos")
        return None

    # Ranking por consistencia
    ranked = sorted(scores.keys(), key=lambda t: scores[t]['score'], reverse=True)

    print(f"\n  Top 30 por score de consistencia:")
    for i, t in enumerate(ranked[:30], 1):
        s = scores[t]
        print(f"  {i:2d}. {t:6s} Score={s['score']:6.1f} CAGR={s['cagr']:5.1f}% "
              f"Sharpe={s['sharpe']:4.2f} DD={s['dd']:4.0f}% "
              f"ATR={s['atr']:4.1f}% Sector={s['sector']}")

    # Fase 2: Backtesting
    print(f"\n{'='*70}")
    print("  Fase 2: Backtesting real")
    print(f"{'='*70}")

    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config_original = f.read()

    resultados = []

    try:
        # Seleccion diversificada por sector + correlacion
        def corr_entre(a, b):
            """Correlacion de retornos entre dos tickers (alineados por indice)."""
            try:
                sa, sb = pd.Series(returns_all[a]).align(pd.Series(returns_all[b]), join='inner')
                r = np.corrcoef(sa.values, sb.values)[0, 1]
                return abs(r) if np.isfinite(r) else 0.0
            except Exception:
                return 0.0

        def seleccion_diversificada(n, max_por_sector=2, max_corr=0.85):
            """Elige n tickers con limite por sector y baja correlacion entre ellos."""
            seleccion = []
            sectores = {}
            for t in ranked:
                if len(seleccion) >= n:
                    break
                s = scores[t]
                sec = s['sector']
                if sectores.get(sec, 0) >= max_por_sector:
                    continue
                # Correlacion con ya seleccionados
                if seleccion:
                    r_max = max(corr_entre(t, sel) for sel in seleccion)
                    if r_max > max_corr:
                        continue
                seleccion.append(t)
                sectores[sec] = sectores.get(sec, 0) + 1
            return seleccion

        # Probar tamaños 7-12 con seleccion diversificada
        for n in [7, 8, 10, 12]:
            top_n = seleccion_diversificada(n)
            print(f"\n  Seleccion {n} (diversificada): {top_n}")
            if len(top_n) < 4:
                continue
            set_tickers(top_n)
            cagr, max_dd = run_backtest()
            if cagr is not None and max_dd is not None:
                ratio = cagr / (max_dd + 0.01)
                resultados.append({
                    'n': n, 'tickers': top_n,
                    'cagr': cagr, 'max_dd': max_dd, 'ratio': ratio,
                })
                print(f"    -> CAGR={cagr:.1f}% MaxDD={max_dd:.1f}% Ratio={ratio:.2f}")

        # Optimizar el mejor con swaps
        if resultados:
            mejor = max(resultados, key=lambda x: x['ratio'])
            n_opt = mejor['n']
            base = mejor['tickers'][:]
            print(f"\n{'='*70}")
            print(f"  Fase 3: Optimizando top {n_opt} con swaps")
            print(f"{'='*70}")

            next_candidates = [t for t in ranked if t not in base][:15]

            for swap_out in base:
                for swap_in in next_candidates:
                    if scores[swap_in]['sector'] == scores[swap_out]['sector']:
                        continue  # no romper el limite por sector
                    test = [t for t in base if t != swap_out] + [swap_in]
                    print(f"\n  -{swap_out} +{swap_in}")
                    set_tickers(test)
                    cagr, max_dd = run_backtest()
                    if cagr is not None and max_dd is not None:
                        ratio = cagr / (max_dd + 0.01)
                        resultados.append({
                            'n': n_opt, 'tickers': test,
                            'cagr': cagr, 'max_dd': max_dd, 'ratio': ratio,
                        })
                        print(f"    -> CAGR={cagr:.1f}% MaxDD={max_dd:.1f}% Ratio={ratio:.2f}")
    finally:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write(config_original)

    if not resultados:
        print("\n  No se obtuvieron resultados")
        return None

    resultados.sort(key=lambda x: x['ratio'], reverse=True)

    print(f"\n{'='*70}")
    print("  TOP 10 RESULTADOS (ordenados por CAGR/MaxDD)")
    print(f"{'='*70}")
    for i, r in enumerate(resultados[:10], 1):
        print(f"  {i:2d}. {r['n']:2d} tickers | CAGR={r['cagr']:6.1f}% | "
              f"MaxDD={r['max_dd']:5.1f}% | Ratio={r['ratio']:.2f}")
        print(f"      {r['tickers']}")

    mejor = resultados[0]
    print(f"\n  MEJOR COMBINACION:")
    print(f"  Tickers ({mejor['n']}): {mejor['tickers']}")
    print(f"  CAGR: {mejor['cagr']:.1f}%")
    print(f"  MaxDD: {mejor['max_dd']:.1f}%")
    print(f"  Ratio: {mejor['ratio']:.2f}")

    with open(os.path.join(RUTA, 'optimizacion_cedears.json'), 'w') as f:
        json.dump({'mejor': mejor, 'todos': resultados,
                   'fecha': datetime.now().strftime('%Y-%m-%d %H:%M')}, f, indent=2)

    return mejor


if __name__ == '__main__':
    optimizar()
