"""Per-stock trade insight = news sentiment (Hugging Face) + technicals + chart patterns → action, reasons,
entry zone, stop-loss and exit targets."""
from __future__ import annotations

import time

import pandas as pd

from .indicators import add_indicators, technical_score
from .nifty50 import name, sector
from .patterns import detect


def news_score(items: list[dict], half_life_h: float = 12.0) -> tuple[float, int]:
    """Confidence-weighted, time-decayed mean of signed sentiment in [-1, 1]."""
    now = time.time()
    num = den = 0.0
    for it in items:
        age_h = max(0.0, (now - (it.get("ts") or now)) / 3600)
        w = 0.5 ** (age_h / half_life_h)
        num += w * it["nlp"]["score"]
        den += w
    return (num / den if den else 0.0), len(items)


def _clean(txt: str) -> tuple[str, str]:
    """'✅ Price above 50-DMA' → ('bullish', 'Price above 50-DMA')."""
    if txt.startswith("✅"):
        return "bullish", txt[1:].strip()
    if txt.startswith("❌"):
        return "bearish", txt[1:].strip()
    return "neutral", txt


def build(symbol: str, df: pd.DataFrame, news: list[dict], cfg: dict, is_demo: bool = False) -> dict:
    icfg = cfg.get("insights", {})
    w = icfg.get("weights", {"technical": 0.45, "news": 0.35, "pattern": 0.20})
    df = add_indicators(df)
    last, prev = df.iloc[-1], df.iloc[-2]
    tech, tech_why = technical_score(df)
    ns, n_count = news_score(news, icfg.get("news_half_life_hours", 12))
    pat = detect(df)
    tot = pat["bullish"] + pat["bearish"]
    ps = (pat["bullish"] - pat["bearish"]) / tot if tot else 0.0
    score = w["technical"] * tech + w["news"] * ns + w["pattern"] * ps

    buy_t, sell_t = icfg.get("buy_threshold", 0.25), icfg.get("sell_threshold", -0.25)
    if score >= buy_t and tech > 0:
        action = "BUY"
    elif score <= sell_t and tech < 0:
        action = "SELL"
    elif score >= buy_t * 0.6:
        action = "WATCH"
    else:
        action = "AVOID" if score <= sell_t * 0.6 else "HOLD"

    px, a = float(last.Close), float(last.ATR)
    lv = pat["levels"]
    stop_mult, rr = cfg["scoring"].get("stop_atr_mult", 1.5), cfg["scoring"].get("reward_risk", 2.0)
    if action == "SELL":
        entry_lo, entry_hi = px, min(lv["resistance"][0], px + 0.5 * a) if lv["resistance"] else px + 0.5 * a
        entry = px
        stop = max(entry_hi, px) + stop_mult * a
        risk = stop - entry
        t1 = entry - rr * risk
        t2 = min(t1, lv["support"][0]) if lv["support"] else entry - (rr + 1) * risk
        t2 = min(t2, entry - (rr + 1) * risk)
    else:
        entry_hi = px
        entry_lo = max(lv["support"][0], px - 0.5 * a) if lv["support"] else px - 0.5 * a
        entry = px
        stop = min(entry_lo, px) - stop_mult * a
        risk = entry - stop
        t1 = entry + rr * risk
        t2 = max(t1, lv["resistance"][-1]) if lv["resistance"] else entry + (rr + 1) * risk
        t2 = max(t2, entry + (rr + 1) * risk)

    reasons = []
    for it in sorted(news, key=lambda x: -abs(x["nlp"]["score"]))[:4]:
        reasons.append({"kind": "news", "bias": it["nlp"]["sentiment"].replace("positive", "bullish")
                        .replace("negative", "bearish"), "text": it["title"], "event": it["nlp"]["event"],
                        "confidence": it["nlp"]["confidence"], "link": it.get("link", "")})
    for txt in tech_why:
        b, t = _clean(txt)
        reasons.append({"kind": "technical", "bias": b, "text": t})
    for p in [p for p in pat["chart"] if p["bars_ago"] <= 40] + [p for p in pat["candlestick"] if p["bars_ago"] <= 3]:
        reasons.append({"kind": "pattern", "bias": p["bias"],
                        "text": p["name"] + (f" ({p['status']})" if p.get("status") else f" · {p['date']}")})

    conf = min(0.95, 0.35 + abs(score) * 0.9 + (0.05 if n_count >= 3 else 0))
    return {
        "symbol": symbol, "name": name(symbol), "sector": sector(symbol),
        "price": round(px, 2), "change_pct": round((px / float(prev.Close) - 1) * 100, 2),
        "action": action, "score": round(score, 3), "confidence": round(conf, 2),
        "scores": {"technical": round(tech, 3), "news": round(ns, 3), "pattern": round(ps, 3)},
        "news_count": n_count, "rsi": round(float(last.RSI), 1), "atr": round(a, 2),
        "plan": {"entry": round(entry, 2), "entry_zone": [round(min(entry_lo, entry_hi), 2), round(max(entry_lo, entry_hi), 2)],
                 "stop": round(stop, 2), "target1": round(t1, 2), "target2": round(t2, 2),
                 "risk_pct": round(abs(entry - stop) / entry * 100, 2),
                 "reward_pct": round(abs(t1 - entry) / entry * 100, 2), "rr": rr,
                 "side": "short" if action in ("SELL", "AVOID") else "long"},
        "levels": lv, "reasons": reasons, "pattern_bias": pat["bias"], "demo": is_demo,
        "updated": int(time.time()),
    }


def headline_thesis(llm, ins: dict) -> str | None:
    """Optional 2-sentence rationale from the free-LLM chain (Groq/Gemini/OpenRouter/Ollama)."""
    if llm is None:
        return None
    facts = {k: ins[k] for k in ("symbol", "name", "price", "action", "scores", "plan", "rsi")}
    facts["reasons"] = [r["text"] for r in ins["reasons"][:8]]
    txt = llm.chat("You are a concise Indian equity analyst. Use only the facts given; never invent numbers.",
                   f"Facts: {facts}\nWrite a 2-sentence trade thesis explaining the {ins['action']} view, "
                   "mentioning the entry and exit levels.", max_tokens=160)
    return txt.strip() if txt else None
