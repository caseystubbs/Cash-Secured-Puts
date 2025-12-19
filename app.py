import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import datetime
import time
import numpy as np
import requests
import pytz
import yfinance as yf
from finvizfinance.screener.overview import Overview
from scipy.stats import norm

# --- CONFIGURATION ---
MIN_PRICE = 10.0
MIN_VOLUME_STR = 'Over 1M'
MIN_ANN_ROI = 15.0
MIN_PREMIUM = 0.15
MIN_PROB_WIN = 0.60  

# --- BRANDING ---
LOGO_URL = "https://freedomincomeoptions.com/wp-content/uploads/2025/03/Freedom-income-options-440-x-100.png"
FAVICON_URL = "https://freedomincomeoptions.com/wp-content/uploads/2025/03/freedom-income-options-512-x-512.png"

# --- TRADIER API CONFIG ---
TRADIER_ACCESS_TOKEN = "elOrs2eZGsf7cp9JOGomCL21tUpQ"

# --- GUARANTEED LIQUID TICKERS ---
LIQUID_TICKERS = [
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "AMD", "NVDA", "AMZN", 
    "GOOGL", "META", "NFLX", "BAC", "JPM", "DIS", "COIN", "MARA", "PLTR",
    "UBER", "INTC", "F", "T", "VZ", "CSCO", "CMCSA", "PFE", "XOM", "CVX"
]

def get_headers():
    return {
        'Authorization': f'Bearer {TRADIER_ACCESS_TOKEN}',
        'Accept': 'application/json'
    }

def get_finviz_candidates(status_container):
    status_container.text("⏳ Contacting Finviz for candidates...")
    filters_dict = {
        'Option/Short': 'Optionable',
        'Average Volume': MIN_VOLUME_STR,
        'Price': 'Over $10',
        '200-Day Simple Moving Average': 'Price above SMA200',
        'EPS growthqtr over qtr': 'Positive (>0%)',
    }
    try:
        foverview = Overview()
        foverview.set_filter(filters_dict=filters_dict)
        df_finviz = foverview.screener_view(verbose=0)
        
        if 'Volatility (Month)' in df_finviz.columns:
            df_finviz['Vol_Num'] = df_finviz['Volatility (Month)'].astype(str).str.replace('%', '', regex=False)
            df_finviz['Vol_Num'] = pd.to_numeric(df_finviz['Vol_Num'], errors='coerce')
            df_finviz = df_finviz.sort_values(by='Vol_Num', ascending=False)
        
        candidates = df_finviz['Ticker'].tolist()
        return candidates

    except Exception as e:
        status_container.text(f"❌ Finviz Error: {e}")
        return []

def calculate_probability_of_win(stock_price, strike_price, days_to_expiry, implied_volatility):
    if not implied_volatility or implied_volatility <= 0 or days_to_expiry <= 0:
        return 0.0
    
    t = days_to_expiry / 365.0
    d2 = (np.log(stock_price / strike_price) - 0.5 * implied_volatility**2 * t) / (implied_volatility * np.sqrt(t))
    return norm.cdf(d2)

def get_smart_buckets():
    return [
        (4, 10, "1 Week"), (11, 17, "2 Weeks"), (18, 24, "3 Weeks"), (25, 31, "4 Weeks"),
        (32, 38, "5 Weeks"), (39, 45, "6 Weeks"), (46, 55, "7 Weeks (45+ Day Target)"), 
        (56, 70, "8 Weeks (60+ Day Target)")  
    ]

# --- HELPER FUNCTIONS ---
def check_trend_stability(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="2y") 
        
        if len(hist) < 230: return False 
        
        hist['SMA_200'] = hist['Close'].rolling(window=200).mean()
        last_30 = hist.iloc[-30:]
        
        # Strict trend check
        is_stable = all(last_30['Close'] > last_30['SMA_200'])
        return is_stable
    except:
        return False

def get_tradier_expirations(symbol):
    url = "https://api.tradier.com/v1/markets/options/expirations"
    try:
        response = requests.get(url, params={'symbol': symbol, 'includeAllRoots': 'true'}, headers=get_headers())
        if response.status_code == 200:
            data = response.json()
            if 'expirations' in data and data['expirations'] is not None:
                exps = data['expirations']['date']
                if isinstance(exps, str): return [exps]
                return exps
    except: pass
    return []

def get_tradier_chain(symbol, expiration):
    url = "https://api.tradier.com/v1/markets/options/chains"
    try:
        response = requests.get(url, params={'symbol': symbol, 'expiration': expiration, 'greeks': 'true'}, headers=get_headers())
        if response.status_code == 200:
            data = response.json()
            if 'options' in data and data['options'] is not None:
                opts = data['options']['option']
                if isinstance(opts, dict): return [opts] 
                return opts
    except: pass
    return []

