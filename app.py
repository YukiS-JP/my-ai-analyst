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

st.set_page_config(page_title="AIアナリスト", page_icon="📊", layout="wide")

st.title("📊 My AI Analyst Dashboard")

# --- セッションステート（初期設定とカスタムデータの保存） ---
if 'watch_list' not in st.session_state:
    st.session_state.watch_list = ["SOXL", "RDW", "DNA", "FNGU"]

if 'macro_dict' not in st.session_state:
    st.session_state.macro_dict = {
        "米ドル/円": "JPY=X",
        "S&P 500": "^GSPC",
        "NASDAQ": "^IXIC",
        "日経平均": "^N225",
        "米国10年債利回り": "^TNX",
        "原油(WTI)": "CL=F",
        "ゴールド(金)": "GC=F",
        "ビットコイン": "BTC-USD"
    }

if 'macro_display_list' not in st.session_state:
    st.session_state.macro_display_list = ["米ドル/円", "S&P 500", "NASDAQ", "日経平均"]

if 'portfolio' not in st.session_state:
    st.session_state.portfolio = {}

if 'screener_indicators' not in st.session_state:
    st.session_state.screener_indicators = ["RSI (14日)", "MACD", "PER (株価収益率)"]

INDICATOR_MAP = {
    "RSI (14日)": {"cols": ["RSI"]},
    "MACD": {"cols": ["MACD.macd", "MACD.signal"]},
    "PER (株価収益率)": {"cols": ["price_earnings_ttm"]},
    "PBR (株価純資産倍率)": {"cols": ["price_book_ratio"]},
    "ROE (自己資本利益率)": {"cols": ["return_on_equity"]},
    "SMA20 (20日移動平均)": {"cols": ["SMA20"]},
    "SMA50 (50日移動平均)": {"cols": ["SMA50"]},
    "SMA200 (200日移動平均)": {"cols": ["SMA200"]},
    "配当利回り(%)": {"cols": ["dividend_yield_recent"]}
}


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
                background-color: #12141A;
                padding: 15px 20px;
                border-radius: 12px;
                box-shadow: 0 4px 10px rgba(0,0,0,0.4);
                border: 1px solid #2D303E;
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                margin-bottom: 25px;
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

    with st.expander("💼 ポートフォリオの編集（保有銘柄の登録・削除）"):
        st.markdown("**1️⃣ 保有銘柄の登録・更新** (米国株・ETF専用)")
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        with c1: p_tick = st.text_input("ティッカー (例: SOXL)", key="p_tick")
        with c2: p_price = st.number_input("平均取得単価 ($)", min_value=0.0, step=0.1, format="%.2f", key="p_price")
        with c3: p_qty = st.number_input("保有数量 (株)", min_value=0.0, step=1.0, format="%.2f", key="p_qty")
        with c4:
            st.write(""); st.write("")
            if st.button("登録", key="p_add"):
                if p_tick and p_qty > 0:
                    st.session_state.portfolio[p_tick.strip().upper()] = {'avg_price': p_price, 'qty': p_qty}
                    st.rerun()
        
        st.divider()
        st.markdown("**2️⃣ 現在の登録内容（削除）**")
        if st.session_state.portfolio:
            for t in list(st.session_state.portfolio.keys()):
                col_a, col_b = st.columns([5, 1])
                with col_a: st.write(f"**{t}** : {st.session_state.portfolio[t]['qty']:,.2f} 株 (平均 ${st.session_state.portfolio[t]['avg_price']:,.2f})")
                with col_b:
                    if st.button("削除", key=f"del_port_{t}"):
                        del st.session_state.portfolio[t]
                        st.rerun()
        else:
            st.info("現在登録されている保有銘柄はありません。")
    st.write("")

    with st.spinner("最新データを取得中..."):
        port_html = "<div class='dashboard-panel'><div class='panel-header'>💼 ポートフォリオ状況</div>"
        if st.session_state.portfolio:
            total_cost = 0; total_value = 0; details_html = ""
            for sym, data in st.session_state.portfolio.items():
                qty = data['qty']; avg_p = data['avg_price']
                try:
                    t = yf.Ticker(sym)
                    h = t.history(period="1d")
                    if not h.empty:
                        c_price = h['Close'].iloc[-1]
                        cost = avg_p * qty; val = c_price * qty; pnl = val - cost
                        pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
                        total_cost += cost; total_value += val
                        pnl_class = 'val-up' if pnl > 0 else 'val-down' if pnl < 0 else 'val-neutral'
                        sign = '+' if pnl > 0 else ''
                        details_html += f"<div class='item-row sym-title'>🔹 {sym} <span style='font-size: 13px; color:#888; font-weight:normal;'>({qty:,.2f}株)</span></div>"
                        details_html += f"<div class='item-sub-row'>┣ <strong>評価額:</strong> ${val:,.2f} (現在値: ${c_price:,.2f})<br>┗ <strong>含み損益:</strong> <span class='{pnl_class}'>{sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%)</span> ｜ 取得単価: ${avg_p:,.2f}</div>"
                    else: details_html += f"<div class='item-row'>🔹 <strong>{sym}</strong>: データ取得エラー</div>"
                except: details_html += f"<div class='item-row'>🔹 <strong>{sym}</strong>: エラー (ティッカーを確認)</div>"
            
            tot_pnl = total_value - total_cost
            tot_pct = (tot_pnl / total_cost) * 100 if total_cost > 0 else 0
            tot_class = 'val-up' if tot_pnl > 0 else 'val-down' if tot_pnl < 0 else 'val-neutral'
            tot_sign = '+' if tot_pnl > 0 else ''
            
            port_html += f"<div style='font-size: 24px; color: #FFFFFF; font-weight: bold; margin-bottom: 5px;'>総評価額: ${total_value:,.2f}</div>"
            port_html += f"<div style='font-size: 18px; margin-bottom: 15px;'>トータル含み損益: <span class='{tot_class}'>{tot_sign}${tot_pnl:,.2f} ({tot_sign}{tot_pct:.2f}%)</span></div><hr style='border-color: #2D303E; margin: 10px 0;'>"
            port_html += details_html
        else: port_html += "<div class='item-row val-neutral'>保有銘柄が登録されていません。「💼 ポートフォリオの編集」から追加してください。</div>"
        port_html += "</div>"
        st.markdown(port_html, unsafe_allow_html=True)

        col1, col2 = st.columns([5, 1])
        with col1: st.subheader("🌍 主要市場サマリー")
        with col2:
            with st.popover("⚙️ 編集"):
                new_macro_name = st.text_input("📝 表示名", placeholder="半導体指数", key="mac_name")
                new_macro_tick = st.text_input("🔤 ティッカー", placeholder="^SOX", key="mac_tick")
                if st.button("➕ 追加する", key="add_macro_btn"):
                    if new_macro_name and new_macro_tick:
                        st.session_state.macro_dict[new_macro_name] = new_macro_tick
                        if new_macro_name not in st.session_state.macro_display_list:
                            st.session_state.macro_display_list.append(new_macro_name)
                        st.rerun()
                st.divider()
                selected_macros = st.multiselect("表示する指標", options=list(st.session_state.macro_dict.keys()), default=st.session_state.macro_display_list, key="macro_select")
                if set(selected_macros) != set(st.session_state.macro_display_list):
                    new_list = [m for m in st.session_state.macro_display_list if m in selected_macros]
                    for m in selected_macros:
                        if m not in new_list: new_list.append(m)
                    st.session_state.macro_display_list = new_list
                    st.rerun()
                if st.session_state.macro_display_list:
                    sorted_macros = sort_items(st.session_state.macro_display_list, key="macro_sort")
                    if sorted_macros != st.session_state.macro_display_list:
                        st.session_state.macro_display_list = sorted_macros
                        st.rerun()

        html_macro = "<div class='dashboard-panel'>"
        for name in st.session_state.macro_display_list:
            symbol = st.session_state.macro_dict.get(name, "")
            try:
                t = yf.Ticker(symbol)
                h = t.history(period="5d")
                if not h.empty and len(h) >= 2:
                    c_price = h['Close'].iloc[-1]; p_price = h['Close'].iloc[-2]
                    diff = c_price - p_price; pct = (diff / p_price) * 100
                    if diff > 0: trend_html = f"<span class='val-up'>↑+{diff:,.2f} (+{pct:.2f}%)</span>"
                    elif diff < 0: trend_html = f"<span class='val-down'>↓{diff:,.2f} ({pct:.2f}%)</span>"
                    else: trend_html = f"<span class='val-neutral'>±0.00 (0.00%)</span>"
                    if "JPY" in symbol or "円" in name: val_str = f"¥{c_price:.2f}"
                    else: val_str = f"{c_price:,.2f}"
                    html_macro += f"<div class='item-row'><strong>{name}</strong>: {val_str} ({trend_html})</div>"
                else: html_macro += f"<div class='item-row'><strong>{name}</strong>: 取得失敗</div>"
            except: html_macro += f"<div class='item-row'><strong>{name}</strong>: エラー</div>"
        html_macro += "</div>"
        st.markdown(html_macro, unsafe_allow_html=True)

        col3, col4 = st.columns([5, 1])
        with col3: st.subheader("📌 監視銘柄 データ一覧")
        with col4:
            with st.popover("⚙️ 編集"):
                new_watch_tick = st.text_input("🔤 ティッカー", placeholder="NVDA", key="watch_tick")
                if st.button("➕ 追加する", key="add_watch_btn"):
                    c_tick = new_watch_tick.strip().upper()
                    if c_tick and c_tick not in st.session_state.watch_list:
                        st.session_state.watch_list.append(c_tick)
                        st.rerun()
                st.divider()
                selected_watch = st.multiselect("表示する銘柄", options=st.session_state.watch_list, default=st.session_state.watch_list, key="watch_select")
                if set(selected_watch) != set(st.session_state.watch_list):
                    new_w_list = [m for m in st.session_state.watch_list if m in selected_watch]
                    for m in selected_watch:
                        if m not in new_w_list: new_w_list.append(m)
                    st.session_state.watch_list = new_w_list
                    st.rerun()
                if st.session_state.watch_list:
                    sorted_watch = sort_items(st.session_state.watch_list, key="watch_sort_dd")
                    if sorted_watch != st.session_state.watch_list:
                        st.session_state.watch_list = sorted_watch
                        st.rerun()

        html_watch = "<div class='dashboard-panel'>"
        if st.session_state.watch_list:
            for sym in st.session_state.watch_list:
                try:
                    ticker = yf.Ticker(sym)
                    hist = ticker.history(period="1y")
                    if not hist.empty and len(hist) > 22:
                        curr_p = hist['Close'].iloc[-1]; prev_p = hist['Close'].iloc[-2]
                        week_p = hist['Close'].iloc[-6] if len(hist) >= 6 else prev_p
                        month_p = hist['Close'].iloc[-22]
                        day_diff = curr_p - prev_p; day_pct = (day_diff / prev_p) * 100
                        week_pct = ((curr_p - week_p) / week_p) * 100
                        month_pct = ((curr_p - month_p) / month_p) * 100
                        high_52 = hist['High'].max(); dd_52 = ((curr_p - high_52) / high_52) * 100
                        delta = hist['Close'].diff()
                        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                        rs = gain / loss
                        rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
                        
                        if day_diff > 0: d_trend = f"<span class='val-up'>↑+{day_diff:.2f} (+{day_pct:.2f}%)</span>"
                        elif day_diff < 0: d_trend = f"<span class='val-down'>↓{day_diff:.2f} ({day_pct:.2f}%)</span>"
                        else: d_trend = f"<span class='val-neutral'>±0.00 (0.00%)</span>"
                        if rsi_val >= 70: rsi_stat = "<span class='val-down'>🔴 過熱</span>"
                        elif rsi_val <= 45: rsi_stat = "<span class='val-up'>🟢 割安</span>"
                        else: rsi_stat = "<span class='val-neutral'>⚪️ 中立</span>"
                        week_color = 'val-up' if week_pct > 0 else 'val-down' if week_pct < 0 else 'val-neutral'
                        month_color = 'val-up' if month_pct > 0 else 'val-down' if month_pct < 0 else 'val-neutral'
                        
                        html_watch += f"<div class='item-row sym-title'>🔹 {sym}</div>"
                        html_watch += f"<div class='item-sub-row'>┣ <strong>現在値:</strong> ${curr_p:.2f} (前日比: {d_trend})<br>┣ <strong>前週比:</strong> <span class='{week_color}'>{week_pct:+.2f}%</span> ｜ <strong>前月比:</strong> <span class='{month_color}'>{month_pct:+.2f}%</span><br>┗ <strong>RSI:</strong> {rsi_val:.1f} ({rsi_stat}) ｜ <strong>高値差:</strong> {dd_52:+.1f}%</div>"
                except: html_watch += f"<div class='item-row sym-title'>🔹 {sym}</div><div class='item-sub-row'>データ取得エラー</div>"
        else: html_watch += "<div class='item-row val-neutral'>表示する銘柄がありません。</div>"
        html_watch += "</div>"
        st.markdown(html_watch, unsafe_allow_html=True)
    
    st.write("")
    if st.session_state.watch_list:
        for sym in st.session_state.watch_list:
            with st.expander(f"📈 {sym} の詳細チャートを開く / 閉じる"):
                html_code = f"""<div class="tradingview-widget-container"><div id="tradingview_{sym}"></div><script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script><script type="text/javascript">new TradingView.widget({{"width": "100%", "height": 400, "symbol": "{sym}", "interval": "D", "timezone": "Asia/Tokyo", "theme": "dark", "style": "1", "locale": "ja", "enable_publishing": false, "allow_symbol_change": true, "hide_top_toolbar": false, "container_id": "tradingview_{sym}"}});</script></div>"""
                components.html(html_code, height=400)

