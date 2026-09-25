"""SYSTEM 1 — Signal & notification bot.

Schedule (IST, trading days):
  08:45  pre-market brief: market news + BUY/SELL board from last close
  09:15–15:30 every N min: scan watchlist, alert only when a stock's signal flips
  15:45  end-of-day report
  every N min (07:30–22:00 by default): AI news scan — RSS + NSE/BSE filings (order wins, results, …)
         -> open-source LLM -> detailed BUY / WATCH / AVOID recommendations with reasoning
Telegram commands (any time):  /analyze SYMBOL   /top   /news   /scannews   /help

Run:  python -m notifier.run            (loop)
      python -m notifier.run --once     (single scan, prints/sends and exits)
      python -m notifier.run --news     (one AI news scan now, sends digest and exits)
"""
from __future__ import annotations

import argparse
import json
import threading
import time

from core.analysis import analyze, scan
from core.charts import render_chart
from core.config import DATA_DIR, load_config, setup_logging
from core.llm import LLM
from core.market_hours import is_market_open, is_trading_day, now_ist, past
from core.news import market_news
from core.news_scanner import NewsScanner

from .formatter import board_message, news_digest_message, news_message, signal_message
from .telegram import Telegram

log = setup_logging("notifier")
STATE = DATA_DIR / "notifier_state.json"


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"last_action": {}, "done": {}}


def _save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1))


