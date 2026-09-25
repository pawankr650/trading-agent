"""Free-tier LLM client with provider fallback (Groq -> Gemini -> OpenRouter -> local Ollama).

All providers expose an OpenAI-compatible /chat/completions endpoint, so plain `requests` is enough.
The LLM never places orders — it only (a) scores news sentiment and (b) writes a rationale /
acts as a veto on rule-based signals.
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)


class LLM:
    def __init__(self, cfg: dict):
        self.enabled = cfg.get("llm", {}).get("enabled", True)
        self.providers = cfg.get("llm", {}).get("providers", [])

    def chat(self, system: str, user: str, max_tokens: int = 600) -> str | None:
        if not self.enabled:
            return None
        for p in self.providers:
            key = os.getenv(p.get("api_key_env") or "", "")
            if p.get("api_key_env") and not key:
                continue  # provider not configured
            try:
                r = requests.post(
                    p["base_url"].rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {key or 'ollama'}", "Content-Type": "application/json"},
                    json={"model": p["model"], "temperature": 0.1, "max_tokens": max_tokens,
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                    timeout=45,
                )
                if r.status_code == 429:
                    log.info("LLM %s rate-limited, trying next", p["name"]); continue
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except Exception as e:
                log.info("LLM %s failed (%s), trying next", p["name"], e)
        return None

    def chat_json(self, system: str, user: str) -> dict | None:
        txt = self.chat(system + "\nRespond with ONLY a JSON object, no prose.", user)
        if not txt:
            return None
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None

    # ── domain helpers ──────────────────────────────────────
    def news_sentiment(self, symbol: str, headlines: list[str]) -> float | None:
        if not headlines:
            return 0.0
        out = self.chat_json(
            "You are an Indian equity news analyst. Rate how the headlines affect the stock price over the next 1-10 trading days.",
            f"Stock: {symbol} (NSE)\nHeadlines:\n- " + "\n- ".join(headlines[:12]) +
            '\nReturn {"sentiment": number between -1 (very negative) and 1 (very positive), "reason": "<15 words"}',
        )
        try:
            return max(-1.0, min(1.0, float(out["sentiment"]))) if out else None
        except (KeyError, TypeError, ValueError):
            return None

    def review_signal(self, report: dict) -> dict | None:
        """Second opinion on a rule-based signal. Returns {action, confidence, rationale}."""
        brief = {k: report[k] for k in ("symbol", "price", "action", "score", "tech_score", "fund_score",
                                        "news_score", "criteria", "plan") if k in report}
        brief["headlines"] = [n["title"] for n in report.get("news", [])[:6]]
        return self.chat_json(
            "You are a cautious risk-aware Indian equity analyst. Review the signal using only the data given. "
            "Prefer HOLD when evidence is mixed. Never invent numbers.",
            json.dumps(brief, default=str) +
            '\nReturn {"action": "BUY"|"SELL"|"HOLD", "confidence": 0-1, "rationale": "<=40 words"}',
        )
