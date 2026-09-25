"""Continuous news pipeline: poll RSS → Hugging Face sentiment + event type → tag NIFTY 50 stocks →
refresh per-stock insights → push to live subscribers (SSE)."""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import quote_plus

from . import demo
from .datastore import PriceStore
from .hf_nlp import NewsNLP
from .insights import build, headline_thesis
from .news import _fetch_feed
from .nifty50 import SYMBOLS, name, tag_symbols

log = logging.getLogger(__name__)


class NewsEngine:
    def __init__(self, cfg: dict, prices: PriceStore, llm=None):
        self.cfg = cfg
        self.prices = prices
        self.llm = llm
        self.nlp = NewsNLP(cfg)
        ncfg = cfg.get("news", {})
        self.poll = int(ncfg.get("poll_seconds", 120))
        self.max_age_h = float(ncfg.get("max_age_hours", 36))
        self.items: deque[dict] = deque(maxlen=600)
        self.seen: set[str] = set()
        self.insights: dict[str, dict] = {}
        self.theses: dict[str, tuple[str, str]] = {}
        self.listeners: list = []  # callables(event, payload)
        self.last_poll: float | None = None
        self.cycles = 0
        self._rr = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ── feeds ─────────────────────────────────────────────
    def _feeds(self) -> list[str]:
        feeds = list(self.cfg["news"]["feeds"])
        feeds.append("https://news.google.com/rss/search?q=" + quote_plus("NSE Nifty stocks") + "&hl=en-IN&gl=IN&ceid=IN:en")
        # rotate a few per-stock Google News queries every cycle so all 50 get covered
        k = int(self.cfg["news"].get("stocks_per_cycle", 5))
        for i in range(k):
            sym = SYMBOLS[(self._rr + i) % len(SYMBOLS)]
            feeds.append("https://news.google.com/rss/search?q=" + quote_plus(f"{name(sym)} share") +
                         "&hl=en-IN&gl=IN&ceid=IN:en")
        self._rr = (self._rr + k) % len(SYMBOLS)
        return feeds

    def _fetch(self) -> list[dict]:
        if demo.enabled():
            return demo.headlines(4 if self.cycles else 30)
        bucket = int(time.time() // max(self.poll, 30))
        out = []
        for url in self._feeds():
            out.extend(_fetch_feed(url, bucket))
        return out

    # ── one cycle ─────────────────────────────────────────
    def cycle(self) -> list[dict]:
        cutoff = time.time() - self.max_age_h * 3600
        fresh = []
        for it in self._fetch():
            title = it["title"].rsplit(" - ", 1)[0] if "news.google" in it.get("source", "") else it["title"]
            key = hashlib.md5(title.lower().encode()).hexdigest()
            pub = it.get("published")
            ts = pub.timestamp() if isinstance(pub, datetime) else time.time()
            if key in self.seen or ts < cutoff or not title:
                continue
            self.seen.add(key)
            rec = {"id": key[:12], "title": title, "link": it.get("link", ""), "source": it.get("source", ""),
                   "ts": ts, "symbols": tag_symbols(title), "nlp": self.nlp.analyze(title),
                   "demo": bool(it.get("demo"))}
            fresh.append(rec)
        fresh.sort(key=lambda r: r["ts"])
        with self._lock:
            self.items.extend(fresh)
        self.last_poll = time.time()
        self.cycles += 1
        for r in fresh:
            self._emit("news", r)
        # first cycle builds all 50; later cycles only refresh stocks that just got news
        self.refresh_insights({s for r in fresh for s in r["symbols"]} if self.insights else None)
        return fresh

    def news_for(self, symbol: str) -> list[dict]:
        cutoff = time.time() - self.max_age_h * 3600
        with self._lock:
            return [r for r in self.items if symbol in r["symbols"] and r["ts"] >= cutoff]

    def refresh_insights(self, symbols: set[str] | None = None) -> None:
        """symbols=None → all NIFTY 50 (first run); otherwise only stocks that just got news."""
        syms = list(symbols) if symbols is not None else SYMBOLS
        if not syms:
            return
        self.prices.load(syms)
        changed = []
        for s in syms:
            try:
                df, is_demo = self.prices.get(s)
                ins = build(s, df, self.news_for(s), self.cfg, is_demo)
                sig = f"{ins['action']}|{ins['news_count']}"
                if self.llm is not None and ins["news_count"] and ins["action"] in ("BUY", "SELL"):
                    old = self.theses.get(s)
                    if not old or old[0] != sig:
                        t = headline_thesis(self.llm, ins)
                        if t:
                            self.theses[s] = (sig, t)
                ins["thesis"] = self.theses.get(s, (None, None))[1]
                self.insights[s] = ins
                changed.append(ins)
            except Exception as e:
                log.warning("insight %s failed: %s", s, e)
        if symbols is not None:
            for ins in changed:
                self._emit("insight", ins)

    # ── listeners / loop ──────────────────────────────────
    def _emit(self, event: str, payload: dict) -> None:
        for fn in list(self.listeners):
            try:
                fn(event, payload)
            except Exception:
                pass

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.cycle()
            except Exception as e:
                log.exception("news cycle failed: %s", e)
            self._stop.wait(self.poll if not demo.enabled() else min(self.poll, 20))

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name="news-engine", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        return {"model": self.nlp.label, "backend": self.nlp.backend, "event_model": self.nlp.event_model,
                "poll_seconds": self.poll, "last_poll": self.last_poll, "items": len(self.items),
                "cycles": self.cycles, "llm_thesis": self.llm is not None,
                "now": datetime.now(timezone.utc).isoformat()}
