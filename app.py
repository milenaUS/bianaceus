import os
import time
from datetime import datetime
import numpy as np
from binance.client import Client

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(API_KEY, API_SECRET)

interval = Client.KLINE_INTERVAL_1HOUR
limit = 100
log_file = "conversion_log.txt"

def get_usdt_symbols():
    # Solo símbolos spot que terminan en USDT y están activos
    info = client.get_exchange_info()
    return [s['symbol'] for s in info['symbols'] if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']

def get_ohlc(symbol):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    closes = [float(k[4]) for k in klines]
    opens = [float(k[1]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    return closes, opens, highs, lows

def rsi(prices, period=14):
    prices = np.array(prices)
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi_arr = np.zeros_like(prices)
    rsi_arr[:period] = 100. - 100. / (1. + rs)
    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        upval = delta if delta > 0 else 0.
        downval = -delta if delta < 0 else 0.
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi_arr[i] = 100. - 100. / (1. + rs)
    return rsi_arr

def detect_patterns(closes, opens, highs, lows):
    patterns = []
    ma5 = np.mean(closes[-5:])
    ma20 = np.mean(closes[-20:])
    rsi_val = rsi(closes)[-1]
    if ma5 > ma20:
        patterns.append("Cruce alcista MA")
    if rsi_val < 35:
        patterns.append(f"RSI bajo ({rsi_val:.1f})")
    # Martillo alcista
    o, c, h, l = opens[-1], closes[-1], highs[-1], lows[-1]
    body = abs(c - o)
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)
    if body < lower_shadow and lower_shadow > 2 * body and upper_shadow < body:
        patterns.append("Martillo alcista")
    return patterns

def log_conversion(prev_asset, prev_amount, new_asset, new_amount, reason):
    with open(log_file, "a") as f:
        f.write(
            f"{datetime.now()} | De: {prev_asset} ({prev_amount:.8f}) "
            f"-> A: {new_asset} ({new_amount:.8f}) | "
            f"Resultado: {'GANANCIA' if new_amount > prev_amount else 'PÉRDIDA'} "
            f"({new_amount - prev_amount:.8f}) | Motivo: {reason}\n"
        )

def get_all_balances():
    balances = client.get_account()['balances']
    return {b['asset']: float(b['free']) for b in balances if float(b['free']) > 0}

def sell_to_usdt(asset, amount):
    if asset == "USDT":
        return amount
    symbol = asset + "USDT"
    try:
        price = get_ohlc(symbol)[0][-1]
        qty = round(amount, 6)
        client.order_market_sell(symbol=symbol, quantity=qty)
        print(f"Vendido {qty} {asset} a USDT")
        return qty * price
    except Exception as e:
        print(f"No se pudo vender {asset}: {e}")
        return 0

def buy_with_usdt(symbol, usdt_amount):
    price = get_ohlc(symbol)[0][-1]
    qty = round(usdt_amount / price, 6)
    try:
        client.order_market_buy(symbol=symbol, quantity=qty)
        print(f"Comprado {qty} {symbol[:-4]} con {usdt_amount} USDT")
        return qty
    except Exception as e:
        print(f"No se pudo comprar {symbol}: {e}")
        return 0

while True:
    print(f"\nAnalizando activos a las {datetime.now()}...")
    symbols = get_usdt_symbols()
    print(f"Total de símbolos USDT: {len(symbols)}")

    # Analiza todos los símbolos y busca el mejor patrón
    best_symbol = None
    best_patterns = []
    for symbol in symbols:
        try:
            closes, opens, highs, lows = get_ohlc(symbol)
            patterns = detect_patterns(closes, opens, highs, lows)
            if patterns:
                best_symbol = symbol
                best_patterns = patterns
                print(f"{symbol}: Patrones detectados: {', '.join(patterns)}")
                break  # Elige el primero con patrón, o puedes buscar el "mejor"
        except Exception as e:
            continue

    balances = get_all_balances()
    print("Tus saldos:", balances)

    # Vende todo a USDT excepto USDT
    total_usdt = balances.get("USDT", 0)
    for asset, amount in balances.items():
        if asset != "USDT":
            usdt_recibido = sell_to_usdt(asset, amount)
            log_conversion(asset, amount, "USDT", usdt_recibido, "Conversión a USDT para rotación")
            total_usdt += usdt_recibido

    # Compra el mejor activo
    if best_symbol and total_usdt > 0.0001:
        qty = buy_with_usdt(best_symbol, total_usdt)
        log_conversion("USDT", total_usdt, best_symbol[:-4], qty, ", ".join(best_patterns))
    else:
        print("No se detectó patrón o saldo insuficiente.")

    time.sleep(3600)  # Espera 1 hora