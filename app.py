from flask import Flask, request, send_file, render_template_string
import yfinance as yf
import pandas as pd
import io
import datetime

app = Flask(__name__)

HTML_FORM = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Volume Breakout Strategy</title>
</head>
<body>
  <h1>Volume Breakout Strategy Tester</h1>
  <form method="POST" action="/generate_report">
    <label for="ticker">Ticker Symbol (e.g. AAPL):</label><br>
    <input type="text" id="ticker" name="ticker" value="AAPL"><br><br>

    <label for="start_date">Start Date (YYYY-MM-DD):</label><br>
    <input type="text" id="start_date" name="start_date" value="2020-01-01"><br><br>

    <label for="end_date">End Date (YYYY-MM-DD):</label><br>
    <input type="text" id="end_date" name="end_date" value="2021-01-01"><br><br>

    <label for="volume_threshold">Volume Threshold (%):</label><br>
    <input type="number" id="volume_threshold" name="volume_threshold" value="200"><br><br>

    <label for="daily_change_threshold">Daily Change Threshold (%):</label><br>
    <input type="number" id="daily_change_threshold" name="daily_change_threshold" value="2"><br><br>

    <label for="holding_period">Holding Period (Days):</label><br>
    <input type="number" id="holding_period" name="holding_period" value="10"><br><br>

    <input type="submit" value="Generate Report">
  </form>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML_FORM)

@app.route("/generate_report", methods=["POST"])
def generate_report():
    # Extract form data
    ticker = request.form.get("ticker", "AAPL").strip()
    start_date = request.form.get("start_date", "2020-01-01").strip()
    end_date = request.form.get("end_date", "2021-01-01").strip()
    volume_threshold = float(request.form.get("volume_threshold", "200"))
    daily_change_threshold = float(request.form.get("daily_change_threshold", "2"))
    holding_period = int(request.form.get("holding_period", "10"))

    # Validate and parse dates
    try:
        start_date_parsed = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        end_date_parsed = datetime.datetime.strptime(end_date, "%Y-%m-%d")
        if end_date_parsed <= start_date_parsed:
            return "Error: End date must be after start date."
    except ValueError:
        return "Error: Invalid date format. Please use YYYY-MM-DD."

    # Download data using yfinance
    df = yf.download(ticker, start=start_date, end=end_date)
    if df.empty:
        return f"No data found for {ticker} in the given date range."

    # Print columns for debugging
    print("DF columns before flatten:", df.columns)
    print(df.head())

    # If columns are multi-index, flatten them
    if isinstance(df.columns, pd.MultiIndex):
        # Flatten the multi-index columns
        df.columns = ['_'.join(col).strip() if isinstance(col, tuple) else col for col in df.columns]
        print("DF columns after flatten:", df.columns)

    # Check if 'Close' column exists
    close_col_candidates = [c for c in df.columns if 'Close' in c]
    if len(close_col_candidates) == 0:
        return "No 'Close' column found in the data. Columns are: " + str(df.columns)
    # Assume the first close-like column is our Close
    close_col = close_col_candidates[0]

    # Ensure data is sorted by date
    df.sort_index(inplace=True)

    # Compute 20-day rolling avg volume
    # Find a volume-like column
    volume_col_candidates = [c for c in df.columns if 'Volume' in c]
    if len(volume_col_candidates) == 0:
        return "No 'Volume' column found in data. Columns: " + str(df.columns)
    volume_col = volume_col_candidates[0]

    df['20d_avg_volume'] = df[volume_col].rolling(20).mean().shift(1)

    # Create Prev_Close using the close column identified
    df['Prev_Close'] = df[close_col].shift(1)

    # Another debugging print
    print("Check types:")
    print("Close column type:", type(df[close_col]))
    print("Prev_Close column type:", type(df['Prev_Close']))

    # Now calculate Daily_Change_Pct as a Series
    df['Daily_Change_Pct'] = ((df[close_col] / df['Prev_Close']) - 1) * 100

    # Volume breakout condition
    df['Volume_Breakout'] = df[volume_col] > (volume_threshold / 100.0) * df['20d_avg_volume']

    # Price breakout condition
    df['Price_Breakout'] = df['Daily_Change_Pct'] > daily_change_threshold

    # Combined breakout condition
    df['Breakout'] = df['Volume_Breakout'] & df['Price_Breakout']

    signals = []
    for i in range(len(df)):
        if df['Breakout'].iloc[i]:
            if i + holding_period < len(df):
                buy_date = df.index[i]
                exit_date = df.index[i + holding_period]
                buy_price = df[close_col].iloc[i]
                sell_price = df[close_col].iloc[i + holding_period]
                ret = (sell_price / buy_price - 1) * 100
                signals.append({
                    'Breakout_Date': buy_date.strftime('%Y-%m-%d'),
                    'Buy_Price': buy_price,
                    'Exit_Date': exit_date.strftime('%Y-%m-%d'),
                    'Sell_Price': sell_price,
                    'Holding_Period_Days': holding_period,
                    'Return_%': ret
                })

    if not signals:
        return "No breakout signals found for the given criteria."

    results_df = pd.DataFrame(signals)

    # Convert to CSV for download
    csv_buffer = io.StringIO()
    results_df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    return send_file(
        io.BytesIO(csv_buffer.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='breakout_results.csv'
    )

if __name__ == "__main__":
    app.run(debug=True)
