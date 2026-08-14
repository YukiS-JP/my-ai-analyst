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

st.set_page_config(page_title="AIアナリスト", page_icon="📊", layout="wide")

st.title("📊 My AI Analyst Dashboard")

if 'watch_list' not in st.session_state:
    st.session_state.watch_list = ["SOXL", "RDW", "DNA", "FNGU"]

# ------------------------------------------------
# AIによる「ステータス判定・選定理由」を生成する関数
# ------------------------------------------------
def generate_reason(row):
    reasons = []
    
    rsi = pd.to_numeric(row.get('日足RSI'), errors='coerce')
    macd = pd.to_numeric(row.get('日足MACD'), errors='coerce')
    sig = pd.to_numeric(row.get('日足シグナル'), errors='coerce')
    perf = pd.to_numeric(row.get('週足パフォーマンス(%)'), errors='coerce')
    per = pd.to_numeric(row.get('PER(倍)'), errors='coerce')
    
    if pd.notna(rsi):
        if rsi < 35:
            reasons.append(f"日足RSIが{rsi:.1f}と極度の売られすぎ水準です。")
        elif rsi < 45:
            reasons.append(f"日足RSI{rsi:.1f}で調整が進み、押し目買い候補です。")
        elif rsi > 70:
            reasons.append(f"日足RSI{rsi:.1f}で過熱感あり。短期的な利確目安です。")
            
    if pd.notna(macd) and pd.notna(sig):
        if macd > sig:
            reasons.append("MACD好転（買いシグナル）点灯中。")

    if pd.notna(perf):
        if perf > 0:
            reasons.append("週足トレンドは上向きを維持。")
        else:
            reasons.append("週足は調整局面（スイング底打ち狙い）。")

    if pd.notna(per) and per > 0:
        if per < 15:
            reasons.append(f"PER{per:.1f}倍で非常に割安な水準です。")
        elif per < 30:
            reasons.append(f"PER{per:.1f}倍と適正な評価水準です。")

    if not reasons:
        return "現在、特筆すべき強いシグナルはありません（静観推奨）。"
    
    return " ".join(reasons)


# ------------------------------------------------
# アプリ画面の構築（タブで4画面に分割）
# ------------------------------------------------
tab_top, tab1, tab2, tab3 = st.tabs(["🏠 トップ", "🔍 スクリーニング", "🎯 トラッカー", "📰 ニュース"])

