import streamlit as st
import pandas as pd
import yfinance as yf
from finvizfinance.screener.overview import Overview
from datetime import datetime
import math
from scipy.stats import norm

# --- YOUR ORIGINAL CONFIGURATION ---
MIN_PRICE = 10.0
MIN_VOLUME_STR = 'Over 1M'  # Using your exact string
MIN_ANN_ROI = 15.0          # Annualized Return
MIN_PREMIUM = 0.15
MIN_PROB_WIN = 0.60         # Probability of Profit (1 - Delta)

# --- HELPER FUNCTIONS ---

def get_finviz_candidates():
    """Fetches stocks using your exact Volume and Price filters"""
    try:
        f = Overview()
        filters_dict = {
            'Average Volume': MIN_VOLUME_STR,
            'Price': f'Over ${int(MIN_PRICE)}',
            'Option/Short': 'Optionable' # Ensure they have options
        }
        f.set_filter(filters_dict=filters_dict)
        df = f.screener_view()
        if df.empty: return []
        return df['Ticker'].tolist()
    except Exception as e:
        st.error(f"Finviz Error: {e}")
        return []

def black_scholes_delta(S, K, T, r, sigma, option_type='put'):
    """Calculates Delta to determine Probability of Winning"""
    if T <= 0 or sigma <= 0: return 0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    if option_type == 'call':
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1

def analyze_market():
    # 1. Get Candidates
    status_text.text("🔍 Fetching candidates from Finviz...")
    tickers = get_finviz_candidates()
    
    if not tickers:
        st.warning("No stocks found matching the Finviz criteria.")
        return []

    # NO LIMIT: Scanning everyone found
    total_found = len(tickers)
    status_text.text(f"✅ Found {total_found} candidates. Starting Analysis...")
    
    results = []
    
    # 2. Loop through candidates
    for i, ticker in enumerate(tickers):
        # Update status every few stocks so you know it's alive
        if i % 5 == 0:
            status_text.text(f"Scanning {i+1}/{total_found}: {ticker}...")
            bar.progress((i + 1) / total_found)

        try:
            stock = yf.Ticker(ticker)
            # Fetch very short history to get current price fast
            hist = stock.history(period="1d")
            if hist.empty: continue
            current_price = hist['Close'].iloc[-1]
            
            # Get Options
            exps = stock.options
            if not exps: continue
            
            # Target ~30 days out (simplified logic from your old script)
            # We pick the 2nd expiration to avoid expiring tomorrow
            target_date = exps[1] if len(exps) > 1 else exps[0]
            opt_chain = stock.option_chain(target_date)
            puts = opt_chain.puts
            
            # Calculate Days to Expiration (DTE)
            exp_dt = datetime.strptime(target_date, "%Y-%m-%d")
            dte = (exp_dt - datetime.now()).days
            if dte < 1: continue # Skip if expiring today
            
            # Filter Puts
            # 1. Strike must be below current price (OTM)
            puts = puts[puts['strike'] < current_price]
            
            for index, row in puts.iterrows():
                bid = row['bid']
                strike = row['strike']
                sigma = row['impliedVolatility']
                
                # Filter: Minimum Premium
                if bid is None or bid < MIN_PREMIUM: continue
                
                # CALCULATION: Probability of Winning (1 - |Delta|)
                # We estimate Risk Free Rate (r) as 4.5% (0.045)
                delta = black_scholes_delta(current_price, strike, dte/365, 0.045, sigma, 'put')
                prob_win = 1 - abs(delta)
                
                # Filter: Min Prob Win
                if prob_win < MIN_PROB_WIN: continue
                
                # CALCULATION: Annualized ROI
                # (Premium / Strike) * (365 / DTE) * 100
                simple_roi = bid / strike
                ann_roi = simple_roi * (365 / dte) * 100
                
                # Filter: Min Annualized ROI
                if ann_roi < MIN_ANN_ROI: continue
                
                # Add to Results
                results.append({
                    'Ticker': ticker,
                    'Price': f"${current_price:.2f}",
                    'Strike': f"${strike:.2f}",
                    'Exp Date': target_date,
                    'DTE': dte,
                    'Bid': f"${bid:.2f}",
                    'Ann ROI': f"{ann_roi:.1f}%",
                    'Prob Win': f"{prob_win:.1%}"
                })
                
        except Exception as e:
            continue # Skip bad tickers without crashing
            
    return results

# --- WEB APP DISPLAY ---
st.set_page_config(page_title="Freedom Scanner", layout="wide")
st.title("💰 Freedom Income Scanner (Classic Logic)")

st.markdown(f"""
**Current Filters:**
* Min Price: ${MIN_PRICE}
* Volume: {MIN_VOLUME_STR}
* Min Premium: ${MIN_PREMIUM}
* **Min Ann. ROI: {MIN_ANN_ROI}%**
* **Min Prob Win: {int(MIN_PROB_WIN*100)}%**
""")

if st.button('Run Full Scan'):
    status_text = st.empty()
    bar = st.progress(0)
    
    data = analyze_market()
    
    bar.empty()
    status_text.text(f"Scan Complete. Found {len(data)} trades.")
    
    if data:
        df = pd.DataFrame(data)
        st.dataframe(df, height=800, use_container_width=True)
    else:
        st.warning("No trades found matching these strict criteria.")