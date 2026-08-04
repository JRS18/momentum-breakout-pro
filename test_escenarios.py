# -*- coding: utf-8 -*-
"""
Test de escenarios: seleccion diversificada + 1-2 cripto mineros.
Descarga una vez, prueba varias combinaciones, corre backtest de cada una.
"""
import json
import os
import re
import numpy as np
import pandas as pd
import yfinance as yf
import subprocess
import sys
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

RUTA = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(RUTA, 'strategies', 'strategy_config.py')

from optimizar_cedears import UNIVERSE


def set_tickers(tickers):
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    content = re.sub(
        r"TICKERS\s*=\s*\[.*?\]",
        f"TICKERS = {tickers}",
        content, flags=re.DOTALL
    )
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(content)


def run_backtest():
    result = subprocess.run(
        [sys.executable, 'run_backtest.py'],
        capture_output=True, text=True, cwd=RUTA, timeout=600
    )
    output = result.stdout + result.stderr
    cagr = trades = winrate = None
    for line in output.split('\n'):
        if 'CAGR:' in line and 'realista' not in line:
            try: cagr = float(line.split('CAGR:')[1].strip().replace('%', ''))
            except: pass
        if 'Win Rate global' in line:
            try: winrate = float(line.split(':')[1].strip().replace('%', ''))
            except: pass
    # MaxDD desde el reporte xlsx
    import glob
    max_dd = None
    try:
        files = sorted(glob.glob(os.path.join(RUTA, 'reports', 'BACKTESTING_REPORT_*.xlsx')))
        if files:
            df = pd.read_excel(files[-1], sheet_name='RESUMEN EJECUTIVO')
            for i, row in df.iterrows():
                v0 = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
                if 'Max Drawdown' in v0:
                    max_dd = float(str(row.iloc[1]).replace('%', ''))
    except Exception:
        pass
    # total trades del csv
    if trades is None:
        try:
            import csv as _csv
            p = os.path.join(RUTA, 'reports', 'trades.csv')
            if os.path.exists(p):
                with open(p, encoding='utf-8') as f:
                    trades = sum(1 for _ in f) - 1
        except Exception:
            pass
    return cagr, max_dd, trades, winrate


