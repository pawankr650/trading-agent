"""StockPilot web app — REST API + web UI in one process.

Run:   python -m server.app                 (http://127.0.0.1:8000)
       uvicorn server.app:app --host 0.0.0.0 --port 8000
Docs:  /docs (interactive OpenAPI)

Set APP_TOKEN in .env to require a token (header `X-App-Token`) on every /api call — do this whenever the
app is reachable from anything but your own machine, because it can trigger scans, trades and the kill switch.
"""
from __future__ import annotations

import logging
import math
import os
import re
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.config import ROOT, load_config, save_override, setup_logging
from core.llm import LLM
from core.market_hours import is_market_open, now_ist
from core.news import market_news
from core.news_scanner import NewsScanner, load_digest

log = setup_logging("server")
WEB = ROOT / "frontend" / "dist"  # React build output (cd frontend && npm run build)
SYMBOL = re.compile(r"^[A-Z0-9&\-]{1,20}$")


# ── shared state ───────────────────────────────────────────
class State:
    def __init__(self):
        self.reload()
        self.cache: dict[str, tuple[float, object]] = {}
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def reload(self) -> None:
        self.cfg = load_config()
        self.llm = LLM(self.cfg)
        self.scanner = NewsScanner(self.cfg, self.llm)

    def cached(self, key: str, ttl: int, fn):
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        val = fn()
        self.cache[key] = (time.time(), val)
        return val

    def start_job(self, kind: str, fn) -> str:
        with self.lock:  # one job of a kind at a time — scans are expensive
            for jid, j in self.jobs.items():
                if j["kind"] == kind and j["status"] == "running":
                    return jid
            jid = uuid.uuid4().hex[:10]
            self.jobs[jid] = {"id": jid, "kind": kind, "status": "running", "started": time.time(), "result": None}

        def run():
            try:
                self.jobs[jid].update(status="done", result=jsonable(fn()))
            except Exception as e:
                log.exception("job %s failed", kind)
                self.jobs[jid].update(status="error", error=str(e))
            self.jobs[jid]["finished"] = time.time()

        threading.Thread(target=run, daemon=True).start()
        return jid


S = State()


