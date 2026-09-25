"""Cached OHLCV for many symbols (one bulk yfinance call), with demo fallback when offline."""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta

import pandas as pd

from . import demo
from .market_data import get_history, yf_ticker

log = logging.getLogger(__name__)
TTL = 15 * 60


class PriceStore:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._cache: dict[str, tuple[float, pd.DataFrame, bool]] = {}
        self._long: dict[str, tuple[float, pd.DataFrame, bool]] = {}
        self._lock = threading.Lock()

    def _fresh(self, sym: str) -> bool:
        hit = self._cache.get(sym)
        return bool(hit) and time.time() - hit[0] < TTL

    def _bulk_yf(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        import yfinance as yf
        ex = self.cfg.get("exchange", "NSE")
        start = date.today() - timedelta(days=int(self.cfg["data"].get("lookback_days", 400)))
        tick = {yf_ticker(s, ex): s for s in symbols}
        raw = yf.download(list(tick), start=str(start), interval=self.cfg["data"].get("interval", "1d"),
                          group_by="ticker", auto_adjust=True, progress=False, threads=True)
        out = {}
        for t, s in tick.items():
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(df) > 30:
                    out[s] = df
            except Exception:
                pass
        return out

    def load(self, symbols: list[str]) -> None:
        need = [s for s in symbols if not self._fresh(s)]
        if not need:
            return
        got: dict[str, pd.DataFrame] = {}
        if not demo.enabled():
            try:
                if self.cfg["data"].get("source") == "openalgo":
                    for s in need:
                        got[s] = get_history(s, self.cfg)
                else:
                    got = self._bulk_yf(need)
            except Exception as e:
                log.warning("price download failed (%s) — using demo data", e)
        now = time.time()
        with self._lock:
            for s in need:
                if s in got:
                    self._cache[s] = (now, got[s], False)
                else:
                    self._cache[s] = (now, demo.ohlcv(s, int(self.cfg["data"].get("lookback_days", 400))), True)

    def get(self, symbol: str) -> tuple[pd.DataFrame, bool]:
        """(OHLCV, is_demo)."""
        self.load([symbol])
        _, df, is_demo = self._cache[symbol]
        return df, is_demo

    def history(self, symbol: str, years: float) -> tuple[pd.DataFrame, bool]:
        """Longer daily history for backtests (separate cache from the scanner's lookback)."""
        key = f"{symbol}|{years}"
        hit = self._long.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1], hit[2]
        days = int(365 * years) + 5
        df, is_demo = None, True
        if not demo.enabled():
            try:
                import yfinance as yf
                df = yf.download(yf_ticker(symbol, self.cfg.get("exchange", "NSE")),
                                 start=str(date.today() - timedelta(days=days)), interval="1d",
                                 auto_adjust=True, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                is_demo = len(df) < 60
            except Exception as e:
                log.warning("history %s failed (%s) — using demo data", symbol, e)
        if is_demo:
            df = demo.ohlcv(symbol, days)
        self._long[key] = (time.time(), df, is_demo)
        return df, is_demo

    def any_demo(self) -> bool:
        return any(v[2] for v in self._cache.values())
