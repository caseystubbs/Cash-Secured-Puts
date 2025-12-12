import pandas as pd
import yfinance as yf
import datetime
import time
from finvizfinance.screener.overview import Overview

# --- CONFIGURATION ---
# Freedom Income Options Criteria
MIN_PRICE = 10.0
MIN_VOLUME_STR = 'Over 1M'
MIN_DTE = 20         # Minimum days to expiration
MAX_DTE = 45         # Maximum days to expiration
MIN_ANNUALIZED_ROI = 15.0 # Minimum Annualized Return to show

def get_finviz_candidates():
    """
    Fetches stocks from Finviz that match the "Freedom" criteria:
    - Optionable, Price > $10, Avg Vol > 1M, Price > SMA200 (Uptrend)
    """
    print("⏳ Contacting Finviz for market scan...")

    filters_dict = {
        'Option/Short': 'Optionable',
        'Average Volume': MIN_VOLUME_STR,
        'Price': 'Over $10',
        '200-Day Simple Moving Average': 'Price above SMA200'
    }

    try:
        foverview = Overview()
        foverview.set_filter(filters_dict=filters_dict)
        df_finviz = foverview.screener_view(verbose=0)
        candidates = df_finviz['Ticker'].tolist()
        print(f"✅ Found {len(candidates)} candidates.")
        return candidates
    except Exception as e:
        print(f"❌ Finviz Error: {e}")
        return []

def analyze_options(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period='1d')
        if hist.empty: return None
        current_price = hist['Close'].iloc[-1]

        # Get Expirations
        expirations = stock.options
        if not expirations: return None

        valid_exps = []
        today = datetime.date.today()

        for exp_date_str in expirations:
            try:
                exp_date = datetime.datetime.strptime(exp_date_str, "%Y-%m-%d").date()
                days_to_exp = (exp_date - today).days
                if MIN_DTE <= days_to_exp <= MAX_DTE:
                    valid_exps.append(exp_date_str)
            except:
                continue

        best_option = None

        for exp in valid_exps:
            try:
                # Download Put Chain
                opt_chain = stock.option_chain(exp)
                puts = opt_chain.puts
            except:
                continue

            # Filter: Strike < Current Price (OTM)
            otm_puts = puts[puts['strike'] < current_price].copy()

            for _, row in otm_puts.iterrows():
                strike = row['strike']
                bid = row['bid']

                if bid < 0.05: continue 

                # Safety Filter: Skip if > 20% OTM (Too far out)
                distance_otm = (current_price - strike) / current_price
                if distance_otm > 0.20: continue 

                # ROI Math
                premium = bid * 100
                capital_req = strike * 100
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
                        "Annualized_ROI": round(annualized_roi, 2),
                        "Distance_OTM": round(distance_otm * 100, 1)
                    }

                    if best_option is None or candidate['Annualized_ROI'] > best_option['Annualized_ROI']:
                        best_option = candidate

        return best_option

    except Exception:
        return None

def generate_html(df_results):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Freedom Income Options Scanner</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ background: #f4f6f9; font-family: sans-serif; }}
            .navbar {{ background: #0d6efd; }}
            .badge-roi {{ background: #198754; color: white; }}
        </style>
    </head>
    <body>
        <nav class="navbar navbar-dark mb-4">
            <div class="container">
                <span class="navbar-brand mb-0 h1">Freedom Income Options Tool</span>
            </div>
        </nav>
        <div class="container">
            <div class="card shadow-sm">
                <div class="card-header bg-white">
                    <h5 class="mb-0">Daily CSP Candidates</h5>
                    <small class="text-muted">Updated: {timestamp} EST</small>
                </div>
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Ticker</th>
                                <th>Price</th>
                                <th>Strike</th>
                                <th>Exp (DTE)</th>
                                <th>Premium</th>
                                <th>Ann. ROI</th>
                            </tr>
                        </thead>
                        <tbody>
    """
    for _, row in df_results.iterrows():
        html += f"""
        <tr>
            <td><strong>{row['Symbol']}</strong></td>
            <td>${row['Price']}</td>
            <td>${row['Strike']}</td>
            <td>{row['Expiration']} ({row['DTE']}d)</td>
            <td>${row['Premium']}</td>
            <td><span class="badge badge-roi">{row['Annualized_ROI']}%</span></td>
        </tr>
        """
    html += """
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html

def main():
    tickers = get_finviz_candidates()
    if not tickers: return

    # Limit to first 60 tickers to keep runtime short for free GitHub Actions
    # You can increase this number if needed.
    scan_list = tickers[:60] 
    print(f"🔬 Scanning {len(scan_list)} tickers...")

    results = []
    for ticker in scan_list:
        res = analyze_options(ticker)
        if res: results.append(res)
        time.sleep(1) # Polite delay to avoid API bans

    if results:
        df = pd.DataFrame(results).sort_values(by='Annualized_ROI', ascending=False).head(20)
        with open("index.html", "w") as f:
            f.write(generate_html(df))
        print("✅ HTML Generated.")
    else:
        print("⚠️ No results found.")

if __name__ == "__main__":
    main()
