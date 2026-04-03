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
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
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
st.set_page_config(page_title="台股自選監控 V3", layout="centered")
st.markdown("""
    <style>
    [data-testid="stMetricDelta"] svg { display: none; }
    .status-box { padding: 12px; border-radius: 8px; margin-bottom: 20px; text-align: center; font-weight: bold; }
    .open { background-color: #ffe6e6; color: #ff0000; border: 1px solid #ff0000; }
    .closed { background-color: #f0f2f6; color: #555; border: 1px solid #ccc; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 功能函數 ---
def get_market_status():
    """精準判斷台灣開盤時間"""
    now_tw = datetime.now(tw_tz)
    if now_tw.weekday() >= 5: 
        return f"💤 休市中 (週末) - {now_tw.strftime('%H:%M')}", False
    
    current_time = now_tw.time()
    # 台灣股市交易時間：09:00 ~ 13:35
    if dt_time(9, 0) <= current_time <= dt_time(13, 35):
        return f"⚡ 開盤中 (監控中) - {now_tw.strftime('%H:%M')}", True
    return f"🌙 休市中 (停止掃描) - {now_tw.strftime('%H:%M')}", False

def send_telegram_msg(token, chat_id, message):
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=5)
            return True
        except: return False
    return False

dl = DataLoader()
status_label, is_open = get_market_status()

@st.cache_data(ttl=60) # 盤中每分鐘更新一次
def get_stock_data(stock_id):
    # 優先嘗試 FinMind (盤中即時)
    try:
        now_s = datetime.now(tw_tz).strftime('%Y-%m-%d')
        start_s = (datetime.now(tw_tz) - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_price(stock_id=stock_id, start_date=start_s, end_date=now_s)
        if not df.empty:
            df = df.dropna(subset=['close'])
            curr, prev = float(df.iloc[-1]['close']), float(df.iloc[-2]['close'])
            return {"price": curr, "change": curr - prev, "pct": (curr-prev)/prev*100, "src": "FinMind"}
    except: pass
    
    # 備援嘗試 yfinance
    for suffix in [".TW", ".TWO"]:
        try:
            time.sleep(0.5) # 避開頻率限制
            df = yf.download(f"{stock_id}{suffix}", period="5d", progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Close'])
            if len(df) >= 2:
                curr, prev = float(df.iloc[-1]['Close']), float(df.iloc[-2]['Close'])
                return {"price": curr, "change": curr - prev, "pct": (curr-prev)/prev*100, "src": f"yf{suffix}"}
        except: continue
    return None

# --- 4. 主介面介面 ---
st.title("📈 台股智慧自選監控")
st.markdown(f'<div class="status-box {"open" if is_open else "closed"}">{status_label}</div>', unsafe_allow_html=True)

# 管理區域 (Expander)
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
    st.session_state.tg_threshold = st.number_input("通知觸發門檻 (漲跌幅%)", value=st.session_state.tg_threshold, step=0.1)
    if st.button("💾 儲存所有設定"):
        save_data()
        st.success("設定已成功永久保存！")

# --- 5. 監控邏輯 ---
if not is_open:
    st.info("💡 目前非交易時段，系統暫停自動更新與通知發送。")

for index, stock in enumerate(st.session_state.my_stocks):
    # 抓取數據 (如果是休市，依然顯示最後收盤價，但不執行通知檢查)
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
            
            # 刪除按鈕
            if c3.button("🗑️", key=f"del_{stock['id']}"):
                st.session_state.my_stocks.pop(index)
                save_data()
                st.rerun()

            # --- 關鍵通知邏輯 ---
            # 只有在「開盤中」且「符合門檻」且「今天還沒報過」時才發送
            if is_open and st.session_state.tg_token and st.session_state.tg_chat_id:
                if abs(data['pct']) >= st.session_state.tg_threshold:
                    today_str = datetime.now(tw_tz).strftime('%Y%m%d')
                    alert_key = f"alert_{stock['id']}_{today_str}"
                    
                    if alert_key not in st.session_state.alert_history:
                        # 恢復詳細通知格式
                        msg = (f"🚨 <b>台股異動通知</b>\n\n"
                               f"標的：<b>{stock['name']} ({stock['id']})</b>\n"
                               f"成交：{data['price']:.2f}\n"
                               f"幅度：<b>{data['pct']:+.2f}%</b>\n"
                               f"時間：{datetime.now(tw_tz).strftime('%H:%M:%S')}")
                        
                        if send_telegram_msg(st.session_state.tg_token, st.session_state.tg_chat_id, msg):
                            st.session_state.alert_history[alert_key] = True
                            st.toast(f"✅ {stock['name']} 已發送 Telegram 通知")
        else:
            st.error(f"無法讀取 {stock['id']} 的資料")
            if c3.button("🗑️ 移除", key=f"err_{stock['id']}"):
                st.session_state.my_stocks.pop(index)
                save_data()
                st.rerun()

st.divider()
if st.button("🔄 手動刷新數據"):
    st.cache_data.clear()
    st.rerun()
st.caption(f"系統時間 (台灣): {datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')}")
