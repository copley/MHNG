#!/usr/bin/env python3
"""
Illustration: Combining EIA weekly storage data, a free consensus estimate from TradingEconomics,
and NOAA weather forecasts, then printing a fundamental NG "surprise" analysis.
"""

import os
import requests
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timedelta

###############################################################################
# LOAD ENVIRONMENT VARIABLES
###############################################################################
load_dotenv()
EIA_API_KEY = os.getenv("EIA_API_KEY")
TE_CLIENT_KEY = os.getenv("TE_API_CLIENT_KEY")
TE_CLIENT_SECRET = os.getenv("TE_API_CLIENT_SECRET")
NOAA_TOKEN = os.getenv("NOAA_TOKEN")

if not EIA_API_KEY:
    raise ValueError("EIA_API_KEY is missing. Please add to your .env file.")

###############################################################################
# 1. FETCH WEEKLY STORAGE DATA (EIA v2)
###############################################################################

def fetch_eia_storage(eia_key, length=2):
    """
    Pulls the 2 latest weekly storage readings (current vs. previous) from EIA v2.
    Reference docs: https://www.eia.gov/opendata/browser/natural-gas
    """
    base_url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
    params = {
        "api_key": eia_key,
        "frequency": "weekly",
        "data[0]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "offset": 0,
        "length": length
    }
    resp = requests.get(base_url, params=params)
    resp.raise_for_status()
    data = resp.json()
    # Should have something like data['response']['data']
    records = data.get('response', {}).get('data', [])
    return records

###############################################################################
# 2. FETCH CONSENSUS ESTIMATE (TRADINGECONOMICS)
###############################################################################

def fetch_consensus_storage(te_key, te_secret):
    """
    TradingEconomics has an economic calendar with forecasts. 
    We'll attempt to find 'United States Natural Gas Stocks Change' or similar. 
    This can be tricky—check their docs. 
    Example endpoint: /forecast/country/united states/indicator/natural gas storage
      or /calendar/country/united states/indicator/natural gas stocks change
    NOTE: The free plan can be limited. Adjust as needed.
    """
    url = f"https://api.tradingeconomics.com/forecast/country/united states/indicator/natural gas stocks change"
    params = {
        "c": f"{te_key}:{te_secret}"
    }
    resp = requests.get(url, params=params)
    if resp.status_code == 200:
        data = resp.json()
        # We need to parse the result to find the next forecast...
        # The returned data may vary, so let's attempt to parse.
        if data:
            # We'll look for the nearest future date or the last forecast
            # Example structure: data[0]["Forecast"] might hold the forecast injection/withdrawal
            # This is purely example logic:
            for item in data:
                forecast_val = item.get("Forecast")
                date_str = item.get("Date")
                # date_str might be something like "2025-03-20T00:00:00"
                if forecast_val is not None:
                    return float(forecast_val)
    return None

###############################################################################
# 3. FETCH WEATHER FORECAST (NOAA or Another Free Service)
###############################################################################

def fetch_noaa_weather(noaa_token, city="New York", state="NY"):
    """
    Example of pulling a simplified NOAA forecast.
    NOAA's API requires a two-step approach:
       1) get gridpoint from city/state
       2) get forecast from gridpoint
    For brevity, let's just do a direct call to a known lat/lon or skip the city->gridpoint step.
    NOAA docs: https://www.weather.gov/documentation/services-web-api
    """
    # Hardcode lat/lon for NYC, for example.
    lat, lon = 40.7128, -74.0060
    # 1) fetch gridpoint
    points_url = f"https://api.weather.gov/points/{lat},{lon}"
    headers = {"User-Agent": "NGTraderApp/1.0", "Accept": "application/ld+json"}
    if noaa_token:
        headers["token"] = noaa_token  # or "Authorization": f"Bearer {noaa_token}"
    r1 = requests.get(points_url, headers=headers)
    if r1.status_code != 200:
        return None

    grid_data = r1.json()
    forecast_url = grid_data["properties"]["forecast"]
    r2 = requests.get(forecast_url, headers=headers)
    if r2.status_code == 200:
        forecast_data = r2.json()
        # Typically forecast_data['properties']['periods'] is a list
        return forecast_data['properties'].get('periods', [])
    return None

