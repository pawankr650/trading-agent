"""Minimal Telegram Bot API client (requests only). Falls back to console when not configured."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.base = f"https://api.telegram.org/bot{self.token}"

    @property
    def ready(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str, chat_id: str | None = None) -> bool:
        if not self.ready:
            print("\n[TELEGRAM not configured — console output]\n" + text)
            return False
        for chunk in [text[i:i + 3900] for i in range(0, len(text), 3900)]:
            try:
                requests.post(f"{self.base}/sendMessage", timeout=15, data={
                    "chat_id": chat_id or self.chat_id, "text": chunk, "parse_mode": "HTML",
                    "disable_web_page_preview": True})
            except Exception as e:
                log.warning("telegram send failed: %s", e); return False
        return True

    def send_photo(self, path: Path, caption: str = "", chat_id: str | None = None) -> bool:
        if not self.ready:
            print(f"[chart saved: {path}]"); return False
        try:
            with open(path, "rb") as f:
                requests.post(f"{self.base}/sendPhoto", timeout=30, files={"photo": f},
                              data={"chat_id": chat_id or self.chat_id, "caption": caption[:1000], "parse_mode": "HTML"})
            return True
        except Exception as e:
            log.warning("telegram photo failed: %s", e); return False

    def updates(self, offset: int, timeout: int = 20) -> list[dict]:
        if not self.token:
            return []
        try:
            r = requests.get(f"{self.base}/getUpdates", params={"offset": offset, "timeout": timeout}, timeout=timeout + 5)
            return r.json().get("result", [])
        except Exception:
            return []
