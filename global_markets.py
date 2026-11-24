"""Read international markets and measure how Nifty and its stocks respond to them."""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from indicators import quote


def detect_session(now_ist: pd.Timestamp) -> str:
    hm = now_ist.hour * 60 + now_ist.minute
    if hm < 9 * 60 + 15:
        return "pre_open"
    if hm < 13 * 60 + 30:
        return "intraday"
    if hm < 15 * 60 + 30:
        return "closing"
    return "post_close"


def lag_align(series: pd.Series, target_index: pd.DatetimeIndex) -> pd.Series:
    """For each Indian date, take the value from the latest foreign session strictly
    *before* it (US/Europe close after the Indian market)."""
    s = series.dropna().sort_index()
    s.index = s.index + pd.Timedelta(hours=12)
    return s.reindex(target_index, method="ffill")


def same_day_align(series: pd.Series, target_index: pd.DatetimeIndex) -> pd.Series:
    return series.dropna().sort_index().reindex(target_index, method="ffill")


def global_snapshot(gdata: dict[str, pd.DataFrame], session: str) -> pd.DataFrame:
    weights = config.SESSIONS[session]
    rows = []
    for name, meta in config.GLOBAL.items():
        df = gdata.get(meta["ticker"])
        if df is None or len(df) < 30:
            continue
        ret = df["Close"].pct_change().dropna()
        q = quote(df)
        chg = q["Chg %"] / 100
        sd = ret.tail(60).std() or np.nan
        z = float(np.clip(chg / sd, -3, 3)) if sd == sd else 0.0
        w = weights.get(name, 0.0)
        rows.append({"Market": name, "Ticker": meta["ticker"], "LTP": q["LTP"], "LCP": q["LCP"],
                     "Open": q["Open"], "Day High": q["Day High"], "Day Low": q["Day Low"],
                     "Chg %": q["Chg %"], "2D %": q["2D %"], "1W %": q["1W %"],
                     "Z": z, "Weight": w, "Impact": w * z * meta["sign"]})
    return pd.DataFrame(rows).set_index("Market")


def global_score(snap: pd.DataFrame) -> tuple[float, str]:
    """Return a score in [-1, 1] and a label."""
    w = snap["Weight"].sum()
    score = float(np.clip(snap["Impact"].sum() / w / 1.5, -1, 1)) if w else 0.0
    label = ("Strongly positive" if score > 0.5 else "Positive" if score > 0.2 else
             "Strongly negative" if score < -0.5 else "Negative" if score < -0.2 else "Neutral / mixed")
    return score, label


def nifty_vs_global(nifty: pd.DataFrame, gdata: dict, window: int = 120) -> pd.DataFrame:
    """How Nifty has moved relative to each international market."""
    n_ret = nifty["Close"].pct_change().dropna().tail(window)
    rows = []
    for name, meta in config.GLOBAL.items():
        df = gdata.get(meta["ticker"])
        if df is None:
            continue
        g = df["Close"].pct_change()
        g = lag_align(g, n_ret.index) if meta["lagged"] else same_day_align(g, n_ret.index)
        pair = pd.concat([n_ret, g], axis=1).dropna()
        if len(pair) < 30:
            continue
        a, b = pair.iloc[:, 0], pair.iloc[:, 1]
        corr = a.corr(b)
        beta = np.cov(a, b)[0, 1] / b.var() if b.var() > 0 else np.nan
        big = b.abs() > b.std()  # days with a meaningful foreign move
        hit = (np.sign(a[big]) == np.sign(b[big] * meta["sign"])).mean() * 100 if big.any() else np.nan
        rows.append({"Market": name, "Timing": "prev. session" if meta["lagged"] else "same day",
                     "Correlation": corr, "Beta": beta, "Same-direction % (big days)": hit})
    return pd.DataFrame(rows).set_index("Market").sort_values("Correlation", key=abs, ascending=False)


def stock_sensitivity(daily: dict, gdata: dict, sectors: dict, window: int = 180) -> pd.DataFrame:
    """Regress each stock's daily return on the previous US session and its sector driver,
    then project today's expected move from the latest global readings."""
    spx = gdata.get(config.GLOBAL["S&P 500"]["ticker"])
    rows = []
    for t, df in daily.items():
        r = df["Close"].pct_change().dropna().tail(window)
        if spx is None or len(r) < 60:
            continue
        f1 = lag_align(spx["Close"].pct_change(), r.index)
        drv_name = config.SECTOR_DRIVER.get(sectors.get(t, ""), "Nasdaq")
        meta = config.GLOBAL[drv_name]
        ddf = gdata.get(meta["ticker"])
        f2 = None
        if ddf is not None:
            g = ddf["Close"].pct_change()
            f2 = lag_align(g, r.index) if meta["lagged"] else same_day_align(g, r.index)
        X = pd.concat([f1, f2], axis=1) if f2 is not None else f1.to_frame()
        d = pd.concat([r, X], axis=1).dropna()
        y, Xm = d.iloc[:, 0].values, np.c_[np.ones(len(d)), d.iloc[:, 1:].values]
        coef, *_ = np.linalg.lstsq(Xm, y, rcond=None)
        b_us = coef[1]
        b_drv = coef[2] if len(coef) > 2 else 0.0
        resid = y - Xm @ coef
        r2 = 1 - resid.var() / y.var() if y.var() > 0 else 0
        last_us = spx["Close"].pct_change().iloc[-1]
        last_drv = ddf["Close"].pct_change().iloc[-1] if ddf is not None else 0
        rows.append({"Ticker": t, "Sector": sectors.get(t, ""), "Driver": drv_name,
                     "Beta US": b_us, "Beta driver": b_drv, "R2": r2,
                     "Corr US": d.iloc[:, 0].corr(d.iloc[:, 1]),
                     "Expected move %": (b_us * last_us + b_drv * last_drv) * 100})
    return pd.DataFrame(rows).set_index("Ticker")


def market_regime(nifty: pd.DataFrame, vix: pd.DataFrame | None) -> dict:
    c = nifty["Close"]
    sma50, sma200 = c.rolling(50).mean().iloc[-1], c.rolling(200, min_periods=120).mean().iloc[-1]
    last = c.iloc[-1]
    trend = ("Uptrend" if last > sma50 > sma200 else "Downtrend" if last < sma50 < sma200 else "Sideways")
    v = float(vix["Close"].iloc[-1]) if vix is not None and len(vix) else np.nan
    risk = "High volatility – cut size" if v > 20 else "Normal volatility" if v > 12 else "Low volatility"
    return {"Nifty": last, "Nifty 1d %": (c.iloc[-1] / c.iloc[-2] - 1) * 100,
            "Trend": trend, "SMA50": sma50, "SMA200": sma200, "India VIX": v, "Risk": risk,
            "size_mult": 0.5 if v > 20 else 1.0}
