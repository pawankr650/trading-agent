"""Offline tests for the web app's engines (no network, no API keys).  Run:  python -m unittest -v"""
import os
import unittest

os.environ["STOCKPILOT_DEMO"] = "1"  # never touch the network from tests

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core import algo  # noqa: E402
from core.config import load_config  # noqa: E402
from core.datastore import PriceStore  # noqa: E402
from core.hf_nlp import NewsNLP  # noqa: E402
from core.insights import build  # noqa: E402
from core.news_engine import NewsEngine  # noqa: E402
from core.nifty50 import SYMBOLS, tag_symbols  # noqa: E402
from core.patterns import candlestick_patterns, chart_patterns, detect  # noqa: E402
from tests.test_all import ohlcv  # noqa: E402

CFG = load_config()
CFG["llm"]["enabled"] = False
CFG["hf"]["backend"] = "keyword"


def double_bottom(n=260):
    """Downtrend → two equal lows ~30 bars apart → rally through the neckline."""
    a = np.linspace(1200, 1000, n - 50)
    b = np.r_[np.linspace(1000, 1080, 15)[1:], np.linspace(1080, 1000, 15)[1:], np.linspace(1000, 1110, 22)[1:]]
    close = np.r_[a, b]
    idx = pd.bdate_range(end="2026-09-23", periods=len(close))
    return pd.DataFrame({"Open": close * 0.998, "High": close * 1.004, "Low": close * 0.996, "Close": close,
                         "Volume": 1e5}, index=idx)


class Universe(unittest.TestCase):
    def test_fifty(self):
        self.assertEqual(len(SYMBOLS), 50)

    def test_tagging(self):
        self.assertEqual(tag_symbols("SBI Life premium grows 12%"), ["SBILIFE"])
        self.assertEqual(tag_symbols("Infosys and TCS lead IT rally"), ["INFY", "TCS"])
        self.assertEqual(tag_symbols("Titanic losses for investors"), [])


class NLP(unittest.TestCase):
    def test_keyword_backend(self):
        nlp = NewsNLP(CFG)
        self.assertEqual(nlp.backend, "keyword")
        pos = nlp.analyze("Tata Steel shares surge after record profit")
        neg = nlp.analyze("SEBI probe: shares plunge")
        self.assertGreater(pos["score"], 0); self.assertLess(neg["score"], 0)
        self.assertEqual(nlp.analyze("L&T bags large order from NHAI")["event"], "order win or contract")


class Patterns(unittest.TestCase):
    def test_detect_shapes(self):
        p = detect(ohlcv(0.002))
        for k in ("candlestick", "chart", "levels", "bias"):
            self.assertIn(k, p)
        for x in p["candlestick"] + p["chart"]:
            self.assertIn(x["bias"], ("bullish", "bearish", "neutral"))
            self.assertIsInstance(x["bars_ago"], int)

    def test_double_bottom(self):
        names = [p["name"] for p in chart_patterns(double_bottom())]
        self.assertIn("Double Bottom", names)

    def test_candles_found(self):
        self.assertTrue(candlestick_patterns(ohlcv(0.001, seed=3)))


class Insights(unittest.TestCase):
    def test_buy_plan_ordering(self):
        news = [{"title": "x", "ts": None, "nlp": {"score": 0.9, "sentiment": "positive", "event": "e", "confidence": 0.9}}]
        ins = build("TCS", ohlcv(0.004), news, CFG)
        p = ins["plan"]
        if p["side"] == "long":
            self.assertLess(p["stop"], p["entry_zone"][0]); self.assertGreater(p["target1"], p["entry"])
            self.assertGreaterEqual(p["target2"], p["target1"])
        self.assertIn(ins["action"], ("BUY", "SELL", "WATCH", "HOLD", "AVOID"))

    def test_engine_cycle(self):
        e = NewsEngine(CFG, PriceStore(CFG))
        got = e.cycle()
        self.assertTrue(got)
        self.assertEqual(len(e.insights), 50)


class Algo(unittest.TestCase):
    def test_every_strategy_runs(self):
        df = ohlcv(0.001, n=600, seed=5)
        for k in algo.STRATEGIES:
            r = algo.run(df, k)
            self.assertEqual(len(r["equity"]), len(df))
            self.assertIn("sharpe", r["stats"])

    def test_optimize_and_compare(self):
        df = ohlcv(0.001, n=600, seed=5)
        r = algo.run(df, "sma_cross", optimize=True)
        self.assertLess(r["params"]["fast"], r["params"]["slow"])
        self.assertIsNotNone(r["out_of_sample"])
        self.assertEqual(len(algo.compare(df)), len(algo.STRATEGIES))


if __name__ == "__main__":
    unittest.main()
