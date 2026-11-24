# Nifty Global-Markets Agent

Reads international markets at the right moments of the Indian trading day, measures how
Nifty and each Nifty-50 stock respond to them, and produces ranked **buy and sell candidates**
for **intraday**, **swing (3–15 days)** and **long term (1 year+)**, each with entry, stop-loss,
targets and a position size.

## Web app
`streamlit run app.py` opens the app at http://localhost:8501. To get your own online link and the
daily schedule, follow **DEPLOY.md** (free: GitHub + Streamlit Community Cloud).

## Command line
```bash
pip install -r requirements.txt
python agent.py --demo --print        # offline test with synthetic data
python agent.py --print               # live run (session picked from IST clock)
python agent.py --schedule            # runs itself Mon–Fri at the times below
```
Add your own stocks permanently in `EXTRA_STOCKS` in `config.py` (Ambuja Cements is there
already), or for one run: `python agent.py --add AMBUJACEM ACC SHREECEM`.

Options: `--session pre_open|intraday|closing|post_close`, `--fundamentals` (adds PE, ROE,
debt, EPS growth to long-term ranking), `--llm` (plain-English brief by Claude, needs
`ANTHROPIC_API_KEY`), `--telegram` (needs `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`),
`--universe ind_nifty50list.csv` (official list from niftyindices.com; the built-in list should be
checked after each index rebalance).

Each run saves to `reports/`:
- `<date>_<time>_<session>.xlsx`, one tab each for **Nifty 50 Prices**, **Global Markets**, Intraday,
  Swing, Long Term, Nifty vs Global and Sensitivity (green/red % changes, frozen headers)
- `.md`, the readable report: market read, picks for each horizon and the Nifty 50 price board
- `.json`, a short summary (used for Telegram and the AI brief)

Price columns in every table:
| Column | Meaning |
|---|---|
| LTP | Last traded price (live 5-min bar during market hours, else latest close) |
| LCP | Last closing price, i.e. yesterday's close |
| Open | Today's opening price |
| Chg % | LTP vs yesterday's close |
| 2D % | LTP vs the close 2 sessions ago |
| 1W % | LTP vs the close 5 sessions ago (one trading week) |

Before 09:15 there is no trade yet today, so LTP and Open show the last session's values.

## Daily timetable (IST)
| Time  | Session    | Global inputs weighted most                         | Output focus |
|-------|------------|-----------------------------------------------------|--------------|
| 08:50 | pre_open   | US close, S&P futures, Nikkei, Hang Seng, crude, ₹  | Gap plan, intraday watchlist, swing |
| 09:35 | intraday   | Asia live, US futures, crude, USD/INR               | Intraday with VWAP + 15-min opening range |
| 11:30 | intraday   | same                                                 | Refreshed intraday list |
| 13:45 | closing    | DAX, FTSE (Europe open), US futures                 | Late-session trades, swing |
| 15:45 | post_close | Europe, US futures, VIX                              | Swing + long-term picks for tomorrow |

## How it works
1. **Global cue**: every market's move is converted to a z-score (move ÷ its 60-day volatility),
   flipped for inverse drivers (crude, USD/INR, dollar index, US yields, VIX), and weighted for
   the time of day → one score from −1 to +1.
2. **Nifty vs. world**: correlation, beta and the share of big global days when Nifty moved the
   same way, over the last 120 sessions. US/Europe are lagged one session, since they close after India.
3. **Stock sensitivity**: each stock's daily return is regressed on the previous US session plus
   its sector's driver (IT→Nasdaq, Energy→crude, Metals→Hang Seng, Pharma→USD/INR, Banks→US 10Y…)
   to project today's expected move.
4. **Scoring** (positive = buy, negative = sell):
   - *Intraday*: global expected move vs ATR, EMA9/21, RSI, prev-day high/low break; once the
     market is open, VWAP, 15-min opening-range breakout and relative volume. Stop 0.5×ATR.
   - *Swing*: EMA20/50/200 alignment, RSI zone, MACD cross, 20-day breakout on volume, pullback
     to EMA20, 20-day strength vs Nifty, global cue and market trend. Stop 1.5×ATR.
   - *Long term*: 12-1 month momentum, 200-DMA trend and slope, low volatility, distance from
     52-week high, plus quality/valuation with `--fundamentals`.
5. **Risk**: size = 1% of capital ÷ (entry − stop); halved when India VIX > 20. Edit `config.py`.

## Before using real money
- Free Yahoo data is ~15 min delayed. For live intraday use a broker API (Zerodha Kite, Upstox,
  Angel One SmartAPI, Dhan): replace `YahooData.intraday` in `data.py`.
- Backtest the rules on 2–3 years of data and paper-trade for a few weeks before trusting them.
- The agent ignores news, results dates, F&O ban lists and NSE holidays. Check those yourself.
- This is a screening tool, not investment advice.
