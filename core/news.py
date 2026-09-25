"""Indian market news from public RSS (ET, Moneycontrol, BS, Mint, NSE announcements, Google News).

Pure requests + xml.etree — no feedparser dependency.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from html import unescape
from urllib.parse import quote_plus

import requests

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (StockPilot news reader)"}

POS = {"surge", "jumps", "rally", "gains", "beats", "record", "upgrade", "buy", "order win", "bags", "profit rises",
       "soars", "bullish", "outperform", "approval", "dividend", "bonus", "acquires", "strong", "higher"}
NEG = {"falls", "slumps", "plunge", "loss", "downgrade", "sell", "misses", "probe", "penalty", "fraud", "raid",
       "weak", "decline", "bearish", "cuts", "resigns", "default", "lower", "crash", "sebi order", "tumbles"}


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


@lru_cache(maxsize=64)
def _fetch_feed(url: str, _bucket: int) -> tuple:
    """_bucket makes the cache expire every ~10 minutes."""
    try:
        r = requests.get(url, headers=UA, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log.debug("feed %s failed: %s", url, e)
        return ()
    items = []
    source = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "link": (it.findtext("link") or "").strip(),
            "published": _parse_date(it.findtext("pubDate")),
            "source": source,
            "summary": _strip_html(it.findtext("description") or "")[:500],
        })
    return tuple(items)


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _bucket() -> int:
    return int(datetime.now().timestamp() // 600)


def market_news(cfg: dict, limit: int = 30) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg["news"].get("max_age_hours", 36))
    out, seen = [], set()
    for url in cfg["news"]["feeds"]:
        for it in _fetch_feed(url, _bucket()):
            if it["title"].lower() in seen or (it["published"] and it["published"] < cutoff):
                continue
            seen.add(it["title"].lower()); out.append(it)
    out.sort(key=lambda x: x["published"] or cutoff, reverse=True)
    return out[:limit]


def stock_news(symbol: str, cfg: dict, company: str | None = None, limit: int = 8) -> list[dict]:
    keys = {symbol.lower()}
    if company:
        keys.add(company.lower().replace(" limited", "").replace(" ltd", "").strip())
    # word-boundary match: "LT" must not match "result", "ITC" must not match "pitch"
    pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys if k) + r")\b", re.I)
    hits = [n for n in market_news(cfg, limit=300) if pat.search(n["title"])]
    if cfg["news"].get("google_news_per_symbol", True):
        q = quote_plus(f"{company or symbol} share NSE")
        url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg["news"].get("max_age_hours", 36) * 2)
        hits += [n for n in _fetch_feed(url, _bucket()) if not n["published"] or n["published"] >= cutoff]
    uniq = {n["title"]: n for n in hits}
    return sorted(uniq.values(), key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc),
                  reverse=True)[:limit]


def keyword_sentiment(headlines: list[str]) -> float:
    """Cheap fallback when no LLM is available. Returns [-1, 1]."""
    if not headlines:
        return 0.0
    s = 0
    for h in headlines:
        h = h.lower()
        s += sum(w in h for w in POS) - sum(w in h for w in NEG)
    return max(-1.0, min(1.0, s / (2 * len(headlines))))
