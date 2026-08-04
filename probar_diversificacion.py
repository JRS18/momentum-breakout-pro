# -*- coding: utf-8 -*-
"""
Validacion rapida de la seleccion diversificada:
1. Descarga, scoring de consistencia, seleccion con max 2 por sector
2. Corre UN backtest con la seleccion y muestra el resultado
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
    cagr = max_dd = trades = winrate = None
    for line in output.split('\n'):
        if 'CAGR:' in line and 'realista' not in line:
            try: cagr = float(line.split('CAGR:')[1].strip().replace('%', ''))
            except: pass
        if 'Max Drawdown' in line:
            try: max_dd = float(line.split('Max Drawdown')[1].strip().replace('%', ''))
            except: pass
        if 'Trades' in line or 'Operaciones' in line:
            try:
                import re as _re
                m = _re.search(r'(\d+)', line)
                if m: trades = int(m.group(1))
            except: pass
        if 'Win Rate' in line:
            try:
                import re as _re
                m = _re.search(r'([\d.]+)%', line)
                if m: winrate = float(m.group(1))
            except: pass
    return cagr, max_dd, trades, winrate


def main():
    print("=" * 70)
    print("  VALIDACION SELECCION DIVERSIFICADA")
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

    print(f"\n  Top 15 por score de consistencia:")
    for i, t in enumerate(ranked[:15], 1):
        s = scores[t]
        print(f"  {i:2d}. {t:6s} Score={s['score']:6.1f} CAGR={s['cagr']:5.1f}% "
              f"Sharpe={s['sharpe']:4.2f} DD={s['dd']:4.0f}% Sector={s['sector']}")

    def corr_entre(a, b):
        try:
            sa = pd.Series(returns_all[a])
            sb = pd.Series(returns_all[b])
            sa, sb = sa.align(sb, join='inner')
            r = np.corrcoef(sa.values, sb.values)[0, 1]
            return abs(r) if np.isfinite(r) else 0.0
        except Exception:
            return 0.0

    def seleccion_diversificada(n, max_por_sector=2, max_corr=0.85):
        seleccion = []
        sectores = {}
        for t in ranked:
            if len(seleccion) >= n:
                break
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

    for n in [8]:
        sel = seleccion_diversificada(n)
        print(f"\n{'='*70}")
        print(f"  SELECCION DIVERSIFICADA ({len(sel)} tickers):")
        print(f"{'='*70}")
        for i, t in enumerate(sel, 1):
            s = scores[t]
            print(f"  {i:2d}. {t:6s} | {s['sector']:10s} | CAGR={s['cagr']:5.1f}% | "
                  f"Sharpe={s['sharpe']:4.2f} | DD={s['dd']:4.0f}% | Ratio={s['ratio']}")

        set_tickers(sel)
        print(f"\n  Corriendo backtest con {len(sel)} tickers...")
        cagr, max_dd, trades, winrate = run_backtest()
        print(f"\n  RESULTADO:")
        print(f"  CAGR: {cagr:.1f}%" if cagr else "  CAGR: n/d")
        print(f"  MaxDD: {max_dd:.1f}%" if max_dd else "  MaxDD: n/d")
        print(f"  Trades: {trades}" if trades else "  Trades: n/d")
        print(f"  WinRate: {winrate:.1f}%" if winrate else "  WinRate: n/d")

    print("\n  [DONE]")


if __name__ == '__main__':
    main()
