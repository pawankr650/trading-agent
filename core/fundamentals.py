"""Fundamental snapshot + score from free Yahoo Finance data (works for .NS/.BO)."""
from __future__ import annotations

import logging

import numpy as np

from .market_data import yf_ticker

log = logging.getLogger(__name__)

FIELDS = {
    "marketCap": "Market cap", "trailingPE": "P/E", "priceToBook": "P/B",
    "returnOnEquity": "ROE", "debtToEquity": "Debt/Equity", "revenueGrowth": "Revenue growth (YoY)",
    "earningsGrowth": "Earnings growth (YoY)", "profitMargins": "Net margin",
    "dividendYield": "Dividend yield", "sector": "Sector", "longName": "Name",
}


def get_fundamentals(symbol: str, exchange: str = "NSE") -> dict:
    try:
        import yfinance as yf
        info = yf.Ticker(yf_ticker(symbol, exchange)).info or {}
    except Exception as e:  # network / rate-limit
        log.warning("fundamentals %s failed: %s", symbol, e)
        info = {}
    return {k: info.get(k) for k in FIELDS}


def fundamental_score(f: dict) -> tuple[float, list[str]]:
    pts, why = [], []

    def rule(val, good, bad, w, good_txt, bad_txt):
        if val is None:
            return
        if good(val):
            pts.append(w); why.append(f"✅ {good_txt}")
        elif bad(val):
            pts.append(-w); why.append(f"❌ {bad_txt}")
        else:
            pts.append(0)

    pct = lambda v: f"{v*100:.1f}%"
    rule(f.get("returnOnEquity"), lambda v: v > 0.15, lambda v: v < 0.08, 1,
         f"ROE {pct(f.get('returnOnEquity') or 0)} (>15%)", f"ROE {pct(f.get('returnOnEquity') or 0)} (weak)")
    rule(f.get("debtToEquity"), lambda v: v < 50, lambda v: v > 150, 1,  # yfinance reports D/E in %
         "Low debt", f"High debt (D/E {((f.get('debtToEquity') or 0)/100):.1f}x)")
    rule(f.get("revenueGrowth"), lambda v: v > 0.10, lambda v: v < 0, 1,
         f"Revenue growing {pct(f.get('revenueGrowth') or 0)}", f"Revenue shrinking {pct(f.get('revenueGrowth') or 0)}")
    rule(f.get("earningsGrowth"), lambda v: v > 0.10, lambda v: v < 0, 1,
         f"Profit growing {pct(f.get('earningsGrowth') or 0)}", f"Profit falling {pct(f.get('earningsGrowth') or 0)}")
    rule(f.get("profitMargins"), lambda v: v > 0.12, lambda v: v < 0.03, 0.5, "Healthy net margin", "Thin net margin")
    rule(f.get("trailingPE"), lambda v: 0 < v < 25, lambda v: v > 60 or v <= 0, 0.5,
         f"Reasonable P/E {f.get('trailingPE') or 0:.1f}", f"Stretched/negative P/E {f.get('trailingPE') or 0:.1f}")
    if not pts:
        return 0.0, ["Fundamentals unavailable"]
    return float(np.clip(sum(pts) / 5.0, -1, 1)), why