###############################################################################
# 4. (OPTIONAL) SIMPLE TECHNICAL CHECK — NEED PRICE DATA
###############################################################################
def fetch_ng_price():
    """
    For real trading, you'd use a paid data source (like CME data via a broker).
    As a placeholder, let's pretend we have a free daily Henry Hub price from EIA v2 
    in backward-compat mode. (We won't do intraday.)
    
    EIA v2 backward-compat for Henry Hub daily spot:
    https://api.eia.gov/v2/seriesid/NG.RNGWHHD.D?api_key=...
    """
    url = f"https://api.eia.gov/v2/seriesid/NG.RNGWHHD.D?api_key={EIA_API_KEY}"
    resp = requests.get(url)
    if resp.status_code == 200:
        data = resp.json()
        records = data.get('response', {}).get('data', [])
        # Each record might have { "period": "2025-03-17", "value": 4.15, ... }
        df = pd.DataFrame(records)
        if not df.empty:
            # sort by date
            df['period'] = pd.to_datetime(df['period'])
            df.sort_values('period', inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df
    return pd.DataFrame()

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = -1 * delta.clip(upper=0).rolling(period).mean()
    rs = up / down
    rsi = 100 - (100/(1+rs))
    return rsi

###############################################################################
# MAIN SCRIPT: COMBINE EVERYTHING
###############################################################################

def main():
    # 1) Get the 2 most recent EIA weekly storage records
    storage_records = fetch_eia_storage(EIA_API_KEY, length=2)
    if len(storage_records) < 2:
        print("[ERROR] Not enough weekly storage data returned from EIA.")
        return
    
    # Our record structure might have:
    # e.g., storage_records[0] -> {'period': '2025-03-14', 'value': 1900}
    current_record = storage_records[0]
    prev_record = storage_records[1]

    current_storage = float(current_record['value'])
    current_date = current_record['period']
    prev_storage = float(prev_record['value'])
    prev_date = prev_record['period']
    weekly_change = current_storage - prev_storage  # injection(+) or withdrawal(-)

    # 2) Attempt to fetch consensus from TradingEconomics (free tier is limited!)
    consensus_est = fetch_consensus_storage(TE_CLIENT_KEY, TE_CLIENT_SECRET)
    if consensus_est is None:
        print("[WARNING] No consensus estimate found (TradingEconomics free tier might be limited).")
        consensus_est = 0.0  # fallback or skip
    storage_surprise = weekly_change - consensus_est

    # 3) Basic NOAA forecast fetch (for one location)
    forecast_data = fetch_noaa_weather(NOAA_TOKEN, city="New York", state="NY")
    if forecast_data is None:
        print("[WARNING] Could not fetch NOAA weather forecast.")
        forecast_data = []
    # We might just print the next couple of days
    upcoming_forecast = forecast_data[:3]

    # 4) Optional: fetch a daily Henry Hub series from EIA v2
    ng_prices_df = fetch_ng_price()
    recent_price = None
    rsi_14_val = None
    if not ng_prices_df.empty:
        recent_price = ng_prices_df['value'].iloc[-1]
        ng_prices_df['rsi_14'] = compute_rsi(ng_prices_df['value'], 14)
        rsi_14_val = ng_prices_df['rsi_14'].iloc[-1]

    # 5) Print a combined fundamental analysis
    print("================================================================")
    print(f"Natural Gas Weekly Storage (EIA) as of {current_date}:")
    print(f"  Current storage: {current_storage:.1f} Bcf")
    print(f"  Previous storage: {prev_storage:.1f} Bcf (as of {prev_date})")
    print(f"  Weekly Change: {weekly_change:+.1f} Bcf")

    if consensus_est != 0.0:
        print(f"  Consensus Estimate: {consensus_est:+.1f} Bcf")
        print(f"  Surprise (Actual - Consensus): {storage_surprise:+.1f} Bcf")
    else:
        print("  (No consensus estimate available)")

    print("================================================================")
    print("Weather Outlook (NYC) - Next 3 Periods from NOAA:")
    for f in upcoming_forecast:
        name = f.get("name")
        detail = f.get("detailedForecast", "")
        print(f"  {name}: {detail}")

    if recent_price:
        print("================================================================")
        print(f"Recent Henry Hub Spot Price: ${recent_price:.2f}")
        print(f"14-day RSI: {rsi_14_val:.2f}" if rsi_14_val else "RSI not available.")
    else:
        print("[INFO] No recent Henry Hub price data found from EIA v2 request.")

    # 6) A super-basic “trade idea”:
    #    If (storage surprise < 0) => less injection / bigger withdrawal => bullish if big
    #    If RSI < 30 => oversold
    # This is obviously simplistic.
    trade_idea = ""
    if storage_surprise < -10:
        trade_idea = "Bullish surprise on storage (big draw vs. consensus). Potential upside."
        if rsi_14_val and rsi_14_val < 30:
            trade_idea += " RSI < 30 => oversold, further supporting a bounce."
    elif storage_surprise > 10:
        trade_idea = "Bearish surprise (big injection vs. consensus). Potential downside."
        if rsi_14_val and rsi_14_val > 70:
            trade_idea += " RSI > 70 => overbought, could amplify sell-off."
    else:
        trade_idea = "Storage near consensus. Watch weather and short-term price signals."

    print("================================================================")
    print("Simple Trade Interpretation:")
    print(f"  {trade_idea}")
    print("================================================================")


if __name__ == "__main__":
    main()
