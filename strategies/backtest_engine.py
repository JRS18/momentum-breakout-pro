# -*- coding: utf-8 -*-
"""
Motor de Backtesting - Nivel Portafolio
Capital compartido entre todos los tickers con asignacion por momentum
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.ema_triple_cross import MomentumBreakoutStrategy, SignalType, Signal
from strategies.strategy_config import (
    STRATEGY, RISK_MANAGEMENT, BACKTEST, TICKERS, INITIAL_CAPITAL
)


@dataclass
class Trade:
    ticker: str
    quantity: int
    buy_date: str
    buy_price: float
    sell_date: str
    sell_price: float
    pnl: float
    pnl_pct: float
    buy_reason: str
    sell_reason: str
    holding_days: int
    max_drawdown: float
    entry_amount: float = 0.0   # quantity * buy_price (monto bruto compra)
    exit_amount: float = 0.0    # quantity * sell_price (monto bruto venta)
    invested_amount: float = 0.0  # cost_basis total (monto invertido con comisiones)
    total_amount: float = 0.0   # proceeds total (monto recibido despues de comisiones e impuestos)

    def to_dict(self) -> dict:
        return asdict(self)


class BacktestEngine:

    def __init__(self):
        self.strategy = MomentumBreakoutStrategy(STRATEGY)
        self.initial_capital = BACKTEST['initial_capital']
        self.commission_buy = RISK_MANAGEMENT['commission_buy']
        self.commission_sell = RISK_MANAGEMENT['commission_sell']
        self.tax_rate = RISK_MANAGEMENT['tax_rate']
        self.slippage = BACKTEST['slippage']
        self.max_positions = RISK_MANAGEMENT['max_positions']
        self.position_size_pct = RISK_MANAGEMENT['position_size_pct']
        self.max_risk = RISK_MANAGEMENT['max_risk_per_trade']
        self.use_leverage = RISK_MANAGEMENT.get('use_leverage', False)
        self.leverage_ratio = RISK_MANAGEMENT.get('leverage_ratio', 1.0)

    def download_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        print(f"Descargando datos para {ticker}...")
        data = yf.download(ticker, start=start_date, end=end_date,
                           progress=False, auto_adjust=True)
        if data.empty:
            raise ValueError(f"No se encontraron datos para {ticker}")
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return data

    def calculate_position_size(self, price: float, stop_loss: float,
                                capital: float) -> int:
        risk_per_share = price - stop_loss
        if risk_per_share <= 0:
            return 0

        available = capital * self.leverage_ratio if self.use_leverage else capital
        max_loss = capital * self.max_risk
        shares_by_risk = int(max_loss / risk_per_share)
        shares_by_pct = int((available * self.position_size_pct) / price)

        return min(shares_by_risk, shares_by_pct)

    def run_portfolio_backtest(self) -> Dict:
        """
        Backtesting a nivel portafolio: capital compartido entre todos los tickers.
        Prioriza las senales con mayor confianza.
        """
        # Descargar y calcular indicadores para todos los tickers
        ticker_data = {}
        for ticker in TICKERS:
            try:
                df = self.download_data(ticker, BACKTEST['start_date'], BACKTEST['end_date'])
                df = self.strategy.calculate_indicators(df)
                ticker_data[ticker] = df
            except Exception as e:
                print(f"[!!] Error descargando {ticker}: {e}")
                continue

        print(f"\n[OK] {len(ticker_data)} tickers descargados")

        # Descargar SPY para filtro de regimen de mercado
        print("Descargando SPY para filtro de mercado...")
        spy_data = self.download_data('SPY', BACKTEST['start_date'], BACKTEST['end_date'])
        spy_data['EMA_200'] = spy_data['Close'].ewm(span=200, adjust=False).mean()
        spy_bullish = set()
        for idx in spy_data.index:
            if spy_data.loc[idx, 'Close'] > spy_data.loc[idx, 'EMA_200']:
                spy_bullish.add(idx)

        # Encontrar rango de fechas union (cada ticker opera cuando tenga datos)
        all_dates = set()
        for ticker, df in ticker_data.items():
            all_dates.update(df.index)
        all_dates = sorted(all_dates)

        if not all_dates:
            print("[!!] No hay fechas")
            return {}

        start = all_dates[0]
        end = all_dates[-1]
        print(f"Rango total: {start.strftime('%Y-%m-%d')} a {end.strftime('%Y-%m-%d')} ({(end-start).days/365:.1f} anos)")

        # Variables de estado del portafolio
        capital = self.initial_capital
        positions = {}  # ticker -> position dict
        trades = []
        signals_data = []
        equity_curve = []
        pending_entries = {}  # ticker -> {price, stop, tp, atr, score, reason}

        warmup = 210
        date_list = list(all_dates)

        for day_idx in range(warmup, len(date_list)):
            current_date = date_list[day_idx]

            # 1. Actualizar posiciones abiertas
            for ticker in list(positions.keys()):
                if ticker not in ticker_data:
                    continue
                df = ticker_data[ticker]
                if current_date not in df.index:
                    continue  # Este ticker no tiene datos este dia, mantener posicion

                pos = positions[ticker]
                last_row = df.loc[current_date]
                current_data = df.loc[:current_date]

                # Actualizar max precio y drawdown
                if last_row['Close'] > pos['max_price']:
                    pos['max_price'] = last_row['Close']
                dd = (pos['max_price'] - last_row['Close']) / pos['max_price']
                pos['max_drawdown'] = max(pos['max_drawdown'], dd)

                # Actualizar trailing stop (usar ATR actual para adaptarse)
                current_atr = last_row['ATR']
                new_stop = last_row['Close'] - (current_atr * self.strategy.config.get('atr_trail_mult', 3.5))
                pos['current_stop'] = max(pos.get('current_stop', 0), new_stop)

                # BREAKEVEN STOP DINAMICO: proteger mas agresivamente trades viejos
                entry_price = pos['entry_price']
                initial_stop = pos.get('initial_stop', entry_price - current_atr * 2)
                risk_per_share = entry_price - initial_stop
                if risk_per_share > 0:
                    gain = last_row['Close'] - entry_price
                    days_held = (current_date - pos['entry_date']).days
                    # Trades viejos (>15 dias): breakeven mas agresivo (1.5x)
                    # Trades nuevos (<15 dias): breakeven mas amplio (2.5x)
                    if days_held > 15:
                        trigger = 1.5 * risk_per_share
                        protect = entry_price + risk_per_share * 0.3
                    else:
                        trigger = 2.5 * risk_per_share
                        protect = entry_price + risk_per_share * 0.5
                    if gain >= trigger:
                        pos['current_stop'] = max(pos['current_stop'], protect)

                # PIRAMIDACION: agregar a posiciones ganadoras con momentum fuerte
                gain_pct = (last_row['Close'] - pos['entry_price']) / pos['entry_price']
                pyramid_count = pos.get('pyramid_count', 0)
                if gain_pct > 0.15 and pyramid_count < 1 and last_row['RSI'] < 72:
                    # Agregar 40% del tamano original
                    add_shares = int(pos['shares'] * 0.40)
                    add_cost = add_shares * last_row['Close'] * (1 + self.commission_buy)
                    if add_cost <= capital and add_shares > 0:
                        capital -= add_cost
                        pos['shares'] += add_shares
                        pos['cost_basis'] += add_cost
                        pos['pyramid_count'] = pyramid_count + 1
                        signals_data.append({
                            'date': current_date, 'signal': 'PIRAMIDE', 'ticker': ticker,
                            'price': last_row['Close'], 'shares': add_shares,
                            'reason': f"PIRAMIDE | Ganancia: {gain_pct*100:.1f}%",
                            'capital_after': capital
                        })


                # Verificar senal de salida
                signal = self.strategy.generate_signal(current_data, ticker, pos)
                if signal and signal.signal_type == SignalType.SELL:
                    # Ejecutar venta
                    gross_proceeds = pos['shares'] * signal.price
                    commission = gross_proceeds * self.commission_sell
                    entry_cost = pos['cost_basis']
                    gross_pnl = gross_proceeds - entry_cost
                    tax = max(0, gross_pnl * self.tax_rate)
                    proceeds = gross_proceeds - commission - tax
                    capital += proceeds

                    pnl = proceeds - entry_cost
                    pnl_pct = (pnl / entry_cost) * 100 if entry_cost > 0 else 0
                    holding_days = (current_date - pos['entry_date']).days

                    trade = Trade(
                        ticker=ticker,
                        quantity=pos['shares'],
                        buy_date=pos['entry_date'].strftime('%Y-%m-%d'),
                        buy_price=pos['entry_price'],
                        sell_date=current_date.strftime('%Y-%m-%d'),
                        sell_price=signal.price,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        buy_reason=pos['entry_reason'],
                        sell_reason=signal.reason,
                        holding_days=holding_days,
                        max_drawdown=pos['max_drawdown'] * 100,
                        entry_amount=pos['shares'] * pos['entry_price'],
                        exit_amount=pos['shares'] * signal.price,
                        invested_amount=entry_cost,
                        total_amount=proceeds
                    )
                    trades.append(trade)

                    signals_data.append({
                        'date': current_date, 'signal': 'VENTA', 'ticker': ticker,
                        'price': signal.price, 'pnl': pnl, 'pnl_pct': pnl_pct,
                        'reason': signal.reason, 'capital_after': capital
                    })

                    del positions[ticker]

            # 2a. Ejecutar entradas pendientes confirmadas
            market_bullish = current_date in spy_bullish
            sizing_mult = 1.0 if market_bullish else 0.7
            confirmed_tickers = []
            for ticker in list(pending_entries.keys()):
                if ticker in positions or len(positions) >= self.max_positions:
                    pending_entries.pop(ticker, None)
                    continue
                if ticker not in ticker_data or current_date not in ticker_data[ticker].index:
                    continue
                pend = pending_entries[ticker]
                df = ticker_data[ticker]
                today_close = df.loc[current_date, 'Close']
                # Confirmar: precio + condiciones todavia fuertes
                if today_close >= pend['price'] * 0.995:
                    # Filtros de confirmacion
                    confirm_row = df.loc[current_date]
                    if confirm_row['RSI'] < 40 or confirm_row['MACD_Hist'] <= 0:
                        pending_entries.pop(ticker, None)
                        continue
                    shares = self.calculate_position_size(
                        pend['price'], pend['stop'], capital
                    )
                    shares = int(shares * sizing_mult)
                    cost_per_share = pend['price'] * (1 + self.commission_buy)
                    total_cost = shares * cost_per_share
                    if shares > 0 and total_cost <= capital:
                        capital -= total_cost
                        positions[ticker] = {
                            'ticker': ticker,
                            'shares': shares,
                            'entry_date': pend['entry_date'],
                            'entry_price': pend['price'],
                            'entry_reason': pend['reason'],
                            'entry_atr': pend['atr'],
                            'current_stop': pend['stop'],
                            'initial_stop': pend['stop'],
                            'take_profit': pend['tp'],
                            'max_price': pend['price'],
                            'max_drawdown': 0.0,
                            'cost_basis': total_cost,
                            'entry_score': pend.get('score', 30),
                        }
                        signals_data.append({
                            'date': current_date, 'signal': 'COMPRA CONFIRMADA', 'ticker': ticker,
                            'price': pend['price'], 'shares': shares,
                            'reason': pend['reason'], 'capital_after': capital
                        })
                pending_entries.pop(ticker, None)

            # 2b. Buscar nuevas entradas candidatas (guardar como pendientes)
            candidates = []
            for ticker, df in ticker_data.items():
                if ticker in positions or ticker in pending_entries:
                    continue
                if current_date not in df.index:
                    continue
                if len(positions) >= self.max_positions:
                    break

                current_data = df.loc[:current_date]
                # Warmup por ticker: necesita al menos 210 dias de datos
                if len(current_data) < 210:
                    continue

                # Verificar si hay senal de compra hoy
                last = current_data.iloc[-1]
                prev = current_data.iloc[-2] if len(current_data) > 1 else last

                # Simular verificacion de entrada directamente
                entry_ok = self._check_entry_fast(last, prev)
                if not entry_ok:
                    continue

                atr = last['ATR']
                stop = last['Close'] - (atr * self.strategy.config.get('atr_stop_mult', 2.5))
                risk = last['Close'] - stop
                tp = last['Close'] + (risk * self.strategy.config.get('tp_ratio', 4.0))

                # Score de confianza: basado en fuerza de senal
                score = (
                    last.get('Trend_Score', 0) * 10 +
                    min(last.get('RSI', 50), 70) * 0.5 +
                    last.get('Vol_Ratio', 1) * 5 +
                    min(last.get('MACD_Hist', 0) * 1000, 20)
                )

                candidates.append({
                    'ticker': ticker,
                    'price': last['Close'],
                    'stop': stop,
                    'tp': tp,
                    'atr': atr,
                    'score': score,
                    'reason': f"MOMENTUM | Trend:{last.get('Trend_Score',0)} RSI:{last['RSI']:.0f} Vol:{last.get('Vol_Ratio',1):.1f}x"
                })

            # Ordenar por score y guardar como pendientes
            candidates.sort(key=lambda x: x['score'], reverse=True)

            for cand in candidates:
                if len(positions) >= self.max_positions:
                    break

                ticker = cand['ticker']
                # Guardar como pendiente para confirmacion manana
                pending_entries[ticker] = {
                    'price': cand['price'],
                    'stop': cand['stop'],
                    'tp': cand['tp'],
                    'atr': cand['atr'],
                    'score': cand['score'],
                    'reason': cand['reason'],
                    'entry_date': current_date,
                }

            # 3. Calcular valor total del portafolio
            position_value = 0
            for ticker, pos in positions.items():
                if ticker in ticker_data and current_date in ticker_data[ticker].index:
                    position_value += pos['shares'] * ticker_data[ticker].loc[current_date, 'Close']

            total_value = capital + position_value

            equity_curve.append({
                'date': current_date,
                'capital': capital,
                'positions_value': position_value,
                'total_value': total_value,
                'num_positions': len(positions)
            })

        # Cerrar posiciones abiertas al final
        for ticker in list(positions.keys()):
            if ticker not in ticker_data:
                continue
            pos = positions[ticker]
            last_date = date_list[-1]
            if last_date in ticker_data[ticker].index:
                last_price = ticker_data[ticker].loc[last_date, 'Close']
                gross_proceeds = pos['shares'] * last_price
                commission = gross_proceeds * self.commission_sell
                entry_cost = pos['cost_basis']
                gross_pnl = gross_proceeds - entry_cost
                tax = max(0, gross_pnl * self.tax_rate)
                proceeds = gross_proceeds - commission - tax
                capital += proceeds

                pnl = proceeds - entry_cost
                pnl_pct = (pnl / entry_cost) * 100 if entry_cost > 0 else 0
                holding_days = (last_date - pos['entry_date']).days

                trade = Trade(
                    ticker=ticker, quantity=pos['shares'],
                    buy_date=pos['entry_date'].strftime('%Y-%m-%d'),
                    buy_price=pos['entry_price'],
                    sell_date=last_date.strftime('%Y-%m-%d'),
                    sell_price=last_price,
                    pnl=pnl, pnl_pct=pnl_pct,
                    buy_reason=pos['entry_reason'],
                    sell_reason="FIN DE DATOS",
                    holding_days=holding_days,
                    max_drawdown=pos['max_drawdown'] * 100,
                    entry_amount=pos['shares'] * pos['entry_price'],
                    exit_amount=pos['shares'] * last_price,
                    invested_amount=entry_cost,
                    total_amount=proceeds
                )
                trades.append(trade)

        # Calcular metricas por ticker
        ticker_results = {}
        for trade in trades:
            t = trade.ticker
            if t not in ticker_results:
                ticker_results[t] = {
                    'total_trades': 0, 'wins': 0, 'losses': 0,
                    'win_rate': 0, 'total_pnl': 0, 'avg_pnl': 0,
                    'avg_pnl_pct': 0, 'best_trade': 0, 'worst_trade': 0,
                    'final_capital': self.initial_capital,
                    'return_pct': 0, 'pnl_list': [], 'pnl_pct_list': []
                }
            r = ticker_results[t]
            r['total_trades'] += 1
            r['total_pnl'] += trade.pnl
            r['pnl_list'].append(trade.pnl)
            r['pnl_pct_list'].append(trade.pnl_pct)
            if trade.pnl > 0:
                r['wins'] += 1
            else:
                r['losses'] += 1

        for t, r in ticker_results.items():
            r['win_rate'] = r['wins'] / r['total_trades'] * 100 if r['total_trades'] > 0 else 0
            r['avg_pnl'] = np.mean(r['pnl_list']) if r['pnl_list'] else 0
            r['avg_pnl_pct'] = np.mean(r['pnl_pct_list']) if r['pnl_pct_list'] else 0
            r['best_trade'] = max(r['pnl_list']) if r['pnl_list'] else 0
            r['worst_trade'] = min(r['pnl_list']) if r['pnl_list'] else 0
            # Final capital per ticker = initial + proportional share of total PnL
            ticker_share = r['total_pnl'] / sum(tr.pnl for tr in trades) if sum(tr.pnl for tr in trades) != 0 else 0
            r['final_capital'] = self.initial_capital * (1 + ticker_share * (capital + sum(pos['shares'] * ticker_data[t].iloc[-1]['Close'] for t, pos in positions.items() if t in ticker_data) - self.initial_capital) / self.initial_capital)
            r['return_pct'] = ((r['final_capital'] - self.initial_capital) / self.initial_capital) * 100

        # Imprimir resumen
        print("\n" + "=" * 60)
        print("BACKTESTING PORTAFOLIO - CAPITAL COMPARTIDO")
        print("=" * 60)

        total_pnl = capital - self.initial_capital
        # Agregar valor de posiciones abiertas
        open_value = sum(
            pos['shares'] * ticker_data[t].iloc[-1]['Close']
            for t, pos in positions.items() if t in ticker_data
        )
        final_value = capital + open_value
        total_return_pct = ((final_value - self.initial_capital) / self.initial_capital) * 100

        for t, r in sorted(ticker_results.items(), key=lambda x: x[1]['total_pnl'], reverse=True):
            if r['total_trades'] > 0:
                print(f"  {t:6s}: {r['total_trades']:3d} trades | WR: {r['win_rate']:5.1f}% | "
                      f"P&L: ${r['total_pnl']:>10,.2f}")

        print(f"\n  Trades totales: {len(trades)}")
        print(f"  Win Rate global: {len([t for t in trades if t.pnl > 0])/len(trades)*100:.1f}%" if trades else "  N/A")
        print(f"  Capital inicial: ${self.initial_capital:,.2f}")
        print(f"  Capital final (efectivo): ${capital:,.2f}")
        print(f"  Valor posiciones abiertas: ${open_value:,.2f}")
        print(f"  Valor total final: ${final_value:,.2f}")
        print(f"  Retorno total: {total_return_pct:,.2f}%")

        years = (end - start).days / 365.25
        if years > 0:
            cagr = ((final_value / self.initial_capital) ** (1 / years) - 1) * 100
            print(f"  CAGR: {cagr:.2f}%")
            print(f"  Periodo: {years:.1f} anos")

        return {
            'trades': trades,
            'signals': signals_data,
            'ticker_results': ticker_results,
            'initial_capital': self.initial_capital,
            'final_capital': final_value,
            'equity_curve': equity_curve,
            'cagr': cagr if years > 0 else 0,
            'total_return': total_return_pct
        }

    def _check_entry_fast(self, last, prev) -> bool:
        """Verificacion rapida de condiciones de entrada"""
        # Tendencia
        trend_up = last['Close'] > last['EMA_50'] and last['EMA_50'] > last['EMA_200']
        if not trend_up:
            return False

        # RSI
        if last['RSI'] > 80 or last['RSI'] < 35:
            return False

        # MACD
        if last['MACD_Hist'] <= 0:
            return False

        # Precio sobre EMA8
        if last['Close'] <= last['EMA_8']:
            return False

        # Volumen
        if last['Vol_Ratio'] < 1.0:
            return False

        # Trend score
        if last.get('Trend_Score', 0) < 3:
            return False

        return True

    # Mantener compatibilidad con codigo existente
    def run_full_backtest(self) -> Dict:
        """Wrapper para compatibilidad"""
        return self.run_portfolio_backtest()
