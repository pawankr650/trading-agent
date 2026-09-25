"""Broker adapters. PaperBroker (default, no money) and OpenAlgoBroker (30+ Indian brokers: Zerodha,
Angel One, Upstox, Dhan, Fyers, Shoonya, ...). Both expose the same small interface."""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid

from core.market_data import get_ltp

log = logging.getLogger(__name__)


class RateLimiter:
    """Keeps order rate under SEBI's 10 orders/sec retail-algo threshold."""

    def __init__(self, per_second: int):
        self.min_gap, self.last, self.lock = 1.0 / max(1, per_second), 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            gap = time.time() - self.last
            if gap < self.min_gap:
                time.sleep(self.min_gap - gap)
            self.last = time.time()


class PaperBroker:
    mode = "paper"

    def __init__(self, cfg: dict, slippage_pct: float = 0.05):
        self.cfg, self.slip = cfg, slippage_pct / 100
        self.qty: dict[str, int] = {}

    def ltp(self, symbol: str) -> float:
        return get_ltp(symbol, self.cfg)

    def place_order(self, symbol, action, qty, price_type="MARKET", trigger_price=0.0, product="CNC"):
        if price_type == "SL-M":  # paper stop is enforced by the engine, just acknowledge
            return {"status": "success", "orderid": "PAPER-SL-" + uuid.uuid4().hex[:8], "price": trigger_price}
        px = self.ltp(symbol)
        px = px * (1 + self.slip) if action == "BUY" else px * (1 - self.slip)
        self.qty[symbol] = self.qty.get(symbol, 0) + (qty if action == "BUY" else -qty)
        return {"status": "success", "orderid": "PAPER-" + uuid.uuid4().hex[:8], "price": round(px, 2)}

    def cancel_order(self, order_id: str):
        return {"status": "success"}

    def position_qty(self, symbol: str, product: str = "CNC") -> int | None:
        return None  # paper: engine's journal is the source of truth


class OpenAlgoBroker:
    """Talks to a self-hosted OpenAlgo server (https://github.com/marketcalls/openalgo).
    Tip: switch OpenAlgo to *Analyzer mode* first — orders are simulated by OpenAlgo itself."""
    mode = "live"
    STRATEGY = "StockPilot"

    def __init__(self, cfg: dict):
        from openalgo import api
        self.cfg, self.ex = cfg, cfg.get("exchange", "NSE")
        self.c = api(api_key=os.environ["OPENALGO_API_KEY"], host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"))

    def ltp(self, symbol: str) -> float:
        return float(self.c.quotes(symbol=symbol, exchange=self.ex)["data"]["ltp"])

    def place_order(self, symbol, action, qty, price_type="MARKET", trigger_price=0.0, product="CNC"):
        kw = dict(strategy=self.STRATEGY, symbol=symbol, action=action, exchange=self.ex,
                  price_type=price_type, product=product, quantity=int(qty))
        if price_type in ("SL", "SL-M"):
            kw["trigger_price"] = round(trigger_price, 1)
        res = self.c.placeorder(**kw)
        if res.get("status") == "success" and price_type == "MARKET":
            res["price"] = self.ltp(symbol)  # approximate fill; reconcile from orderbook if needed
        return res

    def cancel_order(self, order_id: str):
        return self.c.cancelorder(order_id=order_id, strategy=self.STRATEGY)

    def position_qty(self, symbol: str, product: str = "CNC") -> int | None:
        try:
            r = self.c.openposition(strategy=self.STRATEGY, symbol=symbol, exchange=self.ex, product=product)
            return int(float(r.get("quantity", 0)))
        except Exception as e:
            log.warning("openposition %s failed: %s", symbol, e)
            return None


def make_broker(cfg: dict):
    return OpenAlgoBroker(cfg) if cfg["autotrader"]["mode"] == "live" else PaperBroker(cfg)
