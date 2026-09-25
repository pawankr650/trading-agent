"""StockPilot web app — one page, three desks: News Intelligence · NIFTY 50 Patterns · Algo Lab.

Run:  uvicorn web.server:app --port 8000     (or: python -m web.server)
      STOCKPILOT_DEMO=1 uvicorn web.server:app   → offline demo data (synthetic, badged in the UI)
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from core import algo, demo  # noqa: E402
from core.config import load_config, setup_logging  # noqa: E402
from core.datastore import PriceStore  # noqa: E402
from core.indicators import add_indicators  # noqa: E402
from core.llm import LLM  # noqa: E402
from core.market_hours import is_market_open, now_ist  # noqa: E402
from core.news_engine import NewsEngine  # noqa: E402
from core.nifty50 import NIFTY50, SYMBOLS, name, sector  # noqa: E402
from core.patterns import HAS_TALIB, detect, ts  # noqa: E402

log = setup_logging("web")
STATIC = Path(__file__).resolve().parent / "static"
cfg = load_config()
prices = PriceStore(cfg)
llm = LLM(cfg) if cfg.get("insights", {}).get("llm_thesis", True) and cfg.get("llm", {}).get("enabled") else None
engine = NewsEngine(cfg, prices, llm)
_pattern_cache: dict = {"at": 0.0, "rows": []}


@asynccontextmanager
async def lifespan(_app):
    engine.start()
    yield
    engine.stop()


app = FastAPI(title="StockPilot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _sym(symbol: str) -> str:
    s = symbol.upper()
    if s not in NIFTY50 and s not in cfg.get("watchlist", []):
        raise HTTPException(404, f"Unknown symbol {symbol}")
    return s


def _candles(df: pd.DataFrame, bars: int) -> dict:
    d = add_indicators(df).tail(bars)
    t = [ts(i) for i in d.index]
    line = lambda col: [{"time": a, "value": round(float(v), 2)} for a, v in zip(t, d[col]) if pd.notna(v)]
    return {
        "candles": [{"time": a, "open": round(float(r.Open), 2), "high": round(float(r.High), 2),
                     "low": round(float(r.Low), 2), "close": round(float(r.Close), 2)}
                    for a, r in zip(t, d.itertuples())],
        "volume": [{"time": a, "value": float(r.Volume), "up": bool(r.Close >= r.Open)} for a, r in zip(t, d.itertuples())],
        "sma20": line("SMA20"), "sma50": line("SMA50"), "sma200": line("SMA200"), "rsi": line("RSI"),
    }


# ── pages ──────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return {"engine": engine.status(), "market_open": is_market_open(cfg), "ist": now_ist().strftime("%d %b %Y %H:%M"),
            "demo": demo.enabled() or prices.any_demo(), "universe": len(SYMBOLS),
            "pattern_engine": "TA-Lib" if HAS_TALIB else "pandas fallback"}


# ── desk 1: news intelligence ──────────────────────────────────
@app.get("/api/news")
def news(limit: int = 80, symbol: str | None = None):
    items = list(engine.items)
    if symbol:
        items = [i for i in items if symbol.upper() in i["symbols"]]
    return sorted(items, key=lambda r: -r["ts"])[:limit]


@app.get("/api/insights")
def insights():
    order = {"BUY": 0, "SELL": 1, "WATCH": 2, "AVOID": 3, "HOLD": 4}
    return sorted(engine.insights.values(), key=lambda r: (order[r["action"]], -r["news_count"], -abs(r["score"])))


@app.get("/api/stream")
async def stream():
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    loop = asyncio.get_running_loop()

    def push(event, payload):
        loop.call_soon_threadsafe(lambda: q.full() or q.put_nowait((event, payload)))

    engine.listeners.append(push)

    async def gen():
        try:
            yield "retry: 5000\n\n"
            while True:
                try:
                    ev, data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {ev}\ndata: {json.dumps(data, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            engine.listeners.remove(push)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/stock/{symbol}")
def stock(symbol: str, bars: int = 200):
    s = _sym(symbol)
    df, is_demo = prices.get(s)
    pat = detect(df)
    out = {"symbol": s, "name": name(s), "sector": sector(s), "demo": is_demo, **_candles(df, bars),
           "patterns": pat, "insight": engine.insights.get(s), "news": news(40, s)}
    return out


# ── desk 2: NIFTY 50 patterns ──────────────────────────────────
@app.get("/api/patterns")
def patterns(refresh: bool = False):
    if refresh or time.time() - _pattern_cache["at"] > 900 or not _pattern_cache["rows"]:
        prices.load(SYMBOLS)
        rows = []
        for s in SYMBOLS:
            try:
                df, is_demo = prices.get(s)
                p = detect(df)
                c = df.Close
                rows.append({
                    "symbol": s, "name": name(s), "sector": sector(s), "price": round(float(c.iloc[-1]), 2),
                    "change_pct": round(float((c.iloc[-1] / c.iloc[-2] - 1) * 100), 2),
                    "bias": p["bias"], "bullish": p["bullish"], "bearish": p["bearish"],
                    "chart": [{k: x[k] for k in ("name", "bias", "status", "bars_ago")} for x in p["chart"]],
                    "candles": [{k: x[k] for k in ("name", "bias", "date", "bars_ago")}
                                for x in p["candlestick"] if x["bars_ago"] <= 5],
                    "spark": [round(float(v), 2) for v in c.tail(40)], "demo": is_demo,
                })
            except Exception as e:
                log.warning("patterns %s failed: %s", s, e)
        _pattern_cache.update(at=time.time(), rows=rows)
    return {"updated": int(_pattern_cache["at"]), "rows": _pattern_cache["rows"]}


# ── desk 3: algo lab ───────────────────────────────────────────
@app.get("/api/strategies")
def strategies():
    return algo.catalog()


class BacktestReq(BaseModel):
    symbol: str
    strategy: str = "ema_atr"
    cash: float = Field(100_000, gt=1000)
    commission: float = Field(0.0012, ge=0, le=0.02)
    params: dict = {}
    optimize: bool = False
    years: float = Field(3, gt=0.25, le=20)


def _history(symbol: str, years: float) -> pd.DataFrame:
    return prices.history(_sym(symbol), years)[0]


@app.post("/api/backtest")
def backtest(req: BacktestReq):
    if req.strategy not in algo.STRATEGIES:
        raise HTTPException(400, "Unknown strategy")
    df = _history(req.symbol, req.years)
    res = algo.run(df, req.strategy, req.cash, req.commission, req.params, req.optimize)
    res["candles"] = _candles(df, len(df))["candles"]
    res["symbol"] = req.symbol.upper()
    return res


@app.post("/api/compare")
def compare(req: BacktestReq):
    return algo.compare(_history(req.symbol, req.years), req.cash, req.commission)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
