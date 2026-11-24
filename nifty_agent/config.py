"""Configuration for the Nifty global-markets agent.

Edit this file to change the stock universe, global drivers, session weights,
capital/risk settings and how many picks to show.
"""
import os

# ---------------------------------------------------------------------------
# Stock universe: Nifty 50 (Yahoo Finance tickers -> sector).
# Index composition changes twice a year. To always use the official list,
# download "ind_nifty50list.csv" from niftyindices.com and run with
#   python agent.py --universe ind_nifty50list.csv
# Tickers that fail to download are skipped automatically.
# ---------------------------------------------------------------------------
NIFTY50 = {
    "ADANIENT.NS": "Metals & Mining", "ADANIPORTS.NS": "Services",
    "APOLLOHOSP.NS": "Healthcare", "ASIANPAINT.NS": "Consumer",
    "AXISBANK.NS": "Banks", "BAJAJ-AUTO.NS": "Auto",
    "BAJFINANCE.NS": "Financials", "BAJAJFINSV.NS": "Financials",
    "BEL.NS": "Capital Goods", "BHARTIARTL.NS": "Telecom",
    "CIPLA.NS": "Pharma", "COALINDIA.NS": "Energy",
    "DRREDDY.NS": "Pharma", "EICHERMOT.NS": "Auto",
    "ETERNAL.NS": "Consumer Services", "GRASIM.NS": "Cement",
    "HCLTECH.NS": "IT", "HDFCBANK.NS": "Banks",
    "HDFCLIFE.NS": "Financials", "HINDALCO.NS": "Metals & Mining",
    "HINDUNILVR.NS": "FMCG", "ICICIBANK.NS": "Banks",
    "INDIGO.NS": "Services", "INFY.NS": "IT",
    "ITC.NS": "FMCG", "JIOFIN.NS": "Financials",
    "JSWSTEEL.NS": "Metals & Mining", "KOTAKBANK.NS": "Banks",
    "LT.NS": "Capital Goods", "M&M.NS": "Auto",
    "MARUTI.NS": "Auto", "MAXHEALTH.NS": "Healthcare",
    "NESTLEIND.NS": "FMCG", "NTPC.NS": "Power",
    "ONGC.NS": "Energy", "POWERGRID.NS": "Power",
    "RELIANCE.NS": "Energy", "SBILIFE.NS": "Financials",
    "SBIN.NS": "Banks", "SHRIRAMFIN.NS": "Financials",
    "SUNPHARMA.NS": "Pharma", "TCS.NS": "IT",
    "TATACONSUM.NS": "FMCG", "TMPV.NS": "Auto",
    "TATASTEEL.NS": "Metals & Mining", "TECHM.NS": "IT",
    "TITAN.NS": "Consumer", "TRENT.NS": "Consumer",
    "ULTRACEMCO.NS": "Cement", "BSE.NS": "Financials",  # BSE replaced Wipro on 30 Sep 2026
}

# ---------------------------------------------------------------------------
# Your own extra stocks, analysed alongside the Nifty 50 (any NSE stock: add ".NS").
# You can also add stocks for a single run:  python agent.py --add AMBUJACEM ACC WIPRO
# ---------------------------------------------------------------------------
EXTRA_STOCKS = {
    "AMBUJACEM.NS": "Cement",
}

NIFTY_INDEX = "^NSEI"
INDIA_VIX = "^INDIAVIX"

