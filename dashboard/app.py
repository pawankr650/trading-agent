"""StockPilot dashboard — screener, charts, fundamentals, news, auto-trader journal.

Run:  streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from autotrader.journal import Journal  # noqa: E402
from core.analysis import analyze, scan  # noqa: E402
from core.config import load_config  # noqa: E402
from core.llm import LLM  # noqa: E402
from core.news import market_news  # noqa: E402

st.set_page_config("StockPilot · NSE/BSE", layout="wide", page_icon="📈")
cfg = load_config()
llm = LLM(cfg)


@st.cache_data(ttl=900, show_spinner="Scanning watchlist…")
def _scan(symbols: tuple, use_llm: bool):
    return [{k: v for k, v in r.items() if k != "df"} for r in scan(cfg, llm if use_llm else None, list(symbols))]


@st.cache_data(ttl=900, show_spinner="Analyzing…")
def _one(symbol: str, use_llm: bool):
    return analyze(symbol, cfg, llm if use_llm else None, review=use_llm)


with st.sidebar:
    st.title("📈 StockPilot")
    wl = st.text_area("Watchlist (NSE symbols)", "\n".join(cfg["watchlist"]), height=220)
    symbols = tuple(s.strip().upper() for s in wl.splitlines() if s.strip())
    use_llm = st.toggle("Use free LLM (news sentiment + AI review)", value=False)
    st.caption("Educational tool — not investment advice.")

tab_scr, tab_chart, tab_news, tab_bot = st.tabs(["🧮 Screener", "📊 Stock deep-dive", "📰 News", "🤖 Auto-trader"])

with tab_scr:
    rows = _scan(symbols, use_llm)
    df = pd.DataFrame([{
        "Symbol": r["symbol"], "Price": r["price"], "Chg %": r["change_pct"], "Signal": r["action"],
        "Score": r["score"], "Technical": r["tech_score"], "Fundamental": r["fund_score"], "News": r["news_score"],
        "RSI": r["rsi"], "Entry": (r["plan"] or {}).get("entry"), "Stop": (r["plan"] or {}).get("stop"),
        "Target": (r["plan"] or {}).get("target")} for r in rows])
    c1, c2, c3 = st.columns(3)
    c1.metric("BUY signals", int((df.Signal == "BUY").sum()) if len(df) else 0)
    c2.metric("SELL signals", int((df.Signal == "SELL").sum()) if len(df) else 0)
    c3.metric("Scanned", len(df))
    st.dataframe(df, use_container_width=True, hide_index=True, column_config={
        "Score": st.column_config.ProgressColumn(min_value=-1, max_value=1, format="%.2f")})

with tab_chart:
    sym = st.selectbox("Symbol", symbols)
    r = _one(sym, use_llm)
    d = r["df"].tail(180)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.15, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close, name=sym), 1, 1)
    for c in ("SMA20", "SMA50", "SMA200"):
        fig.add_trace(go.Scatter(x=d.index, y=d[c], name=c, line=dict(width=1)), 1, 1)
    if r["plan"]:
        for k, col in (("entry", "gray"), ("stop", "red"), ("target", "green")):
            fig.add_hline(y=r["plan"][k], line_dash="dash", line_color=col, annotation_text=k, row=1, col=1)
    fig.add_trace(go.Bar(x=d.index, y=d.Volume, name="Volume"), 2, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.RSI, name="RSI"), 3, 1)
    fig.add_hline(y=70, line_dash="dot", row=3, col=1); fig.add_hline(y=30, line_dash="dot", row=3, col=1)
    fig.update_layout(height=680, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10))
    st.subheader(f"{sym} · ₹{r['price']} ({r['change_pct']:+.2f}%) → {r['action']} (score {r['score']:+.2f})")
    st.plotly_chart(fig, use_container_width=True)
    a, b = st.columns(2)
    with a:
        st.markdown("**Criteria**"); st.markdown("\n".join(f"- {c}" for c in r["criteria"]))
        if r.get("llm_review"):
            st.info(f"🤖 AI view: {r['llm_review']}")
    with b:
        st.markdown("**Fundamentals**")
        st.table(pd.Series({k: v for k, v in r["fundamentals"].items() if v is not None}, name="value").astype(str))
    st.markdown("**Latest news**")
    for n in r["news"]:
        st.markdown(f"- [{n['title']}]({n['link']})")

with tab_news:
    for n in market_news(cfg, limit=40):
        ts = n["published"].strftime("%d %b %H:%M") if n["published"] else ""
        st.markdown(f"- [{n['title']}]({n['link']}) · *{n['source']} {ts}*")

with tab_bot:
    j = Journal()
    trades = pd.DataFrame(j.all())
    st.metric("Realized P&L today", f"₹{j.realized_today():,.0f}")
    if trades.empty:
        st.info("No trades yet. Run `python -m autotrader.run --once` (paper mode) to start.")
    else:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        closed = trades[trades.status == "CLOSED"].sort_values("id")
        if not closed.empty:
            st.line_chart(closed.set_index("closed_at")["pnl"].cumsum(), height=220)
