"""Nifty Global-Markets Agent.

Reads international markets, measures how Nifty and each Nifty-50 stock respond
to them, and produces ranked candidate lists for intraday, swing and long-term.

  python agent.py                    # one run, session picked from IST clock
  python agent.py --session pre_open # force a session
  python agent.py --schedule         # run automatically at the times in config.py
  python agent.py --demo             # offline test with synthetic data
  python agent.py --fundamentals     # add PE/ROE/debt/growth to long-term ranking (slower)
  python agent.py --llm              # add a plain-English market brief written by Claude
  python agent.py --telegram         # push the summary to Telegram

Screening tool only - not investment advice. Verify every idea before trading.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

import config
from global_markets import (detect_session, global_score, global_snapshot, market_regime,
                            nifty_vs_global, stock_sensitivity)
from indicators import add_daily_indicators, price_board
from strategies import intraday_scores, longterm_scores, split, swing_scores

IST = ZoneInfo("Asia/Kolkata")
DISCLAIMER = ("_Rules-based screen for research and education. Not investment advice and not a "
              "SEBI-registered recommendation. Data from free sources can be delayed or wrong. "
              "Check charts, news and results dates yourself and always use a stop-loss._")


def load_universe(path: str | None, extra: list[str] | None = None) -> dict[str, str]:
    if path:
        df = pd.read_csv(path)  # NSE format: "Company Name, Industry, Symbol, Series, ISIN Code"
        uni = {f"{s.strip()}.NS": ind for s, ind in zip(df["Symbol"], df["Industry"])}
    else:
        uni = dict(config.NIFTY50)
    uni.update(config.EXTRA_STOCKS)
    for sym in extra or []:
        t = sym.upper() if sym.upper().endswith((".NS", ".BO")) else f"{sym.upper()}.NS"
        uni.setdefault(t, "")
    return uni


QUOTE_COLS = ["LTP", "LCP", "Open", "Chg %", "2D %", "1W %", "EMA20", "EMA50", "SuperTrend", "ST signal"]


def with_quotes(df: pd.DataFrame, board: pd.DataFrame) -> pd.DataFrame:
    """Put LTP / LCP / Open / % changes right after the ticker in a picks table."""
    if df is None or df.empty:
        return df
    keyed = df.set_index("Ticker") if "Ticker" in df.columns else df
    keyed = keyed.drop(columns=["Price"], errors="ignore")
    out = board[QUOTE_COLS].join(keyed, how="inner").loc[keyed.index]
    return out.reset_index() if "Ticker" in df.columns else out


def md(df: pd.DataFrame, floatfmt=".2f") -> str:
    if df is None or df.empty:
        return "_No candidates passed the filters._\n"
    return df.to_markdown(floatfmt=floatfmt) + "\n"


def compute(session: str | None = None, demo=False, fundamentals=False,
            universe_path=None, extra=None) -> dict:
    """Download the latest data and score everything. Nothing is cached: every call
    pulls fresh prices, so each run reflects the market at that moment."""
    now = datetime.now(IST)
    session = session or detect_session(pd.Timestamp(now))
    universe = load_universe(universe_path, extra)
    if demo:
        from data import DemoData
        src = DemoData()
    else:
        from data import YahooData
        src = YahooData()

    gtickers = [m["ticker"] for m in config.GLOBAL.values()]
    print(f"[{now:%H:%M} IST] session={session}  downloading data…")
    gdata = src.daily(gtickers + [config.NIFTY_INDEX, config.INDIA_VIX], period="2y")
    daily = {t: add_daily_indicators(d) for t, d in src.daily(list(universe), period="2y").items()}
    intraday = src.intraday(list(universe)) if session in ("intraday", "closing") else {}
    nifty, vix = gdata.get(config.NIFTY_INDEX), gdata.get(config.INDIA_VIX)
    if nifty is None or not daily:
        raise SystemExit("No data downloaded - check your internet connection / tickers.")

    snap = global_snapshot(gdata, session)
    gscore, glabel = global_score(snap)
    regime = market_regime(nifty, vix)
    nvg = nifty_vs_global(nifty, gdata)
    sens = stock_sensitivity(daily, gdata, universe)

    intra = intraday_scores(daily, intraday, sens, gscore, regime, session)
    swing = swing_scores(daily, nifty, gscore, regime)
    funds = {t: src.fundamentals(t) for t in daily} if fundamentals else None
    lt = longterm_scores(daily, funds)

    board = price_board(daily, intraday, universe)
    board["Exp. move % (global)"] = sens["Expected move %"].rename(lambda t: t.replace(".NS", ""))
    board = board.sort_values("Chg %", ascending=False)

    ib, is_ = (with_quotes(x, board) for x in split(intra, config.TOP_N_BUY, config.TOP_N_SELL))
    sb, ss = (with_quotes(x, board) for x in split(swing, config.TOP_N_BUY, config.TOP_N_SELL))
    lt = with_quotes(lt, board)
    lt_buy = lt[lt.View == "Accumulate on dips"].head(config.TOP_N_BUY)
    lt_avoid = lt[lt.View == "Review / avoid"].tail(config.TOP_N_SELL)

    sens_view = sens.sort_values("Expected move %")
    movers = pd.concat([sens_view.tail(5)[::-1], sens_view.head(5)])
    movers.index = movers.index.str.replace(".NS", "", regex=False)
    return dict(now=now, session=session, demo=demo, fundamentals=fundamentals, snap=snap,
                gscore=gscore, glabel=glabel, regime=regime, nvg=nvg, sens=sens, intra=intra,
                swing=swing, lt=lt, board=board, ib=ib, is_=is_, sb=sb, ss=ss, lt_buy=lt_buy,
                lt_avoid=lt_avoid, movers=movers)


def stance(gscore, regime):
    if gscore > 0.2 and regime["Trend"] != "Downtrend":
        return "favour longs, buy dips"
    if gscore < -0.2 and regime["Trend"] != "Uptrend":
        return "favour shorts / stay light"
    return "mixed signals – trade smaller, take quick profits"


def run(session: str | None, demo=False, fundamentals=False, llm=False, telegram=False,
        universe_path=None, extra=None) -> str:
    R = compute(session, demo, fundamentals, universe_path, extra)
    (now, session, snap, gscore, glabel, regime, nvg, sens, intra, swing, lt, board, ib, is_, sb, ss,
     lt_buy, lt_avoid, movers) = (R[k] for k in ("now", "session", "snap", "gscore", "glabel", "regime",
     "nvg", "sens", "intra", "swing", "lt", "board", "ib", "is_", "sb", "ss", "lt_buy", "lt_avoid", "movers"))

    # ---------------------------------------------------------------- report
    title = {"pre_open": "Pre-open plan", "intraday": "Intraday update",
             "closing": "Closing-hour update", "post_close": "Post-close plan for next session"}[session]
    out = [f"# Nifty Global-Markets Agent – {title}",
           f"**{now:%A %d %b %Y, %H:%M} IST**{'  ·  DEMO DATA' if demo else ''}\n",
           "## 1. Market read",
           f"- **Global cue:** {glabel} (score {gscore:+.2f} on a −1 to +1 scale)",
           f"- **Nifty:** {regime['Nifty']:.0f} ({regime['Nifty 1d %']:+.2f}%) · trend **{regime['Trend']}** "
           f"(50-DMA {regime['SMA50']:.0f}, 200-DMA {regime['SMA200']:.0f})",
           f"- **India VIX:** {regime['India VIX']:.1f} → {regime['Risk']}",
           f"- **Stance:** " + stance(gscore, regime), "",
           "### International markets (weighted for this time of day)",
           md(snap.sort_values("Weight", ascending=False)[["LTP", "LCP", "Open", "Chg %", "2D %", "1W %", "Weight", "Impact"]]),
           "### How Nifty has tracked these markets (last 120 sessions)",
           md(nvg),
           "### Nifty stocks most exposed to today's global cue",
           md(movers[["Sector", "Driver", "Beta US", "Beta driver", "Corr US", "Expected move %"]]),
           ]
    if session != "post_close":
        out += [f"## 2. Intraday – top {config.TOP_N_BUY} buy candidates",
                "_Stop 0.5×ATR, targets 0.8× / 1.6×ATR. Square off by 15:15. "
                + ("Pre-open list: confirm after 09:30 with VWAP and the opening range._" if session == "pre_open"
                   else "Uses live VWAP, 15-min opening range and volume._"),
                md(ib), f"### Intraday – top {config.TOP_N_SELL} sell / short candidates", md(is_)]
    out += [f"## 3. Swing (3–15 days) – top {config.TOP_N_BUY} buy candidates",
            "_Stop 1.5×ATR below close, targets 2.5× / 5×ATR. Once in profit, the SuperTrend line works as a trailing stop. Skip if it gaps far above the listed price._",
            md(sb), f"### Swing – top {config.TOP_N_SELL} sell / avoid candidates", md(ss),
            f"## 4. Long term (1 year+) – top {config.TOP_N_BUY} accumulate candidates",
            "_Ranked on 12-month momentum, 200-DMA trend, low volatility"
            + (", ROE, debt, earnings growth and valuation" if fundamentals else
               " (run with --fundamentals to add ROE/debt/growth/PE)") + "._",
            md(lt_buy, ".1f"), "### Long term – review / avoid", md(lt_avoid, ".1f"),
            "## 5. Price board – Nifty 50 + your extra stocks (sorted by today's change)",
            "_LTP = last traded price · LCP = last (previous) closing price · Chg % vs yesterday's close · "
            "2D % vs close 2 sessions ago · 1W % vs close 5 sessions ago · EMA20/EMA50 = 20/50-day "
            "exponential moving averages · SuperTrend (10, 3) on daily candles: Buy when price is above it._",
            md(board[["Sector", "LTP", "LCP", "Open", "Day High", "Day Low", "Chg %", "2D %", "1W %",
                       "EMA20", "EMA50", "SuperTrend", "ST signal"]])]

    summary = {"session": session, "global_score": round(gscore, 2), "global_label": glabel,
               "regime": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in regime.items()},
               "top_global": snap.sort_values("Weight", ascending=False).head(6)[["Chg %"]].round(2).to_dict()["Chg %"],
               "intraday_buy": ib.Ticker.tolist() if not ib.empty else [],
               "intraday_sell": is_.Ticker.tolist() if not is_.empty else [],
               "swing_buy": sb.Ticker.tolist() if not sb.empty else [],
               "swing_sell": ss.Ticker.tolist() if not ss.empty else [],
               "longterm": lt_buy.index.tolist()}
    if llm:
        out.insert(3, "### AI brief\n" + llm_brief(summary) + "\n")
    out += ["---", DISCLAIMER]
    report = "\n".join(out)

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    stem = os.path.join(config.REPORT_DIR, f"{now:%Y-%m-%d_%H%M}_{session}")
    with open(stem + ".md", "w") as f:
        f.write(report)
    if _has_openpyxl():
        write_excel(stem + ".xlsx", [
            ("Nifty 50 Prices", board.reset_index()),
            ("Global Markets", snap.reset_index()),
            ("Intraday", with_quotes(intra.sort_values("Score", ascending=False), board)),
            ("Swing", with_quotes(swing.sort_values("Score", ascending=False), board)),
            ("Long Term", lt.reset_index()),
            ("Nifty vs Global", nvg.reset_index()),
            ("Sensitivity", sens.reset_index())])
    with open(stem + ".json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Report saved: {stem}.md")
    if telegram:
        send_telegram(summary)
    return report


def write_excel(path, sheets):
    """One tab per table: frozen header, sized columns, green/red % changes."""
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    green, red = Font(color="1B7F3B"), Font(color="C0392B")
    head = PatternFill("solid", fgColor="1F3A5F")
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets:
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "B2"
            for j, col in enumerate(df.columns, 1):
                cell = ws.cell(1, j)
                cell.font, cell.fill = Font(bold=True, color="FFFFFF"), head
                width = max(len(str(col)), *(len(f"{v:.2f}" if isinstance(v, float) else str(v))
                                             for v in df[col].head(60))) if len(df) else len(str(col))
                ws.column_dimensions[get_column_letter(j)].width = min(width + 2, 60)
                is_pct = "%" in str(col)
                for i in range(2, len(df) + 2):
                    c = ws.cell(i, j)
                    if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                        c.number_format = "#,##0" if col == "Volume" else "0.00"
                        if is_pct or col in ("Score", "Impact"):
                            if c.value:
                                c.font = green if c.value > 0 else red


def _has_openpyxl():
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        return False


def llm_brief(summary: dict) -> str:
    """Optional: ask Claude to explain the numbers in plain English."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=config.LLM_MODEL, max_tokens=500,
            messages=[{"role": "user", "content":
                       "You are a markets analyst. In 5 short bullet points, explain what these "
                       "screen results imply for Indian equities this session: global cue, Nifty trend, "
                       "risk level, and which sectors look strong or weak. Do not invent numbers; do not "
                       "give personalised advice.\n\n" + json.dumps(summary, default=str)}])
        return msg.content[0].text
    except Exception as e:  # missing key / package / network
        return f"_AI brief unavailable ({e.__class__.__name__})._"


