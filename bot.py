import threading
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- ۱. بخش حیاتی: باز کردن سریع پورت برای رندر ---
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"BTC PRO VIP IS ONLINE")

def start_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"Port {port} opened successfully!")
    server.serve_forever()

# پورت رو همین الان باز کن قبل از اینکه سراغ ایمپورت‌های سنگین بری
threading.Thread(target=start_server, daemon=True).start()
print("Health check is LIVE. Now loading AI...")

# --- ۲. حالا ایمپورت‌های سنگین رو انجام بده ---
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
import ccxt
import requests
import psycopg2 

# ================= CONFIG =================
DATABASE_URL = os.environ.get("DATABASE_URL")
TELEGRAM_TOKEN = "8753161051:AAFI_4KaBPGzFQH7hLuGPy1Abos20VfcrNs"
CHANNEL_1 = -1003893409389      
CHANNEL_2 = -1003698594050      
CHANNEL_3_PRO = -1003764001634   
MODEL_FILE = "lstm_model.h5"
LOOKBACK = 60
# ==========================================

def get_pro_stats():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT result FROM pro_logic ORDER BY id DESC LIMIT 15")
        rows = cur.fetchall()
        conn.close()
        if len(rows) < 3: return False, len(rows), 0
        results = [r[0] for r in rows]
        winrate = sum(results) / len(results)
        return (winrate >= 0.70), len(results), winrate
    except: return False, 0, 0

def save_to_supabase(direction, price, result):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        now = datetime.now()
        cur.execute(
            "INSERT INTO pro_logic (day, hour, direction, price, result) VALUES (%s, %s, %s, %s, %s)",
            (now.strftime("%A"), now.hour, direction, price, result)
        )
        conn.commit()
        cur.close()
        conn.close()
    except: pass

def send_telegram(msg, chat_id):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

# --- ۳. منطق اصلی و لود مدل ---
print("All libraries loaded. Initializing Model...")
exchange = ccxt.mexc()

if os.path.exists(MODEL_FILE):
    model = load_model(MODEL_FILE)
else:
    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=(LOOKBACK, 2)),
        Dropout(0.3),
        LSTM(32),
        Dense(1, activation="sigmoid")
    ])
    model.compile(optimizer="adam", loss="binary_crossentropy")

last_signal = None

while True:
    try:
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '1h', limit=500)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        scaler = MinMaxScaler()
        scaled = scaler.fit_transform(df[['c','v']])
        X_input = np.array([scaled[-LOOKBACK:]])

        prob = float(model.predict(X_input, verbose=0)[0][0])
        direction = "UP" if prob > 0.52 else "DOWN"
        price = float(exchange.fetch_ticker("BTC/USDT")['last'])
        
        # سیگنال نرمال
        send_telegram(f"📊 NORMAL SIGNAL\nDir: {direction}\nPrice: {price:,.2f}", CHANNEL_1)

        # منطق پرو
        is_pro, count, wr = get_pro_stats()
        if is_pro:
            send_telegram(f"💎 PRO VIP SIGNAL\nDir: {direction}\nWinrate: {wr:.1%}", CHANNEL_3_PRO)

        # ذخیره برای یادگیری پرو
        if last_signal:
            success = int((last_signal['dir'] == "UP" and price > last_signal['p']) or 
                          (last_signal['dir'] == "DOWN" and price < last_signal['p']))
            save_to_supabase(last_signal['dir'], last_signal['p'], success)

        last_signal = {'p': price, 'dir': direction}
        time.sleep(600)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(60)
