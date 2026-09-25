"""Candlestick chart PNG (price + 20/50/200 DMA + volume + RSI) for Telegram alerts."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .config import DATA_DIR  # noqa: E402


def render_chart(report: dict, bars: int = 120) -> Path:
    df = report["df"].tail(bars)
    x = np.arange(len(df))
    up = (df.Close >= df.Open).values
    fig, (ax, axv, axr) = plt.subplots(3, 1, figsize=(10, 7), sharex=True,
                                       gridspec_kw={"height_ratios": [4, 1, 1.3]})
    col = np.where(up, "#16a34a", "#dc2626")
    ax.vlines(x, df.Low, df.High, color=col, linewidth=0.8)
    ax.bar(x, (df.Close - df.Open).abs().clip(lower=1e-6), bottom=np.minimum(df.Open, df.Close), color=col, width=0.6)
    for c, clr in (("SMA20", "#2563eb"), ("SMA50", "#f59e0b"), ("SMA200", "#7c3aed")):
        ax.plot(x, df[c], color=clr, linewidth=1, label=c)
    plan = report.get("plan")
    if plan:
        for k, clr in (("entry", "#111827"), ("stop", "#dc2626"), ("target", "#16a34a")):
            ax.axhline(plan[k], color=clr, linestyle="--", linewidth=0.8)
            ax.text(x[-1] + 1, plan[k], f"{k} {plan[k]}", fontsize=7, color=clr, va="center")
    ax.set_title(f"{report['symbol']}  ₹{report['price']}  ({report['change_pct']:+.2f}%)  →  {report['action']}  "
                 f"score {report['score']:+.2f}", fontsize=11, loc="left")
    ax.set_xlim(-1, len(df) + 14)
    ax.legend(loc="upper left", fontsize=7, frameon=False)
    axv.bar(x, df.Volume, color=col, width=0.6)
    axv.set_ylabel("Vol", fontsize=7)
    axr.plot(x, df.RSI, color="#0ea5e9", linewidth=1)
    axr.axhline(70, color="#dc2626", linewidth=0.6); axr.axhline(30, color="#16a34a", linewidth=0.6)
    axr.set_ylim(0, 100); axr.set_ylabel("RSI", fontsize=7)
    step = max(1, len(df) // 8)
    axr.set_xticks(x[::step]); axr.set_xticklabels([d.strftime("%d-%b") for d in df.index[::step]], fontsize=7)
    for a in (ax, axv, axr):
        a.grid(alpha=0.2); a.tick_params(labelsize=7)
    fig.tight_layout()
    out = DATA_DIR / "charts" / f"{report['symbol']}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=110); plt.close(fig)
    return out
