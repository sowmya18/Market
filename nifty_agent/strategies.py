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
        st5 = None
        if session != "pre_open" and idf is not None and len(idf) > 20:
            from indicators import supertrend
            line5, dir5 = supertrend(idf, 10, 3.0)
            st5 = ("Buy" if dir5.iloc[-1] > 0 else "Sell")
            s += 1.0 * dir5.iloc[-1]
            if (dir5.tail(3) != dir5.iloc[-1]).any():
                s += 0.5 * dir5.iloc[-1]; why.append(f"5-min SuperTrend just turned {st5.lower()}")
            else:
                why.append(f"{'above' if dir5.iloc[-1] > 0 else 'below'} 5-min SuperTrend")
        else:
            s += 0.5 * last.STdir
            if last.STflip:
                why.append(f"daily SuperTrend turned {'buy' if last.STdir > 0 else 'sell'}")
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
                     "RSI": round(last.RSI, 1), "ST 5-min": st5 or "–",
                     "Reasons": ", ".join(why) or "trend/RSI"})
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
        s += 1.5 * l.STdir
        if l.STflip:
            s += 1.0 * l.STdir
            why.append(f"SuperTrend turned {'BUY' if l.STdir > 0 else 'SELL'} today")
        else:
            why.append(f"{'above' if l.STdir > 0 else 'below'} SuperTrend")
        if l.EMA20 > l.EMA50 and p.EMA20 <= p.EMA50:
            s += 1; why.append("EMA20 crossed above EMA50")
        elif l.EMA20 < l.EMA50 and p.EMA20 >= p.EMA50:
            s -= 1; why.append("EMA20 crossed below EMA50")
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
                     "RSI": round(l.RSI, 1), "Hold": "3–15 days",
                     "Reasons": ", ".join(why)})
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
            "st_up": float(l.STdir > 0),
            "Price": l.Close,
        })
    d = pd.DataFrame(rows).set_index("Ticker")
    if d.empty:
        return d
    rank = lambda s, asc=True: s.rank(pct=True, ascending=asc)
    score = (0.35 * rank(d.mom_12_1) + 0.15 * d.above_200 + 0.15 * rank(d.sma200_slope)
             + 0.15 * rank(d.vol, asc=False) + 0.05 * rank(d.dd_52w)) - 0.05 + 0.05 * d.st_up
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


# --------------------------------------------------------------------------- 20/50 crossover
def crossover_scan(daily):
    """Find stocks whose 20-day average crossed the 50-day average recently, rank them,
    and list stocks that are about to cross. Returns (bullish, bearish, approaching)."""
    kind, f, sl = config.CROSS_MA_TYPE.upper(), config.CROSS_FAST, config.CROSS_SLOW
    fast_col, slow_col = f"{kind}{f}", f"{kind}{sl}"
    lb = config.CROSS_LOOKBACK_DAYS
    cross_rows, near_rows = [], []
    for t, df in daily.items():
        if len(df) < sl + 20 or fast_col not in df or not _liquid(df):
            continue
        d = (df[fast_col] - df[slow_col]).dropna()
        sign = np.sign(d)
        flips = np.where(sign.values[1:] != sign.values[:-1])[0] + 1
        l = df.iloc[-1]
        gap = (l[fast_col] / l[slow_col] - 1) * 100
        base = {"Ticker": t.replace(".NS", ""), f"{kind}{f}": l[fast_col], f"{kind}{sl}": l[slow_col],
                "Gap %": gap, "RSI": l.RSI}
        if len(flips) and len(d) - 1 - flips[-1] <= lb:
            i = flips[-1]
            day = d.index[i]
            ago = len(d) - 1 - i
            bull = d.iloc[-1] > 0
            side = 1 if bull else -1
            cross_px = df.loc[day, "Close"]
            vol_x = df.loc[day, "Volume"] / df.loc[day, "VolAvg20"] if df.loc[day, "VolAvg20"] else 1
            slope = (l[slow_col] / df[slow_col].iloc[-6] - 1) * 100       # is the 50 turning?
            st_ok = (l.STdir > 0) == bull
            above = (l.Close > l[fast_col] > l[slow_col]) if bull else (l.Close < l[fast_col] < l[slow_col])
            score = ((lb + 1 - ago) / (lb + 1) * 3                        # fresher cross ranks higher
                     + min(abs(gap), 3)                                    # cleaner separation
                     + min(vol_x, 3) / 1.5                                 # volume confirmed the cross
                     + side * np.clip(slope, -1, 1)                        # slow average turning the same way
                     + (1.5 if st_ok else -1) + (1 if above else 0)
                     + (0.5 if (bull and 50 <= l.RSI <= 70) or (not bull and 30 <= l.RSI <= 50) else 0))
            why = [f"crossed {ago} session{'s' if ago != 1 else ''} ago" if ago else "crossed TODAY"]
            if vol_x > 1.3: why.append(f"{vol_x:.1f}x volume on cross day")
            if st_ok: why.append(f"SuperTrend agrees ({'Buy' if bull else 'Sell'})")
            if above: why.append(f"price {'above' if bull else 'below'} both averages")
            if side * slope > 0: why.append(f"{sl}-day average turning {'up' if bull else 'down'}")
            stop = min(l[slow_col], l.ST) if bull else max(l[slow_col], l.ST)
            cross_rows.append({**base, "Cross": "Bullish (20 ↑ 50)" if bull else "Bearish (20 ↓ 50)",
                               "Cross date": day.strftime("%d %b %Y"), "Days ago": ago,
                               "Move since cross %": (l.Close / cross_px - 1) * 100, "Vol on cross (x)": vol_x,
                               "Stop": stop, "Score": round(score, 2), "Reasons": ", ".join(why), "_side": side})
        elif abs(gap) <= config.CROSS_NEAR_PCT and len(d) > 3:
            closing_in = abs(d.iloc[-1]) < abs(d.iloc[-4])                 # gap shrinking over 3 sessions
            if closing_in:
                near_rows.append({**base, "Watch": "May cross UP (bullish)" if d.iloc[-1] < 0 else "May cross DOWN (bearish)",
                                  "Gap 3 sessions ago %": (df[fast_col].iloc[-4] / df[slow_col].iloc[-4] - 1) * 100,
                                  "ST signal": "Buy" if l.STdir > 0 else "Sell"})
    cr = pd.DataFrame(cross_rows)
    if cr.empty:
        bull = bear = cr
    else:
        bull = cr[cr._side > 0].sort_values(["Score"], ascending=False).head(config.TOP_N_CROSS).drop(columns="_side")
        bear = cr[cr._side < 0].sort_values(["Score"], ascending=False).head(config.TOP_N_CROSS).drop(columns="_side")
    near = pd.DataFrame(near_rows)
    if not near.empty:
        near = near.reindex(near["Gap %"].abs().sort_values().index).head(config.TOP_N_CROSS)
    return bull.reset_index(drop=True), bear.reset_index(drop=True), near.reset_index(drop=True)


def split(df: pd.DataFrame, n_buy: int, n_sell: int):
    if df.empty:
        return df, df
    buys = df[df.Score > 0].sort_values("Score", ascending=False).head(n_buy)
    sells = df[df.Score < 0].sort_values("Score").head(n_sell)
    return buys.reset_index(drop=True), sells.reset_index(drop=True)
