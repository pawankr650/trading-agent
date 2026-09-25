"""AI news scanner: all news sources -> open-source LLM -> "should I buy this stock?" recommendations.

Pipeline
  1. collect   market RSS (ET, Moneycontrol, BS, Mint, …) + Google News queries
               + NSE / BSE corporate filings (order wins, results, dividends, M&A, penalties, …)
  2. filter    drop already-seen items and routine filings; rank by event importance
  3. LLM       batch-summarise each item -> stock, event, summary, BUY / WATCH / AVOID / SELL,
               confidence, horizon, step-by-step reasoning ("thinking") and risks
  4. confirm   optional technical + fundamental check of every BUY/WATCH stock with core.analysis
  5. digest    grouped per stock, ready for Telegram (notifier.formatter.news_digest_message)

Works without any LLM (keyword fallback) so the bot never goes silent.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from urllib.parse import quote_plus

from .announcements import classify_event, exchange_announcements, is_noise, normalise_symbol
from .config import DATA_DIR
from .llm import LLM, to_float
from .news import _bucket, _fetch_feed, keyword_sentiment, market_news

log = logging.getLogger(__name__)
SEEN_FILE = DATA_DIR / "news_seen.json"
DIGEST_FILE = DATA_DIR / "news_digest.json"  # latest digest, shown in the web app

# how much an event type usually matters for the share price (used to rank before the LLM sees it)
EVENT_WEIGHT = {"order_win": 5, "results": 5, "mna": 4, "regulatory": 4, "fund_raise": 3, "rating": 3,
                "dividend_bonus_split": 3, "capacity_expansion": 3, "guidance": 2, "management": 2, "other": 1}
EVENT_LABEL = {"order_win": "Order win / contract", "results": "Financial results", "mna": "M&A / stake deal",
               "regulatory": "Regulatory / legal", "fund_raise": "Fund raising", "rating": "Rating / broker call",
               "dividend_bonus_split": "Dividend / bonus / split / buyback", "capacity_expansion": "Capex / expansion",
               "guidance": "Guidance / management commentary", "management": "Management change",
               "market": "Market / macro", "other": "Other"}
RECS = ("BUY", "WATCH", "AVOID", "SELL")
_SYM_OK = re.compile(r"^[A-Z0-9&\-]{1,20}$")

SYSTEM_PROMPT = """You are a senior Indian equity research analyst (NSE/BSE) writing for a retail swing trader.
For every news item decide whether it is a reason to BUY the stock now. Think step by step:
 1. What exactly happened? (numbers, order size, profit growth, counterparty)
 2. How material is it for THIS company's size and business? (an order of 10% of annual revenue is big, 0.5% is noise)
 3. Is it already priced in / is it a routine filing?
 4. What is the likely price reaction over the next 1-20 trading days?
Rules: use ONLY facts in the item text; never invent numbers; if the text is vague say so and prefer WATCH;
BUY only for clearly positive, material, company-specific news; SELL/AVOID for clearly negative news;
macro/market news without a single listed company -> symbol "" and recommendation WATCH or AVOID.
Use the official NSE trading symbol when you know it (e.g. RELIANCE, HDFCBANK, RVNL), else ""."""

ITEM_SCHEMA = """Return JSON: {"market_mood": "<=35 words on what today's news means for Indian stocks overall",
 "items": [{"id": <item id>, "symbol": "NSE symbol or empty", "company": "name",
   "event": "order_win|results|mna|regulatory|fund_raise|rating|dividend_bonus_split|capacity_expansion|guidance|management|market|other",
   "summary": "2-3 sentence plain-English summary with the key numbers",
   "impact": "bullish|bearish|neutral", "materiality": "high|medium|low",
   "recommendation": "BUY|WATCH|AVOID|SELL", "confidence": 0.0-1.0,
   "horizon": "intraday|swing (1-4 weeks)|long term",
   "thinking": ["3-4 short reasoning steps"], "risks": "<=20 words"}]}
