# -*- coding: utf-8 -*-
"""
Script Principal - Sistema de Backtesting de Trading
Ejecuta backtesting a nivel portafolio con capital compartido
"""

import os
import sys
from datetime import datetime

# Configurar path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from strategies.backtest_engine import BacktestEngine
from strategies.report_generator import ReportGenerator
from strategies.strategy_config import TICKERS, RISK_MANAGEMENT


def main():
    """Funcion principal del backtesting"""
    
    output_dir = os.path.join(current_dir, 'reports')
    
    print("=" * 70)
    print("   SISTEMA DE BACKTESTING - MOMENTUM BREAKOUT PRO")
    print("   Portafolio con Capital Compartido")
    print("=" * 70)
    print(f"   Fecha de Ejecucion: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Directorio de Salida: {output_dir}")
    print(f"   Comisiones: {RISK_MANAGEMENT['commission_buy']*100}% compra + {RISK_MANAGEMENT['commission_sell']*100}% venta")
    print(f"   Impuestos: {RISK_MANAGEMENT['tax_rate']*100}% sobre ganancias")
    print(f"   Leverage: {RISK_MANAGEMENT.get('leverage_ratio', 1)}x")
    print("=" * 70)
    
    os.makedirs(output_dir, exist_ok=True)
    
    engine = BacktestEngine()
    
    print("\n[1/3] Ejecutando backtesting...")
    results = engine.run_full_backtest()
    
    print("\n[2/3] Generando reportes Excel...")
    reporter = ReportGenerator(output_dir)
    excel_path = reporter.save_reports(results)
    
    print("\n[3/3] Resumen final:")
    print("=" * 70)
    
    trades = results.get('trades', [])
    if trades:
        final_capital = results.get('final_capital', 0)
        initial_capital = results['initial_capital']
        cagr = results.get('cagr', 0)
        total_return = results.get('total_return', 0)
        
        wins = [t for t in trades if t.pnl > 0]
        win_rate = len(wins) / len(trades) * 100
        
        print(f"  Total de Trades:      {len(trades)}")
        print(f"  Win Rate:             {win_rate:.1f}%")
        print(f"  Capital Inicial:      ${initial_capital:,.2f}")
        print(f"  Capital Final:        ${final_capital:,.2f}")
        print(f"  Ganancia Total:       ${final_capital - initial_capital:,.2f}")
        print(f"  Retorno Total:        {total_return:,.2f}%")
        print(f"  CAGR:                 {cagr:.2f}%")
        
        # Metricas realistas
        print("\n  --- ANALISIS REALISTA ---")
        print(f"  Nota: El backtesting simula ${initial_capital:,.0f} de capital inicial")
        print(f"  distribuido entre {len(TICKERS)} tickers con capital compartido.")
        print(f"  CAGR realista para invertir ${initial_capital:,.0f}: {cagr:.2f}%")
        
        # Proyecciones
        print("\n  --- PROYECCIONES ---")
        for years in [5, 10, 15, 20]:
            projected = initial_capital * (1 + cagr/100) ** years
            print(f"  {years:2d} anos: ${initial_capital:,.0f} -> ${projected:,.0f}")
    else:
        print("  No se generaron trades durante el backtesting.")
    
    print("=" * 70)
    print(f"\n[OK] Backtesting completado exitosamente!")
    print(f"[OK] Reporte Excel: {excel_path}")
    print("=" * 70)
    
    return results


if __name__ == "__main__":
    main()
