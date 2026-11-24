"""Technical indicators (pure pandas, no TA-lib needed)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(s: pd.Series, fast=12, slow=26, signal=9):
    m = ema(s, fast) - ema(s, slow)
    sig = ema(m, signal)
    return m, sig, m - sig


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0):
    """SuperTrend (default 10, 3). Returns (line, direction) where direction is
    +1 = Buy (price above the line) and -1 = Sell (price below the line)."""
    a = atr(df, n).values
    hl2 = ((df["High"] + df["Low"]) / 2).values
    c = df["Close"].values
    ub, lb = hl2 + mult * a, hl2 - mult * a
    fub, flb = ub.copy(), lb.copy()
    d = np.ones(len(df))
    line = np.full(len(df), np.nan)
    for i in range(1, len(df)):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if d[i - 1] == 1:
            d[i] = -1 if c[i] < flb[i] else 1
        else:
            d[i] = 1 if c[i] > fub[i] else -1
        line[i] = flb[i] if d[i] == 1 else fub[i]
    return pd.Series(line, index=df.index), pd.Series(d, index=df.index)


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP for intraday bars (resets each day)."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    day = df.index.date
    pv = (tp * df["Volume"]).groupby(day).cumsum()
    v = df["Volume"].groupby(day).cumsum()
    return pv / v.replace(0, np.nan)


def add_daily_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    for n in (9, 20, 21, 50, 200):
        df[f"EMA{n}"] = ema(c, n)
    df["SMA20"] = c.rolling(20).mean()
    df["SMA50"] = c.rolling(50).mean()
    df["SMA200"] = c.rolling(200, min_periods=120).mean()
    df["RSI"] = rsi(c)
    df["MACD"], df["MACDsig"], df["MACDhist"] = macd(c)
    df["ATR"] = atr(df)
    df["ST"], df["STdir"] = supertrend(df, 10, 3.0)
    df["STflip"] = df["STdir"] != df["STdir"].shift()
    df["VolAvg20"] = df["Volume"].rolling(20).mean()
    df["High20"] = df["High"].rolling(20).max()
    df["Low20"] = df["Low"].rolling(20).min()
    df["High52w"] = df["High"].rolling(252, min_periods=120).max()
    df["Ret"] = c.pct_change()
    df["Turnover"] = c * df["Volume"]
    return df


def quote(daily: pd.DataFrame, intra: pd.DataFrame | None = None) -> dict:
    """Price board fields: LTP, LCP (previous close), Open, day high/low and % changes.
    Uses live intraday bars for today when available, otherwise the latest daily bar."""
    c = daily["Close"].dropna()
    if intra is not None and len(intra):
        today = intra[intra.index.date == intra.index[-1].date()]
        ltp, op = today["Close"].iloc[-1], today["Open"].iloc[0]
        hi, lo, vol = today["High"].max(), today["Low"].min(), today["Volume"].sum()
        same_day = daily.index[-1].date() == today.index[-1].date()
        hist = c.iloc[:-1] if same_day else c
    else:
        last = daily.iloc[-1]
        ltp, op, hi, lo, vol = last["Close"], last["Open"], last["High"], last["Low"], last["Volume"]
        hist = c.iloc[:-1]
    pct = lambda ref: (ltp / ref - 1) * 100 if len(hist) and ref else np.nan
    return {"LTP": ltp, "LCP": hist.iloc[-1], "Open": op, "Day High": hi, "Day Low": lo,
            "Chg %": pct(hist.iloc[-1]),                       # vs yesterday's close
            "2D %": pct(hist.iloc[-2]) if len(hist) > 1 else np.nan,   # vs close 2 sessions ago
            "1W %": pct(hist.iloc[-5]) if len(hist) > 4 else np.nan,   # vs close 5 sessions ago
            "Volume": vol}


def price_board(daily: dict, intraday: dict | None = None, names: dict | None = None) -> pd.DataFrame:
    rows = []
    for t, df in daily.items():
        if len(df) < 6:
            continue
        q = quote(df, (intraday or {}).get(t))
        last = df.iloc[-1]
        tech = {}
        if "EMA20" in df:
            tech = {"EMA20": last["EMA20"], "EMA50": last["EMA50"], "SuperTrend": last["ST"],
                    "ST signal": ("Buy" if last["STdir"] > 0 else "Sell") + (" (new)" if last["STflip"] else "")}
        rows.append({"Ticker": t.replace(".NS", ""), **({"Sector": names.get(t, "")} if names else {}), **q, **tech})
    return pd.DataFrame(rows).set_index("Ticker")
