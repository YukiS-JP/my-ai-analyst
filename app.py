import streamlit as st
import pandas as pd
import numpy as np
from tradingview_screener import Query, Column
import yfinance as yf
import time
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import urllib.request
import xml.etree.ElementTree as ET
import email.utils
import streamlit.components.v1 as components
from streamlit_sortables import sort_items
from deep_translator import GoogleTranslator

st.set_page_config(page_title="AIアナリスト", page_icon="📊", layout="wide")

# ==========================================
# 🌟 スマホUI完全最適化（2列×2行のタイル状ボタンに強制上書き）
# ==========================================
st.markdown("""
    <style>
        /* タブを包む親要素の横スクロールロックを強制解除 */
        div[data-testid="stTabs"] > div:nth-child(1),
        div[data-testid="stTabs"] > div:nth-child(1) > div {
            overflow-x: visible !important;
            overflow-y: visible !important;
        }
        /* タブのリストを折り返し可能（Wrap）に設定 */
        div[data-baseweb="tab-list"] {
            flex-wrap: wrap !important;
            gap: 8px !important;
            padding-bottom: 10px !important;
        }
        /* 各タブを「ボタン風」のタイルにする（スマホ幅で約45%ずつ＝2列になる） */
        button[data-baseweb="tab"] {
            flex: 1 1 40% !important; 
            justify-content: center !important;
            background-color: rgba(255, 255, 255, 0.05) !important;
            border-radius: 8px !important;
            margin: 0 !important;
            padding: 10px 5px !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
        }
        /* 折り返すとズレる標準のアンダーライン（ハイライト）を隠す */
        div[data-baseweb="tab-highlight"] {
            display: none !important;
        }
        /* 選択中のタブは全体を青く光らせる */
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: rgba(130, 177, 255, 0.2) !important;
            border: 1px solid #82B1FF !important;
        }
        button[data-baseweb="tab"] > div[data-testid="stMarkdownContainer"] > p {
            font-size: 15px !important;
            font-weight: bold !important;
        }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 🌟 クラウド同期ヘルパー関数（スプレッドシート連携）
# ==========================================
SHEET_URL = "https://docs.google.com/spreadsheets/d/1IMUxpioGHLPLcLlxXaVR7IYFIltIkkt4muvByDo-LI8/edit?gid=0#gid=0"

def get_cloud_client():
    creds_json = json.loads(st.secrets["google_sheets_creds"])
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    return gspread.authorize(Credentials.from_service_account_info(creds_json, scopes=scopes))

def check_already_saved(market_mode, current_date, sheet_type="screener"):
    try:
        client = get_cloud_client()
        sheet = client.open_by_url(SHEET_URL)
        target_ws_name = "スクリーニング履歴" if sheet_type == "screener" else "シート1"
        try:
            ws = sheet.worksheet(target_ws_name)
        except:
            return False
            
        all_values = ws.get_all_values()
        norm_current_date = current_date.replace('-', '/')
        
        for row in reversed(all_values):
            if len(row) >= 2:
                row_date = row[0].replace('-', '/')
                if norm_current_date in row_date and market_mode.split(' ')[0] in row[1]:
                    return True
        return False
    except:
        return False

def load_watchlist_from_cloud(market_type):
    default_us = ["SOXL", "RDW", "DNA", "FNGU"]
    default_jp = ["7203.T", "1959.T", "8035.T", "9984.T"]
    defaults = default_us if market_type == "US" else default_jp
    try:
        client = get_cloud_client()
        sheet = client.open_by_url(SHEET_URL)
        try:
            ws = sheet.worksheet("設定_監視リスト")
        except:
            ws = sheet.add_worksheet(title="設定_監視リスト", rows="100", cols="5")
            ws.append_row(["市場", "ティッカー"])
            for d in default_us: ws.append_row(["US", d])
            for d in default_jp: ws.append_row(["JP", d])
            return defaults
            
        vals = ws.get_all_values()
        list_items = [row[1] for row in vals[1:] if len(row) >= 2 and row[0] == market_type]
        return list_items if list_items else defaults
    except:
        return defaults

def save_watchlist_to_cloud(market_type, watch_list):
    try:
        client = get_cloud_client()
        sheet = client.open_by_url(SHEET_URL)
        try:
            ws = sheet.worksheet("設定_監視リスト")
        except:
            ws = sheet.add_worksheet(title="設定_監視リスト", rows="100", cols="5")
            ws.append_row(["市場", "ティッカー"])
            
        vals = ws.get_all_values()
        new_rows = [row for row in vals if row[0] != market_type]
        for sym in watch_list:
            new_rows.append([market_type, sym])
            
        ws.clear()
        if new_rows:
            ws.update(new_rows)
    except Exception as e:
        st.error(f"監視リストのクラウド同期エラー: {e}")

def load_portfolio_from_cloud(market_type):
    try:
        client = get_cloud_client()
        sheet = client.open_by_url(SHEET_URL)
        try:
            ws = sheet.worksheet("設定_ポートフォリオ")
        except:
            ws = sheet.add_worksheet(title="設定_ポートフォリオ", rows="100", cols="5")
            ws.append_row(["市場", "ティッカー", "取得単価", "数量"])
            return {}
            
        vals = ws.get_all_values()
        port = {}
        for row in vals[1:]:
            if len(row) >= 4 and row[0] == market_type:
                port[row[1]] = {'avg_price': float(row[2]), 'qty': float(row[3])}
        return port
    except:
        return {}

def save_portfolio_to_cloud(market_type, port_dict):
    try:
        client = get_cloud_client()
        sheet = client.open_by_url(SHEET_URL)
        try:
            ws = sheet.worksheet("設定_ポートフォリオ")
        except:
            ws = sheet.add_worksheet(title="設定_ポートフォリオ", rows="100", cols="5")
            ws.append_row(["市場", "ティッカー", "取得単価", "数量"])
            
        vals = ws.get_all_values()
        new_rows = [row for row in vals if row[0] != market_type]
        for sym, data in port_dict.items():
            new_rows.append([market_type, sym, str(data['avg_price']), str(data['qty'])])
            
        ws.clear()
        if new_rows:
            ws.update(new_rows)
    except Exception as e:
        st.error(f"ポートフォリオのクラウド同期エラー: {e}")

# ==========================================
# 🌟 基本設定・トップUI
# ==========================================
col_top1, col_top2 = st.columns([3, 1])
with col_top1:
    st.title("📊 My AI Analyst Dashboard")
with col_top2:
    st.write("")
    if st.button("🔄 スマホ・PC間を同期", type="primary"):
        with st.spinner("クラウドから最新のリストを読み込み中..."):
            st.session_state.watch_list_us = load_watchlist_from_cloud("US")
            st.session_state.watch_list_jp = load_watchlist_from_cloud("JP")
            st.session_state.portfolio_us = load_portfolio_from_cloud("US")
            st.session_state.portfolio_jp = load_portfolio_from_cloud("JP")
            if 'wl_ver' in st.session_state: st.session_state.wl_ver += 1
            st.success("最新データを同期しました！")
            time.sleep(1)
            st.rerun()

market_mode = st.radio("🌍 分析する市場を切り替え", ["🇺🇸 米国市場 (US)", "🇯🇵 日本市場 (JP)"], horizontal=True)
is_us = (market_mode == "🇺🇸 米国市場 (US)")
market_type_str = "US" if is_us else "JP"

curr_sym = "$" if is_us else "¥"
market_name_tv = 'america' if is_us else 'japan'
ticker_suffix_hint = "" if is_us else " (例: 7203 または 7203.T)"

# --- セッションステート初期化 ---
if 'watch_list_us' not in st.session_state: st.session_state.watch_list_us = load_watchlist_from_cloud("US")
if 'watch_list_jp' not in st.session_state: st.session_state.watch_list_jp = load_watchlist_from_cloud("JP")

if 'portfolio_us' not in st.session_state: st.session_state.portfolio_us = load_portfolio_from_cloud("US")
if 'portfolio_jp' not in st.session_state: st.session_state.portfolio_jp = load_portfolio_from_cloud("JP")

if 'company_names' not in st.session_state: st.session_state.company_names = {} 
if 'last_screened_data' not in st.session_state: st.session_state.last_screened_data = [] 

if 'last_tracker_data_us' not in st.session_state: st.session_state.last_tracker_data_us = []
if 'last_tracker_data_jp' not in st.session_state: st.session_state.last_tracker_data_jp = []

if 'wl_ver' not in st.session_state: st.session_state.wl_ver = 0
if 'mac_ver' not in st.session_state: st.session_state.mac_ver = 0

watch_list_key = 'watch_list_us' if is_us else 'watch_list_jp'
portfolio_key = 'portfolio_us' if is_us else 'portfolio_jp'
tracker_data_key = 'last_tracker_data_us' if is_us else 'last_tracker_data_jp'

watch_list = st.session_state[watch_list_key]
portfolio = st.session_state[portfolio_key]

if 'macro_dict' not in st.session_state:
    st.session_state.macro_dict = {
        "米ドル/円": "JPY=X", "S&P 500": "^GSPC", "NASDAQ": "^IXIC", 
        "日経平均": "^N225", "米国10年債利回り": "^TNX", "原油(WTI)": "CL=F", 
        "ゴールド(金)": "GC=F", "ビットコイン": "BTC-USD"
    }
if 'macro_display_list' not in st.session_state: st.session_state.macro_display_list = ["米ドル/円", "S&P 500", "NASDAQ", "日経平均"]

def update_watchlist(new_list):
    st.session_state[watch_list_key] = new_list
    if f"watch_select_{is_us}" in st.session_state:
        del st.session_state[f"watch_select_{is_us}"]
    if f"t2_select_{is_us}" in st.session_state:
        del st.session_state[f"t2_select_{is_us}"]
        
    st.session_state.wl_ver += 1
    save_watchlist_to_cloud(market_type_str, new_list)
    return new_list

def update_macro_list(new_list):
    st.session_state.macro_display_list = new_list
    if f"macro_select_{is_us}" in st.session_state:
        del st.session_state[f"macro_select_{is_us}"]
    st.session_state.mac_ver += 1
    return new_list

if 'screener_indicators' not in st.session_state: st.session_state.screener_indicators = ["RSI (14日)", "MACD", "PER (株価収益率)", "PBR (株価純資産倍率)"]

INDICATOR_MAP = {
    "RSI (14日)": {"cols": ["RSI"]}, "MACD": {"cols": ["MACD.macd", "MACD.signal"]},
    "PER (株価収益率)": {"cols": ["price_earnings_ttm"]}, "PBR (株価純資産倍率)": {"cols": ["price_book_ratio"]},
    "ROE (自己資本利益率)": {"cols": ["return_on_equity"]}, "SMA20 (20日移動平均)": {"cols": ["SMA20"]},
    "SMA50 (50日移動平均)": {"cols": ["SMA50"]}, "SMA200 (200日移動平均)": {"cols": ["SMA200"]},
    "配当利回り(%)": {"cols": ["dividend_yield_recent"]}
}

JP_COMPANY_NAMES = {
    "7203.T": "トヨタ自動車", "1959.T": "九電工", "8035.T": "東京エレクトロン",
    "9984.T": "ソフトバンクグループ", "6758.T": "ソニーグループ", "9432.T": "日本電信電話",
    "8306.T": "三菱UFJフィナンシャル・グループ", "6857.T": "アドバンテスト",
    "9983.T": "ファーストリテイリング", "6594.T": "ニデック"
}

def get_company_name(sym):
    if is_us: return sym
    clean_sym = sym.strip().upper()
    if clean_sym in JP_COMPANY_NAMES: return f"{clean_sym} {JP_COMPANY_NAMES[clean_sym]}"
    if clean_sym in st.session_state.company_names: return f"{clean_sym} {st.session_state.company_names[clean_sym]}"
    try:
        info = yf.Ticker(clean_sym).info
        name_en = info.get('shortName') or info.get('longName') or ""
        if name_en:
            name_ja = GoogleTranslator(source='en', target='ja').translate(name_en)
            st.session_state.company_names[clean_sym] = name_ja
            return f"{clean_sym} {name_ja}"
        return clean_sym
    except: return clean_sym

now_utc = datetime.utcnow()
current_market_date = (now_utc - timedelta(hours=5)).strftime('%Y-%m-%d') if is_us else (now_utc + timedelta(hours=9)).strftime('%Y-%m-%d')
now_jst = now_utc + timedelta(hours=9)

if now_jst.day >= 25:
    st.info("💡 **【AIアナリストからのコンサルティング要求】**\n月末が近づいています！スプレッドシートに蓄積された「スクリーニング履歴」のデータをコピーして、私（AI）に分析をご依頼ください。")

# ------------------------------------------------
# アプリ画面の構築（4タブ）
# ------------------------------------------------
tab_top, tab1, tab2, tab3 = st.tabs(["🏠 トップ", "🔍 スクリーニング", "🎯 トラッカー", "📰 ニュース"])

# ==========================================
# 🏠 トップ画面
# ==========================================
with tab_top:
    st.markdown("""
        <style>
            .dashboard-panel { background-color: #12141A; padding: 15px 20px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.4); border: 1px solid #2D303E; margin-bottom: 25px; }
            .panel-header { color: #82B1FF; margin-top: 0; margin-bottom: 12px; font-size: 18px; border-bottom: 1px solid #2D303E; padding-bottom: 8px;}
            .item-row { margin: 8px 0; color: #EEEEEE; font-size: 15px;}
            .item-sub-row { margin: 2px 0 12px 18px; color: #BBBBBB; font-size: 14px; line-height: 1.6;}
            .val-up { color: #00E676; font-weight: bold;}
            .val-down { color: #FF5252; font-weight: bold;}
            .val-neutral { color: #9E9E9E;}
            .sym-title { font-weight: bold; font-size: 16px; color: #FFFFFF; margin-top: 15px;}
        </style>
    """, unsafe_allow_html=True)

    with st.expander(f"💼 {market_mode.split(' ')[0]} ポートフォリオの編集"):
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        with c1: p_tick_raw = st.text_input(f"ティッカー{ticker_suffix_hint}", key=f"p_tick_{is_us}")
        with c2: p_price = st.number_input(f"平均取得単価 ({curr_sym})", min_value=0.0, step=0.1 if is_us else 1.0, format="%.2f", key=f"p_price_{is_us}")
        with c3: p_qty = st.number_input("保有数量 (株)", min_value=0.0, step=1.0, format="%.2f", key=f"p_qty_{is_us}")
        with c4:
            st.write(""); st.write("")
            if st.button("登録", key=f"p_add_{is_us}"):
                if p_tick_raw and p_qty > 0:
                    pt = p_tick_raw.strip().upper()
                    if not is_us and pt.isdigit(): pt += ".T"
                    st.session_state[portfolio_key][pt] = {'avg_price': p_price, 'qty': p_qty}
                    save_portfolio_to_cloud(market_type_str, st.session_state[portfolio_key])
                    st.rerun()
        st.divider()
        if portfolio:
            for t in list(portfolio.keys()):
                col_a, col_b = st.columns([5, 1])
                with col_a: st.write(f"**{get_company_name(t)}** : {portfolio[t]['qty']:,.2f} 株 (平均 {curr_sym}{portfolio[t]['avg_price']:,.2f})")
                with col_b:
                    if st.button("削除", key=f"del_port_{is_us}_{t}"): 
                        del st.session_state[portfolio_key][t]
                        save_portfolio_to_cloud(market_type_str, st.session_state[portfolio_key])
                        st.rerun()
        else: st.info("登録されている銘柄はありません。")
    st.write("")

    with st.spinner("最新データを取得中..."):
        port_html = f"<div class='dashboard-panel'><div class='panel-header'>💼 {market_mode.split(' ')[0]} ポートフォリオ状況</div>"
        if portfolio:
            total_cost = 0; total_value = 0; details_html = ""
            try: usd_jpy = yf.Ticker("JPY=X").history(period="1d")['Close'].iloc[-1]
            except: usd_jpy = 150.0

            for sym, data in portfolio.items():
                qty = data['qty']; avg_p = data['avg_price']; disp_name = get_company_name(sym)
                try:
                    h = yf.Ticker(sym).history(period="1d")
                    if not h.empty:
                        c_price = h['Close'].iloc[-1]
                        cost = avg_p * qty; val = c_price * qty; pnl = val - cost
                        pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
                        total_cost += cost; total_value += val
                        pnl_class = 'val-up' if pnl > 0 else 'val-down' if pnl < 0 else 'val-neutral'
                        sign = '+' if pnl > 0 else ''
                        jpy_txt = f" <span style='font-size:12px; color:#888;'>(約 ¥{int(val * usd_jpy):,})</span>" if is_us else ""
                        details_html += f"<div class='item-row sym-title'>🔹 {disp_name} <span style='font-size: 13px; color:#888; font-weight:normal;'>({qty:,.2f}株)</span></div>"
                        details_html += f"<div class='item-sub-row'>┣ <strong>評価額:</strong> {curr_sym}{val:,.2f}{jpy_txt} (現在値: {curr_sym}{c_price:,.2f})<br>┗ <strong>含み損益:</strong> <span class='{pnl_class}'>{sign}{curr_sym}{pnl:,.2f} ({sign}{pnl_pct:.2f}%)</span> ｜ 取得単価: {curr_sym}{avg_p:,.2f}</div>"
                    else: details_html += f"<div class='item-row'>🔹 <strong>{disp_name}</strong>: データ取得エラー</div>"
                except: details_html += f"<div class='item-row'>🔹 <strong>{disp_name}</strong>: エラー</div>"
            
            tot_pnl = total_value - total_cost; tot_pct = (tot_pnl / total_cost) * 100 if total_cost > 0 else 0
            tot_class = 'val-up' if tot_pnl > 0 else 'val-down' if tot_pnl < 0 else 'val-neutral'
            tot_sign = '+' if tot_pnl > 0 else ''
            tot_jpy_txt = f" <span style='font-size:16px; color:#888; font-weight:normal;'>(約 ¥{int(total_value * usd_jpy):,})</span>" if is_us else ""
            
            port_html += f"<div style='font-size: 24px; color: #FFFFFF; font-weight: bold; margin-bottom: 5px;'>総評価額: {curr_sym}{total_value:,.2f}{tot_jpy_txt}</div>"
            port_html += f"<div style='font-size: 18px; margin-bottom: 15px;'>トータル含み損益: <span class='{tot_class}'>{tot_sign}{curr_sym}{tot_pnl:,.2f} ({tot_sign}{tot_pct:.2f}%)</span></div><hr style='border-color: #2D303E; margin: 10px 0;'>"
            port_html += details_html
        else: port_html += f"<div class='item-row val-neutral'>保有銘柄が登録されていません。</div>"
        port_html += "</div>"
        st.markdown(port_html, unsafe_allow_html=True)

        col1, col2 = st.columns([5, 1])
        with col1: st.subheader("🌍 主要市場サマリー")
        with col2:
            with st.popover("⚙️ 編集"):
                new_macro_name = st.text_input("📝 表示名", key=f"mac_name_{is_us}"); new_macro_tick = st.text_input("🔤 ティッカー", key=f"mac_tick_{is_us}")
                if st.button("➕ 追加する", key=f"add_macro_btn_{is_us}"):
                    if new_macro_name and new_macro_tick:
                        st.session_state.macro_dict[new_macro_name] = new_macro_tick
                        if new_macro_name not in st.session_state.macro_display_list:
                            st.session_state.macro_display_list.append(new_macro_name)
                            update_macro_list(st.session_state.macro_display_list)
                        st.rerun()
                st.divider()
                selected_macros = st.multiselect("表示", options=list(st.session_state.macro_dict.keys()), default=st.session_state.macro_display_list, key=f"macro_select_{is_us}_{st.session_state.mac_ver}")
                if set(selected_macros) != set(st.session_state.macro_display_list):
                    new_list = [m for m in st.session_state.macro_display_list if m in selected_macros]
                    for m in selected_macros:
                        if m not in new_list: new_list.append(m)
                    update_macro_list(new_list)
                    st.rerun()
                if st.session_state.macro_display_list:
                    sorted_macros = sort_items(st.session_state.macro_display_list, key=f"macro_sort_{is_us}_{st.session_state.mac_ver}")
                    if sorted_macros != st.session_state.macro_display_list:
                        update_macro_list(sorted_macros)
                        st.rerun()

        html_macro = "<div class='dashboard-panel'>"
        for name in st.session_state.macro_display_list:
            symbol = st.session_state.macro_dict.get(name, "")
            try:
                t = yf.Ticker(symbol); h = t.history(period="5d")
                if not h.empty and len(h) >= 2:
                    c_price = h['Close'].iloc[-1]; p_price = h['Close'].iloc[-2]; diff = c_price - p_price; pct = (diff / p_price) * 100
                    if diff > 0: trend_html = f"<span class='val-up'>↑+{diff:,.2f} (+{pct:.2f}%)</span>"
                    elif diff < 0: trend_html = f"<span class='val-down'>↓{diff:,.2f} ({pct:.2f}%)</span>"
                    else: trend_html = f"<span class='val-neutral'>±0.00 (0.00%)</span>"
                    val_str = f"¥{c_price:.2f}" if "JPY" in symbol or "円" in name else f"{c_price:,.2f}"
                    html_macro += f"<div class='item-row'><strong>{name}</strong>: {val_str} ({trend_html})</div>"
                else: html_macro += f"<div class='item-row'><strong>{name}</strong>: 取得失敗</div>"
            except: html_macro += f"<div class='item-row'><strong>{name}</strong>: エラー</div>"
        html_macro += "</div>"
        st.markdown(html_macro, unsafe_allow_html=True)

        col3, col4 = st.columns([5, 1])
        with col3: st.subheader(f"📌 {market_mode.split(' ')[0]} 監視銘柄 データ一覧")
        with col4:
            with st.popover("⚙️ 編集"):
                new_watch_tick_raw = st.text_input(f"🔤 ティッカー{ticker_suffix_hint}", key=f"watch_tick_{is_us}")
                if st.button("➕ 追加", key=f"add_watch_btn_{is_us}"):
                    c_tick = new_watch_tick_raw.strip().upper()
                    if not is_us and c_tick.isdigit(): c_tick += ".T"
                    if c_tick and c_tick not in watch_list:
                        watch_list.append(c_tick)
                        watch_list = update_watchlist(watch_list)
                        st.rerun()
                st.divider()
                selected_watch = st.multiselect("表示", options=watch_list, default=watch_list, key=f"watch_select_{is_us}_{st.session_state.wl_ver}")
                if set(selected_watch) != set(watch_list):
                    new_w_list = [m for m in watch_list if m in selected_watch]
                    for m in selected_watch:
                        if m not in new_w_list: new_w_list.append(m)
                    watch_list = update_watchlist(new_w_list)
                    st.rerun()
                if watch_list:
                    sorted_watch = sort_items(watch_list, key=f"watch_sort_dd_{is_us}_{st.session_state.wl_ver}")
                    if sorted_watch != watch_list:
                        watch_list = update_watchlist(sorted_watch)
                        st.rerun()

        html_watch = "<div class='dashboard-panel'>"
        if watch_list:
            for sym in watch_list:
                disp_name = get_company_name(sym)
                try:
                    ticker = yf.Ticker(sym); hist = ticker.history(period="1y")
                    if not hist.empty and len(hist) > 22:
                        curr_p = hist['Close'].iloc[-1]; prev_p = hist['Close'].iloc[-2]
                        week_p = hist['Close'].iloc[-6] if len(hist) >= 6 else prev_p
                        month_p = hist['Close'].iloc[-22]
                        day_diff = curr_p - prev_p; day_pct = (day_diff / prev_p) * 100
                        week_pct = ((curr_p - week_p) / week_p) * 100; month_pct = ((curr_p - month_p) / month_p) * 100
                        high_52 = hist['High'].max(); dd_52 = ((curr_p - high_52) / high_52) * 100
                        delta = hist['Close'].diff()
                        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                        rs = gain / loss; rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
                        
                        if day_diff > 0: d_trend = f"<span class='val-up'>↑+{day_diff:,.2f} (+{day_pct:.2f}%)</span>"
                        elif day_diff < 0: d_trend = f"<span class='val-down'>↓{day_diff:,.2f} ({day_pct:.2f}%)</span>"
                        else: d_trend = f"<span class='val-neutral'>±0.00 (0.00%)</span>"
                        if rsi_val >= 70: rsi_stat = "<span class='val-down'>🔴 過熱</span>"
                        elif rsi_val <= 45: rsi_stat = "<span class='val-up'>🟢 割安</span>"
                        else: rsi_stat = "<span class='val-neutral'>⚪️ 中立</span>"
                        week_color = 'val-up' if week_pct > 0 else 'val-down' if week_pct < 0 else 'val-neutral'
                        month_color = 'val-up' if month_pct > 0 else 'val-down' if month_pct < 0 else 'val-neutral'
                        
                        html_watch += f"<div class='item-row sym-title'>🔹 {disp_name}</div>"
                        html_watch += f"<div class='item-sub-row'>┣ <strong>現在値:</strong> {curr_sym}{curr_p:,.2f} (前日比: {d_trend})<br>┣ <strong>前週比:</strong> <span class='{week_color}'>{week_pct:+.2f}%</span> ｜ <strong>前月比:</strong> <span class='{month_color}'>{month_pct:+.2f}%</span><br>┗ <strong>RSI:</strong> {rsi_val:.1f} ({rsi_stat}) ｜ <strong>高値差:</strong> {dd_52:+.1f}%</div>"
                except: html_watch += f"<div class='item-row sym-title'>🔹 {disp_name}</div><div class='item-sub-row'>データ取得エラー</div>"
        else: html_watch += "<div class='item-row val-neutral'>表示する銘柄がありません。⚙️編集から追加してください。</div>"
        html_watch += "</div>"
        st.markdown(html_watch, unsafe_allow_html=True)
    
    st.write("")
    if watch_list:
        for sym in watch_list:
            disp_name = get_company_name(sym)
            # 🌟 修正ポイント：日本株の場合はTradingViewがブロックするため、Yahoo Financeのチャートリンクに変更
            with st.expander(f"📈 {disp_name} の詳細チャートを開く / 閉じる"):
                if is_us:
                    html_code = f"""<div class="tradingview-widget-container"><div id="tradingview_{sym}"></div><script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script><script type="text/javascript">new TradingView.widget({{"width": "100%", "height": 400, "symbol": "{sym}", "interval": "D", "timezone": "Asia/Tokyo", "theme": "dark", "style": "1", "locale": "ja", "enable_publishing": false, "allow_symbol_change": true, "hide_top_toolbar": false, "container_id": "tradingview_{sym}"}});</script></div>"""
                    components.html(html_code, height=400)
                else:
                    st.info(f"💡 日本株のインタラクティブチャートはYahoo!ファイナンスで確認できます。")
                    st.markdown(f"👉 **[{disp_name} のチャートを見る (Yahoo! Finance)](https://finance.yahoo.co.jp/quote/{sym}/chart)**")

# ==========================================
# 🔍 タブ1：全体スクリーニング
# ==========================================
with tab1:
    st.write(f"**{market_mode.split(' ')[0]}の市場全体**から、厳しい条件をクリアした反発期待の優良株を探します。")
    
    col_scr1, col_scr2 = st.columns([4, 2])
    with col_scr1:
        if is_us: budget_jpy_man = st.number_input("💰 今回の投資予定資金（万円）", min_value=10, max_value=5000, value=100, step=10, key="budget_input_us")
        else: budget_jpy_man = st.number_input("💰 今回の投資予定資金（万円）", min_value=10, max_value=5000, value=50, step=10, key="budget_input_jp")
        budget_jpy = budget_jpy_man * 10_000

    with col_scr2:
        with st.popover("⚙️ 指標の編集"):
            st.markdown("**追加と並び替え**")
            selected_inds = st.multiselect("表示する指標", options=list(INDICATOR_MAP.keys()), default=st.session_state.screener_indicators, key=f"scr_select_{is_us}")
            if set(selected_inds) != set(st.session_state.screener_indicators):
                new_list = [m for m in st.session_state.screener_indicators if m in selected_inds]
                for m in selected_inds:
                    if m not in new_list: new_list.append(m)
                st.session_state.screener_indicators = new_list; st.rerun()
            if st.session_state.screener_indicators:
                sorted_inds = sort_items(st.session_state.screener_indicators, key=f"scr_sort_dd_{is_us}")
                if sorted_inds != st.session_state.screener_indicators: st.session_state.screener_indicators = sorted_inds; st.rerun()

    if st.button(f"🚀 {market_mode.split(' ')[0]}の厳選チャンス銘柄をスクリーニング", key=f"scr_run_btn_{is_us}"):
        st.session_state.last_screened_data = [] 
        
        with st.spinner(f'{market_mode}から厳しい条件に合う銘柄を抽出中...'):
            try: usd_jpy = yf.Ticker("JPY=X").history(period="1d")['Close'].iloc[-1]
            except: usd_jpy = 150.0 
            
            if is_us:
                budget_target = budget_jpy / usd_jpy
                st.info(f"💡 現在の為替レート: **$1 = ¥{usd_jpy:.2f}** （予定資金: 約 **${budget_target:,.2f}**）")
            else:
                budget_target = budget_jpy
                st.info(f"💡 予定資金: **¥{budget_target:,.0f}**")

            query_cols = ['name', 'description', 'close', 'Perf.W', 'market_cap_basic', 'volume', 'RSI', 'MACD.macd', 'MACD.signal', 'SMA50', 'SMA200']
            for ind in st.session_state.screener_indicators:
                cols = INDICATOR_MAP[ind]["cols"]; query_cols.extend(cols)
            query_cols = list(set(query_cols))
            
            if is_us:
                min_mcap = 10_000_000_000; max_mcap = 10_000_000_000_000; min_vol = 2_000_000; max_price = budget_target  
            else:
                min_mcap = 30_000_000_000; max_mcap = 1_000_000_000_000; min_vol = 300_000; max_price = budget_target / 100  
            
            conditions = [
                Column('market_cap_basic') > min_mcap, Column('market_cap_basic') < max_mcap,  
                Column('volume') > min_vol, Column('price_earnings_ttm') > 0, Column('RSI') < 40,
                Column('close') <= max_price, Column('close') > Column('SMA200'), Column('close') > Column('SMA50')
            ]
                
            q = (Query().select(*query_cols).where(*conditions).order_by('market_cap_basic', ascending=False).limit(10))
            try: df = q.set_markets(market_name_tv).get_scanner_data()[1]
            except: df = pd.DataFrame()
            
            if not df.empty:
                st.success(f"🎯 厳格なスクリーニングを通過した銘柄です！")
                
                for index, row in df.iterrows():
                    if is_us: sym_name = row['name']
                    else:
                        raw_name = row['name']; desc_en = row.get('description', '')
                        try: desc_ja = GoogleTranslator(source='en', target='ja').translate(desc_en) if desc_en else ''
                        except: desc_ja = desc_en
                        sym_name = f"{raw_name}.T {desc_ja}"
                        
                    curr_price = row.get('close', 1)
                    st.markdown(f"### 📌 {sym_name} (現在値: {curr_sym}{curr_price:,.2f})")
                    
                    macd = row.get('MACD.macd'); sig = row.get('MACD.signal')
                    is_golden_cross = (macd > sig) if pd.notna(macd) and pd.notna(sig) else False
                        
                    if is_golden_cross:
                        conv_type = "本気買い"; conviction_title = "🔥 本気買い（フル・エントリー）"; alloc_pct = 1.0
                        strategy_msg = "中長期トレンド（50日線・200日線）が上向きの中で、MACDのゴールデンクロスが確認されました。絶好の押し目買いのタイミングです。"
                    else:
                        conv_type = "打診買い"; conviction_title = "💧 打診買い（テスト・エントリー）"; alloc_pct = 0.3
                        strategy_msg = "中長期トレンドは上向きでRSIも割安ですが、MACDがまだ下落を示しています。底探りの段階です。"

                    alloc_target = budget_target * alloc_pct
                    if is_us: shares_to_buy = int(alloc_target / curr_price)
                    else:
                        shares_to_buy = int((alloc_target / curr_price) // 100) * 100
                        if shares_to_buy == 0: shares_to_buy = 100 
                        
                    st.error(f"**{conviction_title}**\n\n**推奨購入目安:** 約 {shares_to_buy:,} 株\n\n*{strategy_msg}*")
                    
                    rsi_val = row.get('RSI')
                    st.session_state.last_screened_data.append([
                        now_jst.strftime('%Y/%m/%d'), market_mode.split(' ')[0], sym_name,
                        round(curr_price, 2), conv_type, shares_to_buy,
                        round(rsi_val, 1) if pd.notna(rsi_val) else "", round(macd, 2) if pd.notna(macd) else ""
                    ])

                    metrics_strs = []
                    perf_w = row.get('Perf.W')
                    if pd.notna(perf_w): metrics_strs.append(f"前週比: {perf_w:.1f}%")
                    for ind in st.session_state.screener_indicators:
                        if ind == "RSI (14日)":
                            if pd.notna(rsi_val): metrics_strs.append(f"RSI: {rsi_val:.1f}")
                        elif ind == "MACD":
                            if pd.notna(macd) and pd.notna(sig): metrics_strs.append(f"MACD: {macd:.2f}")
                        elif ind == "PER (株価収益率)":
                            val = row.get('price_earnings_ttm')
                            if pd.notna(val): metrics_strs.append(f"PER: {val:.1f}倍")
                        elif ind == "PBR (株価純資産倍率)":
                            val = row.get('price_book_ratio')
                            if pd.notna(val): metrics_strs.append(f"PBR: {val:.2f}倍")
                        elif ind == "ROE (自己資本利益率)":
                            val = row.get('return_on_equity')
                            if pd.notna(val): metrics_strs.append(f"ROE: {val:.1f}%")
                        elif "SMA" in ind:
                            col_name = INDICATOR_MAP[ind]["cols"][0]
                            val = row.get(col_name)
                            if pd.notna(val) and pd.notna(curr_price): metrics_strs.append(f"{ind.split(' ')[0]}: {curr_sym}{val:,.2f}")
                        elif ind == "配当利回り(%)":
                            val = row.get('dividend_yield_recent')
                            if pd.notna(val): metrics_strs.append(f"配当利回り: {val:.2f}%")

                    st.markdown(f"- **取得データ:** " + " ｜ ".join(metrics_strs))
                    st.divider()
            else:
                st.warning("現在、厳しい条件を満たす銘柄は見つかりませんでした。\n無駄なトレードを避け、資金を温存して静観を推奨します。")

    if st.session_state.last_screened_data:
        st.write("")
        if check_already_saved(market_mode, current_market_date, sheet_type="screener"):
            st.success(f"✅ 本日（{current_market_date}）の {market_mode.split(' ')[0]} スクリーニングデータはクラウド上で保存済みです！")
        else:
            if st.button("💾 このスクリーニング結果をスプレッドシートに保存（学習用）", type="primary", key=f"scr_save_btn_{is_us}"):
                with st.spinner("データを保存中..."):
                    try:
                        creds_json = json.loads(st.secrets["google_sheets_creds"])
                        scopes = ['https://www.googleapis.com/auth/spreadsheets']
                        client = gspread.authorize(Credentials.from_service_account_info(creds_json, scopes=scopes))
                        sheet = client.open_by_url(SHEET_URL)
                        try: ws = sheet.worksheet("スクリーニング履歴")
                        except gspread.exceptions.WorksheetNotFound:
                            ws = sheet.add_worksheet(title="スクリーニング履歴", rows="1000", cols="10")
                            ws.append_row(["取得日付", "市場", "ティッカー", "現在値", "判定", "推奨購入株数", "RSI", "MACD"])

                        for row in st.session_state.last_screened_data: ws.append_row(row)
                        st.success("✅ スプレッドシートの「スクリーニング履歴」タブに保存しました！")
                        time.sleep(1.5); st.rerun() 
                    except Exception as e: st.error(f"保存に失敗しました: {e}")

# ==========================================
# 🎯 タブ2：個別銘柄トラッカー
# ==========================================
with tab2:
    st.write(f"監視中の特定銘柄の状況を確認し、**スイング（中期）と長期投資（ガチホ）のダブル判定**を行います。")

    with st.form(key=f"add_ticker_form_{is_us}", clear_on_submit=True):
        col_f1, col_f2 = st.columns([3, 1])
        with col_f1:
            new_ticker_raw = st.text_input(f"➕ 新しい銘柄を追加{ticker_suffix_hint}", placeholder="例: 7203 または 7203.T")
        with col_f2:
            st.write("")
            st.write("")
            submitted = st.form_submit_button("追加する")
            
        if submitted and new_ticker_raw:
            clean_ticker = new_ticker_raw.strip().upper()
            if not is_us and clean_ticker.isdigit(): 
                clean_ticker += ".T"
            
            if clean_ticker in watch_list:
                st.warning(f"⚠️ 「{clean_ticker}」はすでに監視リストに登録されています。")
            else:
                watch_list.append(clean_ticker)
                watch_list = update_watchlist(watch_list) 
                st.success(f"✅ 「{clean_ticker}」を追加しました！自動でデータを取得します。")
                time.sleep(0.5)
                st.rerun()

    st.markdown("📝 **現在の監視リスト**")
    selected = st.multiselect("「×」でリストから削除できます", options=watch_list, default=watch_list, key=f"t2_select_{is_us}_{st.session_state.wl_ver}")
    if set(selected) != set(watch_list):
        new_w_list = [m for m in watch_list if m in selected]
        for m in selected:
            if m not in new_w_list: new_w_list.append(m)
        watch_list = update_watchlist(new_w_list) 
        st.rerun()

    if len(watch_list) > 1:
        with st.popover("↕️ リストの並び替え（ドラッグ＆ドロップ）"):
            st.markdown("**ドラッグ＆ドロップで順番を変更できます**")
            sorted_watch = sort_items(watch_list, key=f"t2_sort_{is_us}_{st.session_state.wl_ver}")
            if sorted_watch != watch_list:
                watch_list = update_watchlist(sorted_watch)
                st.rerun()

    if f"last_fetched_wl_{is_us}" not in st.session_state:
        st.session_state[f"last_fetched_wl_{is_us}"] = []
    
    auto_fetch = (st.session_state[f"last_fetched_wl_{is_us}"] != watch_list)

    if st.button("🔄 最新の株価・AI判定に更新（手動リロード）", key=f"t2_fetch_btn_{is_us}") or auto_fetch:
        with st.spinner('データを取得・計算中...'):
            st.session_state[tracker_data_key] = [] 
            for sym in watch_list:
                disp_name = get_company_name(sym) 
                hist = pd.DataFrame()
                for attempt in range(3):
                    try:
                        hist = yf.Ticker(sym).history(period="2y")
                        if not hist.empty: break 
                        time.sleep(0.5) 
                    except: time.sleep(0.5)
                if hist.empty: continue
                try:
                    close = hist['Close'].iloc[-1]
                    perf_w = ((close - hist['Close'].iloc[-6]) / hist['Close'].iloc[-6]) * 100 if len(hist) >= 6 else np.nan

                    # --- 日足（スイング・中期向け）の計算 ---
                    delta_d = hist['Close'].diff()
                    gain_d = (delta_d.where(delta_d > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    loss_d = (-delta_d.where(delta_d < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    rsi_d = (100 - (100 / (1 + gain_d / loss_d))).iloc[-1]
                    
                    macd_d = hist['Close'].ewm(span=12, adjust=False).mean() - hist['Close'].ewm(span=26, adjust=False).mean()
                    sig_d = macd_d.ewm(span=9, adjust=False).mean()

                    # --- 週足（ガチホ・長期向け）の計算 ---
                    hist_w = hist.resample('W-FRI').agg({'Close':'last'}).dropna()
                    if len(hist_w) > 26:
                        delta_w = hist_w['Close'].diff()
                        gain_w = (delta_w.where(delta_w > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                        loss_w = (-delta_w.where(delta_w < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                        rsi_w = (100 - (100 / (1 + gain_w / loss_w))).iloc[-1]
                        
                        macd_w = hist_w['Close'].ewm(span=12, adjust=False).mean() - hist_w['Close'].ewm(span=26, adjust=False).mean()
                        sig_w = macd_w.ewm(span=9, adjust=False).mean()
                    else:
                        rsi_w = np.nan
                        macd_w = pd.Series([np.nan])
                        sig_w = pd.Series([np.nan])

                    # --- 🎯 スイング（中期）の判定ロジック ---
                    if rsi_d > 70: swing_sig = f"🔴【利確推奨】日足RSI過熱({rsi_d:.1f})。スイング枠は利益確定の目安です。"
                    elif macd_d.iloc[-1] < sig_d.iloc[-1]: swing_sig = f"🔵【様子見】日足MACDがデッドクロス中。下落トレンドです。"
                    elif rsi_d < 45 and macd_d.iloc[-1] > sig_d.iloc[-1]: swing_sig = f"🟢【短期買】日足割安水準でMACD好転。スイングの絶好の押し目です。"
                    else: swing_sig = f"⚪️【静観】日足は中立圏。スイングは次の波を待つ局面です。"

                    # --- 🔭 長期投資（ガチホ）の判定ロジック ---
                    if pd.isna(rsi_w): long_sig = "データ不足により長期判定不可"
                    elif rsi_w > 70: long_sig = f"🔴【警戒】週足RSI過熱({rsi_w:.1f})。長期保有枠の一部利確も検討水準です。"
                    elif macd_w.iloc[-1] < sig_w.iloc[-1]: long_sig = f"🔵【忍耐】週足MACD調整中。長期投資なら焦らず安値を拾うか放置する時期です。"
                    elif rsi_w < 45 and macd_w.iloc[-1] > sig_w.iloc[-1]: long_sig = f"🟢【長期買】週足底打ちサイン。数年スパンでの強力な仕込み時です。"
                    else: long_sig = f"⚪️【ガチホ】週足は安定トレンド。長期枠はそのままホールド推奨です。"
                        
                    st.session_state[tracker_data_key].append({
                        'ティッカー': disp_name, 'sym': sym, '現在値': close, 
                        '日足RSI': rsi_d, '週足RSI': rsi_w,
                        '週足パフォーマンス(%)': perf_w, 
                        'swing_sig': swing_sig, 'long_sig': long_sig
                    })
                except Exception as e: pass
            
            st.session_state[f"last_fetched_wl_{is_us}"] = list(watch_list)

    current_tracker_data = st.session_state[tracker_data_key]
    if current_tracker_data:
        for data in current_tracker_data:
            sym = data['sym']
            disp_name = data['ティッカー']
            
            st.markdown(f"### 📌 {disp_name} (現在値: {curr_sym}{data['現在値']:,.2f})")
            rsi_w_str = f"{data['週足RSI']:.1f}" if pd.notna(data['週足RSI']) else "N/A"
            st.markdown(f"- **日足RSI:** {data['日足RSI']:.1f}  |  **週足RSI:** {rsi_w_str}  |  **週足パフォーマンス:** {data['週足パフォーマンス(%)']:.1f}%")
            
            st.info(f"**🎯 スイング（中期）:** {data['swing_sig']}")
            st.success(f"**🔭 長期（ガチホ）:** {data['long_sig']}")
            
            # 🌟 修正ポイント：日本株の場合はTradingViewがブロックするため、Yahoo Financeのチャートリンクに変更
            with st.expander(f"📈 {disp_name} のチャートを見る"):
                if is_us:
                    html_code = f"""<div class="tradingview-widget-container"><div id="tradingview_t2_{sym}"></div><script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script><script type="text/javascript">new TradingView.widget({{"width": "100%", "height": 400, "symbol": "{sym}", "interval": "D", "timezone": "Asia/Tokyo", "theme": "dark", "style": "1", "locale": "ja", "enable_publishing": false, "allow_symbol_change": true, "hide_top_toolbar": false, "container_id": "tradingview_t2_{sym}"}});</script></div>"""
                    components.html(html_code, height=400)
                else:
                    st.info(f"💡 日本株のインタラクティブチャートはYahoo!ファイナンスで確認できます。")
                    st.markdown(f"👉 **[{disp_name} のチャートを見る (Yahoo! Finance)](https://finance.yahoo.co.jp/quote/{sym}/chart)**")
                
            st.divider()

        st.write("")
        if check_already_saved(market_mode, current_market_date, sheet_type="tracker"):
            st.success(f"✅ 本日（{current_market_date}）の {market_mode.split(' ')[0]} トラッカー記録はクラウド上で保存済みです！")
        else:
            if st.button("💾 この判定結果をスプレッドシートに記録", type="primary", key=f"t2_save_btn_{is_us}"):
                with st.spinner("スプレッドシートに記録中..."):
                    try:
                        creds_json = json.loads(st.secrets["google_sheets_creds"])
                        scopes = ['https://www.googleapis.com/auth/spreadsheets']
                        client = gspread.authorize(Credentials.from_service_account_info(creds_json, scopes=scopes))
                        sheet = client.open_by_url(SHEET_URL).sheet1
                        
                        for data in current_tracker_data:
                            combined_sig = f"[中期] {data['swing_sig']} \n [長期] {data['long_sig']}"
                            
                            row = [
                                now_jst.strftime('%Y/%m/%d %H:%M'), 
                                f"{market_mode.split(' ')[0]} {data['sym']}", 
                                round(data['現在値'], 2), 
                                round(data['日足RSI'], 1), 
                                round(data['週足RSI'], 1) if pd.notna(data['週足RSI']) else "", 
                                round(data['週足パフォーマンス(%)'], 1) if pd.notna(data['週足パフォーマンス(%)']) else "", 
                                combined_sig
                            ]
                            sheet.append_row(row)
                        
                        st.success("✅ スプレッドシートへの記録が完了しました！")
                        time.sleep(1.5)
                        st.rerun()
                    except Exception as e: st.error(f"⚠️ スプレッドシートへの記録に失敗しました: {e}")

# ==========================================
# 📰 タブ3：ニュース
# ==========================================
with tab3:
    st.write("監視中の**全銘柄**に関連する最新ニュースを一覧でチェックできます。")
    if watch_list:
        if st.button("📰 監視リストの最新ニュースを一括取得", key=f"news_btn_{is_us}"):
            with st.spinner('全銘柄のニュースを検索中...'):
                def display_news_item(item):
                    title = item.find('title').text if item.find('title') is not None else 'タイトルなし'
                    link = item.find('link').text if item.find('link') is not None else '#'
                    source_elem = item.find('source')
                    publisher = source_elem.text if source_elem is not None else '配信元不明'
                    pub_date_str = item.find('pubDate').text if item.find('pubDate') is not None else ''
                    dt = "時刻不明"
                    if pub_date_str:
                        time_tuple = email.utils.parsedate_tz(pub_date_str)
                        if time_tuple:
                            timestamp = email.utils.mktime_tz(time_tuple)
                            dt_obj = datetime.utcfromtimestamp(timestamp) + timedelta(hours=9)
                            dt = dt_obj.strftime('%Y/%m/%d %H:%M')
                    st.markdown(f"**[{title}]({link})**")
                    st.caption(f"🏢 {publisher}  |  🕒 {dt}")

                for sym in watch_list:
                    disp_name = get_company_name(sym)
                    st.markdown(f"### 📌 {disp_name} のニュース")
                    try:
                        search_q = sym.replace('.T', '') if is_us else disp_name.split(' ')[-1]
                        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(search_q)}+stock&hl=ja&gl=JP&ceid=JP:ja"
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req) as response: xml_data = response.read()
                        root = ET.fromstring(xml_data); items = root.findall('.//item')
                        if items:
                            for item in items[:3]: display_news_item(item)
                            if len(items) > 3:
                                with st.expander(f"🔽 {disp_name} のその他のニュースを見る"):
                                    for item in items[3:10]: display_news_item(item); st.write("") 
                        else: st.info("ニュースは見つかりませんでした。")
                    except Exception as e: st.error("ニュース取得中にエラーが発生しました。")
                    st.divider()
    else: st.info("タブ2（個別銘柄トラッカー）で監視リストに銘柄を追加してください。")
