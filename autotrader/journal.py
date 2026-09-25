"""SQLite trade journal — single source of truth for open positions and P&L."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from core.config import DATA_DIR

SCHEMA = """CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, symbol TEXT, side TEXT, qty INTEGER,
  entry REAL, stop REAL, target REAL, sl_order_id TEXT, status TEXT DEFAULT 'OPEN',
  exit REAL, pnl REAL, reason_in TEXT, reason_out TEXT, opened_at TEXT, closed_at TEXT)"""


class Journal:
    def __init__(self, path: Path | str = DATA_DIR / "trades.db"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA); self.db.commit()

    def open_trades(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM trades WHERE status='OPEN'")]

    def is_open(self, symbol: str) -> bool:
        return any(t["symbol"] == symbol for t in self.open_trades())

    def add(self, **t) -> int:
        t.setdefault("opened_at", datetime.now().isoformat(timespec="seconds"))
        cols = ",".join(t)
        cur = self.db.execute(f"INSERT INTO trades({cols}) VALUES({','.join('?'*len(t))})", tuple(t.values()))
        self.db.commit(); return cur.lastrowid

    def close(self, tid: int, exit_px: float, reason: str) -> float:
        t = dict(self.db.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone())
        sign = 1 if t["side"] == "BUY" else -1
        pnl = round(sign * (exit_px - t["entry"]) * t["qty"], 2)
        self.db.execute("UPDATE trades SET status='CLOSED', exit=?, pnl=?, reason_out=?, closed_at=? WHERE id=?",
                        (exit_px, pnl, reason, datetime.now().isoformat(timespec="seconds"), tid))
        self.db.commit(); return pnl

    def realized_today(self) -> float:
        day = datetime.now().strftime("%Y-%m-%d")
        r = self.db.execute("SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status='CLOSED' AND closed_at LIKE ?",
                            (day + "%",)).fetchone()
        return float(r[0])

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM trades ORDER BY id DESC")]
