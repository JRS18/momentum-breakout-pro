# -*- coding: utf-8 -*-
"""
Bot de Alertas Diarias - Momentum Breakout Pro
Monitorea 11 tickers y envia señales por email
"""
import json, os, sys, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

from operaciones_tracker import cargar_operaciones, calcular_estado, registrar_compra, registrar_venta, generar_tracker_excel, fmt_ars

RUTA = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(RUTA, 'config.json')
ESTADO_PATH = os.path.join(RUTA, 'estado.json')
DATA_DIR = os.path.join(RUTA, 'data')

os.makedirs(DATA_DIR, exist_ok=True)

# Ratios de conversión CEDEARs (24:1 = 24 CEDEARs = 1 acción en EE.UU.)
CEDEAR_RATIOS = {
    'NVDA': 24, 'AMD': 3, 'GOOGL': 11, 'META': 8, 'CRWD': 4,
    'RIOT': 10, 'AMC': 20, 'MRNA': 5, 'BB': 10, 'PLTR': 10, 'NET': 5
}

def fmt_ars(valor):
    """Formatea números en formato argentino (punto para miles, coma para decimales)"""
    return f"{valor:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

def obtener_dolar_ccl():
    """Obtiene el precio del dolar CCL actual"""
    try:
        import requests
        r = requests.get('https://dolarapi.com/v1/dolares/ccl', timeout=5)
        data = r.json()
        return data.get('venta', 1550)
    except:
        return 1550


def cargar_config():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    raw = json.dumps(cfg)
    import re
    for match in re.findall(r'\$\{(\w+)\}', raw):
        val = os.environ.get(match, '')
        raw = raw.replace(f'${{{match}}}', val)
    return json.loads(raw)


def guardar_estado(estado):
    with open(ESTADO_PATH, 'w') as f:
        json.dump(estado, f, indent=2, default=str)


def cargar_estado():
    if os.path.exists(ESTADO_PATH):
        with open(ESTADO_PATH) as f:
            return json.load(f)
    return {
        'posiciones': {},
        'capital_disponible': 5000,
        'historial': [],
        'ultima_ejecucion': ''
    }


