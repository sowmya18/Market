"""Web UI for the Nifty Global-Markets Agent.

Local:   streamlit run app.py           -> opens http://localhost:8501
Online:  deploy this folder on Streamlit Community Cloud (see DEPLOY.md) for your own link.

Every run downloads fresh prices; nothing is cached between runs. While the page is open
it also runs itself at the scheduled IST times in config.py (and optionally every N minutes).
"""
from __future__ import annotations

import glob
import io
import os
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import config
from agent import IST, compute, stance, with_quotes, write_excel

st.set_page_config(page_title="Nifty Global-Markets Agent", page_icon="📈", layout="wide")

SESSION_NAMES = {"Auto (by time of day)": None, "Pre-open": "pre_open", "Intraday": "intraday",
                 "Closing hour": "closing", "Post-close": "post_close"}

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Run settings")
    session_label = st.selectbox("Session", list(SESSION_NAMES))
    extra_txt = st.text_input("Extra NSE stocks (comma separated)", "",
                              help="Added on top of the Nifty 50 and EXTRA_STOCKS in config.py, e.g. ACC, SHREECEM")
    fundamentals = st.checkbox("Include fundamentals in long-term ranking (slower)", False)
    auto_sched = st.checkbox("Auto-run at scheduled times", True,
                             help="Runs at " + ", ".join(config.SCHEDULE_IST) + " IST, Mon–Fri, while this page is open")
    refresh_min = st.selectbox("Also refresh during market hours every", ["Off", 5, 15, 30, 60], index=2,
                               format_func=lambda v: v if v == "Off" else f"{v} min")
    demo = st.checkbox("Demo data (offline test)", os.getenv("AGENT_DEMO") == "1")
    run_now = st.button("▶ Run agent now", type="primary", width="stretch")
    st.caption("Screening tool for research only — not investment advice.")

extra = [s.strip() for s in extra_txt.replace(";", ",").split(",") if s.strip()]


def do_run(session=None):
    with st.spinner("Downloading latest prices and scoring stocks…"):
        st.session_state.R = compute(session, demo=demo, fundamentals=fundamentals, extra=extra)
        st.session_state.last_run = datetime.now(IST)


def last_due_slot(now):
    """The most recent scheduled IST time that has passed today (Mon–Fri)."""
    if now.weekday() >= 5:
        return None
    due = [(k, v) for k, v in config.SCHEDULE_IST.items() if k <= now.strftime("%H:%M")]
    return due[-1] if due else None


if run_now or "R" not in st.session_state:
    try:
        do_run(SESSION_NAMES[session_label])
    except SystemExit as e:
        st.error(str(e)); st.stop()
    except Exception as e:
        st.error(f"Run failed: {e}"); st.stop()


@st.fragment(run_every=timedelta(seconds=60))
def scheduler():
    """Checks once a minute whether a scheduled time (or the refresh interval) has passed."""
    now = datetime.now(IST)
    last = st.session_state.get("last_run")
    slot = last_due_slot(now)
    market_open = now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"
    due, session = False, None
    if auto_sched and slot:
        slot_time = now.replace(hour=int(slot[0][:2]), minute=int(slot[0][3:]), second=0, microsecond=0)
        if last is None or last < slot_time:
            due, session = True, slot[1]
    if not due and refresh_min != "Off" and market_open and last and now - last >= timedelta(minutes=refresh_min):
        due, session = True, SESSION_NAMES[session_label]
    if due:
        do_run(session)
        st.rerun(scope="app")
    nxt = [k for k in config.SCHEDULE_IST if k > now.strftime("%H:%M")]
    st.caption(f"🕒 {now:%H:%M} IST · last run {last:%H:%M:%S} · next scheduled run "
               f"{nxt[0] + ' IST' if nxt and now.weekday() < 5 else 'next trading day 08:50 IST'}")


R = st.session_state.R
reg = R["regime"]

# ----------------------------------------------------------------------------- header
st.title("📈 Nifty Global-Markets Agent")
title = {"pre_open": "Pre-open plan", "intraday": "Intraday update", "closing": "Closing-hour update",
         "post_close": "Post-close plan for next session"}[R["session"]]
st.subheader(f"{title} — {R['now']:%A %d %b %Y, %H:%M} IST" + ("  ·  DEMO DATA" if R["demo"] else ""))
scheduler()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Global cue", R["glabel"], f"{R['gscore']:+.2f}")
c2.metric("Nifty 50", f"{reg['Nifty']:,.0f}", f"{reg['Nifty 1d %']:+.2f}%")
c3.metric("Trend", reg["Trend"], f"50-DMA {reg['SMA50']:,.0f}", delta_color="off")
c4.metric("India VIX", f"{reg['India VIX']:.1f}", reg["Risk"], delta_color="off")
st.info(f"**Stance:** {stance(R['gscore'], reg)}")

PCT = ["Chg %", "2D %", "1W %", "Score", "Impact", "Expected move %", "Exp. move % (global)"]


