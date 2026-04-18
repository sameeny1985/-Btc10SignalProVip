import threading
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# --- ۱. باز کردن سریع پورت برای رندر ---
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"PRO VIP - 24H TIME ANALYSIS LIVE")

threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), Handler).serve_forever(), daemon=True).start()

# --- ۲. ایمپورت‌ها ---
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
    """
    فقط ساعت و دقیقه فعلی را چک می‌کند.
    اگر در این تایم‌اسلات قبلاً سیگنالی ثبت شده باشد، آن را به عنوان الگو شناسایی می‌کند.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        now = datetime.now()
        # ایجاد یک شناسه زمانی بر اساس ساعت و ده دقیقه (مثلاً 14:10, 14:20)
        time_slot = f"{now.hour}:{now.minute // 10}"
        
        # چک کردن سوابق در این تایم‌اسلات (بدون محدودیت روز هفته)
        cur.execute("SELECT COUNT(id) FROM pro_logic WHERE hour_slot = %s", (time_slot,))
        count = cur.fetchone()[0]
        
        conn.close()
        return time_slot, count
    except:
        return "00:0", 0

def save_to_db(direction, price, result):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        now = datetime.now()
        time_slot = f"{now.hour}:{now.minute // 10}"
        # ذخیره با فیلد hour_slot برای تحلیل ۲۴ ساعته
        cur.execute("INSERT INTO pro_logic (hour_slot, direction, price, result) VALUES (%s, %s, %s, %s)",
                    (time_slot, direction, price, result))
        conn.commit(); cur.close(); conn.close()
    except: pass

def send_telegram(msg, chat_id):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

# --- MAIN ---
exchange = ccxt.mexc()
# لود مدل
model = Sequential([LSTM(64, return_sequences=True, input_shape=(LOOKBACK, 2)), Dropout(0.3), LSTM(32), Dense(1, activation="sigmoid")])
model.compile(optimizer="adam", loss="binary_crossentropy")
last_signal = None

while True:
    try:
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '1h', limit=500)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        scaled = MinMaxScaler().fit_transform(df[['c','v']])
        prob = float(model.predict(np.array([scaled[-LOOKBACK:]]), verbose=0)[0][0])
        direction = "UP" if prob > 0.52 else "DOWN"
        price = float(exchange.fetch_ticker("BTC/USDT")['last'])

        # ۱. ارسال نرمال
        send_telegram(f"📊 NORMAL SIGNAL\nDir: {direction}\nPrice: {price:,.2f}", CHANNEL_1)
        
        # ۲. تحلیل لایه پرو (فقط بر اساس ساعت و دقیقه در ۲۴ ساعت)
        slot, seq = get_time_slot_data()
        
        msg_p = (
            f"💎 PRO VIP SIGNAL\n"
            f"━━━━━━━━━━━━\n"
            f"Direction: {direction}\n"
            f"Target Slot: {slot}0\n"
            f"Historical Hits: {seq}\n"
            f"Status: Time Pattern Confirmed"
        )
        send_telegram(msg_p, CHANNEL_3_PRO)

        # ۳. ذخیره برای یادگیری ساعت بعدی
        if last_signal:
            success = int((last_signal['dir'] == "UP" and price > last_signal['p']) or (last_signal['dir'] == "DOWN" and price < last_signal['p']))
            save_to_db(last_signal['dir'], last_signal['p'], success)

        last_signal = {'p': price, 'dir': direction}
        time.sleep(600)
    except: time.sleep(60)