def send_telegram(summary: dict):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        print("Telegram skipped: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return
    import requests
    text = (f"Nifty agent · {summary['session']}\nGlobal: {summary['global_label']} ({summary['global_score']:+})\n"
            f"Trend: {summary['regime']['Trend']} · VIX {summary['regime']['India VIX']}\n"
            f"Intraday buy: {', '.join(summary['intraday_buy'])}\nIntraday sell: {', '.join(summary['intraday_sell'])}\n"
            f"Swing buy: {', '.join(summary['swing_buy'])}\nSwing sell: {', '.join(summary['swing_sell'])}\n"
            f"Long term: {', '.join(summary['longterm'])}\n(Screen only, not advice)")
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat, "text": text}, timeout=10)


def schedule_loop(**kw):
    print("Scheduler running (Mon–Fri). Times IST:", ", ".join(config.SCHEDULE_IST))
    done = set()
    while True:
        now = datetime.now(IST)
        key = now.strftime("%H:%M")
        if now.weekday() < 5 and key in config.SCHEDULE_IST and (now.date(), key) not in done:
            done.add((now.date(), key))
            try:
                run(config.SCHEDULE_IST[key], **kw)
            except Exception as e:
                print("Run failed:", e)
        time.sleep(20)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", choices=list(config.SESSIONS))
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--fundamentals", action="store_true")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--schedule", action="store_true")
    ap.add_argument("--universe")
    ap.add_argument("--add", nargs="+", metavar="SYMBOL", help="extra NSE stocks for this run, e.g. AMBUJACEM ACC")
    ap.add_argument("--print", action="store_true", help="print the report to the terminal")
    a = ap.parse_args()
    kw = dict(demo=a.demo, fundamentals=a.fundamentals, llm=a.llm, telegram=a.telegram, universe_path=a.universe, extra=a.add)
    if a.schedule:
        schedule_loop(**kw)
    else:
        rep = run(a.session, **kw)
        if a.print:
            print(rep)
