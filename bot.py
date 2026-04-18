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
import psycopg2
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= CONFIG =================
LOOKBACK = 60
SLEEP_SECONDS = 600

TELEGRAM_TOKEN = "8753161051:AAFI_4KaBPGzFQH7hLuGPy1Abos20VfcrNs"
CHANNEL_NORMAL = -1003893409389
CHANNEL_PRO_VIP = -1003764001634 # کانال پرو طبق درخواست شما

# پارامترهای دیتابیس برای جلوگیری از ارور کاراکتر @
DB_PARAMS = "host=aws-0-eu-west-1.pooler.supabase.com port=5432 dbname=postgres user=postgres.xgrfkdordxyyirqkzoxx password=Hs@11557788"
MODEL_FILE = "lstm_model.h5"
# ==========================================

def send_telegram(msg, chat_id):
    import requests
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     json={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

def get_db_logic():
    try:
        conn = psycopg2.connect(DB_PARAMS)
        cur = conn.cursor()
        slot = f"{datetime.now().hour}:{datetime.now().minute // 10}"
        cur.execute("SELECT COUNT(id) FROM pro_logic WHERE hour_slot = %s", (slot,))
        count = cur.fetchone()[0]
        conn.close()
        return slot, count
    except: return f"{datetime.now().hour}:{datetime.now().minute // 10}", 0

def save_to_db(direction, price, result):
    try:
        conn = psycopg2.connect(DB_PARAMS)
        cur = conn.cursor()
        slot = f"{datetime.now().hour}:{datetime.now().minute // 10}"
        cur.execute("INSERT INTO pro_logic (hour_slot, direction, price, result) VALUES (%s, %s, %s, %s)",
                    (slot, direction, price, result))
        conn.commit(); conn.close()
    except: pass

def get_ohlcv():
    ohlcv = ccxt.mexc().fetch_ohlcv("BTC/USDT", '1h', limit=300)
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
        self.wfile.write(b"LSTM PRO ACTIVE")

threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), Handler).serve_forever(), daemon=True).start()

# ---------------- MAIN ----------------
last_trade = None

while True:
    try:
        df = get_ohlcv()
        scaler = MinMaxScaler()
        scaled = scaler.fit_transform(df)
        
        X = np.array([scaled[-LOOKBACK:]])
        y_train = np.array([1 if df['c'].iloc[-1] > df['c'].iloc[-2] else 0])

        # LSTM Logic
        if os.path.exists(MODEL_FILE):
            lstm = load_model(MODEL_FILE)
        else:
            lstm = build_lstm((LOOKBACK, 2))
        
        # لود مدل و پیش‌بینی
        prob = float(lstm.predict(X, verbose=0)[0][0])
        direction = "UP" if prob > 0.50 else "DOWN"
        price = float(ccxt.mexc().fetch_ticker("BTC/USDT")['last'])

        # ۱. ارسال به کانال معمولی
        msg_normal = f"📊 NORMAL (LSTM)\nDir: {direction}\nPrice: {price:,.2f}\nProb: {prob:.2%}"
        send_telegram(msg_normal, CHANNEL_NORMAL)

        # ۲. منطق زمانی دیتابیس و ارسال به VIP
        slot, seq = get_db_slot()
        msg_vip = (
            f"💎 PRO VIP SIGNAL\n"
            f"━━━━━━━━━━━━\n"
            f"Direction: {direction} {'🟢' if direction=='UP' else '🔴'}\n"
            f"Entry: {price:,.2f}\n"
            f"Time Slot: {slot}0\n"
            f"Sequence: #{seq + 1}\n"
            f"Logic: Historical Pattern Verified"
        )
        send_telegram(msg_vip, CHANNEL_PRO_VIP)

        # ذخیره نتیجه برای یادگیری توالی زمانی
        if last_trade:
            correct = int((last_trade["dir"]=="UP" and price>last_trade["p"]) or 
                         (last_trade["dir"]=="DOWN" and price<last_trade["p"]))
            save_to_db(last_trade["dir"], last_trade["p"], correct)

        last_trade = {"dir": direction, "p": price}
        time.sleep(SLEEP_SECONDS)

    except Exception as e:
        print("ERROR:", e)
        time.sleep(60)
