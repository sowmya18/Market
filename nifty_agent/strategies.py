"""Scoring rules for intraday, swing and long-term candidates.

Every score is signed: positive = buy candidate, negative = sell/short candidate.
The reasons behind each score are listed so every pick can be checked by hand.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def _size(entry, stop, mult=1.0):
    risk_amt = config.CAPITAL_INR * config.RISK_PER_TRADE_PCT / 100 * mult
    per_share = abs(entry - stop)
    return int(risk_amt // per_share) if per_share > 0 else 0


def _levels(side, entry, atr, stop_atr, tgt_atr, mult):
    stop = entry - side * stop_atr * atr
    tgt = entry + side * tgt_atr * atr
    tgt2 = entry + side * 2 * tgt_atr * atr
    return round(stop, 2), round(tgt, 2), round(tgt2, 2), _size(entry, stop, mult)


def _liquid(df):
    return df["Turnover"].tail(20).mean() / 1e7 >= config.MIN_AVG_TURNOVER_CR


# --------------------------------------------------------------------------- intraday
def intraday_scores(daily, intraday, sens, gscore, regime, session):
    rows = []
    for t, df in daily.items():
        if len(df) < 60 or not _liquid(df):
            continue
        last = df.iloc[-1]
        atrp = last.ATR / last.Close
        why, s = [], 0.0

        exp = sens["Expected move %"].get(t, 0.0) / 100
        g = float(np.clip(exp / atrp, -2, 2)) if atrp else 0
        s += 1.5 * g
        if abs(g) > 0.3:
            why.append(f"global {'tailwind' if exp > 0 else 'headwind'} {exp*100:+.2f}%")
        s += 0.5 * gscore

        trend = 1 if last.EMA9 > last.EMA21 else -1
        s += 0.7 * trend
        s += float(np.clip((last.RSI - 50) / 25, -1, 1)) * 0.7
        if last.Close > df["High"].iloc[-2]:
            s += 0.6; why.append("closed above prev. high")
        elif last.Close < df["Low"].iloc[-2]:
            s -= 0.6; why.append("closed below prev. low")

        price, relvol = last.Close, 1.0
        idf = intraday.get(t)
        if session != "pre_open" and idf is not None and len(idf):
            today = idf[idf.index.date == idf.index[-1].date()]
            if len(today) >= 3:
                from indicators import vwap
                vw = vwap(today).iloc[-1]
                price = today["Close"].iloc[-1]
                orb_h, orb_l = today["High"].iloc[:3].max(), today["Low"].iloc[:3].min()
                if price > vw:
                    s += 1.0; why.append("above VWAP")
                else:
                    s -= 1.0; why.append("below VWAP")
                if price > orb_h:
                    s += 1.0; why.append("15-min range breakout")
                elif price < orb_l:
                    s -= 1.0; why.append("15-min range breakdown")
                frac = min(len(today) / 75, 1)  # 75 five-minute bars in a session
                relvol = today["Volume"].sum() / (last.VolAvg20 * frac) if last.VolAvg20 else 1
                if relvol > 1.5:
                    why.append(f"volume {relvol:.1f}x normal")
        s *= 0.6 + min(relvol, 2.5) / 2.5 * 0.6  # conviction grows with participation

        side = 1 if s > 0 else -1
        stop, tgt, tgt2, qty = _levels(side, price, last.ATR, 0.5, 0.8, regime["size_mult"])
        rows.append({"Ticker": t.replace(".NS", ""), "Score": round(s, 2), "Price": round(price, 2),
                     "Stop": stop, "Target 1": tgt, "Target 2": tgt2, "Qty": qty,
                     "RSI": round(last.RSI, 1), "Reasons": ", ".join(why) or "trend/RSI"})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- swing
def swing_scores(daily, nifty, gscore, regime):
    n20 = nifty["Close"].iloc[-1] / nifty["Close"].iloc[-21] - 1
    rows = []
    for t, df in daily.items():
        if len(df) < 120 or not _liquid(df):
            continue
        l, p = df.iloc[-1], df.iloc[-2]
        s, why = 0.0, []
        if l.Close > l.EMA20 > l.EMA50:
            s += 2; why.append("price > EMA20 > EMA50")
        elif l.Close < l.EMA20 < l.EMA50:
            s -= 2; why.append("price < EMA20 < EMA50")
        s += 1 if l.EMA50 > l.EMA200 else -1
        if 50 <= l.RSI <= 68:
            s += 1; why.append(f"RSI {l.RSI:.0f} healthy")
        elif l.RSI > 75:
            s -= 1; why.append(f"RSI {l.RSI:.0f} overbought")
        elif 32 <= l.RSI < 45:
            s -= 1
        elif l.RSI < 25:
            s += 0.5; why.append("deeply oversold")
        if l.MACDhist > 0 and p.MACDhist <= 0:
            s += 1.5; why.append("MACD bullish cross")
        elif l.MACDhist < 0 and p.MACDhist >= 0:
            s -= 1.5; why.append("MACD bearish cross")
        vr = l.Volume / l.VolAvg20 if l.VolAvg20 else 1
        if l.Close >= 0.99 * df["High20"].iloc[-2] and vr > 1.3:
            s += 2; why.append(f"20-day breakout on {vr:.1f}x volume")
        if l.Close <= 1.01 * df["Low20"].iloc[-2] and vr > 1.3:
            s -= 2; why.append("20-day breakdown on volume")
        if l.Close > l.EMA50 and abs(l.Close - l.EMA20) < 0.7 * l.ATR and l.EMA20 > l.EMA50:
            s += 1; why.append("pullback to EMA20 in uptrend")
        rs = (l.Close / df["Close"].iloc[-21] - 1) - n20
        s += float(np.clip(rs / 0.05, -1, 1))
        if abs(rs) > 0.03:
            why.append(f"{'out' if rs > 0 else 'under'}performing Nifty by {rs*100:+.1f}% (20d)")
        s += 0.7 * gscore + (0.5 if regime["Trend"] == "Uptrend" else -0.5 if regime["Trend"] == "Downtrend" else 0)

        side = 1 if s > 0 else -1
        stop, tgt, tgt2, qty = _levels(side, l.Close, l.ATR, 1.5, 2.5, regime["size_mult"])
        rows.append({"Ticker": t.replace(".NS", ""), "Score": round(s, 2), "Price": round(l.Close, 2),
                     "Stop": stop, "Target 1": tgt, "Target 2": tgt2, "Qty": qty,
                     "RSI": round(l.RSI, 1), "Hold": "3–15 days", "Reasons": ", ".join(why)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- long term
def longterm_scores(daily, fundamentals=None):
    rows = []
    for t, df in daily.items():
        if len(df) < 250:
            continue
        c = df["Close"]
        l = df.iloc[-1]
        rows.append({
            "Ticker": t,
            "mom_12_1": c.iloc[-22] / c.iloc[-253] - 1,          # 12-month momentum skipping last month
            "above_200": float(l.Close > l.SMA200),
            "sma200_slope": l.SMA200 / df["SMA200"].iloc[-21] - 1,
            "vol": df["Ret"].tail(252).std() * np.sqrt(252),
            "dd_52w": l.Close / l.High52w - 1,
            "Price": l.Close,
        })
    d = pd.DataFrame(rows).set_index("Ticker")
    if d.empty:
        return d
    rank = lambda s, asc=True: s.rank(pct=True, ascending=asc)
    score = (0.35 * rank(d.mom_12_1) + 0.15 * d.above_200 + 0.15 * rank(d.sma200_slope)
             + 0.15 * rank(d.vol, asc=False) + 0.05 * rank(d.dd_52w))
    if fundamentals:
        f = pd.DataFrame(fundamentals).T.reindex(d.index).astype(float)
        d = d.join(f)
        for c in ("ROE", "EPSGrowth"):
            d[c] = d[c] * 100  # show as %
        q = (rank(f["ROE"]).fillna(.5) + rank(f["DebtToEquity"], asc=False).fillna(.5)
             + rank(f["EPSGrowth"]).fillna(.5) + rank(f["PE"], asc=False).fillna(.5)) / 4
        score = score * 0.6 / 0.85 + 0.4 * q   # 60 % price quality, 40 % business quality
    else:
        score = score / 0.85
    d["Score"] = (score * 100).round(1)
    d["12-1m mom %"] = (d.mom_12_1 * 100).round(1)
    d["Vol %"] = (d.vol * 100).round(1)
    d["From 52w high %"] = (d.dd_52w * 100).round(1)
    d["Price"] = d["Price"].round(2)
    d["View"] = np.where((d.above_200 == 1) & (d.mom_12_1 > 0), "Accumulate on dips",
                np.where((d.above_200 == 0) & (d.mom_12_1 < 0), "Review / avoid", "Watch"))
    d.index = d.index.str.replace(".NS", "", regex=False)
    cols = ["Score", "Price", "12-1m mom %", "Vol %", "From 52w high %", "View"]
    cols += [c for c in ("PE", "ROE", "DebtToEquity", "EPSGrowth") if c in d.columns]
    return d[cols].sort_values("Score", ascending=False)


def split(df: pd.DataFrame, n_buy: int, n_sell: int):
    if df.empty:
        return df, df
    buys = df[df.Score > 0].sort_values("Score", ascending=False).head(n_buy)
    sells = df[df.Score < 0].sort_values("Score").head(n_sell)
    return buys.reset_index(drop=True), sells.reset_index(drop=True)
