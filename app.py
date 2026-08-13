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

st.set_page_config(page_title="AIアナリスト", page_icon="📊", layout="wide")

st.title("📊 My AI Analyst Dashboard")

# ------------------------------------------------
# アプリ画面の構築（タブで2画面に分割）
# ------------------------------------------------
tab1, tab2 = st.tabs(["🔍 全体スクリーニング", "🎯 個別銘柄トラッカー"])

# ==========================================
# タブ1：全体スクリーニング
# ==========================================
with tab1:
    st.write("日足（タイミング）・週足（トレンド）・ファンダ（割安性）を統合し、反発期待の銘柄を探します。")
    
    if st.button("🚀 最新のチャンス銘柄をスクリーニング"):
        with st.spinner('市場全体から条件に合う銘柄を抽出中...'):
            q = (Query()
                 .select('name', 'close', 'RSI', 'MACD.macd', 'MACD.signal', 'Perf.W', 'price_earnings_ttm', 'market_cap_basic')
                 .where(
                     Column('market_cap_basic') > 1_000_000_000,
                     Column('RSI') < 45,
                     Column('volume') > 1_000_000
                 )
                 .order_by('RSI', ascending=True)
                 .limit(10))
            
            try:
                df = q.set_markets('america').get_scanner_data()[1]
            except Exception:
                df = pd.DataFrame()
            
            if not df.empty:
                df = df[['name', 'close', 'RSI', 'MACD.macd', 'MACD.signal', 'Perf.W', 'price_earnings_ttm']]
                df.columns = ['ティッカー', '現在値($)', '日足RSI', '日足MACD', '日足シグナル', '週足パフォーマンス(%)', 'PER(倍)']
                
                df['日足RSI'] = pd.to_numeric(df['日足RSI'], errors='coerce').round(1)
                df['週足パフォーマンス(%)'] = pd.to_numeric(df['週足パフォーマンス(%)'], errors='coerce').round(1)
                df['PER(倍)'] = pd.to_numeric(df['PER(倍)'], errors='coerce').round(1)
                
                st.success("分析完了！現在のスイング推奨銘柄です。")
                
                # スクリーニング結果をカード形式で表示
                for index, row in df.iterrows():
                    st.markdown(f"### 📌 {row['ティッカー']} (現在値: ${row['現在値($)']})")
                    st.markdown(f"- **日足RSI:** {row['日足RSI']}  |  **週足パフォーマンス:** {row['週足パフォーマンス(%)']}%  |  **PER:** {row['PER(倍)']}倍")
                    st.divider()
            else:
                st.warning("現在、厳しい条件を全て満たす銘柄は見つかりませんでした。")

