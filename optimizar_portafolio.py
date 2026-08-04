# -*- coding: utf-8 -*-
"""
Optimización de portafolio: mejor CAGR y menor MaxDD.
Usa el motor de backtesting existente para precisión.
"""
import json
import os
import sys
import shutil
import subprocess
import re
from datetime import datetime

RUTA = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(RUTA, 'strategies', 'strategy_config.py')
REPORT_DIR = os.path.join(RUTA, 'reports')


def set_tickers(tickers):
    """Actualiza los TICKERS en strategy_config.py."""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    tickers_str = str(tickers)
    content = re.sub(
        r"TICKERS\s*=\s*\[.*?\]",
        f"TICKERS = {tickers_str}",
        content,
        flags=re.DOTALL
    )
    
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(content)


def run_backtest():
    """Ejecuta el backtest y retorna CAGR y MaxDD."""
    result = subprocess.run(
        [sys.executable, 'run_backtest.py'],
        capture_output=True, text=True, cwd=RUTA, timeout=300
    )
    output = result.stdout + result.stderr
    
    cagr = None
    max_dd = None
    
    for line in output.split('\n'):
        if 'CAGR:' in line and 'realista' not in line:
            try:
                cagr = float(line.split('CAGR:')[1].strip().replace('%', ''))
            except:
                pass
        if 'Max Drawdown' in line:
            try:
                max_dd = float(line.split('Max Drawdown')[1].strip().replace('%', ''))
            except:
                pass
    
    # Also try to read from the latest report
    if cagr is None or max_dd is None:
        import glob
        import pandas as pd
        files = sorted(glob.glob(os.path.join(REPORT_DIR, 'BACKTESTING_REPORT_*.xlsx')))
        if files:
            try:
                df = pd.read_excel(files[-1], sheet_name='RESUMEN EJECUTIVO')
                for i, row in df.iterrows():
                    val0 = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
                    val1 = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ''
                    if 'CAGR' == val0.strip():
                        cagr = float(val1.replace('%', '').replace(',', ''))
                    if 'Max Drawdown' in val0:
                        max_dd = float(val1.replace('%', ''))
            except:
                pass
    
    return cagr, max_dd


