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
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {
        "stocks": [{"id": "2330", "name": "台積電"}],
        "tg_token": "",
        "tg_chat_id": "",
        "tg_threshold": 3.0
    }

def save_data():
    data = {
        "stocks": st.session_state.my_stocks,
        "tg_token": st.session_state.get('tg_token', ''),
        "tg_chat_id": st.session_state.get('tg_chat_id', ''),
        "tg_threshold": st.session_state.get('tg_threshold', 3.0)
    }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 初始化 Session State
if 'initialized' not in st.session_state:
    saved_config = load_data()
    st.session_state.my_stocks = saved_config["stocks"]
    st.session_state.tg_token = saved_config["tg_token"]
    st.session_state.tg_chat_id = saved_config["tg_chat_id"]
    st.session_state.tg_threshold = saved_config["tg_threshold"]
    st.session_state.initialized = True
    st.session_state.alert_history = {}

# --- 2. 頁面配置 ---
st.set_page_config(page_title="台股自選監控 V3.2", layout="centered")
st.markdown("""
    <style>
    [data-testid="stMetricDelta"] svg { display: none; }
    .status-box { padding: 12px; border-radius: 8px; margin-bottom: 20px; text-align: center; font-weight: bold; }
    .open { background-color: #ffe6e6; color: #ff0000; border: 1px solid #ff0000; }
    .closed { background-color: #f0f2f6; color: #555; border: 1px solid #ccc; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心功能函數 ---
def get_market_status():
    now_tw = datetime.now(tw_tz)
    if now_tw.weekday() >= 5: 
        return f"💤 休市中 (週末) - {now_tw.strftime('%H:%M')}", False
    current_time = now_tw.time()
    if dt_time(9, 0) <= current_time <= dt_time(13, 35):
        return f"⚡ 開盤中 (自動監控) - {now_tw.strftime('%H:%M')}", True
    return f"🌙 休市中 (暫停自動通知) - {now_tw.strftime('%H:%M')}", False

def send_telegram_msg(token, chat_id, message):
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            res = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
            return res.json().get("ok", False)
        except: return False
    return False

dl = DataLoader()
status_label, is_open = get_market_status()

@st.cache_data(ttl=60)
def get_stock_data(stock_id):
    # 策略 A: FinMind
    try:
        now_s = datetime.now(tw_tz).strftime('%Y-%m-%d')
        start_s = (datetime.now(tw_tz) - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_price(stock_id=stock_id, start_date=start_s, end_date=now_s)
        if not df.empty:
            df = df.dropna(subset=['close'])
            curr, prev = float(df.iloc[-1]['close']), float(df.iloc[-2]['close'])
            return {"price": curr, "change": curr - prev, "pct": (curr-prev)/prev*100, "src": "FinMind"}
    except: pass
    
    # 策略 B: yfinance
    for suffix in [".TW", ".TWO"]:
        try:
            time.sleep(0.3)
            df = yf.download(f"{stock_id}{suffix}", period="5d", progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Close'])
            if len(df) >= 2:
                curr, prev = float(df.iloc[-1]['Close']), float(df.iloc[-2]['Close'])
                return {"price": curr, "change": curr - prev, "pct": (curr-prev)/prev*100, "src": f"yf{suffix}"}
        except: continue
    return None

# --- 4. 主介面 ---
st.title("📈 台股智慧自選監控")
st.markdown(f'<div class="status-box {"open" if is_open else "closed"}">{status_label}</div>', unsafe_allow_html=True)

# 管理區域
with st.expander("🛠️ 管理自選股與通知設定"):
    # 新增股票
    c_id, c_name, c_add = st.columns([2, 3, 1])
    new_id = c_id.text_input("股票代號")
    new_name = c_name.text_input("顯示名稱")
    if c_add.button("➕ 新增"):
        if new_id and new_name:
            if not any(s['id'] == new_id for s in st.session_state.my_stocks):
                st.session_state.my_stocks.append({"id": new_id, "name": new_name})
                save_data()
                st.cache_data.clear()
                st.rerun()
    
    st.divider()
    # 通知設定
    st.session_state.tg_token = st.text_input("Telegram Bot Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Telegram Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (漲跌幅%)", value=st.session_state.tg_threshold, step=0.1)
    
    c_save, c_test = st.columns(2)
    if c_save.button("💾 儲存設定"):
        save_data()
        st.success("設定已儲存！")
    
    # --- 手動全掃描測試按鈕 ---
    if c_test.button("🚀 執行手動全掃描測試"):
        if st.session_state.tg_token and st.session_state.tg_chat_id and st.session_state.my_stocks:
            with st.spinner("正在掃描清單並檢查門檻..."):
                sent_count = 0
                for stock in st.session_state.my_stocks:
                    data = get_stock_data(stock["id"])
                    if data and abs(data['pct']) >= st.session_state.tg_threshold:
                        msg = (f"🧪 <b>【手動掃描測試】</b>\n\n"
                               f"標的：<b>{stock['name']} ({stock['id']})</b>\n"
                               f"成交：{data['price']:.2f}\n"
                               f"幅度：<b>{data['pct']:+.2f}%</b>\n"
                               f"時間：{datetime.now(tw_tz).strftime('%H:%M:%S')}")
                        if send_telegram_msg(st.session_state.tg_token, st.session_state.tg_chat_id, msg):
                            sent_count += 1
                
                if sent_count > 0:
                    st.toast(f"✅ 掃描完成！共發送 {sent_count} 則符合門檻的通知", icon="🚀")
                else:
                    st.info("ℹ️ 掃描完成，目前清單中沒有股票符合門檻設定。")
        else:
            st.warning("請先完成通知設定並新增股票")

# --- 5. 監控顯示與自動邏輯 ---
if not is_open:
    st.info("💡 目前非交易時段，自動通知暫停。您可以點擊上方「手動全掃描測試」來驗證。")

for index, stock in enumerate(st.session_state.my_stocks):
    data = get_stock_data(stock["id"])
    
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 2, 1])
        if data:
            with c1:
                st.subheader(stock["name"])
                st.caption(f"{stock['id']} | 來源: {data['src']}")
            with c2:
                st.metric(label="成交價", value=f"{data['price']:.2f}", 
                          delta=f"{data['change']:+.2f} ({data['pct']:+.2f}%)", delta_color="inverse")
            
            if c3.button("🗑️", key=f"del_{stock['id']}"):
                st.session_state.my_stocks.pop(index)
                save_data()
                st.rerun()

            # 自動通知判斷 (僅限開盤時段)
            if is_open and st.session_state.tg_token and st.session_state.tg_chat_id:
                if abs(data['pct']) >= st.session_state.tg_threshold:
                    today_str = datetime.now(tw_tz).strftime('%Y%m%d')
                    alert_key = f"alert_{stock['id']}_{today_str}"
                    
                    if alert_key not in st.session_state.alert_history:
                        msg = (f"🚨 <b>台股異動通知</b>\n\n"
                               f"標的：<b>{stock['name']} ({stock['id']})</b>\n"
                               f"成交：{data['price']:.2f}\n"
                               f"幅度：<b>{data['pct']:+.2f}%</b>\n"
                               f"時間：{datetime.now(tw_tz).strftime('%H:%M:%S')}")
                        if send_telegram_msg(st.session_state.tg_token, st.session_state.tg_chat_id, msg):
                            st.session_state.alert_history[alert_key] = True
                            st.toast(f"✅ {stock['name']} 異動通知已送出")
        else:
            st.error(f"無法讀取 {stock['id']}")
            if c3.button("🗑️ 移除", key=f"err_{stock['id']}"):
                st.session_state.my_stocks.pop(index)
                save_data()
                st.rerun()

st.divider()
if st.button("🔄 手動刷新數據"):
    st.cache_data.clear()
    st.rerun()
st.caption(f"最後更新時間: {datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')}")