# ==========================================
# 🌟 トップ（スマホ最適化・テキストベース一覧）
# ==========================================
with tab_top:
    st.subheader("🌐 主要市場サマリー（為替・全体指数）")
    
    macro_tickers = {
        "米ドル/円": "JPY=X",
        "S&P 500": "^GSPC",
        "NASDAQ": "^IXIC",
        "日経平均": "^N225"
    }
    
    # パネル表示をやめて、スマホでも綺麗に折り返されるテキストリストに変更
    for name, symbol in macro_tickers.items():
        try:
            t = yf.Ticker(symbol)
            h = t.history(period="5d")
            if not h.empty and len(h) >= 2:
                c_price = h['Close'].iloc[-1]
                p_price = h['Close'].iloc[-2]
                diff = c_price - p_price
                pct = (diff / p_price) * 100
                
                if diff > 0:
                    trend = f"🟢 ↑+{diff:,.2f} (+{pct:.2f}%)"
                elif diff < 0:
                    trend = f"🔴 ↓{diff:,.2f} ({pct:.2f}%)"
                else:
                    trend = "⚪️ ±0.00 (0.00%)"
                    
                if symbol == "JPY=X":
                    val_str = f"¥{c_price:.2f}"
                else:
                    val_str = f"{c_price:,.2f}"
                    
                st.markdown(f"**{name}** {val_str} （{trend}）")
            else:
                st.markdown(f"**{name}** 取得失敗")
        except Exception:
            st.markdown(f"**{name}** エラー")

    st.divider()
    
    st.subheader("📌 監視銘柄 データ一覧 ＆ チャート")
    
    selected_charts = st.multiselect(
        "表示する銘柄を選択（※並び順も自由に変更可能です）",
        options=st.session_state.watch_list,
        default=st.session_state.watch_list
    )
    
    st.write("") 
    
    if selected_charts:
        for sym in selected_charts:
            st.markdown(f"### 🔹 {sym}")
            
            try:
                ticker = yf.Ticker(sym)
                hist = ticker.history(period="1y")
                
                if not hist.empty and len(hist) > 22:
                    curr_p = hist['Close'].iloc[-1]
                    prev_p = hist['Close'].iloc[-2]
                    day_diff = curr_p - prev_p
                    day_pct = (day_diff / prev_p) * 100

                    month_p = hist['Close'].iloc[-22]
                    month_pct = ((curr_p - month_p) / month_p) * 100

                    high_52 = hist['High'].max()
                    dd_52 = ((curr_p - high_52) / high_52) * 100

                    delta = hist['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                    rs = gain / loss
                    rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
                    
                    if day_diff > 0:
                        d_trend = f"🟢 ↑+{day_diff:.2f} (+{day_pct:.2f}%)"
                    elif day_diff < 0:
                        d_trend = f"🔴 ↓{day_diff:.2f} ({day_pct:.2f}%)"
                    else:
                        d_trend = "⚪️ ±0.00 (0.00%)"

                    if rsi_val >= 70:
                        rsi_stat = "🔴 過熱"
                    elif rsi_val <= 45:
                        rsi_stat = "🟢 割安"
                    else:
                        rsi_stat = "⚪️ 中立"
                    
                    # スマホで一目で把握できるようにコンパクトなテキスト2行で表示
                    st.markdown(f"- **現在値:** ${curr_p:.2f} （{d_trend}）")
                    st.markdown(f"- **前月比:** {month_pct:+.2f}% ｜ **RSI:** {rsi_val:.1f} ({rsi_stat}) ｜ **高値差:** {dd_52:+.1f}%")
                    
            except Exception:
                st.warning(f"⚠️ {sym} の指標データ取得に失敗しました。")

            # 📈 折りたたみ式TradingViewチャート（タップでスッと開く）
            with st.expander(f"📈 {sym} の詳細チャートを開く / 閉じる"):
                html_code = f"""
                <div class="tradingview-widget-container">
                  <div id="tradingview_{sym}"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                  <script type="text/javascript">
                  new TradingView.widget(
                  {{
                  "width": "100%",
                  "height": 400,
                  "symbol": "{sym}",
                  "interval": "D",
                  "timezone": "Asia/Tokyo",
                  "theme": "dark",
                  "style": "1",
                  "locale": "ja",
                  "enable_publishing": false,
                  "allow_symbol_change": true,
                  "hide_top_toolbar": false,
                  "container_id": "tradingview_{sym}"
                }}
                  );
                  </script>
                </div>
                """
                components.html(html_code, height=400)
            
            st.divider()
    else:
        st.info("上のメニューから、表示させたい銘柄を選んでください。")

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
            
            if data_list:
                for data in data_list:
                    st.markdown(f"### 📌 {data['ティッカー']} (現在値: ${data['現在値($)']:.2f})")
                    st.markdown(f"- **日足RSI:** {data['日足RSI']:.1f}  |  **週足パフォーマンス:** {data['週足パフォーマンス(%)']:.1f}%")
                    st.info(f"**{data['💡 AI判定']}**")
                    st.divider()

# ==========================================
# タブ3：最新ニュース
# ==========================================
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
                        
                        with urllib.request.urlopen(req) as response:
                            xml_data = response.read()
                        
                        root = ET.fromstring(xml_data)
                        items = root.findall('.//item')
                        
                        if items:
                            for item in items[:3]:
                                display_news_item(item)
                            
                            if len(items) > 3:
                                with st.expander(f"🔽 {news_target} のその他のニュースを見る"):
                                    for item in items[3:10]:
                                        display_news_item(item)
                                        st.write("") 
                        else:
                            st.info(f"{news_target} に関連する最新ニュースは見つかりませんでした。")
                    except Exception as e:
                        st.error(f"{news_target} のニュース取得中にエラーが発生しました。")
                    
                    st.divider()
    else:
        st.info("タブ2（個別銘柄トラッカー）で監視リストに銘柄を追加してください。")
