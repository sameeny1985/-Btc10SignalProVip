import time
from datetime import datetime
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
import ccxt
import threading
import os
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import psycopg2 # کتابخانه اتصال به سوپابیس

# ================= CONFIG =================
# گرفتن لینک از Environment Variable رندر
DATABASE_URL = os.environ.get("DATABASE_URL")

TELEGRAM_TOKEN = "8753161051:AAFI_4KaBPGzFQH7hLuGPy1Abos20VfcrNs"
CHANNEL_1 = -1003893409389      # Normal
CHANNEL_2 = -1003698594050      # VIP
CHANNEL_3_PRO = -1003764001634   # پرو وی‌آی‌پی

MODEL_FILE = "lstm_model.h5"
# ==========================================

def send_telegram(msg, chat_id):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

# ----------------- DATABASE LOGIC (SUPABASE) -----------------
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def save_pro_step_to_db(direction, price, result):
    """ذخیره سیگنال و نتیجه در دیتابیس ابری"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        now = datetime.now()
        cur.execute(
            "INSERT INTO pro_logic (day, hour, direction, price, result) VALUES (%s, %s, %s, %s, %s)",
            (now.strftime("%A"), now.hour, direction, price, result)
        )
        conn.commit()
        cur.close()
        conn.close()
        print("--- Result saved to Supabase ---")
    except Exception as e:
        print(f"--- DB Save Error: {e} ---")

def analyze_pro_sequence_from_db():
    """تحلیل توالی سیگنال‌ها از روی دیتابیس"""
    try:
        conn = get_db_connection()
        # خواندن ۱۰ سیگنال آخر برای محاسبه وین‌ریت
        query = "SELECT result FROM pro_logic ORDER BY id DESC LIMIT 10"
        df = pd.read_sql(query, conn)
        conn.close()
        
        count = len(df)
        if count < 3:
            return False, count
        
        win_rate = df['result'].mean()
        # اگر وین‌ریت ۱۰ سیگنال اخیر بالای ۷۰٪ بود، تایید بده
        if win_rate >= 0.70:
            return True, count
        
        return False, count
    except Exception as e:
        print(f"--- DB Read Error: {e} ---")
        return False, 0

# ----------------- RENDER KEEP-ALIVE SERVER -----------------
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        # نمایش تعداد سیگنال‌ها در صفحه وب رندر برای اطمینان شما
        is_ready, total = analyze_pro_sequence_from_db()
        html = f"""<html><body style='background:#000;color:#0f0;text-align:center;padding-top:50px;font-family:sans-serif;'>
        <h1>ربات کانال پرو وی ای پی فعال است</h1>
        <p>تعداد سیگنال‌های ذخیره شده در دیتابیس: {total}</p>
        <p>وضعیت لایه پرو: {'فعال ✅' if is_ready else 'در حال جمع‌آوری دیتا (نیاز به حداقل ۳ سیگنال)'}</p>
        <script>setTimeout(()=>{{location.reload();}}, 300000);</script>
        </body></html>"""
        self.wfile.write(html.encode())

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# ----------------- MAIN LOOP -----------------
last_vip_data = None
exchange = ccxt.mexc()

while True:
    try:
        # --- بخش دریافت قیمت و تحلیل (لایه ۱ و ۲) ---
        # این بخش را طبق متغیرهای خودت پر کن (مثلاً از خروجی XGB)
        ticker = exchange.fetch_ticker("BTC/USDT")
        price = float(ticker['last'])
        
        # فرض می‌کنیم خروجی لایه دوم شما اینجاست:
        # direction = "UP" یا "DOWN" (اینجا باید کد لایه ۱ و ۲ خودت رو قرار بدی)
        # در حال حاضر برای اینکه کد خطا نده، من مقدار فرضی می‌ذارم که خودت جایگزین کنی
        direction = "UP" # <--- خروجی مدل شما
        
        # --- بخش مخصوص PRO VIP (لایه ۳) ---
        is_pro_ready, total_signals = analyze_pro_sequence_from_db()
        
        if is_pro_ready:
            msg_pro = (
                f"💎 PRO VIP SIGNAL (Sequence-Based)\n"
                f"━━━━━━━━━━━━\n"
                f"Direction: {direction} {'🟢' if direction=='UP' else '🔴'}\n"
                f"Entry: {price:,.2f}\n"
                f"Sequence ID: #{total_signals + 1}\n"
                f"Confidence: High (Database Verified)\n"
                f"Time: {datetime.now().strftime('%H:%M:%S')}"
            )
            send_telegram(msg_pro, CHANNEL_3_PRO)
        
        # ذخیره نتیجه سیگنال قبلی در دیتابیس برای آپدیت الگو
        if last_vip_data:
            curr_p = float(exchange.fetch_ticker("BTC/USDT")['last'])
            # چک کردن اینکه آیا پیش‌بینی قبلی درست بوده یا نه
            is_correct = 0
            if last_vip_data['dir'] == "UP" and curr_p > last_vip_data['p']:
                is_correct = 1
            elif last_vip_data['dir'] == "DOWN" and curr_p < last_vip_data['p']:
                is_correct = 1
            
            # ثبت در سوپابیس
            save_pro_step_to_db(last_vip_data['dir'], last_vip_data['p'], is_correct)
            
        last_vip_data = {'p': price, 'dir': direction}
        
        time.sleep(600) # هر ۱۰ دقیقه یکبار چک کن

    except Exception as e:
        print(f"Error in Main Loop: {e}")
        time.sleep(60)
