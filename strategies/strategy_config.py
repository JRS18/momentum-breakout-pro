# -*- coding: utf-8 -*-
"""
Configuracion - Estrategia Momentum Breakout
Ultra optimizada para maximo CAGR sin leverage
"""

INITIAL_CAPITAL = 5000

# 11 tickers optimizados
TICKERS = [
    'RIOT', 'AMD', 'GOOGL', 'NVDA', 'CRWD', 'AMC',
    'MRNA', 'META', 'BB', 'PLTR', 'NET',
]

STRATEGY = {
    'name': 'Momentum Breakout Portfolio',
    'timeframe': '1d',
    'ema_stop_mult': 2.5,
    'atr_stop_mult': 2.0,
    'atr_trail_mult': 5.0,
    'tp_ratio': 6.0,
}

RISK_MANAGEMENT = {
    'max_risk_per_trade': 0.18,
    'max_positions': 4,
    'position_size_pct': 0.80,
    'use_leverage': False,
    'leverage_ratio': 1.0,
    'min_volume_avg': 50000,
    'min_price': 3.0,
    'commission_buy': 0.006,
    'commission_sell': 0.006,
    'tax_rate': 0.015,
}

BACKTEST = {
    'start_date': '2016-01-01',
    'end_date': '2025-12-31',
    'initial_capital': INITIAL_CAPITAL,
    'slippage': 0.0003,
}
