"""Market data providers: live (Yahoo Finance via yfinance) and synthetic demo."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _clean_index(df: pd.DataFrame, keep_tz: bool = False) -> pd.DataFrame:
    df = df.copy()
    idx = pd.to_datetime(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata") if keep_tz else idx.tz_localize(None)
        if keep_tz:
            idx = idx.tz_localize(None)
    df.index = idx
    return df.sort_index()


class YahooData:
    """Free, ~15-min delayed data. Good enough for screening, not for execution."""

    def __init__(self):
        import yfinance as yf  # imported lazily so --demo works without it
        self.yf = yf

    def _download(self, tickers, **kw) -> dict[str, pd.DataFrame]:
        raw = self.yf.download(list(tickers), group_by="ticker", auto_adjust=True,
                               threads=True, progress=False, **kw)
        out = {}
        for t in tickers:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                if len(df):
                    out[t] = df
            except KeyError:
                continue
        return out

    def daily(self, tickers, period="2y"):
        return {t: _clean_index(d) for t, d in self._download(tickers, period=period, interval="1d").items()}

    def intraday(self, tickers, interval="5m"):
        # keep_tz -> converts to IST then drops tz, so bar times read as IST
        return {t: _clean_index(d, keep_tz=True)
                for t, d in self._download(tickers, period="5d", interval=interval).items()}

    def fundamentals(self, ticker):
        try:
            i = self.yf.Ticker(ticker).info
        except Exception:
            return {}
        return {"PE": i.get("trailingPE"), "ROE": i.get("returnOnEquity"),
                "DebtToEquity": i.get("debtToEquity"), "EPSGrowth": i.get("earningsGrowth"),
                "RevGrowth": i.get("revenueGrowth"), "ProfitMargin": i.get("profitMargins")}


class DemoData:
    """Synthetic but realistic-looking data so the full pipeline can be tested offline.
    Stocks react to the *previous* US session plus their sector driver, like real life."""

    def __init__(self, seed: int = 7, days: int = 400):
        self.rng = np.random.default_rng(seed)
        self.idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
        self.us = self.rng.normal(0.0004, 0.011, days)
        self.factors = {}

    def _series(self, ret, start=100.0, vol_base=1e6):
        close = start * np.exp(np.cumsum(ret))
        rng = self.rng
        op = close * (1 + rng.normal(0, 0.004, len(ret)))
        hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.006, len(ret))))
        lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.006, len(ret))))
        vol = vol_base * np.exp(rng.normal(0, 0.35, len(ret)))
        return pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": close, "Volume": vol},
                            index=self.idx)

    def daily(self, tickers, period="2y"):
        out, n = {}, len(self.idx)
        us_lag = np.r_[0, self.us[:-1]]
        for t in tickers:
            if t in ("^GSPC", "^IXIC", "^DJI", "ES=F", "NQ=F"):
                r = self.us * (1.3 if "IX" in t or "NQ" in t else 1) + self.rng.normal(0, .002, n)
            elif t in ("^VIX",):
                r = -3 * self.us + self.rng.normal(0, .03, n)
            elif t.endswith(".NS") or t == "^NSEI":
                beta = self.rng.uniform(0.2, 0.9)
                r = 0.0003 + beta * us_lag + self.rng.normal(0, 0.012 if t != "^NSEI" else 0.006, n)
                if t == "^NSEI":
                    r = 0.0004 + 0.45 * us_lag + self.rng.normal(0, 0.006, n)
            elif t == "^INDIAVIX":
                r = self.rng.normal(0, 0.04, n)
            else:
                r = 0.4 * self.us + self.rng.normal(0, 0.009, n)
            start = {"^NSEI": 24000, "^INDIAVIX": 14, "USDINR=X": 85, "^VIX": 16}.get(t, self.rng.uniform(200, 4000))
            out[t] = self._series(r, start, vol_base=self.rng.uniform(5e5, 2e7))
        self._prev_close = {t: d["Close"].iloc[-2] for t, d in out.items()}
        return out

    def intraday(self, tickers, interval="5m"):
        today = self.idx[-1]
        times = pd.date_range(today + pd.Timedelta("09:15:00"), periods=40, freq="5min")
        out = {}
        for t in tickers:
            drift = self.rng.normal(0, 0.0008)
            r = drift + self.rng.normal(0, 0.0018, len(times))
            base = getattr(self, "_prev_close", {}).get(t, self.rng.uniform(200, 4000))
            close = base * (1 + self.rng.normal(0, 0.004)) * np.exp(np.cumsum(r))
            df = pd.DataFrame({"Open": close * (1 - r / 2), "Close": close}, index=times)
            df["High"] = df[["Open", "Close"]].max(axis=1) * 1.001
            df["Low"] = df[["Open", "Close"]].min(axis=1) * 0.999
            df["Volume"] = self.rng.uniform(1e4, 5e5, len(times))
            out[t] = df
        return out

    def fundamentals(self, ticker):
        g = self.rng
        return {"PE": g.uniform(10, 70), "ROE": g.uniform(0.05, 0.35), "DebtToEquity": g.uniform(0, 150),
                "EPSGrowth": g.normal(0.12, 0.15), "RevGrowth": g.normal(0.1, 0.08),
                "ProfitMargin": g.uniform(0.03, 0.3)}