class Notifier:
    def __init__(self, cfg: dict):
        self.cfg, self.ncfg = cfg, cfg["notifier"]
        self.llm, self.tg = LLM(cfg), Telegram()
        self.news = NewsScanner(cfg, self.llm)
        self.state = _load_state()
        self.state.setdefault("last_action", {}); self.state.setdefault("done", {})

    def alert(self, r: dict) -> None:
        msg = signal_message(r)
        if self.ncfg.get("send_charts", True):
            path = render_chart(r)
            self.tg.send_photo(path, caption=f"{r['symbol']} · {r['action']}")
        self.tg.send(msg)

    def intraday_scan(self) -> list[dict]:
        reports = scan(self.cfg, self.llm, review=True)
        la = self.state["last_action"]
        for r in reports:
            changed = la.get(r["symbol"]) != r["action"]
            strong = abs(r["score"]) >= self.ncfg.get("min_confidence", 0.35)
            if r["action"] != "HOLD" and strong and (changed or not self.ncfg.get("only_on_change", True)):
                self.alert(r)
            la[r["symbol"]] = r["action"]
        _save_state(self.state)
        log.info("scan done: %s", {r["symbol"]: r["action"] for r in reports})
        return reports

    def premarket(self) -> None:
        self.tg.send(news_message(market_news(self.cfg, limit=12)))
        if self.cfg.get("news_scanner", {}).get("enabled", True):
            self.news_scan(force_send=True)
        self.tg.send(board_message(scan(self.cfg, self.llm), f"🌅 Pre-market board · {now_ist():%d %b %Y}"))

    def news_scan(self, only_new: bool = True, chat_id: str | None = None, force_send: bool = False) -> dict:
        c = self.cfg.get("news_scanner", {})
        d = self.news.run(only_new=only_new)
        min_conf = float(c.get("min_confidence", 0.55))
        actionable = self.news.actionable(d, min_conf)
        log.info("news scan: %s items, %s actionable (%s)", d["scanned"], len(actionable), d["source"])
        if force_send or actionable or (d["picks"] and c.get("send_watch_only_digests", False)):
            self.tg.send(news_digest_message(d, min_conf=min_conf, max_cards=int(c.get("max_cards", 12))),
                         chat_id=chat_id)
        return d

    def eod(self) -> None:
        self.tg.send(board_message(scan(self.cfg, self.llm), f"🌇 End-of-day board · {now_ist():%d %b %Y}"))

    # ── Telegram commands ───────────────────────────────────
    def handle(self, text: str, chat_id: str) -> None:
        parts = text.strip().split()
        cmd = parts[0].lower().split("@")[0] if parts else ""
        if cmd == "/analyze" and len(parts) > 1:
            sym = parts[1].upper()
            try:
                r = analyze(sym, self.cfg, self.llm, review=True)
                if self.ncfg.get("send_charts", True):
                    self.tg.send_photo(render_chart(r), chat_id=chat_id)
                self.tg.send(signal_message(r), chat_id=chat_id)
            except Exception as e:
                self.tg.send(f"Could not analyze {sym}: {e}", chat_id=chat_id)
        elif cmd == "/top":
            self.tg.send(board_message(scan(self.cfg, self.llm), "📊 Watchlist board"), chat_id=chat_id)
        elif cmd == "/news":
            self.tg.send(news_message(market_news(self.cfg, limit=12)), chat_id=chat_id)
        elif cmd in ("/scannews", "/newsai", "/ainews"):
            self.tg.send("🔎 Scanning news & exchange filings… (can take a minute)", chat_id=chat_id)
            self.news_scan(only_new=False, chat_id=chat_id, force_send=True)
        else:
            self.tg.send("Commands:\n/analyze SYMBOL — full chart + signal\n/top — watchlist board\n"
                         "/news — latest headlines\n/scannews — AI news scan: what to buy / avoid and why",
                         chat_id=chat_id)

    def poll_commands(self) -> None:
        offset = 0
        while True:
            for u in self.tg.updates(offset):
                offset = u["update_id"] + 1
                m = u.get("message") or {}
                chat = str(m.get("chat", {}).get("id", ""))
                if m.get("text") and chat == str(self.tg.chat_id):  # only obey your own chat
                    try:
                        self.handle(m["text"], chat)
                    except Exception as e:  # never let one bad command kill the listener thread
                        log.exception("command failed")
                        self.tg.send(f"Command failed: {e}", chat_id=chat)
            time.sleep(1)

    # ── main loop ───────────────────────────────────────────
    def once_per_day(self, key: str, hhmm: str, fn) -> None:
        today = now_ist().strftime("%Y-%m-%d")
        if past(hhmm) and self.state["done"].get(key) != today:
            fn(); self.state["done"][key] = today; _save_state(self.state)

    def run(self) -> None:
        if self.tg.token:
            threading.Thread(target=self.poll_commands, daemon=True).start()
        every = int(self.ncfg.get("scan_every_minutes", 15)) * 60
        nc = self.cfg.get("news_scanner", {})
        news_every = int(nc.get("every_minutes", 30)) * 60
        last_scan = last_news = 0.0
        log.info("Notifier started. Telegram %s.", "ON" if self.tg.ready else "OFF (console mode)")
        while True:
            try:
                if is_trading_day(self.cfg):
                    if not past(self.cfg["market"]["open"]):
                        self.once_per_day("premarket", self.ncfg["premarket_brief"], self.premarket)
                    if is_market_open(self.cfg) and time.time() - last_scan >= every:
                        self.intraday_scan(); last_scan = time.time()
                    self.once_per_day("eod", self.ncfg["eod_report"], self.eod)
                news_day = is_trading_day(self.cfg) or nc.get("weekends", False)
                in_window = past(nc.get("active_from", "07:30")) and not past(nc.get("active_to", "22:00"))
                if nc.get("enabled", True) and news_day and in_window and time.time() - last_news >= news_every:
                    last_news = time.time(); self.news_scan()
            except Exception:
                log.exception("loop error")
            time.sleep(30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run one scan now and exit")
    ap.add_argument("--news", action="store_true", help="run one AI news scan now, send the digest and exit")
    args = ap.parse_args()
    n = Notifier(load_config())
    if args.news:
        n.news_scan(only_new=False, force_send=True)
    elif args.once:
        reports = n.intraday_scan()
        n.tg.send(board_message(reports, "📊 Watchlist board"))
    else:
        n.run()


if __name__ == "__main__":
    main()
