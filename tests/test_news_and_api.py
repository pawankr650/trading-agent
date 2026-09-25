"""Offline tests for the AI news scanner, Telegram helpers and the web API (no network, no keys)."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import core.news_scanner as ns
from core.announcements import classify_event, is_noise
from core.config import load_config
from core.llm import LLM, to_float
from core.news_scanner import NewsScanner
from notifier.formatter import news_digest_message
from notifier.telegram import split_message

CFG = load_config(overrides=False)

ITEMS = [
    {"title": "RVNL: Bagging/Receiving of orders/contracts — LoA worth Rs 850 crore from Central Railway",
     "link": "https://nse/x.pdf", "published": datetime.now(timezone.utc), "source": "NSE filing",
     "summary": "LoA worth Rs 850 crore", "symbol": "RVNL", "company": "Rail Vikas Nigam", "category": "Bagging/Receiving of orders/contracts",
     "event": "order_win"},
    {"title": "XYZ Ltd shares plunge after SEBI probe", "link": "https://et/y", "published": None, "source": "economictimes",
     "summary": "", "event": "regulatory"},
    {"title": "Trading Window closure", "link": "", "published": None, "source": "NSE filing", "event": "other"},
]


class FakeLLM:
    last_provider = "fake/llama"

    def __init__(self, reply):
        self.reply = reply

    def chat_json(self, system, user, max_tokens=800):
        assert "RVNL" in user
        return self.reply


def tech_ok(symbol, cfg, llm):
    return {"price": 400.0, "change_pct": 1.2, "action": "BUY", "score": 0.4, "tech_score": 0.5, "fund_score": 0.2,
            "rsi": 58.0, "plan": {"entry": 400, "stop": 388, "target": 424}, "fundamentals": {"marketCap": 8e11},
            "criteria": ["✅ Price above 50-DMA"]}


def tech_weak(symbol, cfg, llm):
    return {**tech_ok(symbol, cfg, llm), "action": "SELL", "tech_score": -0.6, "score": -0.4}


class Helpers(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify_event("Bagging/Receiving of orders/contracts"), "order_win")
        self.assertEqual(classify_event("Company bags order worth Rs 500 cr"), "order_win")
        self.assertEqual(classify_event("Q2 net profit rises 20%"), "results")
        self.assertEqual(classify_event("SEBI imposes penalty"), "regulatory")
        self.assertEqual(classify_event("Operating update"), "other")  # "rating" inside "operating" must not match
        self.assertTrue(is_noise("Closure of Trading Window"))

    def test_to_float(self):
        self.assertEqual(to_float("80%"), 0.8); self.assertEqual(to_float("high"), 0.8)
        self.assertEqual(to_float(0.6), 0.6); self.assertEqual(to_float(None), 0.0)

    def test_extract_json(self):
        self.assertEqual(LLM.extract_json('<think>hmm {"a": 0}</think>```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(LLM.extract_json('[{"id": 0}]'), [{"id": 0}])
        self.assertIsNone(LLM.extract_json("no json"))

    def test_split_message(self):
        text = "\n".join(f"<b>line {i}</b> " + "x" * 80 for i in range(200))
        chunks = split_message(text, 1000)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual("\n".join(chunks), text)
        self.assertTrue(all(c.count("<b>") == c.count("</b>") for c in chunks))

    def test_llm_skips_unconfigured_and_cools_down_failed(self):
        cfg = {"llm": {"providers": [{"name": "a", "base_url": "http://a", "model": "m", "api_key_env": "NOPE_KEY_X"},
                                     {"name": "b", "base_url": "http://b", "model": "m", "api_key_env": ""}]}}
        llm = LLM(cfg)
        bad = mock.Mock(status_code=404, text="model not found")
        with mock.patch("core.llm.requests.post", return_value=bad) as post:
            self.assertIsNone(llm.chat("s", "u"))
            self.assertIsNone(llm.chat("s", "u"))
        self.assertEqual(post.call_count, 1)  # "a" has no key; "b" failed once then cooled down


class Scanner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.multiple(ns, SEEN_FILE=Path(self.tmp.name) / "seen.json", DIGEST_FILE=Path(self.tmp.name) / "d.json")
        p.start(); self.addCleanup(p.stop); self.addCleanup(self.tmp.cleanup)

    def reply(self):
        return {"market_mood": "Mixed; railway orders strong.", "items": [
            {"id": 0, "symbol": "RVNL", "company": "Rail Vikas Nigam", "event": "order_win",
             "summary": "RVNL won an ₹850 cr order.", "impact": "bullish", "materiality": "high",
             "recommendation": "BUY", "confidence": "0.8", "horizon": "swing (1-4 weeks)",
             "thinking": ["Order is material", "Adds to order book"], "risks": "Execution delays"},
            {"id": 1, "symbol": "", "company": "XYZ", "event": "regulatory", "summary": "SEBI probe.",
             "impact": "bearish", "materiality": "medium", "recommendation": "AVOID", "confidence": 0.7,
             "thinking": "Probe is negative; outcome uncertain", "risks": ""}]}

    def scanner(self, analyzer=tech_ok, reply=None):
        return NewsScanner(CFG, FakeLLM(reply if reply is not None else self.reply()), analyzer=analyzer,
                           collector=lambda: [dict(i) for i in ITEMS])

    def test_llm_digest_with_technical_confirmation(self):
        d = self.scanner().run()
        self.assertEqual(d["scanned"], 2)  # trading-window filing dropped as noise
        top = d["picks"][0]
        self.assertEqual((top["symbol"], top["recommendation"], top["confidence"]), ("RVNL", "BUY", 0.8))
        self.assertEqual(top["tech"]["plan"]["target"], 424)
        self.assertEqual(d["source"], "fake/llama")
        self.assertEqual(len(NewsScanner.actionable(d, 0.55)), 1)
        msg = news_digest_message(d)
        for s in ("BUY candidate · RVNL", "Thinking", "Order is material", "Entry 400", "Market mood"):
            self.assertIn(s, msg)
        self.assertTrue(ns.DIGEST_FILE.exists())

    def test_weak_chart_downgrades_buy(self):
        rvnl = next(p for p in self.scanner(analyzer=tech_weak).run()["picks"] if p["symbol"] == "RVNL")
        self.assertEqual(rvnl["recommendation"], "WATCH")
        self.assertIn("Downgraded", rvnl["thinking"][-1])

    def test_seen_items_not_repeated(self):
        s = self.scanner()
        self.assertEqual(s.run()["scanned"], 2)
        self.assertEqual(s.run()["scanned"], 0)
        self.assertEqual(s.run(only_new=False)["scanned"], 2)

    def test_keyword_fallback_without_llm(self):
        d = self.scanner(reply={}).run(confirm=False)
        self.assertEqual(d["source"], "keywords (no LLM available)")
        self.assertEqual({p["recommendation"] for p in d["picks"]} <= {"WATCH", "AVOID"}, True)
        json.dumps(d, default=str)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            raise unittest.SkipTest("fastapi not installed")
        from server import app as srv
        cls.srv, cls.c = srv, TestClient(srv.app)

    def test_health_and_digest(self):
        r = self.c.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertIn("llm_providers", r.json())
        self.assertEqual(self.c.get("/api/news/digest").status_code, 200)

    def test_bad_symbol_rejected(self):
        self.assertEqual(self.c.get("/api/analyze/..%2Fetc").status_code in (400, 404), True)
        self.assertEqual(self.c.get("/api/analyze/bad sym").status_code, 400)

    def test_token_required_when_set(self):
        with mock.patch.dict("os.environ", {"APP_TOKEN": "s3cret"}):
            self.assertEqual(self.c.get("/api/health").status_code, 401)
            self.assertEqual(self.c.get("/api/health", headers={"X-App-Token": "s3cret"}).status_code, 200)

    def test_trader_endpoint(self):
        r = self.c.get("/api/trader")
        self.assertEqual(r.status_code, 200)
        self.assertIn("stats", r.json())


if __name__ == "__main__":
    unittest.main()
