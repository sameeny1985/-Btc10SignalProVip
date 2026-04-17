import time
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from xgboost import XGBClassifier
import tensorflow as tf # اصلاح شد
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
import ccxt
import threading
import os
import requests
import psycopg2 
from http.server import HTTPServer, BaseHTTPRequestHandler

# تنظیم برای حذف هشدارهای غیرضروری
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# ================= CONFIG =================
DATABASE_URL = os.environ.get("DATABASE_URL")
TELEGRAM_TOKEN = "8753161051:AAFI_4KaBPGzFQH7hLuGPy1Abos20VfcrNs"
CHANNEL_1 = -1003893409389      
CHANNEL_2 = -1003698594050      
CHANNEL_3_PRO = -1003764001634   

MODEL_FILE = "lstm_model.h5"
LOOKBACK = 60
# ==========================================

# ---------------- DATABASE ----------------
def get_pro_stats():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        # استفاده از متد قدیمی و امن برای خواندن دیتا بدون هشدار
        cur = conn.cursor()
        cur.execute("SELECT result FROM pro_logic ORDER BY id DESC LIMIT 15")
        rows = cur.fetchall()
        conn.close()
        
        if len(rows) < 3: return False, len(rows), 0
        
        results = [r[0] for r in rows]
        winrate = sum(results) / len(results)
        return (winrate >= 0.70), len(results), winrate
    except Exception as e:
        print(f"DB Read Error: {e}")
        return False, 0, 0

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
        print("Successfully saved to Database")
    except Exception as e:
        print(f"DB Save Error: {e}")

# ---------------- MODELS ----------------
# مدل را یکبار بیرون از حلقه تعریف می‌کنیم تا هشدار Retracing نگیریم
def build_lstm_model():
    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=(LOOKBACK, 2)),
        Dropout(0.3),
        LSTM(32),
        Dense(1, activation="sigmoid")
    ])
    model.compile(optimizer="adam", loss="binary_crossentropy")
    return model

# لود اولیه مدل
if os.path.exists(MODEL_FILE):
    global_model = load_model(MODEL_FILE)
else:
    global_model = build_lstm_model()

# ---------------- TELEGRAM ----------------
def send_telegram(msg, chat_id):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
        print(f"Telegram status: {r.status_code}")
    except:
        pass

# ---------------- MAIN ----------------
last_signal = None
exchange = ccxt.mexc()

while True:
    try:
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '1h', limit=500)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        
        scaler = MinMaxScaler()
        scaled = scaler.fit_transform(df[['c','v']])
        X_input = np.array([scaled[-LOOKBACK:]])

        # پیش‌بینی با مدل سراسری
        prob = float(global_model.predict(X_input, verbose=0)[0][0])
        direction = "UP" if prob > 0.52 else "DOWN"
        price = float(exchange.fetch_ticker("BTC/USDT")['last'])

        # ارسال به کانال نرمال (همیشه ارسال می‌شود)
        msg_n = f"📊 NORMAL SIGNAL\nDir: {direction}\nPrice: {price:,.2f}"
        send_telegram(msg_n, CHANNEL_1)

        # بررسی و ارسال پرو
        is_pro, count, wr = get_pro_stats()
        if is_pro:
            msg_p = f"💎 PRO VIP SIGNAL\nDir: {direction}\nWinrate: {wr:.1%}\nPatterns: {count}"
            send_telegram(msg_p, CHANNEL_3_PRO)
        else:
            print(f"Pro Filtered: Winrate {wr:.1%} or data too low ({count})")

        # ذخیره نتیجه سیگنال قبلی
        if last_signal:
            success = int((last_signal['dir'] == "UP" and price > last_signal['p']) or 
                          (last_signal['dir'] == "DOWN" and price < last_signal['p']))
            save_to_supabase(last_signal['dir'], last_signal['p'], success)

        last_signal = {'p': price, 'dir': direction}
        print(f"Cycle Complete: {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(600)

    except Exception as e:
        print(f"Main Error: {e}")
        time.sleep(60)
