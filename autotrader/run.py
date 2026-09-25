"""Run SYSTEM 2.

  python -m autotrader.run                 # loop during market hours (paper mode by default)
  python -m autotrader.run --once          # one cycle now, ignores market hours (for testing)
Telegram: /status  /kill  /resume
"""
from __future__ import annotations

import argparse
import os
import threading
import time

from core.config import load_config, setup_logging
from core.market_hours import is_market_open

from .engine import AutoTrader
from .risk import KILL_FILE

log = setup_logging("autotrader")


def status_text(bot: AutoTrader) -> str:
    rows = bot.journal.open_trades()
    lines = [f"<b>Auto-trader [{bot.broker.mode}]</b> · realized today ₹{bot.journal.realized_today():,.0f} · "
             f"kill={'ON' if KILL_FILE.exists() else 'off'}"]
    lines += [f"• {t['side']} {t['symbol']} x{t['qty']} @ {t['entry']} SL {t['stop']} TGT {t['target']}" for t in rows]
    return "\n".join(lines if rows else lines + ["No open positions."])


def commands(bot: AutoTrader) -> None:
    offset = 0
    while True:
        for u in bot.tg.updates(offset):
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            if str(m.get("chat", {}).get("id")) != str(bot.tg.chat_id):
                continue
            cmd = (m.get("text") or "").strip().lower()
            if cmd.startswith("/kill"):
                KILL_FILE.touch(); bot.tg.send("⛔ Kill switch ON — no new entries. Open positions still managed.")
            elif cmd.startswith("/resume"):
                KILL_FILE.unlink(missing_ok=True); bot.tg.send("▶️ Kill switch OFF.")
            elif cmd.startswith("/status"):
                bot.tg.send(status_text(bot))
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    bot = AutoTrader(cfg)
    if cfg["autotrader"]["mode"] == "live":
        log.warning("LIVE MODE — real orders will be sent through OpenAlgo.")
    if args.once:
        bot.cycle(); print(status_text(bot)); return
    # commands need their own bot token (TELEGRAM_TRADER_BOT_TOKEN) so they don't clash with System 1
    if os.getenv("TELEGRAM_TRADER_BOT_TOKEN"):
        threading.Thread(target=commands, args=(bot,), daemon=True).start()
    every = int(cfg["autotrader"]["loop_every_minutes"]) * 60
    while True:
        try:
            if is_market_open(cfg):
                bot.cycle()
        except Exception:
            log.exception("cycle failed")
        time.sleep(every)


if __name__ == "__main__":
    main()
