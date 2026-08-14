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
# 🌟 スマホ最適化！ワンタップ・モード切替（画面トップ）
# ==========================================
st.title("📊 My AI Analyst Dashboard")

market_mode = st.radio(
    "🌍 分析する市場を切り替え",
    ["🇺🇸 米国市場 (US)", "🇯🇵 日本市場 (JP)"],
    horizontal=True 
)
is_us = (market_mode == "🇺🇸 米国市場 (US)")

# 通貨・市場・サフィックス設定
curr_sym = "$" if is_us else "¥"
market_name_tv = 'america' if is_us else 'japan'
ticker_suffix_hint = "" if is_us else " (例: 7203.T)"

# --- セッションステート初期化 ---
if 'watch_list_us' not in st.session_state: st.session_state.watch_list_us = ["SOXL", "RDW", "DNA", "FNGU"]
if 'watch_list_jp' not in st.session_state: st.session_state.watch_list_jp = ["7203.T", "1959.T", "8035.T", "9984.T"]
if 'portfolio_us' not in st.session_state: st.session_state.portfolio_us = {}
if 'portfolio_jp' not in st.session_state: st.session_state.portfolio_jp = {}
if 'company_names' not in st.session_state: st.session_state.company_names = {} 
if 'last_screened_data' not in st.session_state: st.session_state.last_screened_data = [] 
if 'saved_dates' not in st.session_state: st.session_state.saved_dates = {'🇺🇸 米国市場 (US)': None, '🇯🇵 日本市場 (JP)': None} # 🌟 保存日メモリ
if 'current_market_mode' not in st.session_state: st.session_state.current_market_mode = market_mode

# 🌟 市場を切り替えたら、表示中のスクリーニングデータをリセット（誤保存防止）
if st.session_state.current_market_mode != market_mode:
    st.session_state.last_screened_data = []
    st.session_state.current_market_mode = market_mode

watch_list_key = 'watch_list_us' if is_us else 'watch_list_jp'
portfolio_key = 'portfolio_us' if is_us else 'portfolio_jp'
watch_list = st.session_state[watch_list_key]
portfolio = st.session_state[portfolio_key]

if 'macro_dict' not in st.session_state:
    st.session_state.macro_dict = {
        "米ドル/円": "JPY=X", "S&P 500": "^GSPC", "NASDAQ": "^IXIC", 
        "日経平均": "^N225", "米国10年債利回り": "^TNX", "原油(WTI)": "CL=F", 
        "ゴールド(金)": "GC=F", "ビットコイン": "BTC-USD"
    }
if 'macro_display_list' not in st.session_state: st.session_state.macro_display_list = ["米ドル/円", "S&P 500", "NASDAQ", "日経平均"]
if 'screener_indicators' not in st.session_state: st.session_state.screener_indicators = ["RSI (14日)", "MACD", "PER (株価収益率)", "PBR (株価純資産倍率)"]

INDICATOR_MAP = {
    "RSI (14日)": {"cols": ["RSI"]}, "MACD": {"cols": ["MACD.macd", "MACD.signal"]},
    "PER (株価収益率)": {"cols": ["price_earnings_ttm"]}, "PBR (株価純資産倍率)": {"cols": ["price_book_ratio"]},
    "ROE (自己資本利益率)": {"cols": ["return_on_equity"]}, "SMA20 (20日移動平均)": {"cols": ["SMA20"]},
    "SMA50 (50日移動平均)": {"cols": ["SMA50"]}, "SMA200 (200日移動平均)": {"cols": ["SMA200"]},
    "配当利回り(%)": {"cols": ["dividend_yield_recent"]}
}

def get_company_name(sym):
    if is_us: return sym
    if sym in st.session_state.company_names: return f"{sym} {st.session_state.company_names[sym]}"
    try:
        info = yf.Ticker(sym).info
        name_en = info.get('shortName') or info.get('longName') or ""
        if name_en:
            name_ja = GoogleTranslator(source='en', target='ja').translate(name_en)
            st.session_state.company_names[sym] = name_ja
            return f"{sym} {name_ja}"
        return sym
    except: return sym

# 🌟 現在の市場に応じた「今日の日付」を計算（米国はNY時間、日本は日本時間）
now_utc = datetime.utcnow()
if is_us:
    current_market_date = (now_utc - timedelta(hours=5)).strftime('%Y-%m-%d') # NY時間(おおよそ)
