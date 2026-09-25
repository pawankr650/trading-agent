"""SYSTEM 2 — Auto-trading engine.

Pipeline per cycle:
  1. manage open positions  (stop-loss / target / MIS square-off / broker-side SL reconciliation)
  2. risk gate              (kill switch, daily loss, max positions, entry window)
  3. signals                (same analyze() as System 1: technical + fundamental + news)
  4. AI veto                (LLM must agree; optional TradingAgents multi-agent debate)
  5. size -> order -> protective SL-M -> journal -> Telegram
"""
from __future__ import annotations

import logging
import os

from core.analysis import scan
from core.llm import LLM
from core.market_hours import past
from notifier.telegram import Telegram

from .broker import RateLimiter, make_broker
from .journal import Journal
from .risk import RiskManager

log = logging.getLogger("autotrader")


def tradingagents_decision(symbol: str, exchange: str) -> str | None:
    """Optional deep check with TauricResearch/TradingAgents (Apache-2.0). Slow: ~1-3 min & many LLM calls."""
    try:
        from datetime import date

        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        conf = DEFAULT_CONFIG.copy()  # set llm_provider/backend_url there to a free provider (e.g. google/ollama)
        _, decision = TradingAgentsGraph(config=conf).propagate(symbol + (".NS" if exchange == "NSE" else ".BO"),
                                                                 str(date.today()))
        d = str(decision).upper()
        return next((a for a in ("BUY", "SELL", "HOLD") if a in d), None)
    except Exception as e:
        log.info("TradingAgents unavailable/failed: %s", e)
        return None


