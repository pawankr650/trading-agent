"""NIFTY 50 universe: NSE symbol -> (company name, sector, extra aliases used to tag news headlines).

Constituents change twice a year (NSE rebalances in March / September) — edit this table when they do.
"""
from __future__ import annotations

import re

NIFTY50: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ADANIENT": ("Adani Enterprises", "Metals & Mining", ("adani ent", "adani group")),
    "ADANIPORTS": ("Adani Ports & SEZ", "Services", ("adani ports", "apsez")),
    "APOLLOHOSP": ("Apollo Hospitals", "Healthcare", ("apollo hospital",)),
    "ASIANPAINT": ("Asian Paints", "Consumer", ("asian paints",)),
    "AXISBANK": ("Axis Bank", "Financials", ("axis bank",)),
    "BAJAJ-AUTO": ("Bajaj Auto", "Auto", ("bajaj auto",)),
    "BAJFINANCE": ("Bajaj Finance", "Financials", ("bajaj finance",)),
    "BAJAJFINSV": ("Bajaj Finserv", "Financials", ("bajaj finserv",)),
    "BEL": ("Bharat Electronics", "Capital Goods", ("bharat electronics",)),
    "BHARTIARTL": ("Bharti Airtel", "Telecom", ("airtel", "bharti")),
    "CIPLA": ("Cipla", "Healthcare", ("cipla",)),
    "COALINDIA": ("Coal India", "Energy", ("coal india",)),
    "DRREDDY": ("Dr. Reddy's Laboratories", "Healthcare", ("dr reddy", "dr. reddy")),
    "EICHERMOT": ("Eicher Motors", "Auto", ("eicher", "royal enfield")),
    "ETERNAL": ("Eternal (Zomato)", "Consumer Services", ("eternal ltd", "zomato", "blinkit")),
    "GRASIM": ("Grasim Industries", "Materials", ("grasim",)),
    "HCLTECH": ("HCL Technologies", "IT", ("hcl tech", "hcltech")),
    "HDFCBANK": ("HDFC Bank", "Financials", ("hdfc bank",)),
    "HDFCLIFE": ("HDFC Life Insurance", "Financials", ("hdfc life",)),
    "HINDALCO": ("Hindalco Industries", "Metals & Mining", ("hindalco", "novelis")),
    "HINDUNILVR": ("Hindustan Unilever", "FMCG", ("hindustan unilever", "hul")),
    "ICICIBANK": ("ICICI Bank", "Financials", ("icici bank",)),
    "INDIGO": ("InterGlobe Aviation", "Services", ("indigo", "interglobe")),
    "INFY": ("Infosys", "IT", ("infosys",)),
    "ITC": ("ITC", "FMCG", ("itc ltd", "itc hotels")),
    "JIOFIN": ("Jio Financial Services", "Financials", ("jio financial", "jio fin")),
    "JSWSTEEL": ("JSW Steel", "Metals & Mining", ("jsw steel",)),
    "KOTAKBANK": ("Kotak Mahindra Bank", "Financials", ("kotak",)),
    "LT": ("Larsen & Toubro", "Capital Goods", ("larsen", "l&t")),
    "M&M": ("Mahindra & Mahindra", "Auto", ("mahindra", "m&m")),
    "MARUTI": ("Maruti Suzuki", "Auto", ("maruti",)),
    "MAXHEALTH": ("Max Healthcare", "Healthcare", ("max healthcare",)),
    "NESTLEIND": ("Nestle India", "FMCG", ("nestle",)),
    "NTPC": ("NTPC", "Power", ("ntpc",)),
    "ONGC": ("Oil & Natural Gas Corp", "Energy", ("ongc",)),
    "POWERGRID": ("Power Grid Corp", "Power", ("power grid", "powergrid")),
    "RELIANCE": ("Reliance Industries", "Energy", ("reliance", "ril", "jio platforms")),
    "SBILIFE": ("SBI Life Insurance", "Financials", ("sbi life",)),
    "SBIN": ("State Bank of India", "Financials", ("sbi", "state bank")),
    "SHRIRAMFIN": ("Shriram Finance", "Financials", ("shriram finance",)),
    "SUNPHARMA": ("Sun Pharmaceutical", "Healthcare", ("sun pharma",)),
    "TATACONSUM": ("Tata Consumer Products", "FMCG", ("tata consumer",)),
    "TMPV": ("Tata Motors (Passenger Vehicles)", "Auto", ("tata motors", "jaguar land rover", "jlr")),
    "TATASTEEL": ("Tata Steel", "Metals & Mining", ("tata steel",)),
    "TCS": ("Tata Consultancy Services", "IT", ("tcs", "tata consultancy")),
    "TECHM": ("Tech Mahindra", "IT", ("tech mahindra", "techm")),
    "TITAN": ("Titan Company", "Consumer", ("titan",)),
    "TRENT": ("Trent", "Consumer", ("trent", "zudio", "westside")),
    "ULTRACEMCO": ("UltraTech Cement", "Materials", ("ultratech",)),
    "WIPRO": ("Wipro", "IT", ("wipro",)),
}

SYMBOLS = list(NIFTY50)

# "sbi life" must not also count as "sbi": longer aliases are matched first and consume their span.
_ALIASES = sorted(((a, s) for s, (_, _, al) in NIFTY50.items() for a in al), key=lambda x: -len(x[0]))
_PATTERNS = [(re.compile(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])"), s) for a, s in _ALIASES]


def name(symbol: str) -> str:
    return NIFTY50.get(symbol, (symbol, "", ()))[0]


def sector(symbol: str) -> str:
    return NIFTY50.get(symbol, ("", "Other", ()))[1]


def tag_symbols(text: str) -> list[str]:
    """NIFTY 50 symbols mentioned in a headline (alias match on word boundaries)."""
    t = text.lower()
    found: list[str] = []
    for pat, sym in _PATTERNS:
        if pat.search(t):
            t = pat.sub(" ", t)
            if sym not in found:
                found.append(sym)
    return found