else:
    current_market_date = (now_utc + timedelta(hours=9)).strftime('%Y-%m-%d') # 日本時間

now_jst = now_utc + timedelta(hours=9)

# 月末のAIコンサル要求アラート
if now_jst.day >= 25:
    st.info("💡 **【AIアナリストからのコンサルティング要求】**\n月末が近づいています！スプレッドシートに蓄積された「スクリーニング履歴」のデータをコピーして、私（AI）に分析をご依頼ください。抽出銘柄の勝率を割り出し、来月に向けてフィルターの精度を上げるための学習アップデートを行いましょう！")

# ------------------------------------------------
# アプリ画面の構築（タブで4画面に分割）
# ------------------------------------------------
tab_top, tab1, tab2, tab3 = st.tabs(["🏠 トップ", "🔍 スクリーニング", "🎯 トラッカー", "📰 ニュース"])

# ==========================================
# 🌟 トップ（電光掲示板風サマリー ＆ ポートフォリオ機能）
# ==========================================
with tab_top:
    st.markdown("""
        <style>
            .dashboard-panel {
                background-color: #12141A; padding: 15px 20px; border-radius: 12px;
                box-shadow: 0 4px 10px rgba(0,0,0,0.4); border: 1px solid #2D303E;
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; margin-bottom: 25px;
            }
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
        with c1: p_tick = st.text_input(f"ティッカー{ticker_suffix_hint}", key="p_tick")
        with c2: p_price = st.number_input(f"平均取得単価 ({curr_sym})", min_value=0.0, step=0.1 if is_us else 1.0, format="%.2f", key="p_price")
        with c3: p_qty = st.number_input("保有数量 (株)", min_value=0.0, step=1.0, format="%.2f", key="p_qty")
        with c4:
            st.write(""); st.write("")
            if st.button("登録", key="p_add"):
                if p_tick and p_qty > 0:
                    st.session_state[portfolio_key][p_tick.strip().upper()] = {'avg_price': p_price, 'qty': p_qty}; st.rerun()
        st.divider()
        if portfolio:
            for t in list(portfolio.keys()):
                col_a, col_b = st.columns([5, 1])
                with col_a: st.write(f"**{get_company_name(t)}** : {portfolio[t]['qty']:,.2f} 株 (平均 {curr_sym}{portfolio[t]['avg_price']:,.2f})")
                with col_b:
                    if st.button("削除", key=f"del_port_{t}"): del st.session_state[portfolio_key][t]; st.rerun()
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
                new_macro_name = st.text_input("📝 表示名", key="mac_name"); new_macro_tick = st.text_input("🔤 ティッカー", key="mac_tick")
                if st.button("➕ 追加する", key="add_macro_btn"):
                    if new_macro_name and new_macro_tick:
                        st.session_state.macro_dict[new_macro_name] = new_macro_tick
                        if new_macro_name not in st.session_state.macro_display_list: st.session_state.macro_display_list.append(new_macro_name)
                        st.rerun()
                st.divider()
                selected_macros = st.multiselect("表示", options=list(st.session_state.macro_dict.keys()), default=st.session_state.macro_display_list, key="macro_select")
                if set(selected_macros) != set(st.session_state.macro_display_list):
                    new_list = [m for m in st.session_state.macro_display_list if m in selected_macros]
                    for m in selected_macros:
                        if m not in new_list: new_list.append(m)
                    st.session_state.macro_display_list = new_list; st.rerun()
                if st.session_state.macro_display_list:
                    sorted_macros = sort_items(st.session_state.macro_display_list, key="macro_sort")
                    if sorted_macros != st.session_state.macro_display_list: st.session_state.macro_display_list = sorted_macros; st.rerun()

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
                new_watch_tick = st.text_input(f"🔤 ティッカー{ticker_suffix_hint}", key="watch_tick")
                if st.button("➕ 追加", key="add_watch_btn"):
                    c_tick = new_watch_tick.strip().upper()
                    if c_tick and c_tick not in watch_list: st.session_state[watch_list_key].append(c_tick); st.rerun()
                st.divider()
                selected_watch = st.multiselect("表示", options=watch_list, default=watch_list, key="watch_select")
                if set(selected_watch) != set(watch_list):
                    new_w_list = [m for m in watch_list if m in selected_watch]
                    for m in selected_watch:
                        if m not in new_w_list: new_w_list.append(m)
                    st.session_state[watch_list_key] = new_w_list; st.rerun()
                if watch_list:
                    sorted_watch = sort_items(watch_list, key="watch_sort_dd")
                    if sorted_watch != watch_list: st.session_state[watch_list_key] = sorted_watch; st.rerun()

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
        else: html_watch += "<div class='item-row val-neutral'>表示する銘柄がありません。</div>"
        html_watch += "</div>"
        st.markdown(html_watch, unsafe_allow_html=True)
    
    st.write("")
    if watch_list:
        for sym in watch_list:
            disp_name = get_company_name(sym); tv_sym = sym.replace('.T', '') if not is_us else sym
            with st.expander(f"📈 {disp_name} の詳細チャートを開く / 閉じる"):
                html_code = f"""<div class="tradingview-widget-container"><div id="tradingview_{tv_sym}"></div><script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script><script type="text/javascript">new TradingView.widget({{"width": "100%", "height": 400, "symbol": "{tv_sym}", "interval": "D", "timezone": "Asia/Tokyo", "theme": "dark", "style": "1", "locale": "ja", "enable_publishing": false, "allow_symbol_change": true, "hide_top_toolbar": false, "container_id": "tradingview_{tv_sym}"}});</script></div>"""
                components.html(html_code, height=400)

# ==========================================
# 🌟 タブ1：全体スクリーニング（二重保存防止機能付き）
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
            selected_inds = st.multiselect("表示する指標", options=list(INDICATOR_MAP.keys()), default=st.session_state.screener_indicators, key="scr_select")
            if set(selected_inds) != set(st.session_state.screener_indicators):
                new_list = [m for m in st.session_state.screener_indicators if m in selected_inds]
                for m in selected_inds:
                    if m not in new_list: new_list.append(m)
                st.session_state.screener_indicators = new_list; st.rerun()
            if st.session_state.screener_indicators:
                sorted_inds = sort_items(st.session_state.screener_indicators, key="scr_sort_dd")
                if sorted_inds != st.session_state.screener_indicators: st.session_state.screener_indicators = sorted_inds; st.rerun()

    if st.button(f"🚀 {market_mode.split(' ')[0]}の厳選チャンス銘柄をスクリーニング"):
        st.session_state.last_screened_data = [] # 新しい検索で履歴をリセット
        
        with st.spinner(f'{market_mode}から厳しい条件に合う銘柄を抽出中...'):
            try: usd_jpy = yf.Ticker("JPY=X").history(period="1d")['Close'].iloc[-1]
            except: usd_jpy = 150.0 
            
            if is_us:
                budget_target = budget_jpy / usd_jpy
                st.info(f"💡 現在の為替レート: **$1 = ¥{usd_jpy:.2f}** （予定資金: 約 **${budget_target:,.2f}**）")
            else:
                budget_target = budget_jpy
                st.info(f"💡 予定資金: **¥{budget_target:,.0f}**")

            query_cols = ['name', 'description', 'close', 'Perf.W', 'market_cap_basic', 'volume', 'RSI', 'MACD.macd', 'MACD.signal', 'SMA200']
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
                Column('close') <= max_price, Column('close') > Column('SMA200')
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
                        conv_type = "本気買い"
                        conviction_title = "🔥 本気買い（フル・エントリー）"
                        alloc_pct = 1.0
                        strategy_msg = "長期トレンド（200日線）が上向きの中で、MACDのゴールデンクロスが確認されました。絶好の押し目買いのタイミングです。"
                    else:
                        conv_type = "打診買い"
                        conviction_title = "💧 打診買い（テスト・エントリー）"
                        alloc_pct = 0.3
                        strategy_msg = "長期トレンドは上向きでRSIも割安ですが、MACDがまだ下落を示しています。底探りの段階です。"

                    alloc_target = budget_target * alloc_pct
                    if is_us: shares_to_buy = int(alloc_target / curr_price)
                    else:
                        shares_to_buy = int((alloc_target / curr_price) // 100) * 100
                        if shares_to_buy == 0: shares_to_buy = 100 
                        
                    st.error(f"**{conviction_title}**\n\n**推奨購入目安:** 約 {shares_to_buy:,} 株\n\n*{strategy_msg}*")
                    
                    # 履歴保存用のデータを生成
                    rsi_val = row.get('RSI')
                    st.session_state.last_screened_data.append([
                        now_jst.strftime('%Y/%m/%d'),
                        market_mode.split(' ')[0],
                        sym_name,
                        round(curr_price, 2),
                        conv_type,
                        shares_to_buy,
                        round(rsi_val, 1) if pd.notna(rsi_val) else "",
                        round(macd, 2) if pd.notna(macd) else ""
                    ])

                    metrics_strs = []; reasons = []
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

    # 🌟 結果が出ていて、かつ「今日まだ保存していない」場合のみボタンを表示
    if st.session_state.last_screened_data:
        st.write("")
        if st.session_state.saved_dates[market_mode] == current_market_date:
            st.success(f"✅ 本日（{current_market_date}）の {market_mode.split(' ')[0]} のスクリーニングデータは保存済みです！\n二重保存（AIの学習ノイズ）を防ぐため、ボタンを非表示にしています。明日の相場更新をお待ちください。")
        else:
            if st.button("💾 このスクリーニング結果をスプレッドシートに保存（学習用）", type="primary"):
                with st.spinner("データを保存中..."):
                    try:
                        creds_json = json.loads(st.secrets["google_sheets_creds"])
                        scopes = ['https://www.googleapis.com/auth/spreadsheets']
                        client = gspread.authorize(Credentials.from_service_account_info(creds_json, scopes=scopes))
                        sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1IMUxpioGHLPLcLlxXaVR7IYFIltIkkt4muvByDo-LI8/edit?gid=0#gid=0")
                        
                        try:
                            ws = sheet.worksheet("スクリーニング履歴")
                        except gspread.exceptions.WorksheetNotFound:
                            ws = sheet.add_worksheet(title="スクリーニング履歴", rows="1000", cols="10")
                            ws.append_row(["取得日付", "市場", "ティッカー", "現在値", "判定", "推奨購入株数", "RSI", "MACD"])

                        for row in st.session_state.last_screened_data:
                            ws.append_row(row)
                        
                        # 保存日をメモリに記録し、データをクリア
                        st.session_state.saved_dates[market_mode] = current_market_date
                        st.session_state.last_screened_data = [] 
                        
                        st.success("✅ スプレッドシートの「スクリーニング履歴」タブに保存しました！")
                        time.sleep(1.5) # サクセスメッセージを少し見せてからリロード
                        st.rerun() # 画面をリロードしてボタンを消す
                    except Exception as e:
                        st.error(f"保存に失敗しました: {e}")

# ==========================================
# タブ2＆3：トラッカー・ニュース
# ==========================================
with tab2:
    st.write(f"監視中の特定銘柄の状況を確認し、**仮想売買の判定をスプレッドシートに自動記録**します。")
    col1, col2 = st.columns([3, 1])
    with col1: new_ticker = st.text_input(f"➕ 新しい銘柄を追加{ticker_suffix_hint}", key="t2_add")
    with col2:
        st.write(""); st.write("")
        if st.button("追加する", key="t2_add_btn"):
            clean_ticker = new_ticker.strip().upper()
            if clean_ticker and clean_ticker not in watch_list:
                st.session_state[watch_list_key].append(clean_ticker); st.rerun() 
    selected = st.multiselect("📝 現在の監視リスト", options=watch_list, default=watch_list, key="t2_select")
    if selected != watch_list: st.session_state[watch_list_key] = selected; st.rerun()

    if st.button("🎯 最新データを取得 ＆ シートに仮想売買を記録"):
        with st.spinner('データを取得・計算し、スプレッドシートに記録中...'):
            data_list = []; rows_to_append = []
            for sym in watch_list:
                disp_name = get_company_name(sym)
                hist = pd.DataFrame()
                for attempt in range(3):
                    try:
                        hist = yf.Ticker(sym).history(period="6mo")
                        if not hist.empty: break 
                        time.sleep(0.5) 
                    except: time.sleep(0.5)
                if hist.empty: continue
                try:
                    close = hist['Close'].iloc[-1]; delta = hist['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    rs = gain / loss; rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
                    macd = hist['Close'].ewm(span=12, adjust=False).mean() - hist['Close'].ewm(span=26, adjust=False).mean()
                    macd_signal = macd.ewm(span=9, adjust=False).mean()
                    macd_val = macd.iloc[-1]; sig_val = macd_signal.iloc[-1]
                    perf_w = ((close - hist['Close'].iloc[-6]) / hist['Close'].iloc[-6]) * 100 if len(hist) >= 6 else np.nan
                    
                    if rsi_val > 70: signal = f"🔴【仮想売】RSIが{rsi_val:.1f}と過熱圏に達しました。利益確定を推奨します。"
                    elif macd_val < sig_val: signal = f"🔵【仮想売】MACDがデッドクロスしました。撤退推奨です。"
                    elif rsi_val < 45 and macd_val > sig_val: signal = f"🟢【仮想買】割安水準でMACDが上向きました。絶好の押し目買いチャンスです。"
                    else:
                        if rsi_val < 45: signal = f"⚪️【静観】RSIは割安ですが、MACDが下向きのため反転確認待ちです。"
                        elif macd_val > sig_val: signal = f"⚪️【静観】MACDは上向きですが、RSIが割安基準に達していません。"
                        else: signal = f"⚪️【静観】RSIが{rsi_val:.1f}で中立圏。次の波を待つ局面です。"
                        
                    data_list.append({'ティッカー': disp_name, '現在値': close, '日足RSI': rsi_val, '週足パフォーマンス(%)': perf_w, '💡 AI判定': signal})
                    rows_to_append.append([now_jst.strftime('%Y/%m/%d %H:%M'), sym, round(close, 2), round(rsi_val, 1), round(macd_val, 2), round(perf_w, 1) if pd.notna(perf_w) else "", signal])
                except Exception as e: pass
            
            if rows_to_append:
                try:
                    creds_json = json.loads(st.secrets["google_sheets_creds"])
                    scopes = ['https://www.googleapis.com/auth/spreadsheets']
                    client = gspread.authorize(Credentials.from_service_account_info(creds_json, scopes=scopes))
                    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1IMUxpioGHLPLcLlxXaVR7IYFIltIkkt4muvByDo-LI8/edit?gid=0#gid=0").sheet1
                    for row in rows_to_append: sheet.append_row(row)
                    st.success("✅ データ取得 ＆ スプレッドシートへの記録が完了しました！")
                except Exception as e: st.error(f"⚠️ スプレッドシートへの記録に失敗しました: {e}")
            
            if data_list:
                for data in data_list:
                    st.markdown(f"### 📌 {data['ティッカー']} (現在値: {curr_sym}{data['現在値']:,.2f})")
                    st.markdown(f"- **日足RSI:** {data['日足RSI']:.1f}  |  **週足パフォーマンス:** {data['週足パフォーマンス(%)']:.1f}%")
                    st.info(f"**{data['💡 AI判定']}**"); st.divider()

with tab3:
    st.write("監視中の**全銘柄**に関連する最新ニュースを一覧でチェックできます。")
    if watch_list:
        if st.button("📰 監視リストの最新ニュースを一括取得"):
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
                            for item in items[:3]:
                                title = item.find('title').text if item.find('title') is not None else 'タイトルなし'
                                link = item.find('link').text if item.find('link') is not None else '#'
                                pub = item.find('source').text if item.find('source') is not None else '配信元不明'
                                dt = "時刻不明"
                                pub_date_str = item.find('pubDate').text if item.find('pubDate') is not None else ''
                                if pub_date_str:
                                    t_tuple = email.utils.parsedate_tz(pub_date_str)
                                    if t_tuple: dt = (datetime.utcfromtimestamp(email.utils.mktime_tz(t_tuple)) + timedelta(hours=9)).strftime('%Y/%m/%d %H:%M')
                                st.markdown(f"**[{title}]({link})**")
                                st.caption(f"🏢 {pub}  |  🕒 {dt}")
                        else: st.info("ニュースは見つかりませんでした。")
                    except Exception as e: st.error("ニュース取得中にエラーが発生しました。")
                    st.divider()
    else: st.info("タブ2（個別銘柄トラッカー）で監視リストに銘柄を追加してください。")