Include every item id exactly once."""


def _item_id(it: dict) -> str:
    return hashlib.sha1((it.get("symbol", "") + it["title"].lower()).encode()).hexdigest()[:16]


class NewsScanner:
    def __init__(self, cfg: dict, llm: LLM | None = None, analyzer=None, collector=None):
        self.cfg = cfg
        self.c = cfg.get("news_scanner", {})
        self.llm = llm
        self.analyzer = analyzer  # injectable for tests; defaults to core.analysis.analyze
        self.collector = collector or self.collect
        self._lock = threading.Lock()

    # ── 1. collect ─────────────────────────────────────────
    def collect(self) -> list[dict]:
        items: list[dict] = []
        for n in market_news(self.cfg, limit=int(self.c.get("max_market_items", 80))):
            items.append({**n, "event": classify_event(n["title"] + " " + n.get("summary", ""))})
        for q in self.c.get("google_news_queries", []):
            url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:1d&hl=en-IN&gl=IN&ceid=IN:en"
            for n in _fetch_feed(url, _bucket()):
                items.append({**n, "source": "Google News", "event": classify_event(n["title"])})
        items += exchange_announcements(self.cfg)
        return items

    # ── 2. filter ──────────────────────────────────────────
    def _load_seen(self) -> list[str]:
        try:
            return json.loads(SEEN_FILE.read_text())
        except Exception:
            return []

    def _save_seen(self, ids: list[str]) -> None:
        SEEN_FILE.write_text(json.dumps(ids[-int(self.c.get("remember_items", 3000)):]))

    def select(self, items: list[dict], only_new: bool = True) -> list[dict]:
        seen = set(self._load_seen()) if only_new else set()
        uniq: dict[str, dict] = {}
        for it in items:
            if not it.get("title") or is_noise(it["title"] + " " + it.get("category", "")):
                continue
            it["id"] = _item_id(it)
            if it["id"] not in seen:
                uniq.setdefault(it["id"], it)
        old = datetime.min.replace(tzinfo=timezone.utc)
        ranked = sorted(uniq.values(), key=lambda x: (EVENT_WEIGHT.get(x.get("event", "other"), 1),
                                                      bool(x.get("symbol")), x.get("published") or old), reverse=True)
        return ranked[:int(self.c.get("max_items_per_run", 40))]

    # ── 3. LLM analysis ────────────────────────────────────
    def _llm_batch(self, batch: list[dict]) -> tuple[dict[int, dict], str]:
        lines = []
        for i, it in enumerate(batch):
            extra = f" | filing category: {it['category']}" if it.get("category") else ""
            sym = f" | symbol: {it['symbol']}" if it.get("symbol") else ""
            body = (it.get("summary") or "")[:500]
            lines.append(f"[{i}] ({it['source']}{sym}{extra}) {it['title']}" + (f"\n     {body}" if body else ""))
        out = self.llm.chat_json(SYSTEM_PROMPT, "News items:\n" + "\n".join(lines) + "\n\n" + ITEM_SCHEMA,
                                 max_tokens=int(self.c.get("llm_max_tokens", 4000)))
        if isinstance(out, list):
            out = {"items": out}
        if not isinstance(out, dict):
            return {}, ""
        res = {}
        for a in out.get("items") or []:
            try:
                res[int(a.get("id"))] = a
            except (TypeError, ValueError):
                continue
        return res, str(out.get("market_mood") or "")

    @staticmethod
    def _fallback(it: dict) -> dict:
        """No LLM: keyword sentiment + event type -> conservative recommendation."""
        s = keyword_sentiment([it["title"] + " " + it.get("summary", "")])
        ev = it.get("event", "other")
        strong = EVENT_WEIGHT.get(ev, 1) >= 4
        rec = "WATCH" if s > 0 else ("AVOID" if s < 0 else "WATCH")
        return {"symbol": it.get("symbol", ""), "company": it.get("company", ""), "event": ev,
                "summary": it.get("summary") or it["title"], "impact": "bullish" if s > 0 else "bearish" if s < 0 else "neutral",
                "materiality": "medium" if strong else "low", "recommendation": rec, "confidence": round(abs(s), 2),
                "horizon": "swing (1-4 weeks)", "thinking": [f"Keyword sentiment {s:+.2f} (no LLM configured)",
                                                            f"Event type: {EVENT_LABEL.get(ev, ev)}"],
                "risks": "Automated keyword read — verify the filing yourself"}

    def analyse(self, items: list[dict]) -> tuple[list[dict], str, str]:
        size = int(self.c.get("llm_batch_size", 12))
        mood, parts, used_llm = "", [], False
        for start in range(0, len(items), size):
            batch = items[start:start + size]
            got, m = self._llm_batch(batch) if self.llm else ({}, "")
            used_llm |= bool(got)
            mood = mood or m
            for i, it in enumerate(batch):
                a = got.get(i) or self._fallback(it)
                parts.append(self._clean(a, it))
        src = (self.llm.last_provider or "LLM") if used_llm else "keywords (no LLM available)"
        return parts, mood, src

    @staticmethod
    def _clean(a: dict, it: dict) -> dict:
        rec = str(a.get("recommendation", "WATCH")).upper().strip()
        sym = normalise_symbol(str(a.get("symbol") or it.get("symbol") or ""))
        thinking = a.get("thinking") or []
        if isinstance(thinking, str):
            thinking = [t.strip() for t in re.split(r"(?:\n|;|\d\.\s)", thinking) if t.strip()]
        return {
            "symbol": sym if _SYM_OK.match(sym or "-") else "",
            "company": str(a.get("company") or it.get("company") or "").strip(),
            "event": str(a.get("event") or it.get("event") or "other"),
            "summary": str(a.get("summary") or it["title"]).strip(),
            "impact": str(a.get("impact", "neutral")).lower(),
            "materiality": str(a.get("materiality", "low")).lower(),
            "recommendation": rec if rec in RECS else "WATCH",
            "confidence": round(max(0.0, min(1.0, to_float(a.get("confidence")))), 2),
            "horizon": str(a.get("horizon") or ""),
            "thinking": [str(t) for t in thinking][:5],
            "risks": str(a.get("risks") or ""),
            "sources": [{"title": it["title"], "link": it.get("link", ""), "source": it.get("source", "")}],
            "published": it.get("published"),
        }

    # ── 4. technical / fundamental confirmation ────────────
    def confirm(self, pick: dict) -> None:
        analyzer = self.analyzer
        if analyzer is None:
            from .analysis import analyze as analyzer  # lazy: avoids yfinance import for pure-news use
        try:
            r = analyzer(pick["symbol"], self.cfg, None)
        except Exception as e:
            log.info("technical check %s failed: %s", pick["symbol"], e)
            return
        pick["tech"] = {k: r.get(k) for k in ("price", "change_pct", "action", "score", "tech_score",
                                              "fund_score", "rsi", "plan")}
        pick["tech"]["mcap"] = (r.get("fundamentals") or {}).get("marketCap")
        pick["tech"]["criteria"] = (r.get("criteria") or [])[:4]
        # news says BUY but the chart is in a downtrend -> downgrade: wait for the price to confirm
        if pick["recommendation"] == "BUY" and r.get("tech_score", 0) < float(self.c.get("min_tech_score_for_buy", -0.2)):
            pick["recommendation"] = "WATCH"
            pick["thinking"].append("Downgraded to WATCH: chart trend is weak — wait for price confirmation")
        pick["verdict_note"] = f"Chart+fundamentals model says {r.get('action')} ({r.get('score', 0):+.2f})"

    # ── 5. group + run ─────────────────────────────────────
    @staticmethod
    def group(parts: list[dict]) -> list[dict]:
        """Merge several news items about the same stock into one pick (strongest recommendation wins)."""
        rank = {"BUY": 3, "SELL": 3, "AVOID": 2, "WATCH": 1}
        by: dict[str, dict] = {}
        loose: list[dict] = []
        for p in parts:
            if not p["symbol"]:
                loose.append(p); continue
            g = by.get(p["symbol"])
            if g is None:
                by[p["symbol"]] = p; continue
            g["sources"] += p["sources"]
            better = (rank[p["recommendation"]], p["confidence"]) > (rank[g["recommendation"]], g["confidence"])
            if better:
                p["sources"] = g["sources"]; by[p["symbol"]] = p
            else:
                g["summary"] += " " + p["summary"]
        return list(by.values()) + loose

    def run(self, only_new: bool = True, confirm: bool | None = None) -> dict:
        with self._lock:
            items = self.select(self.collector(), only_new=only_new)
            if not items:
                return {"picks": [], "mood": "", "source": "", "scanned": 0, "at": datetime.now(timezone.utc)}
            parts, mood, src = self.analyse(items)
            picks = self.group(parts)
            confirm = self.c.get("confirm_with_technicals", True) if confirm is None else confirm
            if confirm:
                todo = [p for p in picks if p["symbol"] and p["recommendation"] in ("BUY", "WATCH", "SELL")]
                todo.sort(key=lambda p: p["confidence"], reverse=True)
                for p in todo[:int(self.c.get("max_technical_checks", 8))]:
                    self.confirm(p)
            order = {"BUY": 0, "SELL": 1, "AVOID": 2, "WATCH": 3}
            picks.sort(key=lambda p: (order[p["recommendation"]], -p["confidence"]))
            if only_new:
                self._save_seen(self._load_seen() + [it["id"] for it in items])
            d = {"picks": picks, "mood": mood, "source": src, "scanned": len(items), "at": datetime.now(timezone.utc)}
            save_digest(d)
            return d

    @staticmethod
    def actionable(digest: dict, min_conf: float) -> list[dict]:
        return [p for p in digest["picks"] if p["recommendation"] in ("BUY", "SELL", "AVOID")
                and p["confidence"] >= min_conf and p["symbol"]]


def save_digest(d: dict) -> None:
    try:
        DIGEST_FILE.write_text(json.dumps(d, default=str, indent=1))
    except OSError as e:
        log.warning("could not save digest: %s", e)


def load_digest() -> dict | None:
    try:
        return json.loads(DIGEST_FILE.read_text())
    except (OSError, ValueError):
        return None
