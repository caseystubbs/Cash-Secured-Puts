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
OUTPUT_FILENAME = "cash_secured_puts_scan.html"

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

def get_finviz_candidates():
    print("⏳ Contacting Finviz for candidates...")
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
            print("✅ Sorted candidates by Monthly Volatility.")
        
        candidates = df_finviz['Ticker'].tolist()
        print(f"✅ Found {len(candidates)} candidates.")
        return candidates

    except Exception as e:
        print(f"❌ Finviz Error: {e}")
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
            .nav-tabs {{ background-color: #212529; border-bottom: none; justify-content: center; padding-top: 5px; }}
            .nav-tabs .nav-link {{ color: #fff; border: none; border-radius: 0; padding: 10px 15px; font-weight: 600; font-size: 13px; margin: 0 2px; transition: all 0.2s; }}
            .nav-tabs .nav-link:hover {{ background-color: #343a40; color: #fff; }}
            .nav-tabs .nav-link.active {{ background-color: #fff; color: #000; border-top: 3px solid #28a745; font-weight: 700; }}
            .nav-link.best-trades {{ background-color: #198754 !important; color: #fff !important; }}
            .nav-link.best-trades.active {{ background-color: #146c43 !important; border-top-color: #fff !important; }}
            .nav-link.under-40 {{ background-color: #0d6efd !important; color: #fff !important; }}
            .nav-link.under-40.active {{ background-color: #0a58ca !important; border-top-color: #fff !important; }}
            .tab-content {{ background-color: #fff; padding: 20px; border: 1px solid #e0e0e0; border-top: none; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }}
            .top-trades-box {{ background-color: #ffc107; border: 3px solid #e0a800; border-radius: 10px; padding: 5px; margin-bottom: 20px; }}
            .blue-trades-box {{ background-color: #cff4fc; border: 3px solid #0dcaf0; border-radius: 10px; padding: 5px; margin-bottom: 20px; }}
            .top-trades-header {{ text-align: center; font-weight: 700; font-size: 18px; color: #212529; padding: 10px 0; text-transform: uppercase; }}
            .table-custom thead th {{ background-color: #28a745; color: white; font-weight: 600; border-bottom: none; }}
            .premium-txt {{ color: #28a745; font-weight: 700; }}
            .safety-txt {{ font-weight: 700; color: #198754; }}
            .prob-txt {{ font-weight: 700; }}
        </style>
    </head>
    <body>
        <header class="main-header">
            <div class="container-fluid">
                <div class="row align-items-center">
                    <div class="col-md-6">
                        <img src="{LOGO_URL}" alt="Freedom Income Options" class="header-logo">
                        <span class="header-title">Daily Cash Secured Put Scanner</span>
                    </div>
                    <div class="col-md-6">
                        <div class="header-date">{formatted_date}</div>
                    </div>
                </div>
            </div>
        </header>

        <div class="sub-header">
            AVAILABLE EXPIRATIONS (DAYS OUT)
        </div>

        <ul class="nav nav-tabs" id="myTab" role="tablist">
            <li class="nav-item" role="presentation">
                <button class="nav-link best-trades active" id="best-tab" data-bs-toggle="tab" data-bs-target="#best-tab-content" type="button" role="tab">
                    <i class="fas fa-star me-1"></i> BEST TRADES
                </button>
            </li>
            <li class="nav-item" role="presentation">
                <button class="nav-link under-40" id="under40-tab" data-bs-toggle="tab" data-bs-target="#under40-tab-content" type="button" role="tab">
                    <i class="fas fa-star me-1"></i> BEST UNDER $40
                </button>
            </li>
    """
    
    for i in bucket_indices:
        if i in bucket_data and bucket_data[i]:
            exps_in_bucket = [t['Expiration'] for t in bucket_data[i]]
            most_common_exp = max(set(exps_in_bucket), key=exps_in_bucket.count)
            avg_dte = int(np.mean([t['DTE'] for t in bucket_data[i]]))
            tab_label = f"{most_common_exp} ({avg_dte} Days)"
        else:
            tab_label = f"Bucket {i+1} (No Data)"

        html += f"""
            <li class="nav-item" role="presentation">
                <button class="nav-link" id="tab-{i}" data-bs-toggle="tab" data-bs-target="#content-{i}" type="button" role="tab">
                    {tab_label}
                </button>
            </li>
        """

    html += """
        </ul>

        <div class="container-fluid px-0">
            <div class="tab-content" id="myTabContent">
                
                <div class="tab-pane fade show active" id="best-tab-content" role="tabpanel">
                    <div class="top-trades-box">
                        <div class="top-trades-header">
                            <i class="fas fa-medal me-2"></i> TOP 3 FREEDOM PUTS (8-WEEK MAX)
                        </div>
                        <div class="table-responsive">
                            <table class="table table-custom table-striped text-center mb-0 align-middle">
                                <thead>
                                    <tr>
                                        <th>RANK</th><th>TICKER</th><th>EXPIRATION</th><th>STRIKE</th><th>SAFETY NET</th><th>PROB. WIN</th><th>PREMIUM</th><th>ANN. ROI</th>
                                    </tr>
                                </thead>
                                <tbody class="bg-white">
    """
    for idx, trade in enumerate(top_trades):
        html += f"""<tr><td><strong>#{idx+1}</strong></td><td><strong>{trade['Symbol']}</strong></td><td>{trade['Expiration']}</td><td>${trade['Strike']:.1f}</td><td class="safety-txt">{trade['Safety']}%</td><td class="prob-txt">{trade['Prob_Win']}%</td><td class="premium-txt">${trade['Premium']:.2f}</td><td>{trade['Ann_ROI']}%</td></tr>"""
    if not top_trades: html += '<tr><td colspan="8" class="text-muted">No trades found.</td></tr>'
    html += """</tbody></table></div></div></div>"""

    html += """
                <div class="tab-pane fade" id="under40-tab-content" role="tabpanel">
                    <div class="blue-trades-box">
                        <div class="top-trades-header">
                            <i class="fas fa-search-dollar me-2"></i> TOP 3 TRADES UNDER $40
                        </div>
                        <div class="table-responsive">
                            <table class="table table-custom table-striped text-center mb-0 align-middle">
                                <thead>
                                    <tr>
                                        <th>RANK</th><th>TICKER</th><th>PRICE</th><th>EXPIRATION</th><th>STRIKE</th><th>SAFETY NET</th><th>PROB. WIN</th><th>PREMIUM</th><th>ANN. ROI</th>
                                    </tr>
                                </thead>
                                <tbody class="bg-white">
    """
    for idx, trade in enumerate(best_under_40):
        html += f"""<tr><td><strong>#{idx+1}</strong></td><td><strong>{trade['Symbol']}</strong></td><td>${trade['Price']:.2f}</td><td>{trade['Expiration']}</td><td>${trade['Strike']:.1f}</td><td class="safety-txt">{trade['Safety']}%</td><td class="prob-txt">{trade['Prob_Win']}%</td><td class="premium-txt">${trade['Premium']:.2f}</td><td>{trade['Ann_ROI']}%</td></tr>"""
    if not best_under_40: html += '<tr><td colspan="9" class="text-muted">No trades under $40 found.</td></tr>'
    html += """</tbody></table></div></div></div>"""

    for i in bucket_indices:
        if i in bucket_data:
            rows = sorted(bucket_data[i], key=lambda x: x['Score'], reverse=True)[:10]
        else:
            rows = []
        dt_class = "datatable" if rows else ""
        
        html += f"""
                <div class="tab-pane fade" id="content-{i}" role="tabpanel">
                    <div class="table-responsive">
                        <table class="table table-custom table-hover align-middle {dt_class}" style="width:100%">
                            <thead><tr><th>TICKER</th><th>PRICE</th><th>STRIKE</th><th>SAFETY NET</th><th>PROB. WIN</th><th>PREMIUM</th><th>ANN. ROI</th><th>ACTION</th></tr></thead>
                            <tbody>
        """
        if rows:
            for row in rows:
                html += f"""<tr><td><strong>{row['Symbol']}</strong></td><td>${row['Price']:.2f}</td><td>${row['Strike']:.1f}</td><td class="safety-txt">{row['Safety']}%</td><td class="prob-txt">{row['Prob_Win']}%</td><td class="premium-txt">${row['Premium']:.2f}</td><td>{row['Ann_ROI']}%</td><td><a href="https://finance.yahoo.com/quote/{row['Symbol']}/options?date={int(datetime.datetime.strptime(row['Expiration'], '%Y-%m-%d').timestamp())}" target="_blank" class="btn btn-sm btn-outline-success fw-bold">View Chain</a></td></tr>"""
        else: html += '<tr><td colspan="8" class="text-center text-muted p-4">No data.</td></tr>'
        html += """</tbody></table></div></div>"""

    html += """
            </div>
        </div>
        <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.4/js/dataTables.bootstrap5.min.js"></script>
        <script>
            $(document).ready(function () {
                $('.datatable').DataTable({ "order": [[ 6, "desc" ]], "pageLength": 10, "lengthChange": false, "language": { "search": "Filter Tickers:" } });
            });
        </script>
    </body>
    </html>
    """
    return html

def main():
    if "PASTE" in TRADIER_ACCESS_TOKEN:
        print("❌ ERROR: Key not configured.")
        return

    print("📅 Initializing Tradier Scanner (Strict Trend: 30-Day SMA200 Hold)...")
    candidates = get_finviz_candidates()
    full_list = list(set(LIQUID_TICKERS + candidates))
    scan_list = full_list[:100]

    print(f"🔬 Scanning {len(scan_list)} tickers...")
    bucket_data = {}
    
    for i, ticker in enumerate(scan_list):
        analyze_stock(ticker, bucket_data)
        if (i+1) % 5 == 0:
            print(f"   Processed {i+1}/{len(scan_list)}...")
        time.sleep(0.2) 

    if bucket_data:
        html = generate_dashboard_html(bucket_data)
        with open(OUTPUT_FILENAME, "w", encoding='utf-8') as f:
            f.write(html)
        print(f"✅ Dashboard Generated: {OUTPUT_FILENAME}")
    else:
        print("⚠️ No results found.")

if __name__ == "__main__":
    main()