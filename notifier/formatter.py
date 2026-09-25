"""Turn analysis reports into readable Telegram (HTML) messages."""
from __future__ import annotations

from html import escape

ICON = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}


def _cr(v):
    return f"₹{v/1e7:,.0f} Cr" if v else "–"


def _pct(v):
    return f"{v*100:.1f}%" if v is not None else "–"


def signal_message(r: dict) -> str:
    f, p = r["fundamentals"], r.get("plan")
    lines = [
        f"{ICON[r['action']]} <b>{r['action']} · {escape(r['symbol'])}</b>  ₹{r['price']} ({r['change_pct']:+.2f}%)",
        f"Score <b>{r['score']:+.2f}</b>  |  Tech {r['tech_score']:+.2f} · Fund {r['fund_score']:+.2f} · "
        f"News {r['news_score']:+.2f} ({r['news_src']})",
    ]
    if p:
        lines.append(f"🎯 Entry {p['entry']} · SL {p['stop']} · Target {p['target']}")
    lines.append("\n<b>Criteria</b>")
    lines += [escape(c) for c in r["criteria"][:9]]
    lines.append(
        f"\n<b>Fundamentals</b>\nP/E {f.get('trailingPE') or '–'} · P/B {f.get('priceToBook') or '–'} · "
        f"ROE {_pct(f.get('returnOnEquity'))} · Mcap {_cr(f.get('marketCap'))}\n"
        f"Rev g {_pct(f.get('revenueGrowth'))} · EPS g {_pct(f.get('earningsGrowth'))} · Margin {_pct(f.get('profitMargins'))}")
    if r["news"]:
        lines.append("\n<b>News</b>")
        lines += [f"• <a href=\"{escape(n['link'])}\">{escape(n['title'][:110])}</a>" for n in r["news"][:4]]
    rv = r.get("llm_review")
    if rv:
        lines.append(f"\n🤖 <b>AI view:</b> {escape(str(rv.get('action')))} "
                     f"({float(rv.get('confidence', 0)):.0%}) — {escape(str(rv.get('rationale', '')))}")
    lines.append("\n<i>Educational signal, not investment advice.</i>")
    return "\n".join(lines)


def board_message(reports: list[dict], title: str) -> str:
    buys = [r for r in reports if r["action"] == "BUY"]
    sells = [r for r in reports if r["action"] == "SELL"]
    fmt = lambda r: f"{escape(r['symbol'])} ₹{r['price']} ({r['score']:+.2f})"
    out = [f"<b>{escape(title)}</b>",
           "\n🟢 <b>Stocks to BUY</b>", *(["• " + fmt(r) for r in buys] or ["• none"]),
           "\n🔴 <b>Stocks to SELL / avoid</b>", *(["• " + fmt(r) for r in sells] or ["• none"]),
           "\n⚪ <b>Watch (HOLD)</b>",
           ", ".join(escape(r["symbol"]) for r in reports if r["action"] == "HOLD") or "none"]
    return "\n".join(out)


def news_message(items: list[dict], title="📰 Market news (NSE/BSE)") -> str:
    return f"<b>{title}</b>\n" + "\n".join(
        f"• <a href=\"{escape(n['link'])}\">{escape(n['title'][:120])}</a> <i>{escape(n['source'])}</i>" for n in items)
