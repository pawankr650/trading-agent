"""Minimal Telegram Bot API client (requests only). Falls back to console when not configured."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import requests

log = logging.getLogger(__name__)
LIMIT = 3900  # Telegram hard limit is 4096 chars per message


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Split on blank lines / newlines so HTML tags are never cut in half."""
    chunks, cur = [], ""
    for block in text.split("\n"):
        while len(block) > limit:  # a single monster line — hard cut
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(block[:limit]); block = block[limit:]
        if len(cur) + len(block) + 1 > limit:
            chunks.append(cur); cur = block
        else:
            cur = f"{cur}\n{block}" if cur else block
    if cur:
        chunks.append(cur)
    return chunks


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.base = f"https://api.telegram.org/bot{self.token}"

    @property
    def ready(self) -> bool:
        return bool(self.token and self.chat_id)

    def _post(self, chat_id: str, chunk: str) -> bool:
        data = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}
        r = requests.post(f"{self.base}/sendMessage", timeout=15, data=data)
        if r.ok:
            return True
        # usually a stray "<" or unbalanced tag -> resend as plain text rather than lose the alert
        log.warning("telegram HTML rejected (%s): %s — resending as plain text", r.status_code, r.text[:200])
        data.pop("parse_mode")
        data["text"] = re.sub(r"<[^>]+>", "", chunk)
        return requests.post(f"{self.base}/sendMessage", timeout=15, data=data).ok

    def send(self, text: str, chat_id: str | None = None) -> bool:
        if not self.ready:
            print("\n[TELEGRAM not configured — console output]\n" + text)
            return False
        ok = True
        for chunk in split_message(text):
            try:
                ok &= self._post(chat_id or self.chat_id, chunk)
            except Exception as e:
                log.warning("telegram send failed: %s", e); return False
        return ok

    def send_photo(self, path: Path, caption: str = "", chat_id: str | None = None) -> bool:
        if not self.ready:
            print(f"[chart saved: {path}]"); return False
        try:
            with open(path, "rb") as f:
                r = requests.post(f"{self.base}/sendPhoto", timeout=30, files={"photo": f},
                                  data={"chat_id": chat_id or self.chat_id, "caption": caption[:1000], "parse_mode": "HTML"})
            return r.ok
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
