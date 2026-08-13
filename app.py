import streamlit as st
import pandas as pd
from tradingview_screener import Query, Column

st.set_page_config(page_title="AIアナリスト", page_icon="📊", layout="wide")

st.title("📊 My AI Analyst Dashboard")
st.write("ボタンを押すと、現在の米国市場から『押し目買いチャンス』の銘柄を自動抽出します。")

def run_screener():
    q = (Query()
         .select('name', 'close', 'RSI', 'MACD.macd', 'MACD.signal', 'market_cap_basic')
         .where(
             Column('market_cap_basic') > 1_000_000_000,
             Column('RSI') < 40,
             Column('volume') > 500_000
         )
         .order_by('RSI', ascending=True)
         .limit(10))
    
    df_nyse = q.set_markets('america').get_scanner_data()[1]
    
    if not df_nyse.empty:
        df_nyse = df_nyse[['name', 'close', 'RSI', 'MACD.macd', 'MACD.signal']]
        df_nyse.columns = ['ティッカー', '現在値($)', 'RSI(14)', 'MACD', 'シグナル']
        df_nyse['MACD乖離'] = df_nyse['MACD'] - df_nyse['シグナル']
    
    return df_nyse

if st.button("🚀 最新のチャンス銘柄をスクリーニング"):
    with st.spinner('TradingViewのサーバーからデータを取得中...（数秒かかります）'):
        result_df = run_screener()
        
    if not result_df.empty:
        st.success("スクリーニングが完了しました！")
        st.write("### 📌 RSIが低く、反発期待のある銘柄トップ10")
        st.dataframe(result_df)
    else:
        st.warning("現在、条件に合致する銘柄は見つかりませんでした。")
