"""Exchange corporate announcements (NSE + BSE) — the "order win / results / dividend / M&A" filings feed.

Companies must file price-sensitive events with the exchange first, so this is usually faster and more
reliable than media news. Both endpoints are public but unofficial; every fetch is best-effort and
returns [] on failure so the news scan still works with RSS only.

Each item: {title, link, published, source, summary, symbol, company, category, event}
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import requests

from .market_hours import IST

log = logging.getLogger(__name__)

BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# event type -> keywords (checked against category + headline). Order matters: first match wins.
EVENTS: list[tuple[str, tuple[str, ...]]] = [
    ("order_win", ("bagging", "receiving of order", "order win", "bags order", "bags", "wins order", "order worth",
                   "order from", "orders worth", "contract", "letter of award", " loa ", "work order", "purchase order",
                   "secures", "l1 bidder", "lowest bidder")),
    ("results", ("financial result", "quarterly result", "q1 ", "q2 ", "q3 ", "q4 ", "net profit", "earnings",
                 "profit rises", "profit falls", "revenue", "ebitda")),
    ("dividend_bonus_split", ("dividend", "bonus", "split", "sub-division", "buyback", "buy back", "record date")),
    ("mna", ("acquisition", "acquire", "merger", "amalgamation", "demerger", "stake", "joint venture", "takeover")),
    ("fund_raise", ("qip", "preferential", "rights issue", "fund raising", "raise funds", "ncd", "allotment")),
    ("rating", ("credit rating", " rating", "upgrade", "downgrade", "target price")),
    ("management", ("resign", "appointment", "ceo", "managing director", "cfo", "auditor")),
    ("regulatory", ("sebi", "penalty", "show cause", " search", " raid", "fraud", "default", "insolvency", "nclt",
                    "gst demand", "income tax", "litigation", "pledge")),
    ("capacity_expansion", ("capex", "expansion", "new plant", "commissioning", "capacity")),
    ("guidance", ("guidance", "outlook", "investor presentation", "analyst meet", "earnings call")),
]
# routine filings that almost never move a stock
NOISE = ("trading window", "newspaper publication", "copy of newspaper", "certificate under regulation",
         "compliance certificate", "loss of share certificate", "duplicate share", "74(5)", "closure of trading",
         "statement of investor complaints", "reg. 39", "esop", "esos", "shareholding pattern")


def classify_event(text: str) -> str:
    t = f" {text.lower()} "
    for event, keys in EVENTS:
        if any(k in t for k in keys):
            return event
    return "other"


def is_noise(text: str) -> bool:
    t = text.lower()
    return any(n in t for n in NOISE)


def _parse(s: str | None, fmts: tuple[str, ...]) -> datetime | None:
    if not s:
        return None
    for f in fmts:
        try:
            return datetime.strptime(s.strip(), f).replace(tzinfo=IST).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


# ── NSE ────────────────────────────────────────────────────
def nse_announcements(hours: int = 24, timeout: int = 12) -> list[dict]:
    """https://www.nseindia.com/companies-listing/corporate-filings-announcements (JSON behind it)."""
    s = requests.Session()
    s.headers.update(BROWSER)
    try:
        s.get("https://www.nseindia.com/", timeout=timeout)  # sets the cookies the API insists on
        r = s.get("https://www.nseindia.com/api/corporate-announcements", params={"index": "equities"},
                  headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"},
                  timeout=timeout)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:
        log.info("NSE announcements unavailable: %s", e)
        return []
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for a in rows or []:
        cat, text = (a.get("desc") or "").strip(), (a.get("attchmntText") or "").strip()
        pub = _parse(a.get("an_dt") or a.get("sort_date"), ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"))
        if (pub and pub < cutoff) or is_noise(f"{cat} {text}"):
            continue
        sym = (a.get("symbol") or "").strip().upper()
        out.append({
            "title": f"{sym}: {cat}" + (f" — {text[:160]}" if text else ""),
            "link": a.get("attchmntFile") or "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            "published": pub, "source": "NSE filing", "summary": text[:800],
            "symbol": sym, "company": a.get("sm_name") or sym, "category": cat,
            "event": classify_event(f"{cat} {text}"),
        })
    return out


# ── BSE ────────────────────────────────────────────────────
def bse_announcements(hours: int = 24, timeout: int = 12) -> list[dict]:
    """https://www.bseindia.com/corporates/ann.html (JSON behind it). Symbols are BSE scrip codes."""
    today = datetime.now(IST)
    params = {"pageno": 1, "strCat": -1, "strPrevDate": (today - timedelta(days=1)).strftime("%Y%m%d"),
              "strScrip": "", "strSearch": "P", "strToDate": today.strftime("%Y%m%d"), "strType": "C",
              "subcategory": -1}
    try:
        r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w", params=params,
                         headers={**BROWSER, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"},
                         timeout=timeout)
        r.raise_for_status()
        rows = r.json().get("Table", [])
    except Exception as e:
        log.info("BSE announcements unavailable: %s", e)
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for a in rows:
        head, cat = (a.get("HEADLINE") or a.get("NEWSSUB") or "").strip(), (a.get("CATEGORYNAME") or "").strip()
        pub = _parse((a.get("NEWS_DT") or "").split(".")[0], ("%Y-%m-%dT%H:%M:%S",))
        if (pub and pub < cutoff) or is_noise(f"{cat} {head}"):
            continue
        company = (a.get("SLONGNAME") or "").strip()
        att = a.get("ATTACHMENTNAME")
        out.append({
            "title": f"{company}: {head[:200]}",
            "link": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else
                    (a.get("NSURL") or "https://www.bseindia.com/corporates/ann.html"),
            "published": pub, "source": "BSE filing", "summary": head[:800],
            "symbol": "", "bse_code": str(a.get("SCRIP_CD") or ""), "company": company, "category": cat,
            "event": classify_event(f"{cat} {head}"),
        })
    return out


def exchange_announcements(cfg: dict) -> list[dict]:
    ncfg = cfg.get("news_scanner", {})
    hours = int(ncfg.get("announcement_hours", 24))
    items: list[dict] = []
    if ncfg.get("nse_announcements", True):
        items += nse_announcements(hours)
    if ncfg.get("bse_announcements", True):
        items += bse_announcements(hours)
    return items


def normalise_symbol(s: str) -> str:
    return re.sub(r"[^A-Z0-9&\-]", "", (s or "").upper().replace(".NS", "").replace(".BO", ""))
