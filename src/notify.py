"""Instant push to your phone via a Telegram bot (free). No-op if not configured.

Set two GitHub secrets: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (see README).
"""
from __future__ import annotations

import os

import requests


def telegram(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
                          timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] {e}")
        return False


def push_items(items: list[dict]) -> None:
    for it in items:
        telegram(f"{it['title']}\n\n{it.get('private') or it['body']}")
