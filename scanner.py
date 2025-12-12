import pandas as pd
import yfinance as yf
import datetime
import time
from finvizfinance.screener.overview import Overview

# --- CONFIGURATION ---
# Freedom Income Options Criteria
MIN_PRICE = 10.0
MIN_VOLUME_STR = 'Over 1M'
MIN_DTE = 0          # We want upcoming weeks, so we start from 0
MAX_WEEKS = 8        # Look 8 weeks out
MIN_ANNUALIZED_ROI = 15.0 

def get_finviz_candidates():
    """
    Fetches stocks from Finviz with:
    - Optionable, Price > $10, Avg Vol > 1M, Price > SMA200
    - PLUS: Positive Earnings Growth (Qtr over Qtr)
    """
    print("⏳ Contacting Finviz for growth candidates...")
    
    filters_dict = {
        'Option/Short': 'Optionable',
        'Average Volume': MIN_VOLUME_STR,
        'Price': 'Over $10',
        '200-Day Simple Moving Average': 'Price above SMA200',
        'EPS growth qtr over qtr': 'Positive (>0%)' # NEW: Earnings Growth Filter
    }
    
    try:
        foverview = Overview()
        foverview.set_filter(filters_dict=filters_dict)
        df_finviz = foverview.screener_view(verbose=0)
        candidates = df_finviz['Ticker'].tolist()
        print(f"✅ Found {len(candidates)} growth candidates.")
        return candidates
    except Exception as e:
        print(f"❌ Finviz Error: {e}")
        return []

def analyze_options_for_weeks(symbol, weeks_data):
    """
    Scans a stock and slots the best option into the correct weekly bucket.
    """
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period='1d')
        if hist.empty: return
        current_price = hist['Close'].iloc[-1]
        
        expirations = stock.options
        if not expirations: return
        
        today = datetime.date.today()
        
        # We only care about the next 8 weeks of expirations
        # Calculate the date range for 8 weeks
        max_date = today + datetime.timedelta(weeks=MAX_WEEKS)
        
        valid_exps = []
        for exp_str in expirations:
            exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
            if today < exp_date <= max_date:
                valid_exps.append(exp_str)
                
        for exp in valid_exps:
            try:
                opt_chain = stock.option_chain(exp)
                puts = opt_chain.puts
            except:
                continue

            # Filter for OTM Puts
            otm_puts = puts[puts['strike'] < current_price].copy()
            
            best_roi_for_exp = None

            for _, row in otm_puts.iterrows():
                strike = row['strike']
                bid = row['bid']
                
                if bid < 0.05: continue
                
                # Safety: Don't go too deep OTM (>20%)
                if (current_price - strike) / current_price > 0.20: continue

                # ROI Math
                capital_req = strike * 100
                premium = bid * 100
                raw_roi = (premium / capital_req) * 100
                
                days_to_exp = (datetime.datetime.strptime(exp, "%Y-%m-%d").date() - today).days
                if days_to_exp == 0: continue
                
                annualized_roi = raw_roi * (365 / days_to_exp)
                
                if annualized_roi >= MIN_ANNUALIZED_ROI:
                    candidate = {
                        "Symbol": symbol,
                        "Price": round(current_price, 2),
                        "Strike": strike,
                        "Expiration": exp,
                        "DTE": days_to_exp,
                        "Premium": bid,
                        "Raw_ROI": round(raw_roi, 2),
                        "Annualized_ROI": round(annualized_roi, 2)
                    }
                    
                    # Find best ROI for this specific expiration
                    if best_roi_for_exp is None or candidate['Annualized_ROI'] > best_roi_for_exp['Annualized_ROI']:
                        best_roi_for_exp = candidate
            
            # If we found a winner for this expiration, add it to the global weekly bucket
            if best_roi_for_exp:
                # Use Expiration Date as the key
                if exp not in weeks_data:
                    weeks_data[exp] = []
                weeks_data[exp].append(best_roi_for_exp)

    except Exception:
        pass

