"""One function both systems share: analyze(symbol) -> full report with BUY / SELL / HOLD + trade plan."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .fundamentals import fundamental_score, get_fundamentals
from .indicators import add_indicators, technical_score
from .llm import LLM
from .market_data import get_history
from .news import keyword_sentiment, stock_news

log = logging.getLogger(__name__)


def decide(tech: float, fund: float, news: float, cfg: dict) -> tuple[str, float]:
    s = cfg["scoring"]
    w = s["weights"]
    score = w["technical"] * tech + w["fundamental"] * fund + w["news"] * news
    # technicals must agree with the direction — avoids buying a falling knife on good fundamentals alone
    if score >= s["buy_threshold"] and tech > 0:
        return "BUY", score
    if score <= s["sell_threshold"] and tech < 0:
        return "SELL", score
    return "HOLD", score


def trade_plan(df: pd.DataFrame, action: str, cfg: dict) -> dict | None:
    if action == "HOLD":
        return None
    last = df.iloc[-1]
    entry, a = float(last.Close), float(last.ATR)
    risk = cfg["scoring"]["stop_atr_mult"] * a
    rr = cfg["scoring"]["reward_risk"]
    if action == "BUY":
        return {"entry": round(entry, 2), "stop": round(entry - risk, 2), "target": round(entry + rr * risk, 2)}
    return {"entry": round(entry, 2), "stop": round(entry + risk, 2), "target": round(entry - rr * risk, 2)}


def analyze(symbol: str, cfg: dict, llm: LLM | None = None, df: pd.DataFrame | None = None,
            fundamentals: dict | None = None, news: list | None = None, review: bool = False) -> dict:
    df = add_indicators(df if df is not None else get_history(symbol, cfg))
    tech, tech_why = technical_score(df)

    f = fundamentals if fundamentals is not None else get_fundamentals(symbol, cfg.get("exchange", "NSE"))
    fund, fund_why = fundamental_score(f)

    items = news if news is not None else stock_news(symbol, cfg, company=f.get("longName"))
    heads = [n["title"] for n in items]
    ns = llm.news_sentiment(symbol, heads) if (llm and heads) else None
    news_src = "LLM" if ns is not None else "keywords"
    ns = ns if ns is not None else keyword_sentiment(heads)

    action, score = decide(tech, fund, ns, cfg)
    last = df.iloc[-1]
    report = {
        "symbol": symbol, "price": round(float(last.Close), 2),
        "change_pct": round(float((last.Close / df.iloc[-2].Close - 1) * 100), 2),
        "action": action, "score": round(score, 3),
        "tech_score": round(tech, 3), "fund_score": round(fund, 3), "news_score": round(ns, 3), "news_src": news_src,
        "criteria": tech_why + fund_why, "fundamentals": f, "news": items,
        "rsi": round(float(last.RSI), 1), "plan": trade_plan(df, action, cfg), "df": df,
    }
    if review and llm and action != "HOLD":
        report["llm_review"] = llm.review_signal(report)
    return report


def scan(cfg: dict, llm: LLM | None = None, symbols: list[str] | None = None, review: bool = False,
         workers: int = 4) -> list[dict]:
    symbols = symbols or cfg["watchlist"]

    def one(sym):
        try:
            return analyze(sym, cfg, llm, review=review)
        except Exception as e:
            log.warning("analyze %s failed: %s", sym, e)
            return None

    with ThreadPoolExecutor(workers) as ex:
        res = [r for r in ex.map(one, symbols) if r]
    return sorted(res, key=lambda r: r["score"], reverse=True)
