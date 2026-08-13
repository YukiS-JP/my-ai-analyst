import streamlit as st
import pandas as pd
import numpy as np
from tradingview_screener import Query, Column

st.set_page_config(page_title="AIアナリスト", page_icon="📊", layout="wide")

st.title("📊 My AI Analyst Dashboard - スイング特化版")
st.write("日足（タイミング）・週足（トレンド）・ファンダ（割安性）を統合し、明確な根拠のある銘柄を抽出します。")

# AIによる「選定理由」を自動生成するロジック
def generate_reason(row):
    reasons = []
    
    # ①日足のテクニカル分析（エントリータイミング）
    if row['日足RSI'] < 35:
        reasons.append(f"日足RSIが{row['日足RSI']:.1f}と極度の売られすぎ水準にあり、短期的な反発余地が大きいです。")
    elif row['日足RSI'] < 45:
        reasons.append(f"日足RSIが{row['日足RSI']:.1f}と調整が進んでおり、絶好の押し目買い候補です。")
        
    if row['日足MACD'] > row['日足シグナル']:
        reasons.append("日足MACDが好転しており、買いシグナルが点灯中です。")

    # ②週足のトレンド分析（大きな方向感）
    if row['週足パフォーマンス(%)'] > 0:
        reasons.append("週足ベースではプラス成長を維持しており、大局的な上昇トレンドに乗っています。")
    else:
        reasons.append("週足では調整局面ですが、ここからの底打ち反転（スイング）を狙う局面です。")

    # ③ファンダメンタルズ分析（企業価値）
    per = row.get('PER(倍)', np.nan)
    if pd.notna(per) and per > 0 and per < 15:
        reasons.append(f"PERが{per:.1f}倍と、米国株全体と比較して非常に割安に放置されています。")
    elif pd.notna(per) and per >= 15 and per < 30:
        reasons.append(f"PER{per:.1f}倍と適正水準であり、業績と株価のバランスが良い状態です。")
    
    # 理由を一つの文章に結合
    return " ".join(reasons)

def run_screener():
    # 検索条件：時価総額10億ドル以上、日足RSI45以下、出来高100万以上
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
        # 必要な列を整理
        df = df[['name', 'close', 'RSI', 'MACD.macd', 'MACD.signal', 'Perf.W', 'price_earnings_ttm']]
        df.columns = ['ティッカー', '現在値($)', '日足RSI', '日足MACD', '日足シグナル', '週足パフォーマンス(%)', 'PER(倍)']
        
        # 理由の自動生成
        df['💡 AI選定理由'] = df.apply(generate_reason, axis=1)
        
        # 数値を見やすく丸める
        df['日足RSI'] = df['日足RSI'].round(1)
        df['週足パフォーマンス(%)'] = df['週足パフォーマンス(%)'].round(1)
        df['PER(倍)'] = df['PER(倍)'].round(1)
        
        # 表示用の最終整形（MACDの値は理由生成に使ったので隠し、スッキリ見せる）
        df_display = df[['ティッカー', '現在値($)', '日足RSI', '週足パフォーマンス(%)', 'PER(倍)', '💡 AI選定理由']]
        return df_display
    else:
        return pd.DataFrame()

if st.button("🚀 日足×週足×ファンダで最新銘柄をスクリーニング"):
    with st.spinner('各種指標を組み合わせてAIロジックで分析中...'):
        result_df = run_screener()
        
    if not result_df.empty:
        st.success("分析完了！条件に合致したスイング推奨銘柄です。")
        st.dataframe(result_df, use_container_width=True)
    else:
        st.warning("現在、厳しい条件を全て満たす銘柄は見つかりませんでした。")