class AutoTrader:
    def __init__(self, cfg: dict, broker=None, journal: Journal | None = None, llm: LLM | None = None,
                 telegram: Telegram | None = None, scanner=scan):
        self.cfg, self.a = cfg, cfg["autotrader"]
        self.broker = broker or make_broker(cfg)
        self.journal = journal or Journal()
        self.llm = llm if llm is not None else LLM(cfg)
        # separate bot for trade updates so its command polling doesn't clash with System 1
        self.tg = telegram or Telegram(token=os.getenv("TELEGRAM_TRADER_BOT_TOKEN") or None)
        self.risk = RiskManager(cfg)
        self.rl = RateLimiter(self.a.get("max_orders_per_second", 5))
        self.scanner = scanner
        self._halt_notified = False

    # ── helpers ─────────────────────────────────────────────
    def _order(self, symbol, action, qty, **kw):
        self.rl.wait()
        res = self.broker.place_order(symbol, action, qty, product=self.a["product"], **kw)
        log.info("ORDER %s %s x%s %s -> %s", action, symbol, qty, kw, res)
        return res

    def _exit(self, t: dict, px: float, reason: str) -> None:
        if t.get("sl_order_id"):
            self.broker.cancel_order(t["sl_order_id"])
        side = "SELL" if t["side"] == "BUY" else "BUY"
        res = self._order(t["symbol"], side, t["qty"])
        if res.get("status") != "success":
            self.tg.send(f"⚠️ EXIT FAILED {t['symbol']}: {res}"); return
        fill = res.get("price", px)
        pnl = self.journal.close(t["id"], fill, reason)
        self.tg.send(f"{'✅' if pnl >= 0 else '🛑'} <b>EXIT {t['symbol']}</b> ({reason}) @ ₹{fill:.2f} · "
                     f"P&L ₹{pnl:,.0f} · [{self.broker.mode}]")

    def unrealized(self, prices: dict[str, float]) -> float:
        tot = 0.0
        for t in self.journal.open_trades():
            px = prices.get(t["symbol"])
            if px:
                tot += (px - t["entry"]) * t["qty"] * (1 if t["side"] == "BUY" else -1)
        return tot

    # ── 1. manage positions ────────────────────────────────
    def manage_positions(self) -> dict[str, float]:
        prices: dict[str, float] = {}
        square_off = self.a["product"] == "MIS" and past(self.a["mis_square_off"])
        for t in self.journal.open_trades():
            try:
                px = prices[t["symbol"]] = self.broker.ltp(t["symbol"])
            except Exception as e:
                log.warning("ltp %s failed: %s", t["symbol"], e); continue
            # live: broker-side SL-M may already have closed it
            bq = self.broker.position_qty(t["symbol"], self.a["product"])
            if bq == 0:
                pnl = self.journal.close(t["id"], t["stop"], "broker SL filled")
                self.tg.send(f"🛑 <b>{t['symbol']}</b> stop-loss filled at broker · P&L ≈ ₹{pnl:,.0f}")
                continue
            long_ = t["side"] == "BUY"
            if square_off:
                self._exit(t, px, "MIS square-off")
            elif (long_ and px <= t["stop"]) or (not long_ and px >= t["stop"]):
                self._exit(t, px, "stop-loss")
            elif (long_ and px >= t["target"]) or (not long_ and px <= t["target"]):
                self._exit(t, px, "target")
        return prices

    # ── 2-5. entries ───────────────────────────────────────
    def confirm(self, r: dict) -> tuple[bool, str]:
        if self.a.get("llm_confirm", True):
            rv = r.get("llm_review")
            if rv is None:
                return False, "LLM unavailable (llm_confirm=true blocks entry)"
            if str(rv.get("action", "")).upper() != r["action"]:
                return False, f"LLM disagrees: {rv.get('action')} — {rv.get('rationale', '')}"
        if self.a.get("tradingagents_confirm"):
            d = tradingagents_decision(r["symbol"], self.cfg.get("exchange", "NSE"))
            if d != r["action"]:
                return False, f"TradingAgents says {d}"
        return True, "confirmed"

    def enter(self, r: dict) -> bool:
        side, plan = r["action"], r["plan"]
        if side == "SELL" and not (self.a.get("allow_short") and self.a["product"] == "MIS"):
            return False
        qty = self.risk.size(plan["entry"], plan["stop"])
        if qty < 1:
            return False
        res = self._order(r["symbol"], side, qty)
        if res.get("status") != "success":
            self.tg.send(f"⚠️ ENTRY FAILED {r['symbol']}: {res}"); return False
        fill = float(res.get("price") or plan["entry"])
        shift = fill - plan["entry"]  # keep the planned risk distance around the real fill
        stop, target = round(plan["stop"] + shift, 2), round(plan["target"] + shift, 2)
        sl = self._order(r["symbol"], "SELL" if side == "BUY" else "BUY", qty, price_type="SL-M", trigger_price=stop)
        self.journal.add(mode=self.broker.mode, symbol=r["symbol"], side=side, qty=qty, entry=fill, stop=stop,
                         target=target, sl_order_id=sl.get("orderid"),
                         reason_in=f"score {r['score']:+.2f}; " + "; ".join(r["criteria"][:4]))
        rv = r.get("llm_review") or {}
        self.tg.send(f"🚀 <b>{side} {r['symbol']}</b> x{qty} @ ₹{fill:.2f} · SL {stop} · TGT {target} "
                     f"[{self.broker.mode}]\nScore {r['score']:+.2f} · AI: {rv.get('rationale', '–')}")
        return True

    def cycle(self) -> None:
        prices = self.manage_positions()
        open_now = self.journal.open_trades()
        ok, why = self.risk.can_enter(len(open_now), self.journal.realized_today(), self.unrealized(prices))
        if not ok:
            if why == "daily loss limit reached" and not self._halt_notified:
                self.tg.send("⛔ Daily loss limit hit — no new entries today."); self._halt_notified = True
            log.info("no entries: %s", why); return
        held = {t["symbol"] for t in open_now}
        slots = self.a["max_open_positions"] - len(open_now)
        reports = self.scanner(self.cfg, self.llm, review=bool(self.a.get("llm_confirm", True)))
        candidates = [r for r in reports if r["action"] in ("BUY", "SELL") and r["symbol"] not in held and r["plan"]]
        candidates.sort(key=lambda r: abs(r["score"]), reverse=True)
        for r in candidates:
            if slots <= 0:
                break
            good, why = self.confirm(r)
            if not good:
                log.info("skip %s: %s", r["symbol"], why); continue
            if self.enter(r):
                slots -= 1
