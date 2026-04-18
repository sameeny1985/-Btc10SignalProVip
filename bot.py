import threading
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# ۱. استارت سریع پورت برای رندر (سبز شدن دیپلوی)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"PRO VIP - 24H ANALYSIS ONLINE")

threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), Handler).serve_forever(), daemon=True).start()

# ۲. کتابخانه‌ها
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
CHANNEL_3_PRO = -1003764001634   
MODEL_FILE = "lstm_model.h5"
LOOKBACK = 60
# ==========================================

def get_time_slot_data():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        now = datetime.now()
        slot = f"{now.hour}:{now.minute // 10}" # اسلات ۱۰ دقیقه‌ای
        cur.execute("SELECT COUNT(id) FROM pro_logic WHERE hour_slot = %s", (slot,))
        count = cur.fetchone()[0]
        conn.close()
        return slot, count
    except: return "00:0", 0

def save_to_db(direction, price, result):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        now = datetime.now()
        slot = f"{now.hour}:{now.minute // 10}"
        cur.execute("INSERT INTO pro_logic (hour_slot, direction, price, result) VALUES (%s, %s, %s, %s)",
                    (slot, direction, price, result))
        conn.commit(); cur.close(); conn.close()
    except: pass

def send_telegram(msg, chat_id):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

# --- بدنه اصلی ---
exchange = ccxt.mexc()
model = Sequential([LSTM(64, return_sequences=True, input_shape=(LOOKBACK, 2)), Dropout(0.3), LSTM(32), Dense(1, activation="sigmoid")])
model.compile(optimizer="adam", loss="binary_crossentropy")
last_signal = None

print("Bot is starting its 24h analysis...")

while True:
    try:
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '1h', limit=500)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        scaled = MinMaxScaler().fit_transform(df[['c','v']])
        prob = float(model.predict(np.array([scaled[-LOOKBACK:]]), verbose=0)[0][0])
        direction = "UP" if prob > 0.52 else "DOWN"
        price = float(exchange.fetch_ticker("BTC/USDT")['last'])

        # ارسال سیگنال نرمال
        send_telegram(f"📊 NORMAL SIGNAL\nDir: {direction}\nPrice: {price:,.2f}", CHANNEL_1)
        
        # ارسال سیگنال پرو (بدون شرط درصد - فقط بر اساس ساعت و دقیقه)
        slot, seq = get_time_slot_data()
        msg_p = (
            f"💎 PRO VIP SIGNAL\n"
            f"━━━━━━━━━━━━\n"
            f"Direction: {direction}\n"
            f"Price: {price:,.2f}\n"
            f"Time Slot: {slot}0\n"
            f"Pattern Hits: {seq + 1}"
        )
        send_telegram(msg_p, CHANNEL_3_PRO)

        # ثبت نتیجه برای یادگیری الگوی ساعت بعد
        if last_signal:
            current_p = float(exchange.fetch_ticker("BTC/USDT")['last'])
            success = int((last_signal['dir'] == "UP" and current_p > last_signal['p']) or (last_signal['dir'] == "DOWN" and current_p < last_signal['p']))
            save_to_db(last_signal['dir'], last_signal['p'], success)

        last_signal = {'p': price, 'dir': direction}
        time.sleep(600) # ده دقیقه صبر
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(60)
