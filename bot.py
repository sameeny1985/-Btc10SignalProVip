import time
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from xgboost import XGBClassifier
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
import ccxt
import threading
import os
import requests
import psycopg2 
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= CONFIG =================
# این مقدار را رندر از Environment Variable می‌خواند
DATABASE_URL = os.environ.get("DATABASE_URL")

TELEGRAM_TOKEN = "8753161051:AAFI_4KaBPGzFQH7hLuGPy1Abos20VfcrNs"
CHANNEL_1 = -1003893409389      # Normal (منبع اصلی یادگیری)
CHANNEL_2 = -1003698594050      # VIP
CHANNEL_3_PRO = -1003764001634   # Pro VIP

MODEL_FILE = "lstm_model.h5"
LOOKBACK = 60
# ==========================================

# ---------------- DATABASE LOGIC ----------------
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
    except Exception as e:
        print(f"DB Error: {e}")

def get_pro_stats():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        df = pd.read_sql("SELECT result FROM pro_logic ORDER BY id DESC LIMIT 15", conn)
        conn.close()
        if len(df) < 3: return False, len(df), 0
        winrate = df['result'].mean()
        return (winrate >= 0.70), len(df), winrate
    except:
        return False, 0, 0

# ---------------- TELEGRAM ----------------
def send_telegram(msg, chat_id):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

# ---------------- MODEL HELPERS ----------------
def get_ohlcv():
    ohlcv = ccxt.mexc().fetch_ohlcv("BTC/USDT", '1h', limit=500)
    df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
    return df[['c','v']]

def build_lstm(input_shape):
    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=input_shape),
        Dropout(0.3),
        LSTM(32),
        Dense(1, activation="sigmoid")
    ])
    model.compile(optimizer="adam", loss="binary_crossentropy")
    return model

# ---------------- SERVER ----------------
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"BTC Pro VIP Bot is Live")

threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), Handler).serve_forever(), daemon=True).start()

# ---------------- MAIN LOOP ----------------
last_signal = None
exchange = ccxt.mexc()

while True:
    try:
        df = get_ohlcv()
        # بخش ساده‌سازی شده آماده‌سازی دیتا
        scaler = MinMaxScaler()
        scaled = scaler.fit_transform(df)
        X = np.array([scaled[-LOOKBACK:]])
        y_last = 1 if df['c'].iloc[-1] > df['c'].iloc[-2] else 0

        # اجرای مدل
        if os.path.exists(MODEL_FILE): lstm = load_model(MODEL_FILE)
        else: lstm = build_lstm((LOOKBACK, 2))
        
        lstm_prob = float(lstm.predict(X, verbose=0)[0][0])
        direction = "UP" if lstm_prob > 0.52 else "DOWN"
        price = float(exchange.fetch_ticker("BTC/USDT")['last'])

        # ۱. ارسال سیگنال به کانال نرمال
        msg_n = f"📊 NORMAL SIGNAL\nDir: {direction}\nPrice: {price:,.2f}"
        send_telegram(msg_n, CHANNEL_1)

        # ۲. بررسی وضعیت پرو بر اساس دیتابیس
        is_pro, count, wr = get_pro_stats()
        if is_pro:
            msg_p = f"💎 PRO VIP SIGNAL\nDir: {direction}\nEntry: {price:,.2f}\nPattern Winrate: {wr:.1%}"
            send_telegram(msg_p, CHANNEL_3_PRO)

        # ۳. اعتبارسنجی سیگنال قبلی و ذخیره در دیتابیس
        if last_signal:
            current_p = float(exchange.fetch_ticker("BTC/USDT")['last'])
            success = int((last_signal['dir'] == "UP" and current_p > last_signal['p']) or 
                          (last_signal['dir'] == "DOWN" and current_p < last_signal['p']))
            save_to_supabase(last_signal['dir'], last_signal['p'], success)

        last_signal = {'p': price, 'dir': direction}
        time.sleep(600)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(60)
