# -*- coding: utf-8 -*-
"""
Script para actualizar tickers automáticamente
Ejecutar periódicamente para mantener los mejores activos
"""
import json
import os
import sys

RUTA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RUTA)

from ticker_selector import ejecutar_seleccion, cargar_seleccion


def actualizar_configuracion():
    """
    Ejecuta la selección y actualiza config.json automáticamente.
    """
    print("=" * 60)
    print("  ACTUALIZACION AUTOMATICA DE TICKERS")
    print("=" * 60)
    
    # Ejecutar selección
    config = ejecutar_seleccion(n=11)
    
    # Leer config.json actual
    config_path = os.path.join(RUTA, 'config.json')
    with open(config_path) as f:
        config_actual = json.load(f)
    
    # Actualizar tickers
    config_actual['tickers'] = config['tickers']
    config_actual['descripcion'] = f"Swing trading con {len(config['tickers'])} tickers seleccionados automaticamente"
    
    # Guardar config.json
    with open(config_path, 'w') as f:
        json.dump(config_actual, f, indent=2)
    
    print(f"\n[OK] config.json actualizado con {len(config['tickers'])} tickers")
    print(f"  Tickers: {config['tickers']}")
    
    # Actualizar ratios en bot_alertas.py
    actualizar_bot_ratios(config['ratios'])
    
    # Actualizar ratios en operaciones_tracker.py
    actualizar_tracker_ratios(config['ratios'])
    
    # Actualizar tickers en strategy_config.py
    actualizar_strategy_config(config['tickers'])
    
    print(f"\n[OK] Todos los archivos actualizados")
    return config


def actualizar_bot_ratios(ratios):
    """
    Actualiza los ratios en bot_alertas.py
    """
    bot_path = os.path.join(RUTA, 'bot_alertas.py')
    
    with open(bot_path, 'r', encoding='utf-8') as f:
        contenido = f.read()
    
    # Crear nuevo diccionario de ratios
    ratios_str = json.dumps(ratios, indent=4)
    
    # Reemplazar el diccionario de ratios
    import re
    patron = r"CEDEAR_RATIOS\s*=\s*\{[^}]+\}"
    nuevo_ratio = f"CEDEAR_RATIOS = {ratios_str}"
    
    contenido = re.sub(patron, nuevo_ratio, contenido)
    
    with open(bot_path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    
    print(f"[OK] bot_alertas.py actualizado")


def actualizar_tracker_ratios(ratios):
    """
    Actualiza los ratios en operaciones_tracker.py
    """
    tracker_path = os.path.join(RUTA, 'operaciones_tracker.py')
    
    with open(tracker_path, 'r', encoding='utf-8') as f:
        contenido = f.read()
    
    # Crear nuevo diccionario de ratios
    ratios_str = json.dumps(ratios, indent=4)
    
    # Reemplazar el diccionario de ratios
    import re
    patron = r"CEDEAR_RATIOS\s*=\s*\{[^}]+\}"
    nuevo_ratio = f"CEDEAR_RATIOS = {ratios_str}"
    
    contenido = re.sub(patron, nuevo_ratio, contenido)
    
    with open(tracker_path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    
    print(f"[OK] operaciones_tracker.py actualizado")


def actualizar_strategy_config(tickers):
    """
    Actualiza la lista de tickers en strategy_config.py
    """
    config_path = os.path.join(RUTA, 'strategies', 'strategy_config.py')
    
    with open(config_path, 'r', encoding='utf-8') as f:
        contenido = f.read()
    
    import re
    # Reemplazar la lista de tickers
    patron = r"TICKERS\s*=\s*\[[^\]]+\]"
    tickers_str = f"TICKERS = {tickers}"
    contenido = re.sub(patron, tickers_str, contenido)
    
    # Actualizar comentario de fecha
    from datetime import datetime
    fecha = datetime.now().strftime('%Y-%m-%d')
    patron_fecha = r"# Última selección: \d{4}-\d{2}-\d{2}"
    contenido = re.sub(patron_fecha, f"# Última selección: {fecha}", contenido)
    
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    
    print(f"[OK] strategies/strategy_config.py actualizado")


if __name__ == '__main__':
    actualizar_configuracion()
