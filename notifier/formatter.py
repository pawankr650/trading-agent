"""Turn analysis reports into readable Telegram (HTML) messages."""
from __future__ import annotations

from html import escape

from core.news_scanner import EVENT_LABEL
from core.llm import to_float
from core.market_hours import IST

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
                     f"({to_float(rv.get('confidence')):.0%}) — {escape(str(rv.get('rationale', '')))}")
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
    if not items:
        return f"<b>{title}</b>\nNo fresh headlines right now."
    return f"<b>{title}</b>\n" + "\n".join(
        f"• <a href=\"{escape(n['link'], quote=True)}\">{escape(n['title'][:120])}</a> <i>{escape(n['source'])}</i>"
        for n in items)


# ── AI news digest ─────────────────────────────────────────
REC_ICON = {"BUY": "🟢", "SELL": "🔴", "AVOID": "🟠", "WATCH": "👀"}
REC_TEXT = {"BUY": "BUY candidate", "SELL": "SELL / exit", "AVOID": "AVOID for now", "WATCH": "WATCH"}


def pick_card(p: dict) -> str:
    name = escape(p["symbol"] or p["company"] or "Market")
    comp = f" · {escape(p['company'][:40])}" if p["symbol"] and p["company"] else ""
    lines = [f"{REC_ICON[p['recommendation']]} <b>{REC_TEXT[p['recommendation']]} · {name}</b>{comp}",
             f"📌 {escape(EVENT_LABEL.get(p['event'], p['event']))} · impact <b>{escape(p['impact'])}</b> · "
             f"materiality {escape(p['materiality'])} · confidence <b>{p['confidence']:.0%}</b>"
             + (f" · {escape(p['horizon'])}" if p["horizon"] else ""),
             f"📝 {escape(p['summary'][:600])}"]
    if p["thinking"]:
        lines.append("🧠 <b>Thinking</b>")
        lines += [f"  {i}. {escape(t[:200])}" for i, t in enumerate(p["thinking"], 1)]
    if p["risks"]:
        lines.append(f"⚠️ <b>Risks:</b> {escape(p['risks'][:200])}")
    t = p.get("tech")
    if t:
        plan = t.get("plan") or {}
        lines.append(f"📊 ₹{t['price']} ({t['change_pct']:+.2f}%) · model {t['action']} {t['score']:+.2f} "
                     f"(tech {t['tech_score']:+.2f} · fund {t['fund_score']:+.2f}) · RSI {t['rsi']}"
                     + (f" · Mcap {_cr(t.get('mcap'))}" if t.get("mcap") else ""))
        if plan:
            lines.append(f"🎯 Entry {plan['entry']} · SL {plan['stop']} · Target {plan['target']}")
    links = [s for s in p["sources"] if s.get("link")][:3]
    if links:
        lines.append("🔗 " + " · ".join(f"<a href=\"{escape(s['link'], quote=True)}\">{escape(s['source'] or 'link')}</a>"
                                       for s in links))
    return "\n".join(lines)


def news_digest_message(d: dict, title: str = "🗞️ AI news scan", min_conf: float = 0.0,
                        max_cards: int = 12) -> str:
    picks = [p for p in d["picks"] if p["confidence"] >= min_conf or p["recommendation"] == "WATCH"]
    buys = [p for p in picks if p["recommendation"] == "BUY"]
    neg = [p for p in picks if p["recommendation"] in ("SELL", "AVOID")]
    watch = [p for p in picks if p["recommendation"] == "WATCH"]
    at = d.get("at")
    head = [f"<b>{escape(title)}</b>" + (f" · {at.astimezone(IST):%d %b %H:%M} IST" if at else ""),
            f"Scanned {d['scanned']} new items · 🟢 {len(buys)} buy · 🔴 {len(neg)} avoid/sell · 👀 {len(watch)} watch",
            f"<i>AI: {escape(d.get('source') or '–')}</i>"]
    if d.get("mood"):
        head.append(f"\n🌡️ <b>Market mood:</b> {escape(d['mood'])}")
    out = ["\n".join(head)]
    cards = (buys + neg + [w for w in watch if w["symbol"]])[:max_cards]
    for p in cards:
        out.append(pick_card(p))
    rest = [p for p in watch if p not in cards][:8]
    if rest:
        out.append("<b>Other headlines worth knowing</b>\n" + "\n".join(
            f"• {escape((p['symbol'] + ': ') if p['symbol'] else '')}{escape(p['summary'][:140])}" for p in rest))
    if not cards and not rest:
        out.append("Nothing material in the latest news.")
    out.append("<i>AI summary of public news — not investment advice. Verify filings before trading.</i>")
    return "\n\n".join(out)
