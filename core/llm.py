"""Free-tier, open-source LLM client with provider fallback.

Default chain (all OpenAI-compatible /chat/completions, all serve open-weight models):
  Groq -> Cerebras -> Hugging Face router -> OpenRouter (:free) -> local Ollama  [-> Gemini, optional]

Plain `requests` is enough. The LLM never places orders — it only (a) scores news sentiment,
(b) summarises news into BUY / WATCH / AVOID recommendations and (c) acts as a veto on rule-based signals.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

import requests

log = logging.getLogger(__name__)

# after these HTTP codes the provider is skipped for a while (bad key / model not found / bad request)
_HARD_FAIL = {400, 401, 403, 404}


class LLM:
    def __init__(self, cfg: dict):
        c = cfg.get("llm", {})
        self.enabled = c.get("enabled", True)
        self.providers = c.get("providers", [])
        self.temperature = float(c.get("temperature", 0.1))
        self.timeout = int(c.get("timeout_seconds", 60))
        self.cooldown = int(c.get("failure_cooldown_minutes", 15)) * 60
        self._down: dict[str, float] = {}  # provider name -> retry-after epoch
        self._lock = threading.Lock()
        self.last_provider: str | None = None

    # ── transport ───────────────────────────────────────────
    def _model(self, p: dict) -> str:
        return os.getenv(p.get("model_env") or "", "") or p["model"]

    def available(self) -> list[str]:
        """Names of providers that are configured (have a key, or need none)."""
        return [p["name"] for p in self.providers if not p.get("api_key_env") or os.getenv(p["api_key_env"])]

    def _mark_down(self, name: str, seconds: float) -> None:
        with self._lock:
            self._down[name] = time.time() + seconds

    def chat(self, system: str, user: str, max_tokens: int = 800) -> str | None:
        if not self.enabled:
            return None
        for p in self.providers:
            name = p["name"]
            key = os.getenv(p.get("api_key_env") or "", "")
            if p.get("api_key_env") and not key:
                continue  # provider not configured
            if self._down.get(name, 0) > time.time():
                continue  # recently failed — don't spam it
            try:
                r = requests.post(
                    p["base_url"].rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {key or 'ollama'}", "Content-Type": "application/json"},
                    json={"model": self._model(p), "temperature": self.temperature,
                          "max_tokens": int(p.get("max_tokens", max_tokens)),
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                log.info("LLM %s unreachable (%s), trying next", name, type(e).__name__)
                self._mark_down(name, self.cooldown); continue
            if r.status_code == 429:
                log.info("LLM %s rate-limited, trying next", name)
                self._mark_down(name, 60); continue
            if r.status_code >= 400:
                # show the provider's own error text — tells you if it is the key, the model name or quota
                log.warning("LLM %s HTTP %s (model %s): %s", name, r.status_code, self._model(p), r.text[:300])
                self._mark_down(name, self.cooldown if r.status_code in _HARD_FAIL else 120); continue
            try:
                msg = r.json()["choices"][0]["message"]
                txt = msg.get("content") or msg.get("reasoning_content") or ""
            except (ValueError, KeyError, IndexError, TypeError):
                log.info("LLM %s returned an unexpected payload", name); continue
            if txt.strip():
                self.last_provider = f"{name}/{self._model(p)}"
                return txt
        return None

    @staticmethod
    def extract_json(txt: str | None):
        """Pull the first JSON object/array out of a model reply (handles <think> blocks and ``` fences)."""
        if not txt:
            return None
        txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
        txt = re.sub(r"```(?:json)?", "", txt)
        # try whichever bracket opens first, so a top-level array isn't mistaken for its first object
        starts = sorted((i, pat) for pat, ch in ((r"\{.*\}", "{"), (r"\[.*\]", "[")) if (i := txt.find(ch)) >= 0)
        for _, pat in starts:
            m = re.search(pat, txt, re.S)
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def chat_json(self, system: str, user: str, max_tokens: int = 800):
        return self.extract_json(self.chat(system + "\nRespond with ONLY valid JSON, no prose, no markdown.",
                                           user, max_tokens))

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
            return max(-1.0, min(1.0, float(out["sentiment"]))) if isinstance(out, dict) else None
        except (KeyError, TypeError, ValueError):
            return None

    def review_signal(self, report: dict) -> dict | None:
        """Second opinion on a rule-based signal. Returns {action, confidence, rationale}."""
        brief = {k: report[k] for k in ("symbol", "price", "action", "score", "tech_score", "fund_score",
                                        "news_score", "criteria", "plan") if k in report}
        brief["headlines"] = [n["title"] for n in report.get("news", [])[:6]]
        out = self.chat_json(
            "You are a cautious risk-aware Indian equity analyst. Review the signal using only the data given. "
            "Prefer HOLD when evidence is mixed. Never invent numbers.",
            json.dumps(brief, default=str) +
            '\nReturn {"action": "BUY"|"SELL"|"HOLD", "confidence": 0-1, "rationale": "<=40 words"}',
        )
        if not isinstance(out, dict):
            return None
        out["action"] = str(out.get("action", "HOLD")).upper()
        out["confidence"] = to_float(out.get("confidence"))
        return out


def to_float(v, default: float = 0.0) -> float:
    """LLMs sometimes answer "0.8", "80%" or "high" — normalise to [0, 1]."""
    if isinstance(v, str):
        words = {"low": 0.3, "medium": 0.5, "moderate": 0.5, "high": 0.8, "very high": 0.9}
        if v.strip().lower() in words:
            return words[v.strip().lower()]
        v = v.strip().rstrip("%")
        try:
            f = float(v)
            return f / 100 if f > 1 else f
        except ValueError:
            return default
    try:
        f = float(v)
        return f / 100 if f > 1 else f
    except (TypeError, ValueError):
        return default