def generate_tabbed_html(weeks_data):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Sort expirations by date
    sorted_exps = sorted(weeks_data.keys())
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Freedom Income Options - Weekly Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ background-color: #f4f6f9; font-family: 'Segoe UI', sans-serif; }}
            .navbar {{ background: #0d6efd; }}
            .nav-tabs .nav-link.active {{ background-color: #fff; border-color: #dee2e6 #dee2e6 #fff; color: #000; font-weight: bold; border-top: 3px solid #ffc107; }}
            .nav-tabs .nav-link {{ color: #495057; }}
            .badge-roi {{ background-color: #198754; color: white; font-size: 0.9em; }}
            .premium-txt {{ color: #0d6efd; font-weight: 600; }}
        </style>
    </head>
    <body>
        <nav class="navbar navbar-dark mb-4">
            <div class="container">
                <span class="navbar-brand mb-0 h1">Freedom Income Options | Growth Edition</span>
                <span class="text-white small">Updated: {timestamp} EST</span>
            </div>
        </nav>

        <div class="container">
            <h4 class="mb-3">High Premium Puts by Expiration</h4>
            
            <ul class="nav nav-tabs" id="myTab" role="tablist">
    """
    
    # Generate Tab Headers
    for i, exp in enumerate(sorted_exps):
        active_class = "active" if i == 0 else ""
        html += f"""
                <li class="nav-item" role="presentation">
                    <button class="nav-link {active_class}" id="tab-{i}" data-bs-toggle="tab" data-bs-target="#content-{i}" type="button" role="tab">
                        {exp}
                    </button>
                </li>
        """

    html += """
            </ul>
            
            <div class="tab-content bg-white border border-top-0 p-3 shadow-sm rounded-bottom" id="myTabContent">
    """

    # Generate Tab Panes (Tables)
    for i, exp in enumerate(sorted_exps):
        active_class = "show active" if i == 0 else ""
        rows = weeks_data[exp]
        
        # Sort rows by Annualized ROI (Highest first)
        rows = sorted(rows, key=lambda x: x['Annualized_ROI'], reverse=True)
        
        html += f"""
                <div class="tab-pane fade {active_class}" id="content-{i}" role="tabpanel">
                    <div class="table-responsive">
                        <table class="table table-hover align-middle">
                            <thead class="table-light">
                                <tr>
                                    <th>Ticker</th>
                                    <th>Price</th>
                                    <th>Strike</th>
                                    <th>Premium (Bid)</th>
                                    <th>DTE</th>
                                    <th>Ann. ROI</th>
                                </tr>
                            </thead>
                            <tbody>
        """
        
        for row in rows:
            html += f"""
                                <tr>
                                    <td><strong>{row['Symbol']}</strong></td>
                                    <td>${row['Price']}</td>
                                    <td>${row['Strike']}</td>
                                    <td class="premium-txt">${row['Premium']}</td>
                                    <td>{row['DTE']}d</td>
                                    <td><span class="badge badge-roi">{row['Annualized_ROI']}%</span></td>
                                </tr>
            """
            
        html += """
                            </tbody>
                        </table>
                    </div>
                </div>
        """

    html += """
            </div>
            <div class="mt-3 text-muted small">
                <strong>Filters:</strong> Price > $10 | Vol > 1M | Price > SMA200 | EPS Growth (QoQ) > 0%.<br>
                Disclaimer: For educational purposes only.
            </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """
    return html

def main():
    # 1. Get Candidates
    tickers = get_finviz_candidates()
    if not tickers: return

    # Limit scan for speed (Github Actions has a timeout, scanning 200+ stocks deeply takes time)
    # We will scan the first 80 candidates.
    scan_list = tickers[:80]
    print(f"🔬 Scanning {len(scan_list)} tickers for 8-week expirations...")
    
    # Dictionary to hold data: { "2023-10-27": [ {...}, {...} ], "2023-11-03": ... }
    weeks_data = {}
    
    for i, ticker in enumerate(scan_list):
        analyze_options_for_weeks(ticker, weeks_data)
        if (i+1) % 10 == 0: print(f"   Processed {i+1} tickers...")
        time.sleep(1) # Polite delay

    if weeks_data:
        html = generate_tabbed_html(weeks_data)
        with open("index.html", "w") as f:
            f.write(html)
        print("✅ Dashboard Generated with Tabs.")
    else:
        print("⚠️ No results found.")

if __name__ == "__main__":
    main()