# ==========================================
# 🌟 タブ1：全体スクリーニング（資金シミュレーション ＆ 打診/本買い判定 搭載）
# ==========================================
with tab1:
    st.write("日足（タイミング）・週足（トレンド）・ファンダ（割安性）を統合し、反発期待の銘柄を探します。")
    
    # 📖 投資の基礎知識カンペ
    with st.expander("📖 投資の基礎知識（各指標の意味と分析の目安）"):
        st.markdown("""
        **■ オシレーター系（売買のタイミングを図る）**
        *   **RSI (相対力指数)**: 相場の過熱感（買われすぎ・売られすぎ）を0〜100で表します。
            *   **70以上**: 買われすぎ。短期的な利確の目安。
            *   **30以下**: 売られすぎ。底打ち反転、押し目買いのチャンス。
        *   **MACD**: 2つの移動平均線の「差」から、トレンドの方向や転換点を読み取ります。
            *   **ゴールデンクロス**: MACD線がシグナル線を下から上に抜いた時（強い買いサイン）。
            *   **デッドクロス**: MACD線がシグナル線を上から下に抜いた時（強い売りサイン）。

        **■ トレンド・ファンダメンタルズ系**
        *   **SMA (移動平均線)**: 20日(短期)、50日(中期)、200日(長期)の波。
        *   **PER (株価収益率)**: 利益に対して株価が割安か。15倍以下が割安の目安。
        *   **PBR (株価純資産倍率)**: 資産に対して割安か。1倍割れは超割安。
        *   **ROE (自己資本利益率)**: 稼ぐ効率の良さ。10〜15%以上が優良。
        """)
    
    col_scr1, col_scr2 = st.columns([4, 2])
    with col_scr1:
        # 💰 投資予算の設定
        budget_jpy_man = st.number_input("💰 今回の投資予定資金（万円）を入力", min_value=10, max_value=5000, value=100, step=10)
        budget_jpy = budget_jpy_man * 10_000
    with col_scr2:
        with st.popover("⚙️ 指標の編集"):
            st.markdown("**追加と並び替え**")
            selected_inds = st.multiselect("表示する指標", options=list(INDICATOR_MAP.keys()), default=st.session_state.screener_indicators, key="scr_select")
            if set(selected_inds) != set(st.session_state.screener_indicators):
                new_list = [m for m in st.session_state.screener_indicators if m in selected_inds]
                for m in selected_inds:
                    if m not in new_list: new_list.append(m)
                st.session_state.screener_indicators = new_list
                st.rerun()

            if st.session_state.screener_indicators:
                sorted_inds = sort_items(st.session_state.screener_indicators, key="scr_sort_dd")
                if sorted_inds != st.session_state.screener_indicators:
                    st.session_state.screener_indicators = sorted_inds
                    st.rerun()

    # 🚀 スクリーニング実行
    if st.button("🚀 厳選チャンス銘柄をスクリーニング"):
        with st.spinner('市場全体から厳しい条件に合う銘柄を抽出中...'):
            
            # リアルタイム為替レート（ドル円）の取得
            try:
                usd_jpy = yf.Ticker("JPY=X").history(period="1d")['Close'].iloc[-1]
            except:
                usd_jpy = 150.0 # 取得失敗時の安全対策
            
            budget_usd = budget_jpy / usd_jpy
            st.info(f"💡 現在の為替レート: **$1 = ¥{usd_jpy:.2f}** （予定資金: 約 **${budget_usd:,.2f}**）")

            query_cols = ['name', 'close', 'Perf.W', 'market_cap_basic', 'volume', 'RSI', 'MACD.macd', 'MACD.signal']
            for ind in st.session_state.screener_indicators:
                cols = INDICATOR_MAP[ind]["cols"]
                query_cols.extend(cols)
            query_cols = list(set(query_cols))
            
            # 厳格フィルター
            conditions = [
                Column('market_cap_basic') > 10_000_000_000,
                Column('volume') > 2_000_000,
                Column('price_earnings_ttm') > 0,
                Column('RSI') < 40  # 本買い/打診買いの土台としてRSI40未満を強制
            ]
                
            q = (Query().select(*query_cols).where(*conditions).order_by('market_cap_basic', ascending=False).limit(10))
            
            try:
                df = q.set_markets('america').get_scanner_data()[1]
            except Exception:
                df = pd.DataFrame()
            
            if not df.empty:
                st.success(f"🎯 厳格なスクリーニングを通過した銘柄です！")
                
                for index, row in df.iterrows():
                    sym_name = row['name']
                    curr_price = row.get('close', 1)
                    
                    st.markdown(f"### 📌 {sym_name} (現在値: ${curr_price:.2f})")
                    
                    # --- ⚔️ AI売買戦略（打診買い vs 本気買い）の判定 ---
                    macd = row.get('MACD.macd')
                    sig = row.get('MACD.signal')
                    
                    is_golden_cross = False
                    if pd.notna(macd) and pd.notna(sig):
                        is_golden_cross = (macd > sig)
                        
                    if is_golden_cross:
                        conviction_title = "🔥 本気買い（フル・エントリー）"
                        alloc_pct = 1.0 # 資金の100%
                        strategy_msg = "RSIが割安圏にある中、MACDのゴールデンクロスが確認されました。トレンド反転の確度が高いため、予定資金のフルイン（100%）を検討できる強力なチャート形状です。"
                    else:
                        conviction_title = "💧 打診買い（テスト・エントリー）"
                        alloc_pct = 0.3 # 資金の30%
                        strategy_msg = "RSIは売られすぎ水準ですが、MACDがまだ下落トレンドを示しています。底探りの段階のため、まずは予定資金の30%程度で入り、反発を確認してから買い増すのが安全です。"

                    # シミュレーション計算
                    alloc_usd = budget_usd * alloc_pct
                    alloc_jpy = budget_jpy * alloc_pct
                    shares_to_buy = int(alloc_usd / curr_price)
                    actual_cost_usd = shares_to_buy * curr_price
                    actual_cost_jpy = actual_cost_usd * usd_jpy
                    
                    # 戦略結果の表示
                    st.error(f"**{conviction_title}**\n\n"
                             f"**推奨購入目安:** 約 {shares_to_buy:,} 株 （投入資金: 約 ¥{actual_cost_jpy:,.0f}）\n\n"
                             f"*{strategy_msg}*")
                    
                    # --- 指標データと理由の表示 ---
                    metrics_strs = []
                    reasons = []
                    
                    perf_w = row.get('Perf.W')
                    if pd.notna(perf_w):
                        metrics_strs.append(f"前週比: {perf_w:.1f}%")
                    
                    for ind in st.session_state.screener_indicators:
                        if ind == "RSI (14日)":
                            val = row.get('RSI')
                            if pd.notna(val):
                                metrics_strs.append(f"RSI: {val:.1f}")
                        
                        elif ind == "MACD":
                            if pd.notna(macd) and pd.notna(sig):
                                metrics_strs.append(f"MACD: {macd:.2f}")
                        
                        elif ind == "PER (株価収益率)":
                            val = row.get('price_earnings_ttm')
                            if pd.notna(val):
                                metrics_strs.append(f"PER: {val:.1f}倍")
                                if val < 15: reasons.append(f"**PERが{val:.1f}倍**と割安な水準であり、下値不安が限定的です。")
                                elif val < 25: reasons.append(f"**PERが{val:.1f}倍**と適正水準であり、業績の裏付けを持った銘柄です。")
                                else: reasons.append(f"PERは{val:.1f}倍とやや高めですが、成長期待が織り込まれています。")
                                
                        elif ind == "PBR (株価純資産倍率)":
                            val = row.get('price_book_ratio')
                            if pd.notna(val):
                                metrics_strs.append(f"PBR: {val:.2f}倍")
                                if val < 1.0: reasons.append(f"**PBRが{val:.2f}倍**と「1倍割れ」の超割安水準に放置されています。")
                                else: reasons.append(f"PBRは{val:.2f}倍で、極端な割高感はありません。")
                                
                        elif ind == "ROE (自己資本利益率)":
                            val = row.get('return_on_equity')
                            if pd.notna(val):
                                metrics_strs.append(f"ROE: {val:.1f}%")
                                if val > 15: reasons.append(f"**ROEが{val:.1f}%**と非常に高く、効率よく利益を稼ぐ超優秀な企業です。")
                                elif val > 10: reasons.append(f"**ROEが{val:.1f}%**で、基準となる10%をクリアした優良企業です。")
                                
                        elif "SMA" in ind:
                            col_name = INDICATOR_MAP[ind]["cols"][0]
                            val = row.get(col_name)
                            if pd.notna(val) and pd.notna(curr_price):
                                metrics_strs.append(f"{ind.split(' ')[0]}: ${val:.2f}")
                                if curr_price > val: reasons.append(f"現在値が{ind}（${val:.2f}）を**上回って推移**しており、中長期のトレンドは上向きです。")
                                else: reasons.append(f"現在値が{ind}（${val:.2f}）を下回っており、上値が重い調整局面が続いています。")
                                
                        elif ind == "配当利回り(%)":
                            val = row.get('dividend_yield_recent')
                            if pd.notna(val):
                                metrics_strs.append(f"配当利回り: {val:.2f}%")
                                if val > 3.0: reasons.append(f"**配当利回りが{val:.2f}%**と高く、下落時のクッション（インカムゲイン）が期待できます。")

                    st.markdown(f"- **取得データ:** " + " ｜ ".join(metrics_strs))
                    
                    if reasons:
                        st.info("💡 **その他のファンダメンタル分析:**\n\n" + "\n".join([f"- {r}" for r in reasons]))
                    
                    st.divider()
            else:
                st.warning("現在、厳しい条件（RSI40未満など）を満たす銘柄は見つかりませんでした。\n相場全体が過熱しているか、優良な押し目がない状態です。無駄なトレードを避け、資金を温存して静観を推奨します。")

