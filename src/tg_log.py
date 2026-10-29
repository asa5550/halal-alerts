"""Keep the latest Telegram bot chat messages in docs/telegram.json for the dashboard widget.

The Bot API can't fetch a chat's history, so messages are recorded as they pass through:
alerts sent by notify.py, your messages to the bot, and the bot's replies (trade_bot.py).

docs/ is public (GitHub Pages), so in privacy mode the raw text is never written:
alerts use their already-masked public text, and everything else has its numbers
(quantities, prices, amounts) replaced by ••• — dates, times and percentages stay.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "docs" / "telegram.json"
KEEP = 30

_KEEP_RE = r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}|[-+]?\d+(?:\.\d+)?\s?%"
_NUM_RE = re.compile(rf"({_KEEP_RE})|(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?(?![A-Za-z\d]|\.\d)|(?<![A-Za-z\d])\.\d+(?!\w)")


def _private_mode() -> bool:
    try:
        return bool(json.loads((ROOT / "config" / "settings.json").read_text()).get("privacy_mode"))
    except Exception:  # noqa: BLE001
        return True  # unsure -> hide


def mask(text: str) -> str:
    """Hide amounts but keep dates, times and percentages. Numbers glued to letters (BTC2, H1) are left alone."""
    return _NUM_RE.sub(lambda m: m.group(1) or "•••", text)


def record(direction: str, text: str, public: str | None = None, when: datetime | None = None) -> None:
    """direction: 'in' (you -> bot) or 'out' (bot -> you). public: pre-masked text, if the caller has one."""
    try:
        shown = (public if public is not None else mask(text)) if _private_mode() else text
        msgs = json.loads(LOG.read_text()) if LOG.exists() else []
        msgs.append({"t": (when or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                     "dir": direction, "text": shown[:1500]})
        LOG.parent.mkdir(exist_ok=True)
        LOG.write_text(json.dumps(msgs[-KEEP:], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - never let logging break alerts or trade logging
        print(f"[tg_log] {e}")