def jsonable(o):
    """numpy / pandas / datetime / NaN -> plain JSON."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items() if k != "df"}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if math.isnan(o) or math.isinf(o) else float(o)
    if isinstance(o, (datetime, date, pd.Timestamp)):
        return o.isoformat()
    return o


def candles(df: pd.DataFrame, bars: int = 250) -> list[dict]:
    d = df.tail(bars)
    cols = {"Open": "o", "High": "h", "Low": "l", "Close": "c", "Volume": "v", "SMA20": "sma20", "SMA50": "sma50",
            "SMA200": "sma200", "RSI": "rsi", "MACD": "macd", "MACD_signal": "macd_signal", "MACD_hist": "macd_hist",
            "BB_up": "bb_up", "BB_lo": "bb_lo", "SUPERTREND": "supertrend"}
    out = []
    for ts, row in d.iterrows():
        rec = {"t": int(pd.Timestamp(ts).timestamp())}
        for c, k in cols.items():
            if c in row:
                v = float(row[c])
                rec[k] = None if math.isnan(v) else round(v, 4)
        out.append(rec)
    return out


# ── auth ───────────────────────────────────────────────────
def auth(x_app_token: str | None = Header(default=None), token: str | None = Query(default=None)):
    want = os.getenv("APP_TOKEN", "")
    if want and not secrets.compare_digest(x_app_token or token or "", want):
        raise HTTPException(401, "Missing or wrong app token")


def check_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if not SYMBOL.match(s):
        raise HTTPException(400, f"Invalid symbol: {symbol!r}")
    return s


@asynccontextmanager
async def lifespan(_app):
    if not os.getenv("APP_TOKEN"):
        log.warning("APP_TOKEN not set — the API is open to anyone who can reach this port.")
    if S.cfg.get("server", {}).get("background_jobs", False):
        threading.Thread(target=_background, daemon=True).start()
    yield


app = FastAPI(title="StockPilot", version="2.0", lifespan=lifespan,
              description="NSE/BSE signals, AI news scanner and auto-trading — open-source LLMs")
api = Depends(auth)


# ── system ─────────────────────────────────────────────────
@app.get("/api/health", dependencies=[api])
def health():
    from notifier.telegram import Telegram
    from autotrader.risk import KILL_FILE
    c = S.cfg
    return {
        "time_ist": now_ist().isoformat(timespec="seconds"),
        "market_open": is_market_open(c),
        "llm_enabled": S.llm.enabled,
        "llm_providers": [{"name": p["name"], "model": S.llm._model(p),
                           "configured": p["name"] in S.llm.available()} for p in S.llm.providers],
        "llm_last_used": S.llm.last_provider,
        "telegram": Telegram().ready,
        "trader_mode": c["autotrader"]["mode"],
        "kill_switch": KILL_FILE.exists(),
        "watchlist": c["watchlist"],
        "auth_required": bool(os.getenv("APP_TOKEN")),
    }


class Watchlist(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=100)


@app.put("/api/watchlist", dependencies=[api])
def set_watchlist(w: Watchlist):
    syms = list(dict.fromkeys(check_symbol(s) for s in w.symbols if s.strip()))
    save_override("watchlist", syms)
    S.reload(); S.cache.clear()
    return {"watchlist": syms}


@app.post("/api/llm/test", dependencies=[api])
def llm_test():
    t0 = time.time()
    out = S.llm.chat("You are terse.", "Reply with the single word: pong", max_tokens=20)
    return {"ok": bool(out), "reply": (out or "").strip()[:100], "provider": S.llm.last_provider,
            "seconds": round(time.time() - t0, 2)}


@app.post("/api/telegram/test", dependencies=[api])
def telegram_test():
    from notifier.telegram import Telegram
    tg = Telegram()
    if not tg.ready:
        raise HTTPException(400, "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
    return {"ok": tg.send("✅ StockPilot web app can reach this chat.")}


# ── signals ────────────────────────────────────────────────
@app.get("/api/scan", dependencies=[api])
def scan_watchlist(llm: bool = False, refresh: bool = False):
    from core.analysis import scan
    key = f"scan:{llm}"
    if refresh:
        S.cache.pop(key, None)
    rows = S.cached(key, 900, lambda: scan(S.cfg, S.llm if llm else None))
    return {"at": S.cache[key][0], "rows": [jsonable({k: v for k, v in r.items() if k not in ("news",)}) | {
        "headlines": [n["title"] for n in r.get("news", [])[:3]]} for r in rows]}


@app.get("/api/analyze/{symbol}", dependencies=[api])
def analyze_one(symbol: str, llm: bool = False, bars: int = Query(250, ge=30, le=1000)):
    from core.analysis import analyze
    sym = check_symbol(symbol)
    try:
        r = S.cached(f"an:{sym}:{llm}", 600, lambda: analyze(sym, S.cfg, S.llm if llm else None, review=llm))
    except Exception as e:
        raise HTTPException(404, f"Could not analyze {sym}: {e}")
    out = jsonable(r)
    out["candles"] = candles(r["df"], bars)
    return out


# ── news ───────────────────────────────────────────────────
@app.get("/api/news", dependencies=[api])
def news(limit: int = Query(40, ge=1, le=200)):
    return {"items": jsonable(S.cached(f"news:{limit}", 300, lambda: market_news(S.cfg, limit=limit)))}


@app.get("/api/filings", dependencies=[api])
def filings():
    from core.announcements import exchange_announcements
    items = S.cached("filings", 300, lambda: exchange_announcements(S.cfg))
    return {"items": jsonable(sorted(items, key=lambda x: str(x.get("published") or ""), reverse=True))}


@app.get("/api/news/digest", dependencies=[api])
def digest():
    return load_digest() or {"picks": [], "mood": "", "source": "", "scanned": 0, "at": None}


class ScanReq(BaseModel):
    only_new: bool = False
    send_telegram: bool = False


@app.post("/api/news/scan", dependencies=[api])
def news_scan(req: ScanReq):
    def job():
        d = S.scanner.run(only_new=req.only_new)
        if req.send_telegram:
            from notifier.formatter import news_digest_message
            from notifier.telegram import Telegram
            Telegram().send(news_digest_message(d, min_conf=float(S.cfg["news_scanner"].get("min_confidence", 0.55))))
        return d
    return {"job": S.start_job("news_scan", job)}


@app.get("/api/jobs/{jid}", dependencies=[api])
def job_status(jid: str):
    j = S.jobs.get(jid)
    if not j:
        raise HTTPException(404, "unknown job")
    return j


# ── auto-trader ────────────────────────────────────────────
def _journal():
    from autotrader.journal import Journal
    return Journal()


@app.get("/api/trader", dependencies=[api])
def trader():
    from autotrader.risk import KILL_FILE
    j = _journal()
    try:
        rows = j.all()
    finally:
        j.db.close()
    closed = [t for t in rows if t["status"] == "CLOSED"]
    wins = [t for t in closed if (t["pnl"] or 0) > 0]
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "mode": S.cfg["autotrader"]["mode"], "capital": S.cfg["autotrader"]["capital"],
        "product": S.cfg["autotrader"]["product"], "kill_switch": KILL_FILE.exists(),
        "open": [t for t in rows if t["status"] == "OPEN"], "trades": rows,
        "stats": {"closed": len(closed), "win_rate": round(len(wins) / len(closed), 3) if closed else None,
                  "total_pnl": round(sum(t["pnl"] or 0 for t in closed), 2),
                  "today_pnl": round(sum(t["pnl"] or 0 for t in closed if (t["closed_at"] or "").startswith(today)), 2)},
    }


@app.post("/api/trader/kill", dependencies=[api])
def kill():
    from autotrader.risk import KILL_FILE
    KILL_FILE.touch()
    return {"kill_switch": True}


@app.post("/api/trader/resume", dependencies=[api])
def resume():
    from autotrader.risk import KILL_FILE
    KILL_FILE.unlink(missing_ok=True)
    return {"kill_switch": False}


@app.post("/api/trader/cycle", dependencies=[api])
def trader_cycle():
    """Run one auto-trader cycle now. Refused in live mode — use the autotrader service for real money."""
    if S.cfg["autotrader"]["mode"] != "paper":
        raise HTTPException(403, "Manual cycles are only allowed in paper mode")

    def job():
        from autotrader.engine import AutoTrader
        bot = AutoTrader(S.cfg, llm=S.llm)
        try:
            bot.cycle()
            return {"open": bot.journal.open_trades()}
        finally:
            bot.journal.db.close()
    return {"job": S.start_job("trader_cycle", job)}


# ── background news scans (optional) ───────────────────────
def _background():
    from core.market_hours import is_trading_day, past
    while True:
        c = S.cfg.get("news_scanner", {})
        try:
            day = is_trading_day(S.cfg) or c.get("weekends", False)
            if day and past(c.get("active_from", "07:30")) and not past(c.get("active_to", "22:00")):
                # only_new=False: never touches the notifier's "already sent" list, so both can run together
                S.start_job("news_scan", lambda: S.scanner.run(only_new=False))
        except Exception:
            log.exception("background scan failed")
        time.sleep(int(c.get("every_minutes", 30)) * 60)


# ── web UI (React build) ───────────────────────────────────
if (WEB / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    if not (WEB / "index.html").exists():
        return HTMLResponse("<h3>StockPilot API is running.</h3><p>Build the UI: <code>cd frontend &amp;&amp; npm install "
                            "&amp;&amp; npm run build</code>, or run <code>npm run dev</code> for hot reload. "
                            "API docs: <a href='/docs'>/docs</a></p>")
    return FileResponse(WEB / "index.html")


def main():
    import uvicorn
    s = S.cfg.get("server", {})
    uvicorn.run(app, host=os.getenv("HOST", s.get("host", "127.0.0.1")), port=int(os.getenv("PORT", s.get("port", 8000))),
                log_level=logging.getLevelName(log.getEffectiveLevel()).lower())


if __name__ == "__main__":
    main()