def main():
    print("=" * 70)
    print("  ESCENARIOS: DIVERSIFICADO + CRIPTO MINEROS")
    print("=" * 70)

    tickers_list = list(UNIVERSE.keys())
    print(f"\n  Descargando {len(tickers_list)} tickers...")
    data = yf.download(tickers_list, start='2016-01-01', end='2025-12-31',
                       progress=True, auto_adjust=True, threads=True)

    scores = {}
    returns_all = {}
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

            tr = np.maximum(high_vals - low_vals,
                           np.maximum(np.abs(high_vals - np.roll(close_vals, 1)),
                                     np.abs(low_vals - np.roll(close_vals, 1))))
            atr14 = pd.Series(tr).rolling(14).mean().values
            atr_h = np.nanmean(atr14[14:] / close_vals[14:]) * 100

            returns = pd.Series(close_vals).pct_change().dropna().values
            volat = np.std(returns) * np.sqrt(252) * 100
            sharpe = np.mean(returns) / (np.std(returns) + 1e-9) * np.sqrt(252)

            peak = close_vals[0]
            max_dd = 0
            for c in close_vals:
                if c > peak: peak = c
                dd = (peak - c) / peak * 100
                if dd > max_dd: max_dd = dd

            score = sharpe * (1 + cagr / 100)
            if max_dd > 70: score *= 0.4
            elif max_dd > 50: score *= 0.7
            elif max_dd > 30: score *= 0.9
            if atr_h < 1.5 or atr_h > 8: score *= 0.85
            if volat > 120: score *= 0.8

            scores[t] = {'score': score, 'cagr': cagr, 'atr': atr_h,
                        'volat': volat, 'dd': max_dd, 'sharpe': sharpe,
                        'ratio': UNIVERSE[t]['ratio'], 'sector': UNIVERSE[t]['sector']}
            returns_all[t] = returns
        except Exception:
            pass

    ranked = sorted(scores.keys(), key=lambda t: scores[t]['score'], reverse=True)

    print("\n  Score de los cripto mineros:")
    for t in ['HUT', 'NBIS', 'IREN', 'RGTI', 'RIOT', 'COIN', 'MSTR', 'KEEL']:
        if t in scores:
            s = scores[t]
            print(f"  {t:6s} Score={s['score']:6.1f} CAGR={s['cagr']:5.1f}% "
                  f"Sharpe={s['sharpe']:4.2f} DD={s['dd']:4.0f}% Vol={s['volat']:4.0f}%")

    def corr_entre(a, b):
        try:
            sa = pd.Series(returns_all[a])
            sb = pd.Series(returns_all[b])
            sa, sb = sa.align(sb, join='inner')
            r = np.corrcoef(sa.values, sb.values)[0, 1]
            return abs(r) if np.isfinite(r) else 0.0
        except Exception:
            return 0.0

    def seleccion_diversificada(n, max_por_sector=2, max_corr=0.85, fuerzas=None):
        """Seleccion diversificada. fuerzas = tickers a incluir si o si."""
        fuerzas = fuerzas or []
        seleccion = [f for f in fuerzas if f in scores]
        sectores = {}
        for t in seleccion:
            sectores[scores[t]['sector']] = sectores.get(scores[t]['sector'], 0) + 1
        for t in ranked:
            if len(seleccion) >= n:
                break
            if t in seleccion:
                continue
            s = scores[t]
            sec = s['sector']
            if sectores.get(sec, 0) >= max_por_sector:
                continue
            if seleccion:
                r_max = max(corr_entre(t, sel) for sel in seleccion)
                if r_max > max_corr:
                    continue
            seleccion.append(t)
            sectores[sec] = sectores.get(sec, 0) + 1
        return seleccion

    escenarios = {
        'A - Base diversificada (8)': lambda: seleccion_diversificada(8),
        'B - Base + HUT (9)': lambda: seleccion_diversificada(9, fuerzas=['HUT']),
        'C - Base + NBIS (9)': lambda: seleccion_diversificada(9, fuerzas=['NBIS']),
        'D - Base + HUT + NBIS (10)': lambda: seleccion_diversificada(10, fuerzas=['HUT', 'NBIS']),
        'E - Base + HUT (8, saca el peor)': lambda: seleccion_diversificada(8, fuerzas=['HUT']),
    }

    resultados = {}
    for nombre, fn in escenarios.items():
        sel = fn()
        print(f"\n{'='*70}")
        print(f"  {nombre} -> {sel}")
        print(f"{'='*70}")
        for t in sel:
            s = scores[t]
            print(f"  {t:6s} | {s['sector']:10s} | CAGR={s['cagr']:5.1f}% | Sharpe={s['sharpe']:4.2f} | DD={s['dd']:4.0f}%")
        set_tickers(sel)
        cagr, max_dd, trades, winrate = run_backtest()
        resultados[nombre] = {'sel': sel, 'cagr': cagr, 'max_dd': max_dd,
                              'trades': trades, 'winrate': winrate}
        print(f"  >>> CAGR={cagr:.1f}% MaxDD={max_dd:.1f}% Trades={trades} WR={winrate:.1f}%")

    print(f"\n{'='*70}")
    print("  RESUMEN DE ESCENARIOS")
    print(f"{'='*70}")
    for nombre, r in resultados.items():
        ratio = (r['cagr'] / (r['max_dd'] + 0.01)) if r['max_dd'] else None
        print(f"  {nombre}:")
        print(f"    CAGR={r['cagr']:.1f}% | MaxDD={r['max_dd']:.1f}% | "
              f"Ratio C/DD={ratio:.2f} | Trades={r['trades']} | WR={r['winrate']:.1f}%")

    print("\n  [DONE]")


if __name__ == '__main__':
    main()