def calcular_indicators(df):
    df = df.copy()
    df['EMA_8'] = df['Close'].ewm(span=8, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_100'] = df['Close'].ewm(span=100, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()

    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    df['Vol_SMA'] = df['Volume'].rolling(20).mean()
    df['Vol_Ratio'] = df['Volume'] / df['Vol_SMA']

    df['Trend_Score'] = 0
    df.loc[df['Close'] > df['EMA_50'], 'Trend_Score'] += 1
    df.loc[df['EMA_50'] > df['EMA_200'], 'Trend_Score'] += 1
    df.loc[df['Close'] > df['EMA_8'], 'Trend_Score'] += 1
    df.loc[df['RSI'] > 50, 'Trend_Score'] += 1
    df.loc[df['MACD_Hist'] > 0, 'Trend_Score'] += 1

    return df


def verificar_entrada(df):
    if len(df) < 210:
        return False, ""

    last = df.iloc[-1]
    prev = df.iloc[-2]

    if last['Close'] <= last['EMA_50']:
        return False, "Close <= EMA50"
    if not (last['EMA_50'] > last['EMA_200']):
        return False, "EMA50 <= EMA200"
    if last['RSI'] > 80 or last['RSI'] < 35:
        return False, f"RSI {last['RSI']:.0f} fuera de rango"
    if last['MACD_Hist'] <= 0:
        return False, "MACD <= 0"
    if last['Close'] <= last['EMA_8']:
        return False, "Close <= EMA8"
    if last['Vol_Ratio'] < 1.0:
        return False, f"Volumen {last['Vol_Ratio']:.1f}x < 1.0"
    if last.get('Trend_Score', 0) < 3:
        return False, f"Trend Score {last.get('Trend_Score', 0)} < 3"

    return True, (
        f"Trend:{last.get('Trend_Score',0)} "
        f"RSI:{last['RSI']:.0f} "
        f"MACD:{last['MACD_Hist']:.4f} "
        f"Vol:{last['Vol_Ratio']:.1f}x"
    )


def verificar_salida(df, pos):
    if len(df) < 5:
        return False, ""

    last = df.iloc[-1]
    entry_price = pos['entry_price']
    current_atr = last['ATR']

    trailing_stop = last['Close'] - (current_atr * 5.0)
    if last['Close'] < trailing_stop:
        return True, f"Trailing Stop ATR: Close ${last['Close']:.2f} < Stop ${trailing_stop:.2f}"

    gain = last['Close'] - entry_price
    risk = entry_price - (entry_price - current_atr * 2.0)
    if gain >= 6.0 * risk:
        return True, f"Take Profit 6x: ganancia ${gain:.2f}"

    if last['RSI'] < 25 and last['MACD_Hist'] < 0:
        return True, f"Reversal: RSI {last['RSI']:.0f} + MACD negativo"

    return False, ""


def enviar_email(asunto, cuerpo, config):
    email_cfg = config['email']
    if not email_cfg.get('enabled') or not email_cfg.get('sender_email'):
        return False

    receivers = email_cfg.get('receiver_emails', [])
    if isinstance(receivers, str):
        receivers = [receivers]
    if not receivers:
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"[Momentum Breakout] {asunto}"
    msg['From'] = email_cfg['sender_email']
    msg['To'] = email_cfg['sender_email']
    msg['Bcc'] = ', '.join(receivers)

    html = f"""
    <html><body style="font-family:Arial;font-size:14px;background:#1a1a2e;padding:20px;color:#e0e0e0;">
    <div style="max-width:700px;margin:auto;background:#16213e;border-radius:10px;padding:25px;border:1px solid #0f3460;">
    {cuerpo}
    <hr style="border-color:#0f3460">
    <p style="color:#666;font-size:12px;">Momentum Breakout Pro Bot - {datetime.now().strftime('%Y-%m-%d %H:%M')}</p></div></body></html>
    """
    msg.attach(MIMEText(html, 'html'))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(email_cfg['smtp_server'], email_cfg['smtp_port']) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(email_cfg['sender_email'], email_cfg['sender_password'])
            server.sendmail(email_cfg['sender_email'], receivers, msg.as_string())
        print(f"  [EMAIL] Enviado a {', '.join(receivers)}")
        return True
    except Exception as e:
        print(f"  [EMAIL ERROR] {e}")
        return False


def calcular_monto_compra(capital, posiciones_abiertas, max_posiciones):
    """Calcula cuanto invertir por operacion"""
    posiciones_disponibles = max_posiciones - len(posiciones_abiertas)
    if posiciones_disponibles <= 0:
        return 0
    monto_por_posicion = capital * 0.80
    return monto_por_posicion


def generar_html_reporte(señales, posiciones, capital, config):
    monto_compra = calcular_monto_compra(capital, posiciones, config['max_posiciones'])
    ccl = obtener_dolar_ccl()

    html = f"""
    <h2 style="color:#74b9ff;margin-top:0;">Señales del Dia - {datetime.now().strftime('%Y-%m-%d %H:%M')}</h2>
    
    <div style="background:#0f3460;border-radius:8px;padding:15px;margin:15px 0;">
      <p style="color:#fff;font-size:14px;margin:0 0 10px 0;">Para registrar operaciones:</p>
      <ol style="color:#aaa;font-size:13px;margin:0;padding-left:20px;">
        <li>Ejecutá <b style="color:#74b9ff;">abrir_formulario.bat</b></li>
        <li>Completá precio y cantidad</li>
        <li>Click en <b style="color:#00b894;">Copiar Comando</b></li>
        <li>Ejecutá <b style="color:#74b9ff;">pegar_y_ejecutar.bat</b></li>
        <li>Click derecho para pegar, Enter</li>
      </ol>
    </div>
    
    <table style="width:100%;border-collapse:collapse;margin:15px 0;">
      <tr><td style="padding:8px;border-bottom:1px solid #0f3460;color:#aaa;">Capital Disponible</td><td style="padding:8px;border-bottom:1px solid #0f3460;font-weight:bold;text-align:right;">USD {capital:,.2f}</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #0f3460;color:#aaa;">Posiciones Abiertas</td><td style="padding:8px;border-bottom:1px solid #0f3460;font-weight:bold;text-align:right;">{len(posiciones)}/{config['max_posiciones']}</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #0f3460;color:#aaa;">Monto a Invertir por Señal</td><td style="padding:8px;border-bottom:1px solid #0f3460;font-weight:bold;text-align:right;color:#00b894;">USD {monto_compra:,.2f}</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #0f3460;color:#aaa;">Dolar CCL</td><td style="padding:8px;border-bottom:1px solid #0f3460;font-weight:bold;text-align:right;">${fmt_ars(ccl)}</td></tr>
    </table>
    """

    if posiciones:
        html += """
        <h3 style="color:#fdcb6e;">Posiciones Activas</h3>
        <table style="width:100%;border-collapse:collapse;">
        <tr>
            <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:left;">Ticker</th>
            <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;">Entrada</th>
            <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;">Actual</th>
            <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;">CEDEARs</th>
            <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;">Invertido</th>
            <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;">P&L</th>
            <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;">Dias</th>
        </tr>
        """
        for ticker, pos in posiciones.items():
            ratio = CEDEAR_RATIOS.get(ticker, 1)
            pnl_pct = ((pos.get('precio_actual', pos['entry_price']) / pos['entry_price']) - 1) * 100
            dias = (datetime.now() - datetime.fromisoformat(pos['entry_date'])).days
            color = '#00b894' if pnl_pct >= 0 else '#e17055'
            invertido_ars = pos.get('shares', 0) * pos['entry_price'] * ccl / ratio
            html += f"""
            <tr>
                <td style="padding:6px;border-bottom:1px solid #0f3460;font-weight:bold;">{ticker}</td>
                <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;">${fmt_ars(pos['entry_price'] * ccl / ratio)} ARS</td>
                <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;">${fmt_ars(pos.get('precio_actual', 0) * ccl / ratio)} ARS</td>
                <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;">{pos.get('shares', 0)}</td>
                <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;">${fmt_ars(invertido_ars)} ARS</td>
                <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;color:{color};"><b>{pnl_pct:+.2f}%</b></td>
                <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;">{dias}</td>
            </tr>
            """
        html += "</table>"

    if señales:
        compras = [s for s in señales if s['tipo'] == 'COMPRA']
        ventas = [s for s in señales if s['tipo'] == 'VENTA']
        mantenes = [s for s in señales if s['tipo'] == 'MANTENER']

        if compras:
            html += f"""
            <h3 style="color:#00b894;">Señales de COMPRA</h3>
            <table style="width:100%;border-collapse:collapse;">
            <tr>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:left;width:60px;">Ticker</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;width:100px;">P. CEDEAR</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;width:120px;">Inversion</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;width:70px;">CEDEARs</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;width:40px;">RSI</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:left;">Razon</th>
            </tr>
            """
            for s in compras:
                ratio = CEDEAR_RATIOS.get(s['ticker'], 1)
                precio_cedear_ars = s['precio'] * ccl / ratio
                monto_ars = monto_compra * ccl
                cedears = int(monto_ars / precio_cedear_ars) if precio_cedear_ars > 0 else 0
                monto_real_ars = cedears * precio_cedear_ars
                html += f"""
                <tr>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;font-weight:bold;">{s['ticker']}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;">${fmt_ars(precio_cedear_ars)}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;color:#00b894;font-weight:bold;">${fmt_ars(monto_real_ars)}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;font-weight:bold;">{cedears}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;">{s['rsi']:.0f}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;font-size:11px;">{s['razon']}</td>
                </tr>
                """
            html += "</table>"

            # Generar mensaje WhatsApp para asesor
            if len(compras) == 1:
                s = compras[0]
                ratio = CEDEAR_RATIOS.get(s['ticker'], 1)
                precio_cedear_ars = s['precio'] * ccl / ratio
                monto_ars = monto_compra * ccl
                cedears = int(monto_ars / precio_cedear_ars) if precio_cedear_ars > 0 else 0
                total_ars = cedears * precio_cedear_ars
                msg_whatsapp = f"Lucas, buenas tardes. Quisiera realizar una compra de CEDEARs de {s['ticker']}.\n\nTicker: {s['ticker']}\nRatio: {ratio}:1 ({ratio} CEDEARs = 1 accion en EE.UU.)\n{cedears} x ${fmt_ars(precio_cedear_ars)} ARS = ${fmt_ars(total_ars)} ARS\n\nQuedo atento."
            elif len(compras) > 1:
                lineas = []
                monto_total = 0
                for s in compras:
                    ratio = CEDEAR_RATIOS.get(s['ticker'], 1)
                    precio_cedear_ars = s['precio'] * ccl / ratio
                    monto_ars = monto_compra * ccl
                    cedears = int(monto_ars / precio_cedear_ars) if precio_cedear_ars > 0 else 0
                    total_ars = cedears * precio_cedear_ars
                    lineas.append(f"• {s['ticker']}: {cedears} x ${fmt_ars(precio_cedear_ars)} ARS = ${fmt_ars(total_ars)} ARS")
                    monto_total += total_ars
                msg_whatsapp = f"Lucas, buenas tardes. Quisiera realizar compras de CEDEARs:\n\n" + "\n".join(lineas) + f"\n\nMonto total: ${fmt_ars(monto_total)} ARS\n\nQuedo atento."
            else:
                msg_whatsapp = ""

            if msg_whatsapp:
                html += f"""
                <div style="background:#25D366;border-radius:8px;padding:15px;margin:15px 0;">
                  <p style="margin:0 0 10px 0;color:#fff;font-weight:bold;">Mensaje para tu asesor (cortar y pegar en WhatsApp):</p>
                  <div style="background:#fff;border-radius:5px;padding:10px;color:#333;font-family:monospace;white-space:pre-wrap;">{msg_whatsapp}</div>
                </div>
                """

        if ventas:
            html += f"""
            <h3 style="color:#e17055;">Señales de VENTA</h3>
            <table style="width:100%;border-collapse:collapse;">
            <tr>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:left;width:60px;">Ticker</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;width:100px;">P. CEDEAR</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;width:120px;">Ingreso</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;width:70px;">CEDEARs</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:left;">Razon</th>
            </tr>
            """
            for s in ventas:
                ratio = CEDEAR_RATIOS.get(s['ticker'], 1)
                precio_cedear_ars = s['precio'] * ccl / ratio
                # Buscar posicion activa para saber cuantos cedears tenemos
                pos_act = posiciones.get(s['ticker'], {})
                cedears = pos_act.get('shares', 0)
                ingreso_ars = cedears * precio_cedear_ars if cedears > 0 else 0
                html += f"""
                <tr>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;font-weight:bold;">{s['ticker']}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;">${fmt_ars(precio_cedear_ars)}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;color:#e17055;font-weight:bold;">${fmt_ars(ingreso_ars)}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;font-weight:bold;">{cedears}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;font-size:11px;">{s['razon']}</td>
                </tr>
                """
            html += "</table>"

            # Generar mensaje WhatsApp para venta
            if len(ventas) == 1:
                s = ventas[0]
                ratio = CEDEAR_RATIOS.get(s['ticker'], 1)
                precio_cedear_ars = s['precio'] * ccl / ratio
                pos_act = posiciones.get(s['ticker'], {})
                cedears = pos_act.get('shares', 0)
                msg_whatsapp_v = f"Lucas, buenas tardes. Quisiera realizar una venta de CEDEARs de {s['ticker']}.\n\nTicker: {s['ticker']}\nRatio: {ratio}:1\n{cedears} CEDEARs a ${fmt_ars(precio_cedear_ars)} ARS\n\nQuedo atento."
            elif len(ventas) > 1:
                lineas = []
                for s in ventas:
                    ratio = CEDEAR_RATIOS.get(s['ticker'], 1)
                    precio_cedear_ars = s['precio'] * ccl / ratio
                    pos_act = posiciones.get(s['ticker'], {})
                    cedears = pos_act.get('shares', 0)
                    lineas.append(f"• {s['ticker']}: {cedears} CEDEARs a ${fmt_ars(precio_cedear_ars)} ARS")
                msg_whatsapp_v = f"Lucas, buenas tardes. Quisiera realizar ventas de CEDEARs:\n\n" + "\n".join(lineas) + "\n\nQuedo atento."
            else:
                msg_whatsapp_v = ""

            if msg_whatsapp_v:
                html += f"""
                <div style="background:#25D366;border-radius:8px;padding:15px;margin:15px 0;">
                  <p style="margin:0 0 10px 0;color:#fff;font-weight:bold;">Mensaje para tu asesor (cortar y pegar en WhatsApp):</p>
                  <div style="background:#fff;border-radius:5px;padding:10px;color:#333;font-family:monospace;white-space:pre-wrap;">{msg_whatsapp_v}</div>
                </div>
                """

        if mantenes:
            html += """
            <h3 style="color:#74b9ff;">Mantener</h3>
            <table style="width:100%;border-collapse:collapse;">
            <tr>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:left;">Ticker</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:right;">P&L</th>
                <th style="padding:6px;border-bottom:2px solid #0f3460;color:#aaa;text-align:left;">Razón</th>
            </tr>
            """
            for s in mantenes:
                color = '#00b894' if s.get('pnl_pct', 0) >= 0 else '#e17055'
                html += f"""
                <tr>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;font-weight:bold;">{s['ticker']}</td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;text-align:right;color:{color};"><b>{s.get('pnl_pct', 0):+.2f}%</b></td>
                    <td style="padding:6px;border-bottom:1px solid #0f3460;font-size:12px;">{s.get('razon', '')}</td>
                </tr>
                """
            html += "</table>"

    html += """
    <p style="color:#636e72;font-size:11px;margin-top:20px;border-top:1px solid #0f3460;padding-top:10px;">
        Momentum Breakout Pro | Sistema automatico de señales
    </p>
    """
    return html


def comprar_acciones(ticker, precio, cantidad):
    """Registra una compra manual"""
    config = cargar_config()
    estado = cargar_estado()
    ticker = ticker.upper()

    if ticker in estado.get('posiciones', {}):
        print(f"  [ERROR] Ya tenes posicion en {ticker}")
        return False

    if len(estado.get('posiciones', {})) >= config['max_posiciones']:
        print(f"  [ERROR] Ya tenes {config['max_posiciones']} posiciones (maximo)")
        return False

    costo = cantidad * precio * (1 + config['comision'])
    if costo > estado.get('capital_disponible', 0):
        print(f"  [ERROR] Capital insuficiente: necesitas ${costo:,.2f}, tenes ${estado.get('capital_disponible', 0):,.2f}")
        return False

    if 'posiciones' not in estado:
        estado['posiciones'] = {}

    estado['posiciones'][ticker] = {
        'entry_price': precio,
        'shares': cantidad,
        'entry_date': datetime.now().isoformat(),
        'precio_actual': precio,
        'costo_total': costo
    }
    estado['capital_disponible'] -= costo
    estado['historial'].append({
        'fecha': datetime.now().strftime('%Y-%m-%d'),
        'accion': 'COMPRA',
        'ticker': ticker,
        'precio': precio,
        'shares': cantidad,
        'costo': costo
    })
    guardar_estado(estado)

    print(f"  [OK] Compra registrada: {cantidad} acciones de {ticker} a ${precio:.2f}")
    print(f"  [OK] Costo total: ${costo:,.2f}")
    print(f"  [OK] Capital restante: ${estado['capital_disponible']:,.2f}")
    return True


def vender_acciones(ticker, precio):
    """Registra una venta manual"""
    config = cargar_config()
    estado = cargar_estado()
    ticker = ticker.upper()

    if ticker not in estado.get('posiciones', {}):
        print(f"  [ERROR] No tenes posicion en {ticker}")
        return False

    pos = estado['posiciones'][ticker]
    cantidad = pos['shares']
    ingreso = cantidad * precio * (1 - config['comision'])
    pnl = ingreso - pos['costo_total']

    estado['capital_disponible'] += ingreso
    del estado['posiciones'][ticker]
    estado['historial'].append({
        'fecha': datetime.now().strftime('%Y-%m-%d'),
        'accion': 'VENTA',
        'ticker': ticker,
        'precio': precio,
        'shares': cantidad,
        'ingreso': ingreso,
        'pnl': pnl
    })
    guardar_estado(estado)

    print(f"  [OK] Venta registrada: {cantidad} acciones de {ticker} a ${precio:.2f}")
    print(f"  [OK] Ingreso: ${ingreso:,.2f}")
    print(f"  [OK] P&L: ${pnl:,.2f}")
    print(f"  [OK] Capital total: ${estado['capital_disponible']:,.2f}")
    return True


def ejecutar_bot():
    hoy = datetime.now().strftime('%Y-%m-%d')
    print(f"\n{'='*60}")
    print(f"  Momentum Breakout Pro Bot - {hoy} {datetime.now().strftime('%H:%M')}")
    print(f"{'='*60}")

    config = cargar_config()
    estado = cargar_estado()

    tickers = config['tickers']
    print(f"  Tickers: {', '.join(tickers)}")

    end = datetime.now()
    start = end - timedelta(days=400)
    señales = []
    posiciones = estado.get('posiciones', {})

    for ticker in tickers:
        try:
            df = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                             end=end.strftime('%Y-%m-%d'), progress=False, auto_adjust=True)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = calcular_indicators(df)

            last = df.iloc[-1]
            precio = float(last['Close'])
            rsi = float(last['RSI'])

            if ticker in posiciones:
                pos = posiciones[ticker]
                pos['precio_actual'] = precio
                debo_vender, razon = verificar_salida(df, pos)
                if debo_vender:
                    pnl_pct = ((precio / pos['entry_price']) - 1) * 100
                    señales.append({
                        'tipo': 'VENTA', 'ticker': ticker,
                        'precio': precio, 'razon': razon,
                        'pnl_pct': pnl_pct
                    })
                    del posiciones[ticker]
                    estado['capital_disponible'] += pos.get('shares', 0) * precio * 0.984
                else:
                    pnl_pct = ((precio / pos['entry_price']) - 1) * 100
                    señales.append({
                        'tipo': 'MANTENER', 'ticker': ticker,
                        'precio': precio, 'pnl_pct': pnl_pct, 'razon': ''
                    })
            else:
                if len(posiciones) < config['max_posiciones']:
                    entrada_ok, razon_entrada = verificar_entrada(df)
                    if entrada_ok:
                        score = (
                            last.get('Trend_Score', 0) * 10 +
                            min(last.get('RSI', 50), 70) * 0.5 +
                            last.get('Vol_Ratio', 1) * 5 +
                            min(last.get('MACD_Hist', 0) * 1000, 20)
                        )
                        señales.append({
                            'tipo': 'COMPRA', 'ticker': ticker,
                            'precio': precio, 'rsi': rsi,
                            'score': score, 'razon': razon_entrada
                        })
                    else:
                        pass
                else:
                    pass

        except Exception as e:
            print(f"  [ERROR] {ticker}: {e}")
            continue

    señales.sort(key=lambda x: x.get('score', 0) if x['tipo'] == 'COMPRA' else 0, reverse=True)

    print(f"\n  Resumen:")
    print(f"  Posiciones activas: {len(posiciones)}")
    for t, p in posiciones.items():
        pnl = ((p.get('precio_actual', p['entry_price']) / p['entry_price']) - 1) * 100
        print(f"    {t}: ${p['entry_price']:.2f} -> ${p.get('precio_actual', 0):.2f} ({pnl:+.2f}%)")

    compras = [s for s in señales if s['tipo'] == 'COMPRA']
    ventas = [s for s in señales if s['tipo'] == 'VENTA']
    print(f"  Señales COMPRA: {len(compras)}")
    for s in compras:
        print(f"    {s['ticker']}: ${s['precio']:.2f} (score: {s.get('score', 0):.0f})")
    print(f"  Señales VENTA: {len(ventas)}")
    for s in ventas:
        print(f"    {s['ticker']}: ${s['precio']:.2f} ({s['razon']})")

    estado['posiciones'] = posiciones
    estado['ultima_ejecucion'] = hoy
    guardar_estado(estado)

    if config['email']['enabled'] and config['email']['sender_email']:
        html = generar_html_reporte(señales, posiciones, estado['capital_disponible'], config)
        n_acciones = len(compras) + len(ventas)
        asunto = "Sin señales" if n_acciones == 0 else f"{len(compras)} compra(s), {len(ventas)} venta(s)"
        enviar_email(asunto, html, config)
    else:
        print("  [EMAIL] No configurado")

    print(f"{'='*60}\n")
    return señales


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--comprar' and len(sys.argv) >= 5:
            ticker = sys.argv[2]
            precio = float(sys.argv[3])
            cantidad = int(sys.argv[4])
            comprar_acciones(ticker, precio, cantidad)
        elif sys.argv[1] == '--vender' and len(sys.argv) >= 4:
            ticker = sys.argv[2]
            precio = float(sys.argv[3])
            vender_acciones(ticker, precio)
        elif sys.argv[1] == '--estado':
            estado = cargar_estado()
            print(json.dumps(estado, indent=2, default=str))
        elif sys.argv[1] == '--registrar-compra' and len(sys.argv) >= 6:
            from operaciones_tracker import registrar_compra
            ticker = sys.argv[2]
            cedears = int(sys.argv[3])
            precio = float(sys.argv[4])
            ccl = float(sys.argv[5])
            registrar_compra(ticker, datetime.now().strftime('%Y-%m-%d'), cedears, precio, ccl)
            generar_tracker_excel()
            print(f"  [OK] Compra registrada: {cedears} CEDEARs de {ticker} a ARS {precio}")
        elif sys.argv[1] == '--registrar-venta' and len(sys.argv) >= 6:
            from operaciones_tracker import registrar_venta
            ticker = sys.argv[2]
            cedears = int(sys.argv[3])
            precio = float(sys.argv[4])
            ccl = float(sys.argv[5])
            registrar_venta(ticker, datetime.now().strftime('%Y-%m-%d'), cedears, precio, ccl)
            generar_tracker_excel()
            print(f"  [OK] Venta registrada: {cedears} CEDEARs de {ticker} a ARS {precio}")
        elif sys.argv[1] == '--tracker':
            estado = calcular_estado()
            print(f"Capital inicial: USD {estado['capital_inicial']:,.2f}")
            print(f"Capital disponible: ARS {fmt_ars(estado['capital_disponible_ars'])}")
            print(f"Posiciones activas: {len(estado['posiciones'])}")
            for t, p in estado['posiciones'].items():
                print(f"  {t}: {p['cedears']} CEDEARs (invertido: ARS {fmt_ars(p['costo_total'])})")
            generar_tracker_excel()
        else:
            print("Uso:")
            print("  python bot_alertas.py                              # Ejecutar bot")
            print("  python bot_alertas.py --comprar TICKER PRECIO CANTIDAD")
            print("  python bot_alertas.py --vender TICKER PRECIO")
            print("  python bot_alertas.py --estado                     # Ver estado")
            print("  python bot_alertas.py --registrar-compra TICKER CEDEARS PRECIO CCL")
            print("  python bot_alertas.py --registrar-venta TICKER CEDEARS PRECIO CCL")
            print("  python bot_alertas.py --tracker                    # Ver resumen y generar Excel")
    else:
        ejecutar_bot()