def optimizar():
    print("=" * 70)
    print("  OPTIMIZACION DE PORTAFOLIO")
    print("=" * 70)
    
    # Universe completo
    all_tickers = [
        'RIOT', 'AMD', 'GOOGL', 'NVDA', 'CRWD', 'AMC', 'MRNA', 'META',
        'BB', 'PLTR', 'NET', 'AAPL', 'MSFT', 'AMZN', 'TSLA', 'SNOW',
        'DDOG', 'MDB', 'MARA', 'COIN', 'PFE', 'JNJ', 'UNH', 'V', 'MA',
        'JPM', 'NKE', 'SBUX', 'MELI', 'SPOT', 'ABNB', 'UBER',
    ]
    
    # Guardar config original
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config_original = f.read()
    
    resultados = []
    
    # Probar diferentes tamaños con los top tickers por scoring
    # Primero obtener ranking por score rápido (ATR * CAGR positivo)
    print("\n  Fase 1: Ranking por score rapido...")
    
    import yfinance as yf
    import numpy as np
    import pandas as pd
    
    scores = {}
    for t in all_tickers:
        try:
            data = yf.download(t, start='2016-01-01', end='2025-12-31', progress=False, auto_adjust=True)
            if data.columns.nlevels > 1:
                data.columns = data.columns.get_level_values(0)
            if data.empty or len(data) < 250:
                continue
            
            close = data['Close'].values.flatten()
            high = data['High'].values.flatten()
            low = data['Low'].values.flatten()
            
            n_years = len(close) / 252
            cagr = ((close[-1] / close[0]) ** (1/n_years) - 1) * 100
            
            tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
            atr14 = pd.Series(tr).rolling(14).mean().values
            atr_h = np.nanmean(atr14[14:] / close[14:]) * 100
            
            returns = np.diff(close) / close[:-1]
            volat = np.std(returns) * np.sqrt(252) * 100
            
            peak = close[0]
            max_dd = 0
            for c in close:
                if c > peak: peak = c
                dd = (peak - c) / peak * 100
                if dd > max_dd: max_dd = dd
            
            # Score: ATR * Vol * (1 + CAGR/100 if positive, else 0.1)
            score = atr_h * volat / 10
            if cagr > 0:
                score *= (1 + cagr / 100)
            else:
                score *= 0.1
            if max_dd > 70:
                score *= 1.2
            
            scores[t] = {'score': score, 'cagr': cagr, 'atr': atr_h, 'volat': volat, 'dd': max_dd}
        except:
            pass
    
    ranked = sorted(scores.keys(), key=lambda t: scores[t]['score'], reverse=True)
    
    print(f"\n  Ranking top 15:")
    for i, t in enumerate(ranked[:15], 1):
        s = scores[t]
        print(f"  {i:2d}. {t:6s} Score={s['score']:6.0f} CAGR={s['cagr']:5.1f}% ATR={s['atr']:4.1f}%")
    
    # Fase 2: Probar portafolios con backtesting real
    print(f"\n{'='*70}")
    print("  Fase 2: Backtesting real con diferentes tamaños")
    print(f"{'='*70}")
    
    try:
        for n in [5, 7, 9, 11, 13]:
            top_n = ranked[:n]
            print(f"\n  Probando top {n}: {top_n}")
            
            set_tickers(top_n)
            cagr, max_dd = run_backtest()
            
            if cagr is not None and max_dd is not None:
                ratio = cagr / (max_dd + 0.01)
                resultados.append({
                    'n': n, 'tickers': top_n,
                    'cagr': cagr, 'max_dd': max_dd, 'ratio': ratio,
                })
                print(f"    -> CAGR={cagr:.1f}% MaxDD={max_dd:.1f}% Ratio={ratio:.2f}")
            else:
                print(f"    -> Error midiendo resultados")
    finally:
        # Restaurar config original
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write(config_original)
    
    if not resultados:
        print("\n  No se pudieron obtener resultados")
        return None
    
    # Fase 3: Probar mejores candidatos con diferentes combinaciones
    print(f"\n{'='*70}")
    print("  Fase 3: Optimizando combinación del mejor tamaño")
    print(f"{'='*70}")
    
    mejor = max(resultados, key=lambda x: x['ratio'])
    n_opt = mejor['n']
    
    print(f"\n  Tamaño óptimo: {n_opt} tickers")
    print(f"  Probando variaciones...")
    
    # Probar quitando el peor y agregando el siguiente
    base = mejor['tickers'][:]
    next_candidates = ranked[n_opt:n_opt+5]
    
    for swap_out in base[-3:]:
        for swap_in in next_candidates:
            test = [t for t in base if t != swap_out] + [swap_in]
            print(f"\n  Swap: -{swap_out} +{swap_in} -> {test}")
            
            set_tickers(test)
            cagr, max_dd = run_backtest()
            
            if cagr is not None and max_dd is not None:
                ratio = cagr / (max_dd + 0.01)
                resultados.append({
                    'n': n_opt, 'tickers': test,
                    'cagr': cagr, 'max_dd': max_dd, 'ratio': ratio,
                })
                print(f"    -> CAGR={cagr:.1f}% MaxDD={max_dd:.1f}% Ratio={ratio:.2f}")
    
    # Restaurar config original
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(config_original)
    
    # Resultados finales
    resultados.sort(key=lambda x: x['ratio'], reverse=True)
    
    print(f"\n{'='*70}")
    print("  RESULTADOS FINALES (ordenados por CAGR/MaxDD)")
    print(f"{'='*70}")
    for i, r in enumerate(resultados[:10], 1):
        print(f"  {i:2d}. {r['n']:2d} tickers | CAGR={r['cagr']:6.1f}% | MaxDD={r['max_dd']:5.1f}% | Ratio={r['ratio']:.2f}")
        print(f"      {r['tickers']}")
    
    mejor = resultados[0]
    print(f"\n  MEJOR COMBINACIÓN:")
    print(f"  Tickers ({mejor['n']}): {mejor['tickers']}")
    print(f"  CAGR: {mejor['cagr']:.1f}%")
    print(f"  MaxDD: {mejor['max_dd']:.1f}%")
    print(f"  Ratio CAGR/DD: {mejor['ratio']:.2f}")
    
    # Guardar
    with open(os.path.join(RUTA, 'optimizacion.json'), 'w') as f:
        json.dump({
            'mejor': mejor,
            'todos_los_resultados': resultados,
            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }, f, indent=2)
    
    return mejor


if __name__ == '__main__':
    optimizar()