def get_tradier_price(symbol):
    url = "https://api.tradier.com/v1/markets/quotes"
    try:
        response = requests.get(url, params={'symbols': symbol}, headers=get_headers())
        if response.status_code == 200:
            data = response.json()
            if 'quotes' in data and 'quote' in data['quotes']:
                q = data['quotes']['quote']
                if isinstance(q, list): return q[0]['last']
                return q['last']
    except: return None
    return None

def analyze_stock(symbol, bucket_data):
    # Skip if key is missing (prevent partial config crash)
    if "PASTE" in TRADIER_ACCESS_TOKEN: return

    if not check_trend_stability(symbol):
        return

    current_price = get_tradier_price(symbol)
    if not current_price: return

    expirations = get_tradier_expirations(symbol)
    if not expirations: return
    
    today = datetime.date.today()
    buckets = get_smart_buckets()
    exps_to_fetch = {}

    for i, (min_d, max_d, label) in enumerate(buckets):
        valid_exps = []
        for exp in expirations:
            exp_date = datetime.datetime.strptime(exp, "%Y-%m-%d").date()
            days_to_exp = (exp_date - today).days
            if min_d <= days_to_exp <= max_d:
                valid_exps.append((exp, days_to_exp))
        if valid_exps:
            exps_to_fetch[i] = valid_exps[-1]

    for bucket_idx, (exp_date_str, dte) in exps_to_fetch.items():
        chain = get_tradier_chain(symbol, exp_date_str)
        if not chain: continue
        
        best_score = -1
        best_trade = None

        for opt in chain:
            if opt.get('option_type') != 'put': continue
            strike = opt.get('strike', 0)
            bid = opt.get('bid', 0)
            
            # --- CRASH FIX START ---
            if bid is None: continue
            # --- CRASH FIX END ---

            if strike >= current_price: continue
            if bid < MIN_PREMIUM: continue

            vol = opt.get('volume', 0)
            oi = opt.get('open_interest', 0)
            if vol == 0 and oi == 0: continue

            greeks = opt.get('greeks', {})
            iv = 0
            if greeks: iv = greeks.get('mid_iv', 0)
            
            prob_win = calculate_probability_of_win(current_price, strike, dte, iv)
            if prob_win < MIN_PROB_WIN: continue

            safety_cushion_pct = (current_price - strike) / current_price * 100

            capital = strike * 100
            premium = bid * 100
            raw_roi = (premium / capital)
            ann_roi = raw_roi * (365 / dte) * 100

            if ann_roi >= MIN_ANN_ROI:
                score = ann_roi 
                if score > best_score:
                    best_score = score
                    best_trade = {
                        "Symbol": symbol,
                        "Price": current_price,
                        "Strike": strike,
                        "Premium": bid,
                        "DTE": dte,
                        "Prob_Win": round(prob_win * 100, 1),
                        "Safety": round(safety_cushion_pct, 1),
                        "Ann_ROI": round(ann_roi, 2),
                        "Expiration": exp_date_str,
                        "Score": score
                    }

        if best_trade:
            if bucket_idx not in bucket_data:
                bucket_data[bucket_idx] = []
            bucket_data[bucket_idx].append(best_trade)

def generate_dashboard_html(bucket_data):
    utc_now = datetime.datetime.now(pytz.utc)
    est = pytz.timezone('US/Eastern')
    now_est = utc_now.astimezone(est)
    formatted_date = now_est.strftime("Date: <strong>%B %d, %Y %I:%M %p EST</strong>")

    all_trades = []
    for idx in bucket_data:
        all_trades.extend(bucket_data[idx])
    
    top_trades = sorted(all_trades, key=lambda x: x['Score'], reverse=True)[:3]
    under_40_trades = [t for t in all_trades if t['Price'] < 40]
    best_under_40 = sorted(under_40_trades, key=lambda x: x['Score'], reverse=True)[:3]

    bucket_indices = range(8)

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Freedom Income Options | Daily Cash Secured Put Scanner</title>
        <link rel="icon" href="{FAVICON_URL}" type="image/png">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link href="https://cdn.datatables.net/1.13.4/css/dataTables.bootstrap5.min.css" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>
            body {{ background-color: #f4f6f9; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
            .main-header {{ background-color: #fff; padding: 15px 0; border-bottom: 1px solid #e0e0e0; }}
            .header-logo {{ height: 60px; width: auto; margin-right: 15px; }}
            .header-title {{ font-size: 24px; font-weight: 700; color: #333; vertical-align: middle; }}
            .header-date {{ font-size: 14px; color: #666; text-align: right; font-weight: 600; }}
            .sub-header {{ background-color: #212529; color: #fff; padding: 8px 0; text-align: center; font-weight: 700; font-size: 14px; letter-spacing: 0.5px; }}
            .nav-tabs {{ background-color: #212529; border