import os
import time
import requests
import numpy as np
import pandas as pd
import ccxt
import psycopg2  # اضافه شد برای اتصال به دیتابیس سوپابیس
import threading
from datetime import datetime
from sklearn.preprocessing import MinMaxScaler
from xgboost import XGBClassifier
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
from http.server import HTTPServer, BaseHTTPRequestHandler
import os, time, requests, threading
from datetime import datetime, timedelta
# ================= CONFIG =================
LOOKBACK = 60
SLEEP_SECONDS = 600

TELEGRAM_TOKEN = "8434412669:AAGDAptrzK3pw9KBCdJO-GRJKQ6dTPNsdsw"
CHANNEL_1 = -1003893409389
CHANNEL_2 = -1003698594050
# تنظیمات دیتابیس
DB_PARAMS = "host=aws-0-eu-west-1.pooler.supabase.com port=5432 dbname=postgres user=postgres.xgrfkdordxyyirqkzoxx password=Hs@11557788"
CHANNEL_PRO_VIP = -1003764001634
HISTORY_FILE = "trading_history.csv"
MODEL_FILE = "lstm_model.h5"
# ==========================================
web_signals_history = []
# ---------------- TELEGRAM ----------------
def send_telegram(msg, chat_id):
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": msg}
        )
    except:
        pass

# ---------------- DATA ----------------
def get_price():
    return float(ccxt.mexc().fetch_ticker("BTC/USDT")['last'])

def get_ohlcv():
    ohlcv = ccxt.mexc().fetch_ohlcv("BTC/USDT", '15m', limit=500)
    df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
    return df[['c','v']]

# ---------------- MARKET REGIME ----------------
def market_regime(df):
    close = df['c']
    returns = close.pct_change()

    trend = close.iloc[-1] - close.iloc[-20]
    volatility = returns.std()

    if trend > 100:
        regime = "BULL"
        threshold = 0.52
    elif trend < -100:
        regime = "BEAR"
        threshold = 0.52
    else:
        regime = "RANGE"
        threshold = 0.60

    return regime, threshold, volatility

# ---------------- LSTM ----------------
def build_lstm(input_shape):
    model = Sequential()
    model.add(LSTM(64, return_sequences=True, input_shape=input_shape))
    model.add(Dropout(0.3))
    model.add(LSTM(32))
    model.add(Dense(1, activation="sigmoid"))
    model.compile(optimizer="adam", loss="binary_crossentropy")
    return model

def prepare(df):
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(df)

    X, y = [], []
    for i in range(LOOKBACK, len(df)-1):
        X.append(scaled[i-LOOKBACK:i])
        y.append(1 if scaled[i+1][0] > scaled[i][0] else 0)

    return np.array(X), np.array(y)

# ---------------- META MODEL ----------------
def train_meta_model():
    if not os.path.exists(HISTORY_FILE):
        return None, 0.5

    df = pd.read_csv(HISTORY_FILE)

    if len(df) < 5:
        return None, 0.5

    df['weight'] = np.linspace(0.1, 1.0, len(df))

    if len(df) > 15000:
        df = df.sample(15000, weights=df['weight'])

    X = df[['confidence','volatility']]
    y = df['result']
    w = df['weight']

    winrate = y.mean()

    model = XGBClassifier(n_estimators=100, max_depth=4)
    model.fit(X, y, sample_weight=w)

    return model, winrate

# ---------------- SAVE ----------------
def save_trade(data):
    pd.DataFrame([data]).to_csv(
        HISTORY_FILE,
        mode='a',
        header=not os.path.exists(HISTORY_FILE),
        index=False
    )

