"""Hugging Face models for news: financial sentiment (FinBERT) + event type (zero-shot NLI).

Backends, tried in order:
  1. local   – `transformers` pipelines on your CPU/GPU (pip install transformers torch)
  2. api     – Hugging Face Inference API through `huggingface_hub` (set HF_TOKEN, free tier)
  3. keyword – offline word lists, so the pipeline never stops
"""
from __future__ import annotations

import logging
import os
import threading

from .news import NEG, POS

log = logging.getLogger(__name__)

EVENTS = ["earnings results", "merger or acquisition", "order win or contract", "regulatory or legal action",
          "management change", "dividend or buyback", "analyst rating change", "macro economy or policy",
          "product launch or expansion", "fund raising or stake sale"]

_EVENT_WORDS = {
    "earnings results": ("q1", "q2", "q3", "q4", "results", "profit", "revenue", "earnings", "ebitda", "margin"),
    "merger or acquisition": ("acquire", "acquisition", "merger", "takeover", "buys stake", "demerger"),
    "order win or contract": ("order", "contract", "bags", "wins", "deal worth"),
    "regulatory or legal action": ("sebi", "probe", "penalty", "court", "tax notice", "raid", "ban", "rbi"),
    "management change": ("ceo", "md ", "chairman", "resigns", "appoints", "steps down"),
    "dividend or buyback": ("dividend", "buyback", "bonus", "split"),
    "analyst rating change": ("target price", "upgrade", "downgrade", "rating", "brokerage", "overweight"),
    "macro economy or policy": ("gdp", "inflation", "repo rate", "budget", "fii", "rupee", "crude", "fed", "tariff"),
    "product launch or expansion": ("launch", "plant", "capacity", "expansion", "new store", "unveils"),
    "fund raising or stake sale": ("qip", "ipo", "block deal", "stake sale", "raises", "ofs", "rights issue"),
}


def _keyword_sentiment(text: str) -> tuple[str, float]:
    t = text.lower()
    s = sum(w in t for w in POS) - sum(w in t for w in NEG)
    if s > 0:
        return "positive", min(0.55 + 0.1 * s, 0.9)
    if s < 0:
        return "negative", min(0.55 + 0.1 * -s, 0.9)
    return "neutral", 0.6


def _keyword_event(text: str) -> str:
    t = text.lower()
    best = max(EVENTS, key=lambda e: sum(w in t for w in _EVENT_WORDS[e]))
    return best if any(w in t for w in _EVENT_WORDS[best]) else "general market news"


class NewsNLP:
    def __init__(self, cfg: dict):
        c = cfg.get("hf", {})
        self.sent_model = c.get("sentiment_model", "ProsusAI/finbert")
        self.event_model = c.get("event_model", "facebook/bart-large-mnli")
        self.want = c.get("backend", "auto")  # auto | local | api | keyword
        self.classify_events = c.get("classify_events", True)
        self._lock = threading.Lock()
        self._local = None
        self._client = None
        self.backend = self._init_backend()

    # ── backend selection ─────────────────────────────────
    def _init_backend(self) -> str:
        if self.want in ("auto", "local"):
            try:
                from transformers import pipeline  # type: ignore
                self._local = {"sent": pipeline("text-classification", model=self.sent_model, top_k=None)}
                if self.classify_events:
                    self._local["event"] = pipeline("zero-shot-classification", model=self.event_model)
                log.info("HF local pipelines loaded (%s)", self.sent_model)
                return "local"
            except Exception as e:
                log.info("HF local pipeline unavailable (%s)", e)
        if self.want in ("auto", "api") and os.getenv("HF_TOKEN"):
            try:
                from huggingface_hub import InferenceClient  # type: ignore
                self._client = InferenceClient(token=os.environ["HF_TOKEN"], timeout=30)
                return "api"
            except Exception as e:
                log.info("HF Inference API unavailable (%s)", e)
        return "keyword"

    @property
    def label(self) -> str:
        return {"local": f"{self.sent_model} (local)", "api": f"{self.sent_model} (HF Inference API)",
                "keyword": "keyword fallback"}[self.backend]

    # ── inference ─────────────────────────────────────────
    def sentiment(self, text: str) -> tuple[str, float]:
        """('positive'|'negative'|'neutral', confidence)."""
        try:
            if self.backend == "local":
                with self._lock:
                    out = self._local["sent"](text[:512])[0]
                best = max(out, key=lambda d: d["score"])
                return best["label"].lower(), float(best["score"])
            if self.backend == "api":
                out = self._client.text_classification(text[:512], model=self.sent_model)
                best = max(out, key=lambda d: d.score)
                return best.label.lower(), float(best.score)
        except Exception as e:
            log.debug("HF sentiment failed, keyword fallback: %s", e)
        return _keyword_sentiment(text)

    def event(self, text: str) -> str:
        if not self.classify_events:
            return _keyword_event(text)
        try:
            if self.backend == "local":
                with self._lock:
                    out = self._local["event"](text[:512], candidate_labels=EVENTS)
                return out["labels"][0] if out["scores"][0] > 0.3 else "general market news"
            if self.backend == "api":
                out = self._client.zero_shot_classification(text[:512], candidate_labels=EVENTS,
                                                            model=self.event_model)
                return out[0].label if out[0].score > 0.3 else "general market news"
        except Exception as e:
            log.debug("HF event failed, keyword fallback: %s", e)
        return _keyword_event(text)

    def analyze(self, text: str) -> dict:
        label, conf = self.sentiment(text)
        signed = conf if label == "positive" else -conf if label == "negative" else 0.0
        return {"sentiment": label, "confidence": round(conf, 3), "score": round(signed, 3), "event": self.event(text)}
