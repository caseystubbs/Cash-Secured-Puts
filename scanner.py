import pandas as pd
import yfinance as yf
import datetime
import time
import numpy as np
from finvizfinance.screener.overview import Overview

# --- CONFIGURATION ---
MIN_PRICE = 10.0
MIN_VOLUME_STR = 'Over 1M'
MAX_WEEKS = 8         # Look up to 8 weeks out
MIN_ANN_ROI = 15.0    # Minimum Annualized ROI to display
MIN_PREMIUM = 0.15    # Minimum premium ($15 per contract) to filter out garbage
RSI_PERIOD = 14       # Days for RSI calculation

def get_finviz_candidates():
    """
    Fetches growth candidates from Finviz.
    """
    print("⏳ Contacting Finviz for candidates...")
    
    filters_dict = {
        'Option/Short': 'Optionable',
        'Average Volume': MIN_VOLUME_STR,
        'Price': 'Over $10',
        '200-Day Simple Moving Average': 'Price above SMA200', # Uptrend
        'EPS growthqtr over qtr': 'Positive (>0%)',           # Growth
        'RSI (14)': 'Not Overbought (<60)'                    # Avoid buying at the very top
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

def calculate_rsi(series, period=14):
    """
    Manual RSI calculation to avoid heavy dependencies like pandas-ta.
    """
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)

    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def analyze_stock(symbol, weeks_data):
    """
    Analyzes a single stock for Cash Secured Put opportunities.
    """
    try:
        stock = yf.Ticker(symbol)
        # Fetch 3 months of history for RSI calculation
        hist = stock.history(period='3mo')
        
        if hist.empty: return

        current_price = hist['Close'].iloc[-1]
        
        # Calculate RSI
        if len(hist) > RSI_PERIOD:
            hist['RSI'] = calculate_rsi(hist['Close'], RSI_PERIOD)
            current_rsi = round(hist['RSI'].iloc[-1], 2)
        else:
            current_rsi = 50.0 # Neutral default if not enough data

        expirations = stock.options
        if not expirations: return
        
        today = datetime.date.today()
        max_date = today + datetime.timedelta(weeks=MAX_WEEKS)
        
        # Filter expirations to next 8 weeks
        valid_exps = [e for e in expirations if today < datetime.datetime.strptime(e, "%Y-%m-%d").date() <= max_date]

        for exp in valid_exps:
            try:
                opt_chain = stock.option_chain(exp)
                puts = opt_chain.puts
            except:
                continue

            # Filter: Out of the Money AND Bid > Minimum
            puts = puts[(puts['strike'] < current_price) & (puts['bid'] >= MIN_PREMIUM)]
            
            if puts.empty: continue

            # Find the "Sweet Spot" option for this expiration
            # Strategy: Closest strike to price that is still OTM (Aggressive) 
            # OR Strike with ~0.30 Delta proxy (approx 1 standard deviation)
            
            best_option = None
            best_score = -1

            for _, row in puts.iterrows():
                strike = row['strike']
                bid = row['bid']
                
                # Cushion: How much can it drop?
                cushion_pct = (current_price - strike) / current_price
                
                # Skip if too deep OTM (Safety > 20% downside is usually too low premium)
                # Skip if too close (Risk < 1% cushion is dangerous)
                if cushion_pct > 0.20 or cushion_pct < 0.01: continue

                capital = strike * 100
                premium = bid * 100
                raw_roi = (premium / capital) * 100
                
                dte = (datetime.datetime.strptime(exp, "%Y-%m-%d").date() - today).days
                if dte == 0: continue
                
                ann_roi = raw_roi * (365 / dte)

                if ann_roi >= MIN_ANN_ROI:
                    # Score = Combination of ROI and Safety (Cushion)
                    # We slightly favor cushion for "Cash Secured" safety
                    score = ann_roi + (cushion_pct * 100) 

                    if score > best_score:
                        best_score = score
                        best_option = {
                            "Symbol": symbol,
                            "Price": current_price,
                            "RSI": current_rsi,
                            "Strike": strike,
                            "Premium": bid,
                            "DTE": dte,
                            "Cushion": round(cushion_pct * 100, 2),
                            "Ann_ROI": round(ann_roi, 2),
                            "Expiration": exp
                        }
            
            if best_option:
                if exp not in weeks_data:
                    weeks_data[exp] = []
                weeks_data[exp].append(best_option)

    except Exception as e:
        # print(f"Error on {symbol}: {e}") # Uncomment for debugging
        pass