def show(df: pd.DataFrame, height=None):
    if df is None or df.empty:
        st.write("_No candidates passed the filters._")
        return
    df = df.copy()
    num = df.select_dtypes("number").columns
    sty = df.style.format({c: ("{:,.0f}" if c in ("Qty", "Volume") else "{:,.2f}") for c in num}, na_rep="–")
    cols = [c for c in PCT if c in df.columns]
    if cols:
        sty = sty.map(lambda v: "color:#1B7F3B" if isinstance(v, (int, float)) and v > 0 else
                      "color:#C0392B" if isinstance(v, (int, float)) and v < 0 else "", subset=cols)
    sig = [c for c in ("ST signal", "ST 5-min") if c in df.columns]
    if sig:
        sty = sty.map(lambda v: "color:#1B7F3B;font-weight:600" if str(v).startswith("Buy") else
                      "color:#C0392B;font-weight:600" if str(v).startswith("Sell") else "", subset=sig)
    st.dataframe(sty, width="stretch", hide_index=True, **({"height": height} if height else {}))


tabs = st.tabs(["⚡ Intraday", "📈 Swing", "🏦 Long term", "💹 Price board", "🌍 Global markets",
                "🔗 Nifty vs global", "📁 Scheduled reports"])

with tabs[0]:
    if R["session"] == "post_close":
        st.warning("Market is closed — intraday lists are hidden. Switch session to Pre-open to plan tomorrow.")
    else:
        st.markdown(f"**Top {config.TOP_N_BUY} intraday buy candidates** · stop 0.5×ATR, targets 0.8×/1.6×ATR, square off by 15:15"
                    + (" · _pre-open list: confirm after 09:30_" if R["session"] == "pre_open" else ""))
        show(R["ib"])
        st.markdown(f"**Top {config.TOP_N_SELL} intraday sell / short candidates**")
        show(R["is_"])
with tabs[1]:
    st.markdown(f"**Top {config.TOP_N_BUY} swing buy candidates (3–15 days)** · stop 1.5×ATR, targets 2.5×/5×ATR")
    show(R["sb"])
    st.markdown(f"**Top {config.TOP_N_SELL} swing sell / avoid candidates**")
    show(R["ss"])
with tabs[2]:
    st.markdown(f"**Top {config.TOP_N_BUY} long-term accumulate candidates (1 year+)**")
    show(R["lt_buy"].reset_index())
    st.markdown("**Review / avoid**")
    show(R["lt_avoid"].reset_index())
with tabs[3]:
    st.caption("LTP = last traded price · LCP = previous close · Chg % vs yesterday · 2D % vs 2 sessions ago · "
               "1W % vs 5 sessions ago · EMA20/EMA50 = 20/50-day exponential moving averages · "
               "SuperTrend (10, 3) on daily candles — Buy when price is above it; '(new)' = flipped today")
    q = st.text_input("Filter by ticker or sector", "")
    b = R["board"].reset_index()
    if q:
        b = b[b.apply(lambda r: q.lower() in f"{r.Ticker} {r.Sector}".lower(), axis=1)]
    show(b[["Ticker", "Sector", "LTP", "LCP", "Open", "Day High", "Day Low", "Chg %", "2D %", "1W %",
            "EMA20", "EMA50", "SuperTrend", "ST signal", "Volume", "Exp. move % (global)"]], height=640)
with tabs[4]:
    st.caption("Weight = how much each market counts at this time of the Indian day. Impact = its push on Indian stocks.")
    show(R["snap"].sort_values("Weight", ascending=False).reset_index().drop(columns=["Z"]), height=600)
with tabs[5]:
    st.markdown("**How Nifty has moved with each market (last 120 sessions)**")
    show(R["nvg"].reset_index())
    st.markdown("**Stocks most exposed to today's global cue**")
    show(R["movers"].reset_index())
with tabs[6]:
    files = sorted(glob.glob(os.path.join(config.REPORT_DIR, "*.md")), reverse=True)
    if not files:
        st.write("_No scheduled reports yet. Once the GitHub schedule is set up (DEPLOY.md), each run's "
                 "report appears here._")
    else:
        pick = st.selectbox("Report", files, format_func=os.path.basename)
        xl = pick.replace(".md", ".xlsx")
        if os.path.exists(xl):
            st.download_button("Download Excel", open(xl, "rb").read(), os.path.basename(xl))
        st.markdown(open(pick).read())

# ----------------------------------------------------------------------------- download
buf = io.BytesIO()
write_excel(buf, [
    ("Nifty 50 Prices", R["board"].reset_index()), ("Global Markets", R["snap"].reset_index()),
    ("Intraday", with_quotes(R["intra"].sort_values("Score", ascending=False), R["board"])),
    ("Swing", with_quotes(R["swing"].sort_values("Score", ascending=False), R["board"])),
    ("Long Term", R["lt"].reset_index()), ("Nifty vs Global", R["nvg"].reset_index()),
    ("Sensitivity", R["sens"].reset_index())])
st.sidebar.download_button("⬇ Download this run (Excel)", buf.getvalue(),
                           f"nifty_agent_{R['now']:%Y-%m-%d_%H%M}_{R['session']}.xlsx", width="stretch")