# ==========================================
# タブ2：個別銘柄トラッカー ＆ スプレッドシート自動記録
# ==========================================
with tab2:
    st.write("監視中の特定銘柄の状況を確認し、**仮想売買の判定をスプレッドシートに自動記録**します。")
    
    if 'watch_list' not in st.session_state:
        st.session_state.watch_list = ["SOXL", "RDW", "DNA", "FNGU"]

    col1, col2 = st.columns([3, 1])
    with col1:
        new_ticker = st.text_input("➕ 新しい銘柄を追加", placeholder="例: NVDA")
    with col2:
        st.write("") 
        st.write("")
        if st.button("追加する"):
            clean_ticker = new_ticker.strip().upper()
            if clean_ticker and clean_ticker not in st.session_state.watch_list:
                st.session_state.watch_list.append(clean_ticker)
                st.rerun() 
    
    selected = st.multiselect(
        "📝 現在の監視リスト",
        options=st.session_state.watch_list,
        default=st.session_state.watch_list
    )
    
    if selected != st.session_state.watch_list:
        st.session_state.watch_list = selected
        st.rerun()

    # 🚀 取得＆自動記録ボタン
    if st.button("🎯 最新データを取得 ＆ シートに仮想売買を記録"):
        with st.spinner('データを取得・計算し、スプレッドシートに記録中...'):
            symbols_list = st.session_state.watch_list
            data_list = []
            rows_to_append = []
            
            now_jst = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y/%m/%d %H:%M')
            
            for sym in symbols_list:
                hist = pd.DataFrame()
                for attempt in range(3):
                    try:
                        ticker = yf.Ticker(sym)
                        hist = ticker.history(period="6mo")
                        if not hist.empty:
                            break 
                        time.sleep(0.5) 
                    except:
                        time.sleep(0.5)
                        
                if hist.empty:
                    st.warning(f"{sym} のデータ取得に失敗しました。")
                    continue
                    
                try:
                    close = hist['Close'].iloc[-1]
                    
                    delta = hist['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    rs = gain / loss
                    rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
                    
                    ema_fast = hist['Close'].ewm(span=12, adjust=False).mean()
                    ema_slow = hist['Close'].ewm(span=26, adjust=False).mean()
                    macd = ema_fast - ema_slow
                    macd_signal = macd.ewm(span=9, adjust=False).mean()
                    
                    macd_val = macd.iloc[-1]
                    sig_val = macd_signal.iloc[-1]
                    
                    if len(hist) >= 6:
                        perf_w = ((close - hist['Close'].iloc[-6]) / hist['Close'].iloc[-6]) * 100
                    else:
                        perf_w = np.nan
                        
                    # 💡 【仮想売買の自動判定ルール ＋ 詳細な理由付け】
                    if rsi_val > 70:
                        detail = f"RSIが{rsi_val:.1f}と過熱圏に達しました。利益確定を推奨します。"
                        signal = f"🔴【仮想売】{detail}"
                    elif macd_val < sig_val:
                        detail = f"MACDが下向きに交差（デッドクロス）しました。下落トレンド入りのサインのため撤退推奨です。"
                        signal = f"🔵【仮想売】{detail}"
                    elif rsi_val < 45 and macd_val > sig_val:
                        detail = f"RSI{rsi_val:.1f}の割安水準でMACDが上向きました。絶好の押し目買いチャンスです。"
                        signal = f"🟢【仮想買】{detail}"
                    else:
                        if rsi_val < 45:
                            detail = f"RSIは{rsi_val:.1f}と売られすぎですが、MACDがまだ下向きのため反転確認待ちです。"
                        elif macd_val > sig_val:
                            detail = f"MACDは上向きですが、RSIが{rsi_val:.1f}であり新規買いの基準（45未満）には達していません。"
                        else:
                            detail = f"RSIが{rsi_val:.1f}で中立圏。MACDも方向感がなく、次の波を待つ局面です。"
                        signal = f"⚪️【静観】{detail}"
                        
                    data_list.append({
                        'ティッカー': sym,
                        '現在値($)': close,
                        '日足RSI': rsi_val,
                        '週足パフォーマンス(%)': perf_w,
                        '💡 AI判定': signal
                    })
                    
                    row = [
                        now_jst,
                        sym,
                        round(close, 2),
                        round(rsi_val, 1),
                        round(macd_val, 2),
                        round(perf_w, 1) if pd.notna(perf_w) else "",
                        signal
                    ]
                    rows_to_append.append(row)
                    
                except Exception as e:
                    pass
            
            # --- スプレッドシートへの記録 ---
            if rows_to_append:
                try:
                    creds_json = json.loads(st.secrets["google_sheets_creds"])
                    scopes = ['https://www.googleapis.com/auth/spreadsheets']
                    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
                    client = gspread.authorize(creds)
                    
                    sheet_url = "https://docs.google.com/spreadsheets/d/1IMUxpioGHLPLcLlxXaVR7IYFIltIkkt4muvByDo-LI8/edit?gid=0#gid=0" 
                    
                    sheet = client.open_by_url(sheet_url).sheet1
                    for row in rows_to_append:
                        sheet.append_row(row)
                        
                    st.success("✅ データ取得 ＆ スプレッドシートへの記録が完了しました！")
                except Exception as e:
                    st.error(f"⚠️ スプレッドシートへの記録に失敗しました: {e}")
            
            # --- 画面への結果表示（見切れ防止のカード形式） ---
            if data_list:
                for data in data_list:
                    # 銘柄名と価格を見出しにする
                    st.markdown(f"### 📌 {data['ティッカー']} (現在値: ${data['現在値($)']:.2f})")
                    # 数値データを並べる
                    st.markdown(f"- **日足RSI:** {data['日足RSI']:.1f}  |  **週足パフォーマンス:** {data['週足パフォーマンス(%)']:.1f}%")
                    # AIの判定文を独立した行で表示（これで見切れません！）
                    st.info(f"**{data['💡 AI判定']}**")
                    st.divider() # 区切り線
