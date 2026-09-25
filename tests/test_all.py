"""Offline tests (no network, no API keys).  Run:  python -m unittest -v"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from autotrader.engine import AutoTrader
from autotrader.journal import Journal
from autotrader.risk import RiskManager
from core.analysis import analyze, decide
from core.charts import render_chart
from core.config import load_config
from core.indicators import add_indicators, rsi, technical_score
from core.news import keyword_sentiment
from notifier.formatter import board_message, signal_message

CFG = load_config(overrides=False)
CFG["autotrader"]["no_new_entries_after"] = "23:59"
CFG["autotrader"]["mis_square_off"] = "23:59"


def ohlcv(trend=0.002, n=300, seed=1):
    rng = np.random.default_rng(seed)
    close = 1000 * np.cumprod(1 + trend + rng.normal(0, 0.01, n))
    idx = pd.bdate_range(end="2026-09-23", periods=n)
    op = close * (1 + rng.normal(0, 0.003, n))
    return pd.DataFrame({"Open": op, "High": np.maximum(op, close) * 1.005, "Low": np.minimum(op, close) * 0.995,
                         "Close": close, "Volume": rng.integers(1e5, 5e5, n).astype(float)}, index=idx)


GOOD_F = {"returnOnEquity": 0.22, "debtToEquity": 20, "revenueGrowth": 0.15, "earningsGrowth": 0.2,
          "profitMargins": 0.18, "trailingPE": 22, "longName": "Test Ltd"}


class Core(unittest.TestCase):
    def test_rsi_bounds(self):
        r = rsi(ohlcv()["Close"]).dropna()
        self.assertTrue(((r >= 0) & (r <= 100)).all())

    def test_uptrend_scores_positive(self):
        up, _ = technical_score(add_indicators(ohlcv(0.004)))
        dn, _ = technical_score(add_indicators(ohlcv(-0.004)))
        self.assertGreater(up, 0); self.assertLess(dn, 0)

    def test_decide(self):
        self.assertEqual(decide(0.8, 0.6, 0.5, CFG)[0], "BUY")
        self.assertEqual(decide(-0.8, -0.2, -0.5, CFG)[0], "SELL")
        self.assertEqual(decide(-0.1, 1, 1, CFG)[0], "HOLD")  # tech must agree

    def test_keyword_sentiment(self):
        self.assertGreater(keyword_sentiment(["Stock surges after record profit"]), 0)
        self.assertLess(keyword_sentiment(["Shares plunge on SEBI probe"]), 0)

    def test_analyze_and_render(self):
        r = analyze("TEST", CFG, llm=None, df=ohlcv(0.004), fundamentals=GOOD_F,
                    news=[{"title": "Test Ltd bags big order, shares surge", "link": "http://x", "source": "t", "published": None}])
        self.assertEqual(r["action"], "BUY")
        self.assertLess(r["plan"]["stop"], r["plan"]["entry"]); self.assertGreater(r["plan"]["target"], r["plan"]["entry"])
        self.assertIn("BUY", signal_message(r)); self.assertIn("TEST", board_message([r], "t"))
        self.assertTrue(Path(render_chart(r)).exists())


class FakeBroker:
    mode = "paper"

    def __init__(self): self.px, self.orders = 1000.0, []
    def ltp(self, s): return self.px
    def place_order(self, s, a, q, price_type="MARKET", trigger_price=0.0, product="CNC"):
        self.orders.append((s, a, q, price_type)); return {"status": "success", "orderid": str(len(self.orders)), "price": self.px}
    def cancel_order(self, oid): return {"status": "success"}
    def position_qty(self, s, p="CNC"): return None


class FakeLLM:
    def __init__(self, agree=True): self.agree = agree


class SilentTG:
    token, chat_id, ready = "", "", False
    def __init__(self): self.msgs = []
    def send(self, t, chat_id=None): self.msgs.append(t)


def fake_scanner(action):
    def _scan(cfg, llm, review=False):
        r = analyze("TEST", cfg, None, df=ohlcv(0.004), fundamentals=GOOD_F, news=[])
        r.update(action=action, score=0.7 if action == "BUY" else -0.7,
                 plan={"entry": 1000, "stop": 970, "target": 1060},
                 llm_review={"action": action if llm.agree else "HOLD", "confidence": 0.8, "rationale": "test"})
        return [r]
    return _scan


class AutoTrading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.j = Journal(Path(self.tmp.name) / "t.db")
        self.b, self.tg = FakeBroker(), SilentTG()

    def tearDown(self):
        self.j.db.close(); self.tmp.cleanup()

    def bot(self, agree=True, action="BUY"):
        return AutoTrader(CFG, broker=self.b, journal=self.j, llm=FakeLLM(agree), telegram=self.tg,
                          scanner=fake_scanner(action))

    def test_sizing(self):
        qty = RiskManager(CFG).size(1000, 970)  # 1% of 1L = 1000 risk / 30 = 33; cap 20% = 20 shares
        self.assertEqual(qty, 20)

    def test_entry_then_target_exit(self):
        bot = self.bot(); bot.cycle()
        self.assertEqual(len(self.j.open_trades()), 1)
        self.assertEqual([o[3] for o in self.b.orders], ["MARKET", "SL-M"])
        self.b.px = 1065; bot.manage_positions()
        self.assertEqual(len(self.j.open_trades()), 0)
        self.assertGreater(self.j.realized_today(), 0)

    def test_stop_loss_exit(self):
        bot = self.bot(); bot.cycle(); self.b.px = 960; bot.manage_positions()
        self.assertLess(self.j.realized_today(), 0)

    def test_llm_veto_blocks_entry(self):
        self.bot(agree=False).cycle()
        self.assertEqual(self.j.open_trades(), [])

    def test_no_shorts_in_cnc(self):
        self.bot(action="SELL").cycle()
        self.assertEqual(self.j.open_trades(), [])

    def test_daily_loss_kill(self):
        rm = RiskManager(CFG)
        self.assertFalse(rm.can_enter(0, -2500, 0)[0])
        self.assertTrue(rm.can_enter(0, -500, 0)[0])


if __name__ == "__main__":
    unittest.main()