# ---------------------------------------------------------------------------
# Global drivers. sign = +1 if a rise is good for Indian equities, -1 if bad.
# lagged=True means the market closes before India opens (US, Europe), so
# its *previous* session is what Indian stocks react to.
# ---------------------------------------------------------------------------
GLOBAL = {
    "S&P 500":        {"ticker": "^GSPC",    "sign": +1, "lagged": True},
    "Nasdaq":         {"ticker": "^IXIC",    "sign": +1, "lagged": True},
    "Dow Jones":      {"ticker": "^DJI",     "sign": +1, "lagged": True},
    "S&P fut":        {"ticker": "ES=F",     "sign": +1, "lagged": False},
    "Nasdaq fut":     {"ticker": "NQ=F",     "sign": +1, "lagged": False},
    "Nikkei 225":     {"ticker": "^N225",    "sign": +1, "lagged": False},
    "Hang Seng":      {"ticker": "^HSI",     "sign": +1, "lagged": False},
    "Kospi":          {"ticker": "^KS11",    "sign": +1, "lagged": False},
    "DAX":            {"ticker": "^GDAXI",   "sign": +1, "lagged": True},
    "FTSE 100":       {"ticker": "^FTSE",    "sign": +1, "lagged": True},
    "Brent crude":    {"ticker": "BZ=F",     "sign": -1, "lagged": False},
    "Gold":           {"ticker": "GC=F",     "sign": -1, "lagged": False},
    "USD/INR":        {"ticker": "USDINR=X", "sign": -1, "lagged": False},
    "Dollar index":   {"ticker": "DX-Y.NYB", "sign": -1, "lagged": False},
    "US 10Y yield":   {"ticker": "^TNX",     "sign": -1, "lagged": True},
    "CBOE VIX":       {"ticker": "^VIX",     "sign": -1, "lagged": True},
}

# Which global drivers matter at each point of the Indian (IST) day, and how much.
SESSIONS = {
    # 08:30-09:15 IST: US has closed, Asia has opened, US futures trading.
    "pre_open": {"S&P 500": .20, "Nasdaq": .15, "Dow Jones": .05, "S&P fut": .15,
                 "Nikkei 225": .10, "Hang Seng": .08, "Kospi": .05,
                 "Brent crude": .07, "USD/INR": .07, "CBOE VIX": .05, "US 10Y yield": .03},
    # 09:15-13:30 IST: Asia live, Europe shut, US futures drive mood.
    "intraday": {"Nikkei 225": .15, "Hang Seng": .15, "Kospi": .07, "S&P fut": .20,
                 "Nasdaq fut": .10, "Brent crude": .10, "USD/INR": .13, "Dollar index": .05,
                 "Gold": .05},
    # 13:30-15:30 IST: Europe opens, US futures for the coming night.
    "closing": {"DAX": .18, "FTSE 100": .12, "S&P fut": .22, "Nasdaq fut": .12,
                "Hang Seng": .08, "Brent crude": .10, "USD/INR": .13, "Dollar index": .05},
    # After 15:30 IST: plan next day using Europe + US futures.
    "post_close": {"DAX": .15, "FTSE 100": .10, "S&P fut": .25, "Nasdaq fut": .15,
                   "Brent crude": .10, "USD/INR": .10, "Gold": .05, "CBOE VIX": .10},
}

# Each sector's main external driver (used in the sensitivity regression).
SECTOR_DRIVER = {
    "IT": "Nasdaq", "Energy": "Brent crude", "Metals & Mining": "Hang Seng",
    "Pharma": "USD/INR", "Banks": "US 10Y yield", "Financials": "US 10Y yield",
    "Auto": "Nikkei 225", "Capital Goods": "DAX", "Power": "Brent crude",
    "Cement": "Brent crude", "FMCG": "Dollar index", "Consumer": "Gold",
    "Consumer Services": "Nasdaq", "Healthcare": "USD/INR", "Telecom": "S&P 500",
    "Services": "Brent crude",
}

# Run times (IST) when --schedule is used.
SCHEDULE_IST = {
    "08:50": "pre_open",   # before the open: overnight read + gap plan
    "09:35": "intraday",   # after the 15-min opening range is set
    "11:30": "intraday",
    "13:45": "closing",    # Europe open
    "15:45": "post_close", # swing and long-term picks for tomorrow
}

# ---------------------------------------------------------------------------
# Output & risk settings
# ---------------------------------------------------------------------------
TOP_N_BUY = 10
TOP_N_SELL = 5
CAPITAL_INR = 100_000      # used only to suggest position size
RISK_PER_TRADE_PCT = 1.0   # % of capital risked between entry and stop-loss
MIN_AVG_TURNOVER_CR = 50   # skip stocks with avg daily turnover below this (Rs crore)

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")  # works from any folder
LLM_MODEL = "claude-sonnet-5-5"   # used only with --llm and ANTHROPIC_API_KEY set
