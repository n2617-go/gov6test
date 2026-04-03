import streamlit as st
import yfinance as yf
import pandas as pd
import time
import random
import requests
import pytz
import json
import os
from datetime import datetime, time as dt_time
from FinMind.data import DataLoader

# --- 0. 時區與檔案設定 ---
tw_tz = pytz.timezone('Asia/Taipei')
SAVE_FILE = "my_stocks_settings.json"

# --- 1. 檔案存取功能 ---
def load_data():
    """從 JSON 檔案載入股票清單與設定"""
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        # 預設初始值
        return {
            "stocks": [{"id": "2330", "name": "台積電"}, {"id": "00631L", "name": "元大台灣50正2"}],
            "tg_token": "",
            "tg_chat_id": "",
            "tg_threshold": 3.0
        }

def save_data():
    """將目前的 session_state 存入 JSON 檔案"""
    data = {
        "stocks": st.session_state.my_stocks,
        "tg_token": st.session_state.get('tg_token', ''),
        "tg_chat_id": st.session_state.get('tg_chat_id', ''),
        "tg_threshold": st.session_state.get('tg_threshold', 3.0)
    }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 初始化 Session State (僅在第一次執行)
if 'initialized' not in st.session_state:
    saved_config = load_data()
    st.session_state.my_stocks = saved_config["stocks"]
    st.session_state.tg_token = saved_config["tg_token"]
    st.session_state.tg_chat_id = saved_config["tg_chat_id"]
    st.session_state.tg_threshold = saved_config["tg_threshold"]
    st.session_state.initialized = True

# --- 2. 頁面配置與 CSS ---
st.set_page_config(page_title="台股永久自選監控", layout="centered")
st.markdown("""
    <style>
    [data-testid="stMetricDelta"] svg { display: none; }
    .status-box { padding: 12px; border-radius: 8px; margin-bottom: 20px; text-align: center; font-weight: bold; }
    .open { background-color: #ffe6e6; color: #ff0000; border: 1px solid #ff0000; }
    .closed { background-color: #f0f2f6; color: #555; border: 1px solid #ccc; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心功能函數 (與之前相同) ---
def get_market_status():
    now_tw = datetime.now(tw_tz)
    if now_tw.weekday() >= 5: return f"休市中 (週末) - {now_tw.strftime('%H:%M')}", False
    if dt_time(9, 0) <= now_tw.time() <= dt_time(13, 35):
        return f"⚡ 開盤中 - {now_tw.strftime('%H:%M')}", True
    return f"🌙 休市中 - {now_tw.strftime('%H:%M')}", False

def send_telegram_msg(token, chat_id, message):
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try: requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=5)
        except: pass

dl = DataLoader()
status_label, is_open = get_market_status()

@st.cache_data(ttl=60 if is_open else 3600)
def get_stock_data(stock_id):
    if is_open:
        try:
            now_s = datetime.now(tw_tz).strftime('%Y-%m-%d')
            start_s = (datetime.now(tw_tz) - pd.Timedelta(days=10)).strftime('%Y-%m-%d')
            df = dl.taiwan_stock_price(stock_id=stock_id, start_date=start_s, end_date=now_s)
            if not df.empty:
                df = df.dropna(subset=['close'])
                curr, prev = float(df.iloc[-1]['close']), float(df.iloc[-2]['close'])
                return {"price": curr, "change": curr - prev, "pct": (curr-prev)/prev*100, "src": "FinMind"}
        except: pass
    
    for suffix in [".TW", ".TWO"]:
        try:
            time.sleep(random.uniform(0.2, 0.5))
            df = yf.download(f"{stock_id}{suffix}", period="10d", progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Close'])
            if len(df) >= 2:
                curr, prev = float(df.iloc[-1]['Close']), float(df.iloc[-2]['Close'])
                return {"price": curr, "change": curr - prev, "pct": (curr-prev)/prev*100, "src": f"yf{suffix}"}
        except: continue
    return None

# --- 4. 主介面 ---
st.title("📈 永久自選股監控")
st.markdown(f'<div class="status-box {"open" if is_open else "closed"}">{status_label}</div>', unsafe_allow_html=True)

# A. 管理自選股
with st.expander("➕ 新增/管理股票"):
    col_id, col_name, col_btn = st.columns([2, 3, 1])
    new_id = col_id.text_input("代號")
    new_name = col_name.text_input("名稱")
    if col_btn.button("新增"):
        if new_id and new_name:
            if not any(s['id'] == new_id for s in st.session_state.my_stocks):
                st.session_state.my_stocks.append({"id": new_id, "name": new_name})
                save_data() # 存入檔案
                st.cache_data.clear()
                st.rerun()
        else: st.error("請輸入完整資訊")

# B. Telegram 設定
with st.expander("🔔 通知設定"):
    st.session_state.tg_token = st.text_input("Bot Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("門檻 %", value=st.session_state.tg_threshold)
    if st.button("儲存設定並測試"):
        save_data() # 存入檔案
        send_telegram_msg(st.session_state.tg_token, st.session_state.tg_chat_id, "✅ 設定已成功永久保存！")
        st.success("設定已存入伺服器本地空間")

# C. 股票列表
if 'alert_history' not in st.session_state: st.session_state.alert_history = {}

for index, stock in enumerate(st.session_state.my_stocks):
    data = get_stock_data(stock["id"])
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 2, 1])
        if data:
            with c1:
                st.subheader(stock["name"])
                st.caption(f"{stock['id']} | {data['src']}")
            with c2:
                st.metric(label="現價", value=f"{data['price']:.2f}", 
                          delta=f"{data['change']:+.2f} ({data['pct']:+.2f}%)", delta_color="inverse")
            if c3.button("🗑️", key=f"del_{stock['id']}"):
                st.session_state.my_stocks.pop(index)
                save_data() # 同步更新檔案
                st.rerun()

            # 自動通知
            if st.session_state.tg_token and st.session_state.tg_chat_id and abs(data['pct']) >= st.session_state.tg_threshold:
                today_key = f"{stock['id']}_{datetime.now(tw_tz).strftime('%Y%m%d')}"
                if today_key not in st.session_state.alert_history:
                    send_telegram_msg(st.session_state.tg_token, st.session_state.tg_chat_id, f"🚨 {stock['name']} 異動：{data['pct']:+.2f}%")
                    st.session_state.alert_history[today_key] = True
        else:
            st.error(f"無法讀取 {stock['id']}")
            if c3.button("🗑️", key=f"err_{stock['id']}"):
                st.session_state.my_stocks.pop(index)
                save_data()
                st.rerun()

if st.button("🔄 立即刷新"):
    st.cache_data.clear()
    st.rerun()