# ==========================================
# タブ2＆3：トラッカー・ニュース（変更なし）
# ==========================================
# （以下、タブ2とタブ3のコードはこれまでと同様です）
with tab2:
    st.write("監視中の特定銘柄の状況を確認し、**仮想売買の判定をスプレッドシートに自動記録**します。")
    col1, col2 = st.columns([3, 1])
    with col1: new_ticker = st.text_input("➕ 新しい銘柄を追加", placeholder="例: NVDA", key="t2_add")
    with col2:
        st.write(""); st.write("")
        if st.button("追加する", key="t2_add_btn"):
            clean_ticker = new_ticker.strip().upper()
            if clean_ticker and clean_ticker not in st.session_state.watch_list:
                st.session_state.watch_list.append(clean_ticker); st.rerun() 
    selected = st.multiselect("📝 現在の監視リスト", options=st.session_state.watch_list, default=st.session_state.watch_list, key="t2_select")
    if selected != st.session_state.watch_list:
        st.session_state.watch_list = selected; st.rerun()

    if st.button("🎯 最新データを取得 ＆ シートに仮想売買を記録"):
        with st.spinner('データを取得・計算し、スプレッドシートに記録中...'):
            symbols_list = st.session_state.watch_list
            data_list = []; rows_to_append = []
            now_jst = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y/%m/%d %H:%M')
            for sym in symbols_list:
                hist = pd.DataFrame()
                for attempt in range(3):
                    try:
                        ticker = yf.Ticker(sym); hist = ticker.history(period="6mo")
                        if not hist.empty: break 
                        time.sleep(0.5) 
                    except: time.sleep(0.5)
                if hist.empty:
                    st.warning(f"{sym} のデータ取得に失敗しました。")
                    continue
                try:
                    close = hist['Close'].iloc[-1]; delta = hist['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    rs = gain / loss; rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
                    ema_fast = hist['Close'].ewm(span=12, adjust=False).mean()
                    ema_slow = hist['Close'].ewm(span=26, adjust=False).mean()
                    macd = ema_fast - ema_slow; macd_signal = macd.ewm(span=9, adjust=False).mean()
                    macd_val = macd.iloc[-1]; sig_val = macd_signal.iloc[-1]
                    perf_w = ((close - hist['Close'].iloc[-6]) / hist['Close'].iloc[-6]) * 100 if len(hist) >= 6 else np.nan
                    
                    if rsi_val > 70: signal = f"🔴【仮想売】RSIが{rsi_val:.1f}と過熱圏に達しました。利益確定を推奨します。"
                    elif macd_val < sig_val: signal = f"🔵【仮想売】MACDがデッドクロスしました。下落トレンド入りのサインのため撤退推奨です。"
                    elif rsi_val < 45 and macd_val > sig_val: signal = f"🟢【仮想買】RSI{rsi_val:.1f}の割安水準でMACDが上向きました。絶好の押し目買いチャンスです。"
                    else:
                        if rsi_val < 45: signal = f"⚪️【静観】RSIは{rsi_val:.1f}ですが、MACDが下向きのため反転確認待ちです。"
                        elif macd_val > sig_val: signal = f"⚪️【静観】MACDは上向きですが、RSIが{rsi_val:.1f}であり新規買い基準に達していません。"
                        else: signal = f"⚪️【静観】RSIが{rsi_val:.1f}で中立圏。次の波を待つ局面です。"
                        
                    data_list.append({'ティッカー': sym, '現在値($)': close, '日足RSI': rsi_val, '週足パフォーマンス(%)': perf_w, '💡 AI判定': signal})
                    rows_to_append.append([now_jst, sym, round(close, 2), round(rsi_val, 1), round(macd_val, 2), round(perf_w, 1) if pd.notna(perf_w) else "", signal])
                except Exception as e: pass
            
            if rows_to_append:
                try:
                    creds_json = json.loads(st.secrets["google_sheets_creds"])
                    scopes = ['https://www.googleapis.com/auth/spreadsheets']
                    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
                    client = gspread.authorize(creds)
                    sheet_url = "https://docs.google.com/spreadsheets/d/1IMUxpioGHLPLcLlxXaVR7IYFIltIkkt4muvByDo-LI8/edit?gid=0#gid=0" 
                    sheet = client.open_by_url(sheet_url).sheet1
                    for row in rows_to_append: sheet.append_row(row)
                    st.success("✅ データ取得 ＆ スプレッドシートへの記録が完了しました！")
                except Exception as e: st.error(f"⚠️ スプレッドシートへの記録に失敗しました: {e}")
            
            if data_list:
                for data in data_list:
                    st.markdown(f"### 📌 {data['ティッカー']} (現在値: ${data['現在値($)']:.2f})")
                    st.markdown(f"- **日足RSI:** {data['日足RSI']:.1f}  |  **週足パフォーマンス:** {data['週足パフォーマンス(%)']:.1f}%")
                    st.info(f"**{data['💡 AI判定']}**"); st.divider()

with tab3:
    st.write("監視中の**全銘柄**に関連する最新ニュースを一覧でチェックできます。")
    if 'watch_list' in st.session_state and st.session_state.watch_list:
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

                for news_target in st.session_state.watch_list:
                    st.markdown(f"### 📌 {news_target} のニュース")
                    try:
                        url = f"https://news.google.com/rss/search?q={news_target}+stock&hl=ja&gl=JP&ceid=JP:ja"
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req) as response: xml_data = response.read()
                        root = ET.fromstring(xml_data); items = root.findall('.//item')
                        if items:
                            for item in items[:3]: display_news_item(item)
                            if len(items) > 3:
                                with st.expander(f"🔽 {news_target} のその他のニュースを見る"):
                                    for item in items[3:10]: display_news_item(item); st.write("") 
                        else: st.info(f"{news_target} に関連する最新ニュースは見つかりませんでした。")
                    except Exception as e: st.error(f"{news_target} のニュース取得中にエラーが発生しました。")
                    st.divider()
    else: st.info("タブ2（個別銘柄トラッカー）で監視リストに銘柄を追加してください。")
