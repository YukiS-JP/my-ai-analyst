import streamlit as st
import pandas as pd
import numpy as np
from tradingview_screener import Query, Column

st.set_page_config(page_title="AIアナリスト", page_icon="📊", layout="wide")

st.title("📊 My AI Analyst Dashboard")

# ------------------------------------------------
# AIによる「ステータス判定・選定理由」を生成する関数
# ------------------------------------------------
def generate_reason(row):
    reasons = []
    
    # データが空の場合に備えて数値に変換（エラー時はNaNにする安全装置）
    rsi = pd.to_numeric(row.get('日足RSI'), errors='coerce')
    macd = pd.to_numeric(row.get('日足MACD'), errors='coerce')
    sig = pd.to_numeric(row.get('日足シグナル'), errors='coerce')
    perf = pd.to_numeric(row.get('週足パフォーマンス(%)'), errors='coerce')
    per = pd.to_numeric(row.get('PER(倍)'), errors='coerce')
    
    # ①日足のテクニカル
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

    # ②週足のトレンド
    if pd.notna(perf):
        if perf > 0:
            reasons.append("週足トレンドは上向きを維持。")
        else:
            reasons.append("週足は調整局面（スイング底打ち狙い）。")

    # ③ファンダメンタルズ（PER）※ETFなどPERがない場合はスキップ
    if pd.notna(per) and per > 0:
        if per < 15:
            reasons.append(f"PER{per:.1f}倍で非常に割安な水準です。")
        elif per < 30:
            reasons.append(f"PER{per:.1f}倍と適正な評価水準です。")

    if not reasons:
        return "現在、特筆すべき強いシグナルはありません（静観推奨）。"
    
    return " ".join(reasons)


# ------------------------------------------------
# アプリ画面の構築（タブで2画面に分割）
# ------------------------------------------------
tab1, tab2 = st.tabs(["🔍 全体スクリーニング", "🎯 個別銘柄トラッカー"])

# ==========================================
# タブ1：全体スクリーニング（条件で探す）
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
            
            df = q.set_markets('america').get_scanner_data()[1]
            
            if not df.empty:
                df = df[['name', 'close', 'RSI', 'MACD.macd', 'MACD.signal', 'Perf.W', 'price_earnings_ttm']]
                df.columns = ['ティッカー', '現在値($)', '日足RSI', '日足MACD', '日足シグナル', '週足パフォーマンス(%)', 'PER(倍)']
                
                # エラー回避のため確実に数値に変換してから丸める
                df['日足RSI'] = pd.to_numeric(df['日足RSI'], errors='coerce').round(1)
                df['週足パフォーマンス(%)'] = pd.to_numeric(df['週足パフォーマンス(%)'], errors='coerce').round(1)
                df['PER(倍)'] = pd.to_numeric(df['PER(倍)'], errors='coerce').round(1)
                
                df['💡 AI判定'] = df.apply(generate_reason, axis=1)
                
                df_display = df[['ティッカー', '現在値($)', '日足RSI', '週足パフォーマンス(%)', 'PER(倍)', '💡 AI判定']]
                st.success("分析完了！現在のスイング推奨銘柄です。")
                st.dataframe(df_display, use_container_width=True)
            else:
                st.warning("現在、厳しい条件を全て満たす銘柄は見つかりませんでした。")

# ==========================================
# タブ2：個別銘柄トラッカー（指定した銘柄を追う）
# ==========================================
with tab2:
    st.write("監視中の特定銘柄のテクニカル・ファンダメンタルズ状況をピンポイントで確認します。")
    
    target_symbols = st.text_input("確認したいティッカーをカンマ区切りで入力してください", value="SOXL, RDW, DNA, FNGU")
    
    if st.button("🎯 監視銘柄の最新データを取得"):
        with st.spinner('指定された銘柄のデータを取得中...'):
            symbols_list = [s.strip().upper() for s in target_symbols.split(",")]
            
            q2 = (Query()
                 .select('name', 'close', 'RSI', 'MACD.macd', 'MACD.signal', 'Perf.W', 'price_earnings_ttm')
                 .where(Column('name').isin(symbols_list)))
            
            df2 = q2.set_markets('america').get_scanner_data()[1]
            
            if not df2.empty:
                df2 = df2[['name', 'close', 'RSI', 'MACD.macd', 'MACD.signal', 'Perf.W', 'price_earnings_ttm']]
                df2.columns = ['ティッカー', '現在値($)', '日足RSI', '日足MACD', '日足シグナル', '週足パフォーマンス(%)', 'PER(倍)']
                
                # エラー回避のため確実に数値に変換してから丸める
                df2['日足RSI'] = pd.to_numeric(df2['日足RSI'], errors='coerce').round(1)
                df2['週足パフォーマンス(%)'] = pd.to_numeric(df2['週足パフォーマンス(%)'], errors='coerce').round(1)
                df2['PER(倍)'] = pd.to_numeric(df2['PER(倍)'], errors='coerce').round(1)

                df2['💡 現在のステータス'] = df2.apply(generate_reason, axis=1)
                
                df2_display = df2[['ティッカー', '現在値($)', '日足RSI', '週足パフォーマンス(%)', 'PER(倍)', '💡 現在のステータス']]
                st.success("取得完了！監視銘柄の現在の状況です。")
                st.dataframe(df2_display, use_container_width=True)
            else:
                st.warning("入力された銘柄のデータが見つかりませんでした。ティッカーが正しいか確認してください。")
