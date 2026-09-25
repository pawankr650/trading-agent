"""Risk manager: position sizing, exposure caps, daily-loss kill switch, time windows."""
from __future__ import annotations

import math

from core.config import DATA_DIR
from core.market_hours import past

KILL_FILE = DATA_DIR / "KILL"  # `touch data/KILL` (or /kill on Telegram) halts all new entries


class RiskManager:
    def __init__(self, cfg: dict):
        self.a = cfg["autotrader"]

    def size(self, entry: float, stop: float) -> int:
        cap = float(self.a["capital"])
        per_share_risk = abs(entry - stop)
        if per_share_risk <= 0 or entry <= 0:
            return 0
        by_risk = cap * self.a["risk_per_trade_pct"] / 100 / per_share_risk
        by_cap = cap * self.a["max_position_pct"] / 100 / entry
        return max(0, math.floor(min(by_risk, by_cap)))

    def daily_loss_hit(self, realized: float, unrealized: float) -> bool:
        return realized + unrealized <= -float(self.a["capital"]) * self.a["max_daily_loss_pct"] / 100

    def can_enter(self, open_count: int, realized: float, unrealized: float) -> tuple[bool, str]:
        if KILL_FILE.exists():
            return False, "kill switch active"
        if self.daily_loss_hit(realized, unrealized):
            return False, "daily loss limit reached"
        if open_count >= self.a["max_open_positions"]:
            return False, "max open positions"
        if past(self.a["no_new_entries_after"]):
            return False, "entry window closed"
        return True, "ok"
