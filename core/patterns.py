"""Pattern detection for NIFTY 50.

* Candlestick patterns — TA-Lib's 61 CDL* recognisers (github.com/TA-Lib/ta-lib-python), with a pure-pandas
  fallback for the most common ones when TA-Lib is not installed.
* Chart patterns — swing pivots (scipy.signal.argrelextrema) + geometry: double top/bottom, head & shoulders
  (and inverse), triangles, wedges, channels, 52-week / 20-day breakouts, golden/death cross.

Every detection is a plain dict the UI can draw: `points` become markers, `lines` become trend lines.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import talib  # type: ignore
    from talib import abstract  # type: ignore
    HAS_TALIB = True
except Exception:  # pragma: no cover - depends on install
    HAS_TALIB = False

try:
    from scipy.signal import argrelextrema  # type: ignore
except Exception:  # pragma: no cover
    argrelextrema = None


def ts(t) -> int:
    return int(pd.Timestamp(t).timestamp())


# ── candlestick patterns ────────────────────────────────────────
_BULL_ONLY = {"CDLHAMMER", "CDLINVERTEDHAMMER", "CDLMORNINGSTAR", "CDLMORNINGDOJISTAR", "CDL3WHITESOLDIERS",
              "CDLPIERCING", "CDLTAKURI", "CDLLADDERBOTTOM", "CDLMATHOLD", "CDLUNIQUE3RIVER", "CDLHOMINGPIGEON",
              "CDLSTICKSANDWICH", "CDLCONCEALBABYSWALL"}
_BEAR_ONLY = {"CDLHANGINGMAN", "CDLSHOOTINGSTAR", "CDLEVENINGSTAR", "CDLEVENINGDOJISTAR", "CDL3BLACKCROWS",
              "CDLDARKCLOUDCOVER", "CDLADVANCEBLOCK", "CDLSTALLEDPATTERN", "CDLIDENTICAL3CROWS",
              "CDLUPSIDEGAP2CROWS", "CDL2CROWS", "CDLONNECK", "CDLINNECK", "CDLTHRUSTING"}
# weak/noisy single-bar shapes that fire constantly — skipped to keep the signal readable
_NOISY = {"CDLSPINNINGTOP", "CDLLONGLINE", "CDLSHORTLINE", "CDLHIGHWAVE", "CDLMARUBOZU", "CDLCLOSINGMARUBOZU",
          "CDLBELTHOLD", "CDLLONGLEGGEDDOJI", "CDLRICKSHAWMAN", "CDLHIKKAKE", "CDLHIKKAKEMOD"}


def _talib_candles(df: pd.DataFrame, lookback: int) -> list[dict]:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    out = []
    for fn in talib.get_function_groups()["Pattern Recognition"]:
        if fn in _NOISY:
            continue
        res = getattr(talib, fn)(o, h, l, c)
        nice = abstract.Function(fn).info.get("display_name", fn[3:]).title()
        for i in np.nonzero(res[-lookback:])[0]:
            j = len(df) - lookback + i
            v = int(res[j])
            bias = "bullish" if v > 0 else "bearish"
            if fn in _BULL_ONLY and v < 0 or fn in _BEAR_ONLY and v > 0:
                continue
            if fn == "CDLDOJI":
                bias = "neutral"
            out.append(_candle(df, j, nice, bias, strength=abs(v) // 100))
    return out


def _fallback_candles(df: pd.DataFrame, lookback: int) -> list[dict]:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    body, rng = np.abs(c - o), (h - l) + 1e-9
    up_sh, lo_sh = h - np.maximum(o, c), np.minimum(o, c) - l
    trend = pd.Series(c).pct_change(5).to_numpy()
    out = []
    for j in range(max(3, len(df) - lookback), len(df)):
        if body[j] < 0.1 * rng[j]:
            out.append(_candle(df, j, "Doji", "neutral"))
        if lo_sh[j] > 2 * body[j] and up_sh[j] < body[j] and trend[j] < 0:
            out.append(_candle(df, j, "Hammer", "bullish"))
        if up_sh[j] > 2 * body[j] and lo_sh[j] < body[j] and trend[j] > 0:
            out.append(_candle(df, j, "Shooting Star", "bearish"))
        if c[j] > o[j] and c[j - 1] < o[j - 1] and c[j] >= o[j - 1] and o[j] <= c[j - 1]:
            out.append(_candle(df, j, "Engulfing Pattern", "bullish"))
        if c[j] < o[j] and c[j - 1] > o[j - 1] and c[j] <= o[j - 1] and o[j] >= c[j - 1]:
            out.append(_candle(df, j, "Engulfing Pattern", "bearish"))
        if all(c[k] > o[k] for k in (j - 2, j - 1, j)) and c[j] > c[j - 1] > c[j - 2]:
            out.append(_candle(df, j, "Three Advancing White Soldiers", "bullish"))
        if all(c[k] < o[k] for k in (j - 2, j - 1, j)) and c[j] < c[j - 1] < c[j - 2]:
            out.append(_candle(df, j, "Three Black Crows", "bearish"))
    return out


def _candle(df: pd.DataFrame, j: int, nice: str, bias: str, strength: int = 1) -> dict:
    r = df.iloc[j]
    return {"name": nice, "type": "candlestick", "bias": bias, "time": ts(df.index[j]),
            "date": str(df.index[j].date()), "price": round(float(r.High if bias == "bearish" else r.Low), 2),
            "bars_ago": int(len(df) - 1 - j), "strength": int(strength),
            "points": [{"time": ts(df.index[j]), "price": round(float(r.Close), 2)}], "lines": []}


def candlestick_patterns(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    lookback = min(lookback, len(df) - 3)
    return _talib_candles(df, lookback) if HAS_TALIB else _fallback_candles(df, lookback)


# ── chart patterns ──────────────────────────────────────────────
def pivots(df: pd.DataFrame, order: int = 5) -> tuple[np.ndarray, np.ndarray]:
    h, l = df.High.to_numpy(float), df.Low.to_numpy(float)
    if argrelextrema is not None:
        hi, lo = argrelextrema(h, np.greater_equal, order=order)[0], argrelextrema(l, np.less_equal, order=order)[0]
    else:
        hi = [i for i in range(order, len(h) - order) if h[i] == h[i - order:i + order + 1].max()]
        lo = [i for i in range(order, len(l) - order) if l[i] == l[i - order:i + order + 1].min()]
    return _dedupe(hi, h, max), _dedupe(lo, l, min)


def _dedupe(idx, vals, pick) -> np.ndarray:
    """Flat tops/bottoms yield runs of neighbouring pivots — keep one (the extreme, latest on ties) per run."""
    out: list[int] = []
    for i in idx:
        if out and i - out[-1] <= 3:
            if pick(vals[i], vals[out[-1]]) == vals[i]:
                out[-1] = int(i)
        else:
            out.append(int(i))
    return np.array(out, int)


def _pt(df, i, col):
    return {"time": ts(df.index[i]), "price": round(float(df[col].iloc[i]), 2)}


def _chart(name, bias, status, desc, points=(), lines=(), level=None, df=None, end=None):
    return {"name": name, "type": "chart", "bias": bias, "status": status, "description": desc,
            "points": list(points), "lines": [list(x) for x in lines], "level": level,
            "time": points[-1]["time"] if points else None,
            "bars_ago": int(len(df) - 1 - end) if df is not None and end is not None else 0}


def _double(df, hi, lo, c) -> list[dict]:
    out, n = [], len(df)
    H, L = df.High.to_numpy(float), df.Low.to_numpy(float)
    for a, b in list(zip(hi[:-1], hi[1:]))[-1:]:  # double top: the latest two swing highs only
        if 10 <= b - a <= 80 and abs(H[a] / H[b] - 1) < 0.015 and n - b < 25 and H[b] >= H[a:].max() * 0.99:
            trough = a + int(np.argmin(L[a:b + 1]))
            if L[trough] < min(H[a], H[b]) * 0.95:
                neck = float(L[trough])
                st = "confirmed" if c[-1] < neck else "forming"
                out.append(_chart("Double Top", "bearish", st,
                                  f"Two peaks near ₹{H[b]:.0f}; neckline ₹{neck:.0f}. Break below targets ₹{neck - (H[b] - neck):.0f}.",
                                  [_pt(df, a, "High"), _pt(df, trough, "Low"), _pt(df, b, "High")],
                                  [[{"time": ts(df.index[a]), "price": round(neck, 2)},
                                    {"time": ts(df.index[-1]), "price": round(neck, 2)}]], round(neck, 2), df, b))
    for a, b in list(zip(lo[:-1], lo[1:]))[-1:]:  # double bottom: the latest two swing lows only
        if 10 <= b - a <= 80 and abs(L[a] / L[b] - 1) < 0.015 and n - b < 25 and L[b] <= L[a:].min() * 1.01:
            peak = a + int(np.argmax(H[a:b + 1]))
            if H[peak] > max(L[a], L[b]) * 1.05:
                neck = float(H[peak])
                st = "confirmed" if c[-1] > neck else "forming"
                out.append(_chart("Double Bottom", "bullish", st,
                                  f"Two troughs near ₹{L[b]:.0f}; neckline ₹{neck:.0f}. Break above targets ₹{neck + (neck - L[b]):.0f}.",
                                  [_pt(df, a, "Low"), _pt(df, peak, "High"), _pt(df, b, "Low")],
                                  [[{"time": ts(df.index[a]), "price": round(neck, 2)},
                                    {"time": ts(df.index[-1]), "price": round(neck, 2)}]], round(neck, 2), df, b))
    return out


def _head_shoulders(df, hi, lo, c) -> list[dict]:
    out = []
    H, L = df.High.to_numpy(float), df.Low.to_numpy(float)
    if len(hi) >= 3:
        ls, hd, rs = hi[-3:]
        if (H[hd] > H[ls] * 1.02 and H[hd] > H[rs] * 1.02 and abs(H[ls] / H[rs] - 1) < 0.04
                and len(df) - rs < 40):
            t1, t2 = ls + int(np.argmin(L[ls:hd + 1])), hd + int(np.argmin(L[hd:rs + 1]))
            neck = (L[t1] + L[t2]) / 2
            out.append(_chart("Head & Shoulders", "bearish", "confirmed" if c[-1] < neck else "forming",
                              f"Head ₹{H[hd]:.0f} between shoulders ~₹{H[rs]:.0f}; neckline ₹{neck:.0f}.",
                              [_pt(df, ls, "High"), _pt(df, t1, "Low"), _pt(df, hd, "High"), _pt(df, t2, "Low"),
                               _pt(df, rs, "High")],
                              [[_pt(df, t1, "Low"), _pt(df, t2, "Low")]], round(neck, 2), df, rs))
    if len(lo) >= 3:
        ls, hd, rs = lo[-3:]
        if (L[hd] < L[ls] * 0.98 and L[hd] < L[rs] * 0.98 and abs(L[ls] / L[rs] - 1) < 0.04
                and len(df) - rs < 40):
            t1, t2 = ls + int(np.argmax(H[ls:hd + 1])), hd + int(np.argmax(H[hd:rs + 1]))
            neck = (H[t1] + H[t2]) / 2
            out.append(_chart("Inverse Head & Shoulders", "bullish", "confirmed" if c[-1] > neck else "forming",
                              f"Head ₹{L[hd]:.0f} between shoulders ~₹{L[rs]:.0f}; neckline ₹{neck:.0f}.",
                              [_pt(df, ls, "Low"), _pt(df, t1, "High"), _pt(df, hd, "Low"), _pt(df, t2, "High"),
                               _pt(df, rs, "Low")],
                              [[_pt(df, t1, "High"), _pt(df, t2, "High")]], round(neck, 2), df, rs))
    return out


def _trendlines(df, hi, lo, c, window: int = 90) -> list[dict]:
    """Fit lines through recent swing highs and lows → triangle / wedge / channel."""
    n = len(df)
    hi, lo = hi[hi >= n - window], lo[lo >= n - window]
    if len(hi) < 3 or len(lo) < 3:
        return []
    H, L = df.High.to_numpy(float), df.Low.to_numpy(float)
    sh, ih = np.polyfit(hi, H[hi], 1)
    sl, il = np.polyfit(lo, L[lo], 1)
    px = float(c[-1])
    norm = lambda s: s / px * 100  # slope in % of price per bar
    nh, nl = norm(sh), norm(sl)
    flat = 0.03
    start = min(hi[0], lo[0])
    up_now, lo_now = sh * (n - 1) + ih, sl * (n - 1) + il
    width_start, width_now = (sh * start + ih) - (sl * start + il), up_now - lo_now
    converging = width_now < width_start * 0.75

    if abs(nh) < flat and nl > flat:
        name, bias = "Ascending Triangle", "bullish"
    elif nh < -flat and abs(nl) < flat:
        name, bias = "Descending Triangle", "bearish"
    elif nh < -flat and nl > flat:
        name, bias = "Symmetrical Triangle", "neutral"
    elif nh > flat and nl > flat and converging:
        name, bias = "Rising Wedge", "bearish"
    elif nh < -flat and nl < -flat and converging:
        name, bias = "Falling Wedge", "bullish"
    elif nh > flat and nl > flat:
        name, bias = "Rising Channel", "bullish"
    elif nh < -flat and nl < -flat:
        name, bias = "Falling Channel", "bearish"
    elif abs(nh) < flat and abs(nl) < flat:
        name, bias = "Horizontal Range", "neutral"
    else:
        return []
    status = "breakout ↑" if px > up_now else "breakdown ↓" if px < lo_now else "forming"
    if status != "forming":  # a break out of the structure outranks its textbook bias
        bias = "bullish" if px > up_now else "bearish"
    line = lambda s, i: [{"time": ts(df.index[start]), "price": round(s * start + i, 2)},
                         {"time": ts(df.index[-1]), "price": round(s * (n - 1) + i, 2)}]
    return [_chart(name, bias, status,
                   f"Resistance line ₹{up_now:.0f}, support line ₹{lo_now:.0f} over the last {n - start} bars.",
                   [_pt(df, i, "High") for i in hi] + [_pt(df, i, "Low") for i in lo],
                   [line(sh, ih), line(sl, il)], round(float(up_now if bias != "bearish" else lo_now), 2), df, n - 1)]


def _events(df, c) -> list[dict]:
    out, n = [], len(df)
    H, L = df.High.to_numpy(float), df.Low.to_numpy(float)
    if n > 21 and c[-1] > H[-21:-1].max():
        out.append(_chart("20-Day Breakout", "bullish", "confirmed", f"Closed above the 20-day high ₹{H[-21:-1].max():.0f}.",
                          [_pt(df, n - 1, "Close")], [], round(float(H[-21:-1].max()), 2), df, n - 1))
    if n > 21 and c[-1] < L[-21:-1].min():
        out.append(_chart("20-Day Breakdown", "bearish", "confirmed", f"Closed below the 20-day low ₹{L[-21:-1].min():.0f}.",
                          [_pt(df, n - 1, "Close")], [], round(float(L[-21:-1].min()), 2), df, n - 1))
    yr = min(n, 250)
    if c[-1] >= H[-yr:].max() * 0.98:
        out.append(_chart("Near 52-Week High", "bullish", "forming", f"Within 2% of the 52-week high ₹{H[-yr:].max():.0f}.",
                          [_pt(df, n - 1, "Close")], [], round(float(H[-yr:].max()), 2), df, n - 1))
    if c[-1] <= L[-yr:].min() * 1.02:
        out.append(_chart("Near 52-Week Low", "bearish", "forming", f"Within 2% of the 52-week low ₹{L[-yr:].min():.0f}.",
                          [_pt(df, n - 1, "Close")], [], round(float(L[-yr:].min()), 2), df, n - 1))
    s50, s200 = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
    diff = np.sign((s50 - s200).to_numpy())
    for j in range(max(201, n - 15), n):
        if diff[j - 1] < 0 < diff[j]:
            out.append(_chart("Golden Cross", "bullish", "confirmed", "50-DMA crossed above 200-DMA.",
                              [{"time": ts(df.index[j]), "price": round(float(s50.iloc[j]), 2)}], [], None, df, j))
        if diff[j - 1] > 0 > diff[j]:
            out.append(_chart("Death Cross", "bearish", "confirmed", "50-DMA crossed below 200-DMA.",
                              [{"time": ts(df.index[j]), "price": round(float(s50.iloc[j]), 2)}], [], None, df, j))
    return out


def support_resistance(df: pd.DataFrame, hi, lo, k: int = 3) -> dict:
    px = float(df.Close.iloc[-1])
    levels = np.r_[df.High.to_numpy()[hi], df.Low.to_numpy()[lo]]
    levels = levels[len(levels) // 3:] if len(levels) > 9 else levels
    res = sorted({round(float(x), 2) for x in levels if x > px * 1.003})[:k]
    sup = sorted({round(float(x), 2) for x in levels if x < px * 0.997}, reverse=True)[:k]
    return {"support": sup, "resistance": res}


def chart_patterns(df: pd.DataFrame) -> list[dict]:
    if len(df) < 60:
        return []
    c = df.Close.to_numpy(float)
    hi, lo = pivots(df)
    return _double(df, hi, lo, c) + _head_shoulders(df, hi, lo, c) + _trendlines(df, hi, lo, c) + _events(df, c)


def detect(df: pd.DataFrame, candle_lookback: int = 60) -> dict:
    hi, lo = pivots(df)
    candles = candlestick_patterns(df, candle_lookback)
    charts = chart_patterns(df)
    recent = [p for p in candles if p["bars_ago"] <= 5] + [p for p in charts if p["bars_ago"] <= 40]
    bull = sum(p["bias"] == "bullish" for p in recent)
    bear = sum(p["bias"] == "bearish" for p in recent)
    return {"candlestick": candles, "chart": charts, "levels": support_resistance(df, hi, lo),
            "bullish": int(bull), "bearish": int(bear),
            "bias": "bullish" if bull > bear else "bearish" if bear > bull else "neutral",
            "engine": "TA-Lib" if HAS_TALIB else "pandas fallback"}