def generate_dashboard_html(weeks_data):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    sorted_exps = sorted(weeks_data.keys())
    
    # Calculate Summary Stats
    total_ops = sum(len(v) for v in weeks_data.values())
    if total_ops > 0:
        all_ops = [item for sublist in weeks_data.values() for item in sublist]
        avg_roi = round(sum(op['Ann_ROI'] for op in all_ops) / len(all_ops), 2)
        top_pick = max(all_ops, key=lambda x: x['Ann_ROI'])
        top_pick_str = f"{top_pick['Symbol']} ${top_pick['Strike']} Put"
    else:
        avg_roi = 0
        top_pick_str = "N/A"

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Freedom Income Options | Scanner</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link href="https://cdn.datatables.net/1.13.4/css/dataTables.bootstrap5.min.css" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>
            :root {{ --primary-color: #0d6efd; --secondary-bg: #f8f9fa; }}
            body {{ background-color: #f0f2f5; font-family: 'Segoe UI', Roboto, sans-serif; }}
            .navbar {{ background: linear-gradient(135deg, #0d6efd, #0043a8); box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .card-stat {{ border: none; border-radius: 12px; transition: transform 0.2s; }}
            .card-stat:hover {{ transform: translateY(-3px); }}
            .badge-roi-high {{ background-color: #198754; }}
            .badge-roi-med {{ background-color: #ffc107; color: #000; }}
            .badge-safe {{ background-color: #0dcaf0; color: #000; }}
            .table-container {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            .nav-pills .nav-link {{ border-radius: 8px; margin-right: 5px; color: #495057; }}
            .nav-pills .nav-link.active {{ background-color: var(--primary-color); color: white; }}
            .rsi-low {{ color: #dc3545; font-weight: bold; }} /* Oversold - Good for Puts */
            .rsi-high {{ color: #198754; }}
        </style>
    </head>
    <body>
        <nav class="navbar navbar-dark mb-4 py-3">
            <div class="container">
                <span class="navbar-brand mb-0 h1"><i class="fas fa-chart-line me-2"></i>Freedom Income Options</span>
                <span class="text-white-50 small">Updated: {timestamp} EST</span>
            </div>
        </nav>

        <div class="container">
            <div class="row mb-4 g-3">
                <div class="col-md-4">
                    <div class="card card-stat bg-white p-3 shadow-sm h-100">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <h6 class="text-muted text-uppercase small mb-1">Total Opportunities</h6>
                                <h2 class="mb-0">{total_ops}</h2>
                            </div>
                            <div class="bg-primary bg-opacity-10 p-3 rounded-circle text-primary">
                                <i class="fas fa-search fa-lg"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card card-stat bg-white p-3 shadow-sm h-100">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <h6 class="text-muted text-uppercase small mb-1">Avg Annualized ROI</h6>
                                <h2 class="mb-0 text-success">{avg_roi}%</h2>
                            </div>
                            <div class="bg-success bg-opacity-10 p-3 rounded-circle text-success">
                                <i class="fas fa-percentage fa-lg"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card card-stat bg-white p-3 shadow-sm h-100">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <h6 class="text-muted text-uppercase small mb-1">Top Pick (ROI)</h6>
                                <h5 class="mb-0 text-truncate" style="max-width: 200px;">{top_pick_str}</h5>
                            </div>
                            <div class="bg-warning bg-opacity-10 p-3 rounded-circle text-warning">
                                <i class="fas fa-crown fa-lg"></i>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <ul class="nav nav-pills mb-3" id="pills-tab" role="tablist">
    """

    for i, exp in enumerate(sorted_exps):
        active = "active" if i == 0 else ""
        html += f"""
                <li class="nav-item" role="presentation">
                    <button class="nav-link {active}" id="pills-{i}-tab" data-bs-toggle="pill" data-bs-target="#pills-{i}" type="button" role="tab">{exp}</button>
                </li>
        """

    html += """
            </ul>
            
            <div class="tab-content" id="pills-tabContent">
    """

    for i, exp in enumerate(sorted_exps):
        active = "show active" if i == 0 else ""
        rows = weeks_data[exp]
        
        html += f"""
                <div class="tab-pane fade {active}" id="pills-{i}" role="tabpanel">
                    <div class="table-container">
                        <table class="table table-hover align-middle datatable" style="width:100%">
                            <thead class="table-light">
                                <tr>
                                    <th>Ticker</th>
                                    <th>Price</th>
                                    <th>RSI (14)</th>
                                    <th>Strike</th>
                                    <th>Premium</th>
                                    <th>Downside Safety</th>
                                    <th>Ann. ROI</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody>
        """
        
        for row in rows:
            # ROI Badge Logic
            roi_badge = "badge-roi-high" if row['Ann_ROI'] > 25 else "badge-roi-med"
            
            # RSI Styling
            rsi_class = "rsi-low" if row['RSI'] < 40 else ""
            rsi_icon = '<i class="fas fa-arrow-down small"></i>' if row['RSI'] < 40 else ''
            
            html += f"""
                                <tr>
                                    <td><strong>{row['Symbol']}</strong></td>
                                    <td>${row['Price']:.2f}</td>
                                    <td class="{rsi_class}">{row['RSI']} {rsi_icon}</td>
                                    <td>${row['Strike']:.1f}</td>
                                    <td class="text-primary fw-bold">${row['Premium']:.2f}</td>
                                    <td>{row['Cushion']}%</td>
                                    <td><span class="badge {roi_badge}">{row['Ann_ROI']}%</span></td>
                                    <td><a href="https://finance.yahoo.com/quote/{row['Symbol']}" target="_blank" class="btn btn-sm btn-outline-secondary">View</a></td>
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
            
            <div class="mt-4 text-center text-muted small">
                <p>Scanner Criteria: Price > $10 | Vol > 1M | SMA200 Uptrend | Positive Earnings | Sorted by ROI + Safety Score.</p>
                <p>Disclaimer: This tool is for educational purposes only. Options trading involves significant risk.</p>
            </div>
        </div>

        <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.4/js/dataTables.bootstrap5.min.js"></script>
        <script>
            $(document).ready(function () {
                $('.datatable').DataTable({
                    "order": [[ 6, "desc" ]], // Default sort by Annualized ROI
                    "pageLength": 25,
                    "language": {
                        "search": "Filter Tickers:"
                    }
                });
            });
        </script>
    </body>
    </html>
    """
    return html

def main():
    # 1. Get Candidates
    tickers = get_finviz_candidates()
    if not tickers: return

    # Limit for demo/speed; remove slice [0:100] for full scan
    scan_list = tickers[:100] 
    print(f"🔬 Scanning {len(scan_list)} tickers for opportunities...")
    
    weeks_data = {}
    
    for i, ticker in enumerate(scan_list):
        analyze_stock(ticker, weeks_data)
        if (i+1) % 10 == 0: 
            print(f"   Processed {i+1}/{len(scan_list)}...")
        time.sleep(0.5) 

    if weeks_data:
        html = generate_dashboard_html(weeks_data)
        with open("index.html", "w", encoding='utf-8') as f:
            f.write(html)
        print("✅ Dashboard Generated: index.html")
    else:
        print("⚠️ No results found.")

if __name__ == "__main__":
    main()
