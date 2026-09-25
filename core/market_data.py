"""OHLCV + last price. yfinance (free, delayed) or OpenAlgo (live via your broker)."""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import pandas as pd

log = logging.getLogger(__name__)
_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


def yf_ticker(symbol: str, exchange: str = "NSE") -> str:
    return symbol if "." in symbol else symbol + _SUFFIX.get(exchange, ".NS")


def _openalgo_client():
    from openalgo import api  # lazy: optional dependency
    return api(api_key=os.environ["OPENALGO_API_KEY"], host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"))


def get_history(symbol: str, cfg: dict) -> pd.DataFrame:
    d, ex = cfg["data"], cfg.get("exchange", "NSE")
    start = date.today() - timedelta(days=int(d.get("lookback_days", 400)))
    if d.get("source") == "openalgo":
        df = _openalgo_client().history(symbol=symbol, exchange=ex, interval=d.get("interval", "D"),
                                        start_date=str(start), end_date=str(date.today()))
        df = df.rename(columns=str.capitalize)
    else:
        import yfinance as yf
        df = yf.download(yf_ticker(symbol, ex), start=str(start), interval=d.get("interval", "1d"),
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if df.empty:
        raise ValueError(f"No price data for {symbol}")
    return df


def get_ltp(symbol: str, cfg: dict) -> float:
    ex = cfg.get("exchange", "NSE")
    if cfg["data"].get("source") == "openalgo":
        q = _openalgo_client().quotes(symbol=symbol, exchange=ex)
        return float(q["data"]["ltp"])
    import yfinance as yf
    t = yf.Ticker(yf_ticker(symbol, ex))
    try:
        return float(t.fast_info["last_price"])
    except Exception:
        return float(t.history(period="1d")["Close"].iloc[-1])
