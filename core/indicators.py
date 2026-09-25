"""Technical indicators in plain pandas (no TA-Lib build pain) + rule-based technical score.

Every rule returns a human-readable *criterion* so alerts can explain WHY.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.Series:
    """+1 uptrend / -1 downtrend."""
    hl2 = (df["High"] + df["Low"]) / 2
    a = atr(df, n)
    upper, lower = (hl2 + mult * a).values, (hl2 - mult * a).values
    close = df["Close"].values
    fu, fl = upper.copy(), lower.copy()
    direction = np.ones(len(df))
    for i in range(1, len(df)):
        fu[i] = upper[i] if upper[i] < fu[i - 1] or close[i - 1] > fu[i - 1] else fu[i - 1]
        fl[i] = lower[i] if lower[i] > fl[i - 1] or close[i - 1] < fl[i - 1] else fl[i - 1]
        if close[i] > fu[i - 1]:
            direction[i] = 1
        elif close[i] < fl[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return pd.Series(direction, index=df.index)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    df["SMA20"], df["SMA50"], df["SMA200"] = sma(c, 20), sma(c, 50), sma(c, 200)
    df["RSI"] = rsi(c)
    df["MACD"], df["MACD_signal"], df["MACD_hist"] = macd(c)
    df["ATR"] = atr(df)
    std = c.rolling(20).std()
    df["BB_up"], df["BB_lo"] = df["SMA20"] + 2 * std, df["SMA20"] - 2 * std
    df["VOL_ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()
    df["SUPERTREND"] = supertrend(df)
    return df


def technical_score(df: pd.DataFrame) -> tuple[float, list[str]]:
    """Score in [-1, 1] + list of criteria that fired."""
    if len(df) < 60:
        return 0.0, ["Not enough history"]
    r, p = df.iloc[-1], df.iloc[-2]
    pts, why = [], []

    def rule(cond_up: bool, cond_dn: bool, w: float, up_txt: str, dn_txt: str):
        if cond_up:
            pts.append(w); why.append(f"✅ {up_txt}")
        elif cond_dn:
            pts.append(-w); why.append(f"❌ {dn_txt}")
        else:
            pts.append(0)

    rule(r.Close > r.SMA50, r.Close < r.SMA50, 1, "Price above 50-DMA", "Price below 50-DMA")
    if not np.isnan(r.SMA200):
        rule(r.SMA50 > r.SMA200, r.SMA50 < r.SMA200, 1, "Golden alignment (50-DMA > 200-DMA)", "Death alignment (50-DMA < 200-DMA)")
    rule(r.MACD_hist > 0 and r.MACD_hist > p.MACD_hist, r.MACD_hist < 0 and r.MACD_hist < p.MACD_hist, 1,
         "MACD bullish & strengthening", "MACD bearish & weakening")
    rule(r.MACD > r.MACD_signal and p.MACD <= p.MACD_signal, r.MACD < r.MACD_signal and p.MACD >= p.MACD_signal, 1,
         "Fresh MACD bullish crossover", "Fresh MACD bearish crossover")
    rule(r.RSI < 30, r.RSI > 70, 1, f"RSI {r.RSI:.0f} oversold (bounce zone)", f"RSI {r.RSI:.0f} overbought")
    rule(50 <= r.RSI <= 70, 30 <= r.RSI < 45, 0.5, f"RSI {r.RSI:.0f} in bullish momentum zone", f"RSI {r.RSI:.0f} weak momentum")
    rule(r.SUPERTREND > 0, r.SUPERTREND < 0, 1, "Supertrend(10,3) = BUY", "Supertrend(10,3) = SELL")
    rule(r.Close < r.BB_lo, r.Close > r.BB_up, 0.5, "Closed below lower Bollinger (mean-reversion)", "Closed above upper Bollinger (stretched)")
    up_day = r.Close > p.Close
    rule(r.VOL_ratio > 1.5 and up_day, r.VOL_ratio > 1.5 and not up_day, 1,
         f"Volume {r.VOL_ratio:.1f}x avg on up-move", f"Volume {r.VOL_ratio:.1f}x avg on down-move")

    max_pts = 8.0
    return float(np.clip(sum(pts) / max_pts, -1, 1)), why