# ---------------- SERVER (FIXED PORT) ----------------
# ---------------- SERVER (WITH DASHBOARD) ----------------
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        # ۱. خوندن فایل اچ‌تی‌ام‌ال
        try:
            with open('index.html', 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            content = "<html><body style='background:black;color:white;'>فایل index.html پیدا نشد!</body></html>"

        # ۲. ساختن ردیف‌های جدول از حافظه ربات
        rows = ""
        # متغیر web_signals_history رو چند لحظه دیگه بالاتر تعریف می‌کنیم
        for s in reversed(web_signals_history):
            color = "#4ade80" if "UP" in s['dir'] else "#f87171"
            rows += f"""
            <tr style="border-bottom: 1px solid #334155;">
                <td style="padding:12px;">{s['time']}</td>
                <td style="padding:12px; color:{color}; font-weight:bold;">{s['dir']}</td>
                <td style="padding:12px;">{s['price']}</td>
                <td style="padding:12px;">{s['conf']}</td>
                <td style="padding:12px; color:#94a3b8;">{s['regime']}</td>
            </tr>
            """

        # ۳. تزریق ردیف‌ها به فایل اصلی
        final_html = content.replace("{{TABLE_ROWS}}", rows if rows else "<tr><td colspan='5' style='text-align:center;padding:20px;'>در انتظار اولین سیگنال...</td></tr>")
        self.wfile.write(final_html.encode('utf-8'))

PORT = int(os.environ.get("PORT", 10000))

def run_server():
    # حتماً اینجا هم Handler رو بذار
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
def run_server():
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# ---------------- MEMORY ----------------
last_trade = None
def get_db_slot_count():
    import psycopg2
    try:
        conn = psycopg2.connect(DB_PARAMS)
        cur = conn.cursor()
        slot = f"{datetime.now().hour}:{datetime.now().minute // 15}"
        cur.execute("SELECT COUNT(id) FROM pro_logic WHERE hour_slot = %s", (slot,))
        count = cur.fetchone()[0]
        cur.close(); conn.close()
        return slot, count
    except:
        return f"{datetime.now().hour}:{datetime.now().minute // 15}", 0
# ================= MAIN LOOP WITH PRO FILTER =================
while True:
    try:
        df = get_ohlcv()
        X, y = prepare(df)

        if len(X) < 10:
            time.sleep(60)
            continue

        # -------- هوش مصنوعی (LSTM + XGB) --------
        if os.path.exists(MODEL_FILE):
            lstm = load_model(MODEL_FILE)
        else:
            lstm = build_lstm((X.shape[1], X.shape[2]))

        lstm.fit(X, y, epochs=1, verbose=0)
        lstm.save(MODEL_FILE)

        lstm_prob = float(lstm.predict(X[-1].reshape(1,*X[-1].shape))[0][0])
        xgb = XGBClassifier(n_estimators=30)
        xgb.fit(df.values[LOOKBACK:-1], y)
        xgb_prob = xgb.predict_proba(df.values[-1].reshape(1,-1))[0][1]

        # میانگین احتمالات
        base_prob = (lstm_prob + xgb_prob) / 2
        regime, threshold, volatility = market_regime(df)
        direction = "UP" if base_prob > threshold else "DOWN"

        price = get_price()
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        slot, seq = get_db_slot_count()

        # 1️⃣ همیشه ارسال به کانال نرمال (بدون فیلتر سخت‌گیرانه)
        msg_normal = (
            f"📊 **NORMAL SIGNAL**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔔 Direction: {direction} {'🟢' if direction=='UP' else '🔴'}\n"
            f"💵 Price: `${price:,.2f}`\n"
            f"🎯 Confidence: {base_prob:.2%}\n"
            f"⏰ {time_str}"
        )
        send_telegram(msg_normal, CHANNEL_1)

        # 2️⃣ بررسی شرایط ویژه برای کانال "پرو وی‌آی‌پی" (Smart Filter)
        # الف) محاسبه وین‌ریت تاریخی اسلات جاری از دیتابیس
        historic_winrate = 0
        try:
            conn = psycopg2.connect(DB_PARAMS)
            cur = conn.cursor()
            cur.execute("SELECT AVG(result) FROM pro_logic WHERE hour_slot = %s", (slot,))
            res = cur.fetchone()[0]
            historic_winrate = float(res) if res is not None else 0.0
            cur.close(); conn.close()
        except: pass

        # ب) شروط فیلتر طلایی:
        # ۱. اطمینان مدل بالاتر از ۷۰٪ یا کمتر از ۳۰٪ باشد
        # ۲. یا اینکه وین‌ریت تاریخی این ساعت بالای ۶۰٪ باشد
        is_pro_signal = (base_prob >= 0.70 or base_prob <= 0.30) or (historic_winrate >= 0.60)

        if is_pro_signal:
            vip_text = (
                f"💎 **PRO VIP GOLDEN SIGNAL**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🪙 #BTC / USDT\n"
                f"🚀 **Action:** {'BUY' if direction=='UP' else 'SELL'} {'✅'}\n"
                f"📉 **Entry Price:** `${price:,.2f}`\n"
                f"🎯 **Probability:** {max(base_prob, 1-base_prob):.2%}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📊 **Analysis Logic:**\n"
                f"📍 Slot Winrate: `{historic_winrate:.1%}`\n"
                f"🔢 Sequence: `#{seq + 1}`\n"
                f"🧠 Regime: {regime}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⏰ {date_str} {time_str}\n"
                f"👑 **PRO VIP EXCLUSIVE**"
            )
            send_telegram(vip_text, CHANNEL_PRO_VIP)
            print("🔥 Golden Signal sent to PRO VIP")
        else:
            print("ℹ️ Signal filtered: Not strong enough for PRO VIP")

        # 3️⃣ ثبت برای اعتبارسنجی دوره بعد
        if last_trade:
            correct = int(
                (last_trade["direction"]=="UP" and price > last_trade["price"]) or
                (last_trade["direction"]=="DOWN" and price < last_trade["price"])
            )
            # ذخیره در سوپابیس برای الگوسازی‌های بعدی
            try:
                conn = psycopg2.connect(DB_PARAMS)
                cur = conn.cursor()
                db_slot = f"{datetime.now().hour}:{datetime.now().minute // 15}"
                cur.execute("INSERT INTO pro_logic (hour_slot, direction, price, result) VALUES (%s, %s, %s, %s)",
                            (db_slot, last_trade["direction"], last_trade["price"], correct))
                conn.commit(); cur.close(); conn.close()
            except: pass

        last_trade = {
            "price": price,
            "direction": direction,
            "confidence": base_prob,
            "volatility": volatility
        }
# ذخیره اطلاعات برای نمایش در صفحه وب (داشبورد)
        web_signals_history.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "dir": direction,
            "price": f"{price:,.2f}",
            "conf": f"{base_prob:.2%}",
            "regime": regime
        })
        # فقط ۱۰ تای آخر رو نگه دار که حافظه پر نشه
        if len(web_signals_history) > 10:
            web_signals_history.pop(0)
        time.sleep(SLEEP_SECONDS)

    except Exception as e:
        print("ERROR:", e)
        # --- تنظیم دقیق روی دقایق 00, 15, 30, 45 ---
        now = datetime.now()
        
        # تنظیم بازه روی ۱۵ دقیقه
        interval = 15 
        
        # محاسبه دقیق ثانیه‌های باقی‌مانده تا ربع ساعت بعدی
        minutes_to_next_slot = interval - (now.minute % interval)
        
        # محاسبه کل ثانیه‌ها (منهای ثانیه و میکروثانیه فعلی برای دقت صفر ثانیه)
        seconds_to_wait = (minutes_to_next_slot * 60) - now.second - (now.microsecond / 1000000.0)
        
        # اگر کمتر از ۱۰ ثانیه مانده بود، برو برای ۱۵ دقیقه بعد (جلوگیری از تکرار در یک اسلات)
        if seconds_to_wait < 10:
            seconds_to_wait += (interval * 60)

        # محاسبه زمان دقیق بیداری برای نمایش در کنسول
        target_minute = (now.minute + minutes_to_next_slot) % 60
        target_hour = now.hour + ((now.minute + minutes_to_next_slot) // 60)
        
        print(f"🎯 Next signal precisely at: {target_hour:02d}:{target_minute:02d}:00")
        print(f"💤 Sleeping for {int(seconds_to_wait // 60)}m and {int(seconds_to_wait % 60)}s...")
        
        time.sleep(seconds_to_wait)
