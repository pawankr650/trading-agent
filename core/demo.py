"""Offline demo data, used ONLY when live sources are unreachable (or STOCKPILOT_DEMO=1).

Everything produced here is flagged `demo=True` so the UI can badge it — it is synthetic, not market data.
"""
from __future__ import annotations

import os
import random
import zlib
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .nifty50 import NIFTY50, name


def enabled() -> bool:
    return os.getenv("STOCKPILOT_DEMO", "").lower() in ("1", "true", "yes")


def _seed(symbol: str) -> int:
    return zlib.crc32(symbol.encode())


def ohlcv(symbol: str, days: int = 400) -> pd.DataFrame:
    """Deterministic regime-switching random walk per symbol (trends, ranges and reversals).

    Always simulates ~10 years and returns the tail, so a longer request extends the same series."""
    rng = np.random.default_rng(_seed(symbol))
    n = 2600
    base = float(rng.uniform(150, 4500))
    drift = np.repeat(rng.normal(0.0004, 0.0025, n // 40 + 1), 40)[:n]
    vol = np.repeat(rng.uniform(0.008, 0.02, n // 60 + 1), 60)[:n]
    close = base * np.cumprod(1 + drift + rng.normal(0, 1, n) * vol)
    op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, n))
    hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    v = rng.lognormal(13, 0.4, n) * (1 + 3 * (np.abs(close / op - 1) > 0.02))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    df = pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": close, "Volume": v.round()}, index=idx)
    return df[df.index >= idx[-1] - pd.Timedelta(days=days)]


_TEMPLATES = [
    ("{n} Q2 net profit rises 18% YoY, beats street estimates", +1),
    ("{n} bags ₹2,400 crore order from state utility", +1),
    ("Brokerage upgrades {n} to buy, raises target price", +1),
    ("{n} board approves share buyback at a premium", +1),
    ("{n} shares surge after strong monthly sales numbers", +1),
    ("{n} announces capacity expansion with new plant", +1),
    ("{n} slumps as margins miss estimates on higher costs", -1),
    ("SEBI issues show-cause notice to {n} over disclosure lapses", -1),
    ("{n} shares fall after brokerage downgrade on valuation concerns", -1),
    ("Promoter stake sale in {n} via block deal weighs on stock", -1),
    ("{n} CFO resigns; stock declines in early trade", -1),
    ("{n} to hold board meeting to consider fund raising", 0),
    ("{n} completes acquisition of minority stake in unit", 0),
]
_MACRO = [
    "RBI keeps repo rate unchanged, retains neutral stance",
    "FIIs turn net buyers in Indian equities for third straight session",
    "Rupee weakens past 88 per dollar as crude prices climb",
    "GST collections rise 9% year-on-year in September",
    "Nifty ends higher led by banks and IT; midcaps outperform",
]


def headlines(k: int = 6) -> list[dict]:
    """A fresh batch of SAMPLE headlines (clearly marked as demo)."""
    now = datetime.now(timezone.utc)
    out = []
    for i in range(k):
        if random.random() < 0.2:
            title = random.choice(_MACRO)
        else:
            sym = random.choice(list(NIFTY50))
            title = random.choice(_TEMPLATES)[0].format(n=name(sym))
        out.append({"title": title, "link": "", "source": "demo feed",
                    "published": now - timedelta(minutes=random.randint(0, 50)), "demo": True})
    return out
