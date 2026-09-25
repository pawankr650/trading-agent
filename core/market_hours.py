"""NSE/BSE session helpers (IST)."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def is_trading_day(cfg: dict, dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    return dt.weekday() < 5 and dt.strftime("%Y-%m-%d") not in set(cfg["market"].get("holidays") or [])


def is_market_open(cfg: dict, dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    m = cfg["market"]
    return is_trading_day(cfg, dt) and parse_hhmm(m["open"]) <= dt.time() <= parse_hhmm(m["close"])


def past(hhmm: str, dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    return dt.time() >= parse_hhmm(hhmm)
