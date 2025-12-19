import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
from finvizfinance.screener.overview import Overview
from scipy.stats import norm
import math

# --- CONFIGURATION ---
MIN_VOLUME = 200000
MIN_PRICE = 15
MAX_PRICE = 150
MIN_RSI = 50
MIN_IV_RANK = 30
MIN_PREMIUM = 0.15
MIN_ROI = 1.0  # 1% Return on Capital
STRIKE_DISTANCE_PCT = 0.05  # 5% OTM

# --- FUNCTIONS ---
def get_high_iv_stocks():
    f = Overview()
    filters_dict = {
        'Average Volume': 'Over 200K',
        'Price': 'Over $15',
        'RSI (14)': 'Over 50'
    }
    f.set_filter(filters_dict=filters_dict)
    df = f.screener_view()
    if df.empty: return []
    return df['Ticker'].tolist()

def get_option_chain(ticker):
    try:
        stock = yf.Ticker(ticker)
        # Force a fresh fetch by getting history first
        stock.history(period="1d")
        
        exps = stock.options
        if not exps: return None
        
        # Get next monthly expiration (simplified)
        # In a real scenario, you'd filter for dates ~30-45 days out
        target_date = exps[1] if len(exps) > 1 else exps[0]
        
        opt = stock.option_chain(target_date)
        return opt.puts, target_date, stock.info.get('currentPrice', 0)
    except Exception as e:
        return None, None, 0

def black_scholes_delta(S, K, T, r, sigma, option_type='put'):
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    if option_type == 'call':
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1

# --- MAIN APP LOGIC ---

# 1. Page Config
st.set_page_config(page_title="Freedom Options Scanner", layout="wide")

# 2. Title and Clock
st.title("💰 Freedom Income Options Scanner")

current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
st.write(f"**Last Updated:** {current_time} (UTC/Server Time)")
st.info("Click 'Refresh Data' to run a new scan. Please allow 1-2 minutes for processing.")

# 3. Refresh Button
if st.button('Refresh Data'):
    st.rerun()

# 4. Run the Scan Logic
with st.spinner('Scanning the market... this takes a moment...'):
    tickers = get_high_iv_stocks()
    # Limit to first 20 for speed in this demo, increase later
    tickers = tickers[:20] 
    
    results = []

    for ticker in tickers:
        puts, exp_date, share_price = get_option_chain(ticker)
        
        if puts is None or share_price == 0: continue
        
        # Filter Puts
        max_strike = share_price * (1 - STRIKE_DISTANCE_PCT)
        valid_puts = puts[puts['strike'] < max_strike]
        
        for index, row in valid_puts.iterrows():
            bid = row['bid']
            strike = row['strike']
            
            # CRASH FIX: Check for None or 0
            if bid is None or bid < MIN_PREMIUM:
                continue
                
            # ROI Calc
            collateral = strike * 100
            premium = bid * 100
            roi = (premium / collateral) * 100
            
            if roi >= MIN_ROI:
                results.append({
                    'Ticker': ticker,
                    'Price': f"${share_price:.2f}",
                    'Strike': f"${strike:.2f}",
                    'Exp Date': exp_date,
                    'Premium': f"${bid:.2f}",
                    'ROI': f"{roi:.1f}%",
                    'Break Even': f"${(strike - bid):.2f}"
                })

    # 5. Display Results
    if len(results) > 0:
        df_results = pd.DataFrame(results)
        st.success(f"Found {len(results)} Opportunities")
        st.dataframe(df_results, height=800, use_container_width=True)
    else:
        st.warning("No trades found matching criteria right now.")