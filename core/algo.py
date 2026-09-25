"""Algo-trading lab on top of backtesting.py (github.com/kernc/backtesting.py).

Seven classic, well-documented strategies; run one, auto-tune it (train 70% / out-of-sample 30%),
or race them all and pick the best on risk-adjusted return.
"""
from __future__ import annotations

import math
import os
import warnings

os.environ.setdefault("TQDM_DISABLE", "1")  # backtesting.py progress bars would flood the server log

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

from .indicators import atr as _atr
from .indicators import ema as _ema
from .indicators import macd as _macd
from .indicators import rsi as _rsi
from .indicators import supertrend as _supertrend

warnings.filterwarnings("ignore", module="backtesting")


def SMA(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def EMA(x, n):
    return _ema(pd.Series(x), n).to_numpy()


def RSI(x, n):
    return _rsi(pd.Series(x), n).to_numpy()


def _frame(data) -> pd.DataFrame:
    return pd.DataFrame({"Open": data.Open, "High": data.High, "Low": data.Low, "Close": data.Close})


class SmaCross(Strategy):
    """Buy when the fast SMA crosses above the slow SMA, exit on the cross back."""
    fast, slow = 20, 50

    def init(self):
        self.f = self.I(SMA, self.data.Close, self.fast, name=f"SMA{self.fast}")
        self.s = self.I(SMA, self.data.Close, self.slow, name=f"SMA{self.slow}")

    def next(self):
        if crossover(self.f, self.s):
            self.buy()
        elif crossover(self.s, self.f):
            self.position.close()


class EmaAtrTrend(Strategy):
    """EMA crossover entries, ATR trailing stop exits (trend following with volatility-sized risk)."""
    fast, slow, atr_mult = 12, 26, 3.0

    def init(self):
        self.f = self.I(EMA, self.data.Close, self.fast, name=f"EMA{self.fast}")
        self.s = self.I(EMA, self.data.Close, self.slow, name=f"EMA{self.slow}")
        self.a = self.I(lambda: _atr(_frame(self.data)).to_numpy(), name="ATR", plot=False)

    def next(self):
        px = self.data.Close[-1]
        if not self.position and crossover(self.f, self.s):
            self.buy(sl=px - self.atr_mult * self.a[-1])
        for t in self.trades:
            t.sl = max(t.sl or 0, px - self.atr_mult * self.a[-1])
        if self.position and crossover(self.s, self.f):
            self.position.close()


class RsiReversion(Strategy):
    """Buy oversold dips inside a long-term uptrend (above 200-SMA); sell into overbought."""
    rsi_n, lower, upper, trend = 14, 30, 70, 200

    def init(self):
        self.r = self.I(RSI, self.data.Close, self.rsi_n, name="RSI")
        self.t = self.I(SMA, self.data.Close, self.trend, name=f"SMA{self.trend}")

    def next(self):
        if not self.position and self.r[-1] < self.lower and self.data.Close[-1] > self.t[-1]:
            self.buy()
        elif self.position and self.r[-1] > self.upper:
            self.position.close()


class MacdMomentum(Strategy):
    """MACD line crossing its signal line, only while price is above the 50-SMA."""
    fast, slow, signal, trend = 12, 26, 9, 50

    def init(self):
        c = pd.Series(self.data.Close)
        self.m = self.I(lambda: _macd(c, self.fast, self.slow, self.signal)[0].to_numpy(), name="MACD")
        self.sg = self.I(lambda: _macd(c, self.fast, self.slow, self.signal)[1].to_numpy(), name="Signal")
        self.t = self.I(SMA, self.data.Close, self.trend, name=f"SMA{self.trend}")

    def next(self):
        if not self.position and crossover(self.m, self.sg) and self.data.Close[-1] > self.t[-1]:
            self.buy()
        elif self.position and crossover(self.sg, self.m):
            self.position.close()


class BollingerReversion(Strategy):
    """Buy a close below the lower Bollinger band, exit at the middle band; hard stop at k·σ below entry."""
    n, k = 20, 2.0

    def init(self):
        c = pd.Series(self.data.Close)
        mid, sd = c.rolling(self.n).mean(), c.rolling(self.n).std()
        self.mid = self.I(lambda: mid.to_numpy(), name="BB mid")
        self.lo = self.I(lambda: (mid - self.k * sd).to_numpy(), name="BB low")
        self.sd = self.I(lambda: sd.to_numpy(), name="σ", plot=False)

    def next(self):
        px = self.data.Close[-1]
        if not self.position and px < self.lo[-1]:
            self.buy(sl=px - self.k * self.sd[-1])
        elif self.position and px > self.mid[-1]:
            self.position.close()


class SupertrendFollow(Strategy):
    """Long while Supertrend(ATR n, mult) is up; flat when it flips down."""
    n, mult = 10, 3.0

    def init(self):
        self.st = self.I(lambda: _supertrend(_frame(self.data), self.n, self.mult).to_numpy(), name="Supertrend")

    def next(self):
        if not self.position and self.st[-1] > 0 and self.st[-2] < 0:
            self.buy()
        elif self.position and self.st[-1] < 0:
            self.position.close()


class DonchianBreakout(Strategy):
    """Turtle-style: buy a close above the N-day high, exit below the M-day low."""
    entry, exit = 20, 10

    def init(self):
        h, l = pd.Series(self.data.High), pd.Series(self.data.Low)
        self.hh = self.I(lambda: h.rolling(self.entry).max().shift(1).to_numpy(), name=f"High{self.entry}")
        self.ll = self.I(lambda: l.rolling(self.exit).min().shift(1).to_numpy(), name=f"Low{self.exit}")

    def next(self):
        px = self.data.Close[-1]
        if not self.position and px > self.hh[-1]:
            self.buy()
        elif self.position and px < self.ll[-1]:
            self.position.close()


STRATEGIES: dict[str, dict] = {
    "sma_cross": {"cls": SmaCross, "label": "SMA Crossover", "family": "Trend",
                  "grid": {"fast": [10, 20, 30], "slow": [50, 100, 150]},
                  "constraint": lambda p: p.fast < p.slow},
    "ema_atr": {"cls": EmaAtrTrend, "label": "EMA Trend + ATR Trailing Stop", "family": "Trend",
                "grid": {"fast": [9, 12, 20], "slow": [26, 50], "atr_mult": [2.0, 3.0, 4.0]},
                "constraint": lambda p: p.fast < p.slow},
    "rsi_reversion": {"cls": RsiReversion, "label": "RSI Mean Reversion (trend-filtered)", "family": "Mean reversion",
                      "grid": {"lower": [25, 30, 35], "upper": [60, 70, 75], "trend": [100, 200]}},
    "macd": {"cls": MacdMomentum, "label": "MACD Momentum", "family": "Momentum",
             "grid": {"fast": [8, 12], "slow": [21, 26], "signal": [9], "trend": [50, 100]}},
    "bollinger": {"cls": BollingerReversion, "label": "Bollinger Band Reversion", "family": "Mean reversion",
                  "grid": {"n": [14, 20, 30], "k": [1.5, 2.0, 2.5]}},
    "supertrend": {"cls": SupertrendFollow, "label": "Supertrend Follow", "family": "Trend",
                   "grid": {"n": [7, 10, 14], "mult": [2.0, 3.0, 4.0]}},
    "donchian": {"cls": DonchianBreakout, "label": "Donchian Breakout (Turtle)", "family": "Breakout",
                 "grid": {"entry": [20, 40, 55], "exit": [10, 20]},
                 "constraint": lambda p: p.exit < p.entry},
}


def catalog() -> list[dict]:
    out = []
    for k, s in STRATEGIES.items():
        cls = s["cls"]
        params = {p: getattr(cls, p) for p in s["grid"]}
        out.append({"id": k, "label": s["label"], "family": s["family"], "doc": (cls.__doc__ or "").strip(),
                    "params": params})
    return out


def _num(x):
    try:
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else round(x, 3)
    except (TypeError, ValueError):
        return None


STAT_KEYS = {"Return [%]": "return_pct", "Buy & Hold Return [%]": "buy_hold_pct", "Return (Ann.) [%]": "cagr_pct",
             "Volatility (Ann.) [%]": "vol_pct", "Sharpe Ratio": "sharpe", "Sortino Ratio": "sortino",
             "Calmar Ratio": "calmar", "Max. Drawdown [%]": "max_dd_pct", "Win Rate [%]": "win_rate",
             "# Trades": "trades", "Profit Factor": "profit_factor", "Expectancy [%]": "expectancy_pct",
             "Exposure Time [%]": "exposure_pct", "Equity Final [$]": "final_equity",
             "Avg. Trade Duration": "avg_duration"}


def _stats(st: pd.Series) -> dict:
    out = {}
    for k, v in STAT_KEYS.items():
        val = st.get(k)
        out[v] = str(val).split(" days")[0] + " d" if k == "Avg. Trade Duration" and val is not None else _num(val)
    return out


def _ts(t) -> int:
    return int(pd.Timestamp(t).timestamp())


def _serialize(st: pd.Series, df: pd.DataFrame, cash: float) -> dict:
    eq = st["_equity_curve"]
    tr = st["_trades"]
    bh = df.Close / df.Close.iloc[0] * cash
    trades = [{"entry_time": _ts(r.EntryTime), "exit_time": _ts(r.ExitTime), "entry": round(float(r.EntryPrice), 2),
               "exit": round(float(r.ExitPrice), 2), "size": int(r.Size), "pnl": round(float(r.PnL), 2),
               "ret_pct": round(float(r.ReturnPct) * 100, 2), "bars": int(r.ExitBar - r.EntryBar)}
              for r in tr.itertuples()]
    return {
        "stats": _stats(st),
        "equity": [{"time": _ts(t), "value": round(float(v), 2)} for t, v in eq.Equity.items()],
        "drawdown": [{"time": _ts(t), "value": round(-float(v) * 100, 2)} for t, v in eq.DrawdownPct.items()],
        "buy_hold": [{"time": _ts(t), "value": round(float(v), 2)} for t, v in bh.items()],
        "trades": trades,
    }


def _bt(df, cls, cash, commission):
    return Backtest(df, cls, cash=cash, commission=commission, exclusive_orders=True, finalize_trades=True)


def run(df: pd.DataFrame, strategy: str, cash: float = 100_000, commission: float = 0.0012,
        params: dict | None = None, optimize: bool = False) -> dict:
    """Backtest one strategy. `commission` 0.12% ≈ Indian delivery brokerage + STT + charges per side."""
    spec = STRATEGIES[strategy]
    cls = spec["cls"]
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    params = {k: v for k, v in (params or {}).items() if k in spec["grid"]}
    oos = None
    if optimize:
        split = int(len(df) * 0.7)
        train = df.iloc[:split]
        best = _bt(train, cls, cash, commission).optimize(
            **spec["grid"], maximize="Sharpe Ratio", constraint=spec.get("constraint"), max_tries=60,
            random_state=7)
        params = {k: (float(v) if isinstance(v, (float, np.floating)) else int(v))
                  for k, v in best._strategy._params.items()}
        test = df.iloc[split - 1:]
        oos = {"from": _ts(test.index[0]), "stats": _stats(_bt(test, cls, cash, commission).run(**params))}
    st = _bt(df, cls, cash, commission).run(**params)
    used = {p: getattr(st._strategy, p) for p in spec["grid"]}
    out = _serialize(st, df, cash)
    out.update(strategy=strategy, label=spec["label"], params=used, optimized=optimize, out_of_sample=oos,
               cash=cash, commission=commission)
    return out


def compare(df: pd.DataFrame, cash: float = 100_000, commission: float = 0.0012) -> list[dict]:
    """Race every strategy with default params; ranked by Sharpe, then return."""
    rows = []
    for k, s in STRATEGIES.items():
        try:
            st = _bt(df, s["cls"], cash, commission).run()
            rows.append({"id": k, "label": s["label"], "family": s["family"], **_stats(st)})
        except Exception as e:  # a strategy failing must not break the race
            rows.append({"id": k, "label": s["label"], "family": s["family"], "error": str(e)})
    rows.sort(key=lambda r: (r.get("sharpe") or -99, r.get("return_pct") or -999), reverse=True)
    return rows
